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
})();
