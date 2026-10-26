"""
crud.py - turns a Module into a Flask blueprint with list / new / view / edit / delete /
export / actions / comments / file download. Written once, used by every module.
"""
import re
from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for)
from . import db, registry, roles as R, uploads
from .excel import module_export
from .fields import FieldError, File
from .module import ValidationError


def _empty(f, v):
    return f.is_empty(v)


def _read_group(fields, form, files, prefix, old, user, module, editable=lambda f: True):
    """Read + clean a group of fields. Returns (data, raw, errors)."""
    data, raw, errors = {}, {}, {}
    for f in fields:
        if not editable(f):
            if f.stored:
                data[f.name] = old.get(f.name) if old is not None else module.defaults(user).get(f.name)
            continue
        r = f.read(form, files, prefix)
        raw[f.name] = r
        try:
            v = f.clean(r)
        except FieldError as e:
            errors[prefix + f.name] = str(e)
            v = None
        if isinstance(f, File) and v is None and old is not None:
            v = old.get(f.name)
        data[f.name] = v
    return data, raw, errors


def _child_indexes(child, form, files):
    pat = re.compile(r"^%s-(\d+)-" % re.escape(child.key))
    idx = {int(m.group(1)) for k in list(form.keys()) + list(files.keys()) for m in [pat.match(k)] if m}
    return sorted(idx)


def process_form(module, old, user):
    """Shared by create & edit. Returns dict(ok, data, values, errors, child_rows)."""
    form, files = request.form, request.files
    editable = lambda f: module.field_editable(f, user)
    data, raw, errors = _read_group(module.form_fields, form, files, "", old, user, module, editable)
    child_data = {}
    for c in module.children:
        rows = []
        existing = {r["id"]: r for r in module.child_rows(c, old["id"])} if old else {}
        for i in _child_indexes(c, form, files):
            prefix = "%s-%d-" % (c.key, i)
            rid = form.get(prefix + "id")
            rid = int(rid) if rid and rid.isdigit() else None
            old_row = existing.get(rid)
            rdata, rraw, rerr = _read_group([f for f in c.fields], form, files, prefix, old_row, user, module)
            blank = all(_empty(f, rdata.get(f.name)) or f.kind == "bool" for f in c.fields) and not rid
            if blank:
                continue
            for f in c.fields:
                if f.required and _empty(f, rdata.get(f.name)) and (prefix + f.name) not in rerr:
                    rerr[prefix + f.name] = "Required"
            errors.update(rerr)
            rdata["id"] = rid
            rows.append(dict(data=rdata, raw=rraw))
        if len(rows) < c.min_rows:
            errors["__child_" + c.key] = "Add at least %d %s row(s)." % (c.min_rows, c.label.lower())
        child_data[c.key] = rows
    # derived values first, then required / unique / custom validation
    try:
        if module.hooks["prepare"]:
            module.hooks["prepare"](data, old, g.user)
    except ValidationError as e:
        errors.update(e.errors)
    for f in module.form_fields:
        if not editable(f):
            continue
        if f.required and _empty(f, data.get(f.name)) and f.name not in errors:
            errors[f.name] = "This field is required"
        if f.unique and f.stored and data.get(f.name) and f.name not in errors:
            dup = db.q1('SELECT id FROM "%s" WHERE lower("%s")=lower(?) AND id != ?' % (module.table, f.name),
                        (data[f.name], old["id"] if old else 0))
            if dup:
                errors[f.name] = "Already exists - %s must be unique" % f.label
    if not errors and module.hooks["validate"]:
        try:
            module.hooks["validate"](data, old, g.user)
        except ValidationError as e:
            errors.update(e.errors)
    return dict(data=data, raw=raw, errors=errors, child_data=child_data)


def _store_files(module, fields, data):
    for f in fields:
        if isinstance(f, File) and data.get(f.name) is not None and not isinstance(data[f.name], str):
            data[f.name] = uploads.save(data[f.name], module.table)


def _save(module, old, res, user):
    data = res["data"]
    try:
        if module.hooks["before_save"]:
            module.hooks["before_save"](data, old, user)
    except ValidationError as e:
        res["errors"].update(e.errors)
        return None
    _store_files(module, module.form_fields, data)
    if old:
        module.update(old["id"], data, user["id"])
        rid = old["id"]
    else:
        rid = module.insert(data, user["id"])
    for c in module.children:
        rows = []
        for r in res["child_data"][c.key]:
            _store_files(module, c.fields, r["data"])
            rows.append(dict(r["data"], id=r["data"].get("id")))
        module.sync_children(c, rid, rows)
    new = module.get(rid)
    if module.hooks["after_save"]:
        module.hooks["after_save"](new, old, user)
    return rid


def _form_values(module, row, user, args=None):
    """Initial values (strings) for a form: defaults < record < ?prefill args."""
    vals = {}
    src = dict(module.defaults(user))
    if row:
        src.update(row)
        if module.extra_values:
            src.update(module.extra_values(row))
    elif args:
        src.update({k: v for k, v in args.items() if k in module.by_name})
        if module.prefill:
            src.update(module.prefill(dict(args), user) or {})
    for f in module.form_fields:
        vals[f.name] = f.to_form(src.get(f.name)) if f.kind != "file" else src.get(f.name)
    return vals, src


