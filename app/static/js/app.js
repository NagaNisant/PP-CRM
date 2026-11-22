/* app.js - tiny behaviours: autosuggest (duplicate prevention), repeating rows, confirms, auto-submit filters. */
(function () {
  // confirm dialogs on forms
  document.addEventListener('submit', function (e) {
    var m = e.target.getAttribute('data-confirm');
    if (m && !confirm(m)) e.preventDefault();
  });

  // filter selects submit immediately
  document.querySelectorAll('select[data-auto]').forEach(function (s) {
    s.addEventListener('change', function () { document.getElementById('filters').submit(); });
  });
  document.querySelectorAll('tr.filters input').forEach(function (i) {
    i.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); document.getElementById('filters').submit(); } });
  });

  // repeating child rows
  document.querySelectorAll('[data-add-row]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var key = btn.getAttribute('data-add-row');
      var body = document.querySelector('table[data-child="' + key + '"] tbody');
      var idx = body.querySelectorAll('tr').length;
      while (body.querySelector('[name^="' + key + '-' + idx + '-"]')) idx++;
      var html = document.getElementById('tpl-' + key).innerHTML.replace(/__i__/g, idx);
      body.insertAdjacentHTML('beforeend', html);
    });
  });
  document.addEventListener('click', function (e) {
    if (e.target.matches('[data-remove-row]')) e.target.closest('tr').remove();
  });

  // autosuggest: type a customer / person / e-mail and existing records are offered -> no duplicates
  var timer = null, box = null;
  function closeBox() { if (box) { box.remove(); box = null; } }
  document.addEventListener('click', function (e) { if (!e.target.closest('.suggest-box')) closeBox(); });
  document.addEventListener('input', function (e) {
    var el = e.target;
    if (!el.getAttribute || !el.getAttribute('data-suggest-url')) return;
    clearTimeout(timer);
    var q = el.value.trim();
    if (q.length < 2) return closeBox();
    timer = setTimeout(function () {
      fetch(el.getAttribute('data-suggest-url') + '?field=' + encodeURIComponent(el.name) + '&q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (items) {
          closeBox();
          if (!items.length) return;
          box = document.createElement('div'); box.className = 'suggest-box';
          box.innerHTML = '<div class="head">Already in the database - pick one to avoid duplicates</div>';
          var fills = JSON.parse(el.getAttribute('data-fills') || '{}');
          items.forEach(function (it) {
            var d = document.createElement('div');
            d.textContent = it.label;
            d.addEventListener('click', function () {
              Object.keys(fills).forEach(function (target) {
                var t = document.querySelector('[name="' + target + '"]');
                if (t && it[fills[target]] !== undefined && it[fills[target]] !== null) t.value = it[fills[target]];
              });
              closeBox();
            });
            box.appendChild(d);
          });
          el.parentNode.appendChild(box);
        });
    }, 220);
  });

  // Customer selection in New Offer
  var selCust = document.querySelector('select[name="select_customer"]');
  if (selCust) {
    selCust.addEventListener('change', function () {
      var val = selCust.value.trim();
      if (!val) return;
      var custInput = document.querySelector('[name="cust_name"]');
      if (custInput) {
        custInput.value = val;
      }
      fetch('/customers/suggest?field=cust_name&q=' + encodeURIComponent(val), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (items) {
          if (!items || !items.length) return;
          var it = items[0];
          ['cust_address', 'person_name', 'designation', 'mobile', 'landline', 'email'].forEach(function (k) {
            var el = document.querySelector('[name="' + k + '"]');
            if (el && it[k]) el.value = it[k];
          });
          if (typeof triggerDraftSave === 'function') triggerDraftSave();
        });
    });
  }

  // Automatic Draft Saving for New Offers
  var draftBar = document.getElementById('draft-bar');
  var offerForm = draftBar ? draftBar.closest('main').querySelector('form') : null;
  var draftTimer = null;

  function triggerDraftSave() {
    if (!offerForm) return;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveOfferDraft, 1200);
  }

  function saveOfferDraft() {
    if (!offerForm) return;
    var draftText = document.getElementById('draft-text');
    var draftTime = document.getElementById('draft-time');
    if (draftText) draftText.textContent = 'Saving draft...';

    var fd = new FormData(offerForm);
    var fdClean = new FormData();
    for (var pair of fd.entries()) {
      if (pair[1] instanceof File) continue;
      fdClean.append(pair[0], pair[1]);
    }

    fetch('/offers/save-draft', {
      method: 'POST',
      body: fdClean,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.ok) {
          if (draftText) draftText.textContent = 'Draft auto-saved';
          if (draftTime) {
            var d = new Date();
            draftTime.textContent = '(' + d.toLocaleTimeString() + ')';
          }
        }
      })
      .catch(function () {
        if (draftText) draftText.textContent = 'Draft auto-save active';
      });
  }

  if (offerForm && draftBar) {
    fetch('/offers/get-draft', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && res.has_draft) {
          var draftText = document.getElementById('draft-text');
          var draftTime = document.getElementById('draft-time');
          if (draftText) draftText.textContent = 'Draft restored';
          if (draftTime && res.updated_at) draftTime.textContent = '(' + res.updated_at + ')';
        }
      });

    offerForm.addEventListener('input', triggerDraftSave);
    offerForm.addEventListener('change', triggerDraftSave);

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') {
        saveOfferDraft();
      }
    });
    window.addEventListener('beforeunload', saveOfferDraft);
    window.addEventListener('pagehide', saveOfferDraft);

    var btnDiscard = document.getElementById('btn-discard-draft');
    if (btnDiscard) {
      btnDiscard.addEventListener('click', function () {
        if (!confirm('Discard this draft? All unsaved changes will be lost.')) return;
        var csrf = (offerForm.querySelector('input[name="_csrf"]') || {}).value || '';
        var fd = new FormData();
        fd.append('_csrf', csrf);
        fetch('/offers/discard-draft', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
          .then(function () {
            window.location.href = '/offers/new';
          });
      });
    }
  }
})();