def _child_form_rows(module, c, row, res=None):
    if res is not None:
        return [dict(id=r["data"].get("id"), vals=r["raw"], file_values={f.name: r["data"].get(f.name) for f in c.fields if f.kind == "file"}) for r in res["child_data"][c.key]]
    if not row:
        return [dict(id=None, vals={}, file_values={}) for _ in range(max(c.min_rows, 1))]
    out = []
    for r in module.child_rows(c, row["id"]):
        out.append(dict(id=r["id"], vals={f.name: f.to_form(r.get(f.name)) for f in c.fields},
                        file_values={f.name: r.get(f.name) for f in c.fields if f.kind == "file"}))
    return out


def make_blueprint(module):
    bp = Blueprint(module.key, __name__, url_prefix="/" + module.slug)

    def need(action, row=None):
        if not module.can(action, g.user, row):
            abort(403)

    def load(id, action="view"):
        row = module.get(id, g.user)
        if not row:
            abort(404)
        need(action, row)
        return row

    def render_form(row, values, errors, child_rows, locked_refs=(), panel_ctx=None):
        panel = module.panel(panel_ctx if panel_ctx is not None else (row or {}), g.user) if module.panel else None
        return render_template("form.html", module=module, row=row, values=values, errors=errors,
                               child_rows=child_rows, locked_refs=locked_refs, panel=panel)

    # ---------------------------------------------------------------- list
    @bp.route("/")
    def index():
        need("view")
        args = request.args
        if "_f" not in args and module.default_filters:
            args = {**{"f_" + k: v for k, v in module.default_filters.items()}, **args.to_dict()}
        page = max(int(args.get("page", 1) or 1), 1)
        per = module.page_size or int(current_app.config["PAGE_SIZE"])
        res = module.query(g.user, filters=args, sort=args.get("sort"), direction=args.get("dir", "asc"),
                           page=page, per_page=per)
        pages = max((res["total"] + per - 1) // per, 1)
        return render_template("list.html", module=module, rows=res["rows"], total=res["total"], sums=res["sums"],
                               page=page, pages=pages, args=args,
                               can_create=module.can("create", g.user), can_export=module.allowed("export", g.user))

    @bp.route("/export.xlsx")
    def export():
        need("export")
        args = request.args
        if "_f" not in args and module.default_filters:
            args = {**{"f_" + k: v for k, v in module.default_filters.items()}, **args.to_dict()}
        return module_export(module, g.user, args)

    # ---------------------------------------------------------------- create
    @bp.route("/new", methods=["GET", "POST"])
    def new():
        need("create")
        if request.method == "POST":
            res = process_form(module, None, g.user)
            if not res["errors"]:
                rid = _save(module, None, res, g.user)
                if rid:
                    flash("%s saved." % module.label, "ok")
                    nxt = request.form.get("_next")
                    return redirect(nxt if nxt and nxt.startswith("/") else url_for(module.key + ".view", id=rid))
            values = {f.name: (res["raw"].get(f.name) if f.kind != "file" else None) for f in module.form_fields}
            values.update({k: v for k, v in res["raw"].items() if k not in values})
            return render_form(None, values, res["errors"], [dict(c=c, rows=_child_form_rows(module, c, None, res)) for c in module.children],
                               panel_ctx=request.form.to_dict())
        values, _src = _form_values(module, None, g.user, request.args)
        locked = [f.name for f in module.form_fields if f.kind == "ref" and request.args.get(f.name)]
        return render_form(None, values, {}, [dict(c=c, rows=_child_form_rows(module, c, None)) for c in module.children],
                           locked_refs=locked, panel_ctx=request.args.to_dict())

    # ---------------------------------------------------------------- view
    @bp.route("/<int:id>")
    def view(id):
        row = load(id)
        full = dict(row)
        if module.extra_values:
            full.update(module.extra_values(row))
        related = []
        for rel in module.related:
            rm = registry.get(rel.module)
            if not rm.allowed("view", g.user) or (rel.when and not rel.when(row, g.user)):
                continue
            data = rm.query(g.user, where='q."%s" = ?' % rel.fk, params=(id,), order=rm.default_order)
            can_add = rel.add and rm.can("create", g.user) and module.can("view", g.user, row)
            related.append(dict(rel=rel, module=rm, rows=data["rows"],
                                columns=[rm.by_name[c] for c in (rel.columns or [f.name for f in rm.list_fields if f.name != rel.fk][:6])],
                                can_add=can_add))
        actions = [a for a in module.actions
                   if R.has_role(g.user, a.roles if a.roles is not None else module.access["edit"])
                   and (not a.when or a.when(row, g.user))]
        comments = db.q("SELECT c.*, u.full_name FROM comments c LEFT JOIN users u ON u.id=c.user_id "
                        "WHERE entity=? AND entity_id=? ORDER BY c.id", (module.table, id)) if module.comments else []
        children = [dict(c=c, rows=module.child_rows(c, id)) for c in module.children]
        return render_template("detail.html", module=module, row=full, related=related, actions=actions,
                               comments=comments, children=children,
                               panel=module.panel(row, g.user) if module.panel else None,
                               can_edit=module.can("edit", g.user, row), can_delete=module.can("delete", g.user, row),
                               can_comment=module.comments and module.can("comment", g.user, row))

    # ---------------------------------------------------------------- edit
    @bp.route("/<int:id>/edit", methods=["GET", "POST"])
    def edit(id):
        row = load(id, "edit")
        if request.method == "POST":
            res = process_form(module, row, g.user)
            if not res["errors"]:
                if _save(module, row, res, g.user):
                    flash("%s updated." % module.label, "ok")
                    nxt = request.form.get("_next")
                    return redirect(nxt if nxt and nxt.startswith("/") else url_for(module.key + ".view", id=id))
            values = {f.name: (res["raw"].get(f.name) if f.name in res["raw"] else f.to_form(row.get(f.name)) if f.kind != "file" else row.get(f.name))
                      for f in module.form_fields}
            values.update({k: v for k, v in res["raw"].items() if k not in values})
            return render_form(row, values, res["errors"], [dict(c=c, rows=_child_form_rows(module, c, row, res)) for c in module.children],
                               panel_ctx=row)
        values, _src = _form_values(module, row, g.user)
        return render_form(row, values, {}, [dict(c=c, rows=_child_form_rows(module, c, row)) for c in module.children])

    @bp.route("/<int:id>/delete", methods=["POST"])
    def delete(id):
        row = load(id, "delete")
        try:
            if module.hooks["before_delete"]:
                module.hooks["before_delete"](row, g.user)
        except ValidationError as e:
            flash(" ".join(e.errors.values()), "error")
            return redirect(url_for(module.key + ".view", id=id))
        module.delete(id)
        if module.hooks["after_delete"]:
            module.hooks["after_delete"](row, g.user)
        flash("%s deleted." % module.label, "ok")
        return redirect(url_for(module.key + ".index"))

    # ---------------------------------------------------------------- workflow actions
    @bp.route("/<int:id>/action/<akey>", methods=["GET", "POST"])
    def action(id, akey):
        row = load(id)
        act = next((a for a in module.actions if a.key == akey), None)
        if not act or not R.has_role(g.user, act.roles if act.roles is not None else module.access["edit"]) \
                or (act.when and not act.when(row, g.user)):
            abort(403)
        errors, values = {}, {}
        if request.method == "POST":
            data, raw, errors = _read_group(act.fields, request.form, request.files, "", None, g.user, module)
            for f in act.fields:
                if f.required and _empty(f, data.get(f.name)) and f.name not in errors:
                    errors[f.name] = "This field is required"
            if not errors:
                out = act.handler(row, g.user, data)
                msg, url = (out if isinstance(out, tuple) else (out, None))
                if msg:
                    flash(msg, "ok")
                return redirect(url or url_for(module.key + ".view", id=id))
            values = raw
        elif act.prefill:
            values = {k: (v if v is None else str(v)) for k, v in act.prefill(row, g.user).items()}
        if not act.fields and request.method == "GET":
            return render_template("action.html", module=module, row=row, act=act, values={}, errors={})
        return render_template("action.html", module=module, row=row, act=act, values=values, errors=errors)

    # ---------------------------------------------------------------- comments & files
    @bp.route("/<int:id>/comment", methods=["POST"])
    def comment(id):
        row = load(id)
        if not (module.comments and module.can("comment", g.user, row)):
            abort(403)
        body = (request.form.get("body") or "").strip()
        if body:
            from .util import now_iso
            db.execute("INSERT INTO comments(entity,entity_id,user_id,body,created_at) VALUES(?,?,?,?,?)",
                       (module.table, id, g.user["id"], body, now_iso()))
            flash("Comment added.", "ok")
        return redirect(url_for(module.key + ".view", id=id) + "#comments")

    @bp.route("/<int:id>/file/<fname>")
    @bp.route("/<int:id>/file/<ckey>/<int:cid>/<fname>")
    def file(id, fname, ckey=None, cid=None):
        load(id)
        if ckey:
            child = next((c for c in module.children if c.key == ckey), None) or abort(404)
            r = db.q1('SELECT * FROM "%s" WHERE id=? AND "%s"=?' % (child.table, child.fk), (cid, id)) or abort(404)
            fld = next((f for f in child.fields if f.name == fname and f.kind == "file"), None) or abort(404)
        else:
            r = module.get(id)
            fld = module.by_name.get(fname)
            if not fld or fld.kind != "file":
                abort(404)
        rel = r.get(fld.name)
        if not rel:
            abort(404)
        path = uploads.abs_path(rel)
        if not path.exists():
            abort(404)
        return send_file(path, download_name=uploads.download_name(rel), as_attachment=False)

    if module.routes:
        module.routes(bp)
    return bp
