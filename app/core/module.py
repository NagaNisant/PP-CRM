"""
module.py - the declarative building block of the whole application.

A module.py file creates ONE Module(...) describing an entity: its fields,
who may do what, hooks, workflow actions, related lists and dashboard widgets.
Everything else (tables, forms, lists with filters, Excel, detail pages,
permissions) is generated from that description.
"""
from . import db, registry
from . import roles as R
from .fields import Field, Ref, Computed, File
from .util import now_iso


class ValidationError(Exception):
    """Raise from hooks. errors = {field_name or '__all__': message}"""
    def __init__(self, errors):
        if isinstance(errors, str):
            errors = {"__all__": errors}
        super().__init__(errors)
        self.errors = errors


class Child:
    """Inline table of rows owned by a record (e.g. contacts of a customer, lines of an expense claim)."""
    def __init__(self, key, label, fields, *, min_rows=0, add_label="Add row"):
        self.key, self.label, self.fields = key, label, fields
        self.min_rows, self.add_label = min_rows, add_label
        self.table = self.fk = None

    def ddl(self):
        cols = [(self.fk, "INTEGER")] + [(f.name, f.sql_type) for f in self.fields if f.stored]
        return self.table, cols, [self.fk]


class Action:
    """A workflow button on the detail page (approve, start dispatch, create revision ...)."""
    def __init__(self, key, label, handler, *, roles=None, when=None, fields=(), prefill=None,
                 style="", confirm=None):
        self.key, self.label, self.handler = key, label, handler
        self.roles, self.when, self.fields = roles, when, list(fields)
        self.prefill, self.style, self.confirm = prefill, style, confirm


class Related:
    """A table of related records shown on a detail page (e.g. follow-ups of an offer)."""
    def __init__(self, module, fk, title=None, columns=None, add=True, when=None, add_label=None):
        self.module, self.fk, self.title = module, fk, title
        self.columns, self.add, self.when, self.add_label = columns, add, when, add_label


class Widget:
    """A dashboard card that can also be included in the 7 AM e-mail digest."""
    def __init__(self, key, title, fn, *, roles=R.ALL, digest=True, order=50, css=""):
        self.key, self.title, self.fn = key, title, fn
        self.roles, self.digest, self.order, self.css = roles, digest, order, css


class Module:
    def __init__(self, key, label, fields, *, plural=None, table=None, children=(), access=None,
                 scope=None, row_permission=None, label_sql="{t}.name", default_order="id DESC",
                 default_filters=None, page_size=None, list_fields=None, export_fields=None,
                 prepare=None, validate=None, before_save=None, after_save=None,
                 before_delete=None, after_delete=None, extra_values=None, prefill=None,
                 actions=(), related=(), widgets=(), nav=("Sales", 50), comments=False,
                 panel=None, row_class=None, routes=None, intro=None, indexes=(),
                 export_override=None, new_label=None, comment_roles=R.ALL):
        self.key, self.label = key, label
        self.plural = plural or label + "s"
        self.table = table or key
        self.slug = key.replace("_", "-")
        self.fields = list(fields)
        self.children = list(children)
        for c in self.children:
            c.table = c.table or "%s_%s" % (self.table, c.key)
            c.fk = c.fk or "%s_id" % self.table
        self.access = {"view": R.ALL, "create": [], "edit": [], "delete": [], "export": []}
        self.access.update(access or {})
        self.access.setdefault("comment", comment_roles)
        self.scope, self.row_permission = scope, row_permission
        self.label_sql, self.default_order = label_sql, default_order
        self.default_filters = default_filters or {}
        self.page_size = page_size
        self._list_fields, self._export_fields = list_fields, export_fields
        self.hooks = dict(prepare=prepare, validate=validate, before_save=before_save, after_save=after_save,
                          before_delete=before_delete, after_delete=after_delete)
        self.extra_values, self.prefill = extra_values, prefill
        self.actions, self.related, self.widgets = list(actions), list(related), list(widgets)
        self.nav, self.comments = nav, comments
        self.panel, self.row_class, self.routes, self.intro = panel, row_class, routes, intro
        self.indexes, self.export_override, self.new_label = indexes, export_override, new_label
        self.by_name = {f.name: f for f in self.fields}

    # ------------------------------------------------------------ schema
    @property
    def stored_fields(self):
        return [f for f in self.fields if f.stored]

    def ddl(self):
        cols = [(f.name, f.sql_type) for f in self.stored_fields]
        cols += [("created_at", "TEXT"), ("created_by", "INTEGER"), ("updated_at", "TEXT"), ("updated_by", "INTEGER")]
        idx = [f.name for f in self.stored_fields if f.kind == "ref"] + list(self.indexes)
        yield self.table, cols, idx
        for c in self.children:
            yield c.ddl()

    # ------------------------------------------------------------ field groups
    @property
    def list_fields(self):
        if self._list_fields:
            return [self.by_name[n] for n in self._list_fields]
        return [f for f in self.fields if f.show_in_list]

    @property
    def export_fields(self):
        if self._export_fields:
            return [self.by_name[n] for n in self._export_fields]
        return [f for f in self.fields if f.export and f.kind != "file"]

    @property
    def form_fields(self):
        return [f for f in self.fields if f.show_in_form]

    @property
    def filter_fields(self):
        return [f for f in self.list_fields if f.filterable]

    # ------------------------------------------------------------ permissions
    def allowed(self, action, user):
        return R.has_role(user, self.access.get(action, []))

    def can(self, action, user, row=None):
        if not self.allowed(action, user):
            return False
        if row is not None and self.row_permission and not R.is_admin(user):
            return bool(self.row_permission(action, user, row))
        return True

    def field_editable(self, f, user):
        return f.roles is None or R.has_role(user, f.roles)

    def scope_clause(self, user):
        if user is None or not self.scope or R.is_admin(user):
            return None, []
        res = self.scope(user)
        return (res[0], list(res[1])) if res else (None, [])

    # ------------------------------------------------------------ SQL
    def label_expr(self, alias="t"):
        return self.label_sql.format(t=alias)

    def inner_sql(self):
        cols = ["t.*"]
        for f in self.fields:
            if isinstance(f, Computed):
                cols.append("(%s) AS \"%s\"" % (f.sql, f.name))
            elif isinstance(f, Ref):
                ref = registry.get(f.module)
                cols.append('(SELECT %s FROM "%s" rt WHERE rt.id = t."%s") AS "%s__label"'
                            % (ref.label_expr("rt"), ref.table, f.name, f.name))
        return 'SELECT %s FROM "%s" t' % (", ".join(cols), self.table)

    def _filter_clauses(self, args):
        clauses, params = [], []
        for f in self.filter_fields:
            n, k = f.name, f.kind
            col = 'q."%s__label"' % n if k == "ref" else 'q."%s"' % n
            if k == "date":
                lo, hi = args.get("f_%s_from" % n), args.get("f_%s_to" % n)
                if lo:
                    clauses.append("%s >= ?" % col); params.append(lo)
                if hi:
                    clauses.append("%s <= ?" % col); params.append(hi)
            elif k in ("int", "money"):
                for suffix, op in (("min", ">="), ("max", "<=")):
                    v = args.get("f_%s_%s" % (n, suffix))
                    if v not in (None, ""):
                        try:
                            clauses.append("%s %s ?" % (col, op)); params.append(float(v))
                        except ValueError:
                            pass
            else:
                v = args.get("f_%s" % n)
                if v in (None, ""):
                    continue
                if k == "bool":
                    clauses.append("COALESCE(%s,0) = ?" % col); params.append(int(v))
                elif k == "choice":
                    clauses.append("%s = ?" % col); params.append(v)
                else:
                    clauses.append("%s LIKE ?" % col); params.append("%%%s%%" % v)
        return clauses, params

    def query(self, user=None, filters=None, sort=None, direction="asc", page=None, per_page=None,
              where=None, params=(), order=None):
        """Returns dict(rows, total, sums). `where` is raw SQL on the outer alias q (e.g. "status='Open'")."""
        clauses, ps = self._filter_clauses(filters or {})
        sc, sp = self.scope_clause(user)
        if sc:
            clauses.append("(%s)" % sc); ps += sp
        if where:
            clauses.append("(%s)" % where); ps += list(params)
        wh = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        inner = self.inner_sql()
        sums = {}
        sum_fields = [f for f in self.list_fields if f.summary]
        sel = ["COUNT(*) AS n"] + ['SUM(q."%s") AS "s_%s"' % (f.name, f.name) for f in sum_fields]
        agg = db.q1("SELECT %s FROM (%s) q%s" % (", ".join(sel), inner, wh), ps)
        total = agg["n"]
        for f in sum_fields:
            sums[f.name] = agg["s_%s" % f.name]
        order_sql = order or self.default_order
        if sort and sort in self.by_name:
            f = self.by_name[sort]
            col = '"%s__label"' % sort if f.kind == "ref" else '"%s"' % sort
            order_sql = "%s %s" % (col, "DESC" if direction == "desc" else "ASC") + (", id DESC")
        sql = "SELECT * FROM (%s) q%s ORDER BY %s" % (inner, wh, order_sql)
        if per_page:
            sql += " LIMIT %d OFFSET %d" % (per_page, ((page or 1) - 1) * per_page)
        return {"rows": db.q(sql, ps), "total": total, "sums": sums}

    def fetch(self, user=None, where=None, params=(), order=None, limit=None):
        return self.query(user, where=where, params=params, order=order,
                          per_page=limit, page=1)["rows"]

    def get(self, id, user=None):
        res = self.query(user, where="q.id = ?", params=(id,))
        return res["rows"][0] if res["rows"] else None

    def options(self, where=None, params=()):
        sql = 'SELECT t.id, %s AS label FROM "%s" t' % (self.label_expr("t"), self.table)
        if where:
            sql += " WHERE " + where
        sql += " ORDER BY label COLLATE NOCASE LIMIT 3000"
        return [(r["id"], r["label"]) for r in db.q(sql, params)]

    def label_of(self, id):
        r = db.q1('SELECT %s AS label FROM "%s" t WHERE t.id=?' % (self.label_expr("t"), self.table), (id,))
        return r["label"] if r else ""

    # ------------------------------------------------------------ writes
    def _values(self, data):
        return {f.name: data[f.name] for f in self.stored_fields if f.name in data}

    def insert(self, data, user_id=None):
        vals = self._values(data)
        ts = now_iso()
        vals.update(created_at=ts, created_by=user_id, updated_at=ts, updated_by=user_id)
        cols = ", ".join('"%s"' % c for c in vals)
        cur = db.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (self.table, cols, ",".join("?" * len(vals))),
                         list(vals.values()))
        return cur.lastrowid

    def update(self, id, data, user_id=None):
        vals = self._values(data)
        vals.update(updated_at=now_iso(), updated_by=user_id)
        sets = ", ".join('"%s"=?' % c for c in vals)
        db.execute('UPDATE "%s" SET %s WHERE id=?' % (self.table, sets), list(vals.values()) + [id])

    def set(self, id, **values):
        """Quick programmatic update used by actions and hooks (no validation)."""
        values["updated_at"] = now_iso()
        sets = ", ".join('"%s"=?' % c for c in values)
        db.execute('UPDATE "%s" SET %s WHERE id=?' % (self.table, sets), list(values.values()) + [id])

    def delete(self, id):
        for c in self.children:
            db.execute('DELETE FROM "%s" WHERE "%s"=?' % (c.table, c.fk), (id,))
        db.execute('DELETE FROM comments WHERE entity=? AND entity_id=?', (self.table, id))
        db.execute('DELETE FROM "%s" WHERE id=?' % self.table, (id,))

    # ------------------------------------------------------------ children
    def child_rows(self, child, parent_id):
        return db.q('SELECT * FROM "%s" WHERE "%s"=? ORDER BY id' % (child.table, child.fk), (parent_id,))

    def child_insert(self, child, parent_id, data):
        vals = {child.fk: parent_id}
        vals.update({f.name: data.get(f.name) for f in child.fields if f.stored and f.name in data})
        cols = ", ".join('"%s"' % c for c in vals)
        return db.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (child.table, cols, ",".join("?" * len(vals))),
                          list(vals.values())).lastrowid

    def child_update(self, child, row_id, data):
        vals = {f.name: data.get(f.name) for f in child.fields if f.stored and f.name in data}
        if vals:
            sets = ", ".join('"%s"=?' % c for c in vals)
            db.execute('UPDATE "%s" SET %s WHERE id=?' % (child.table, sets), list(vals.values()) + [row_id])

    def sync_children(self, child, parent_id, rows):
        """rows: [{'id': existing_id|None, ...values}] -> insert/update/delete so the table matches."""
        keep = {r["id"] for r in rows if r.get("id")}
        for r in self.child_rows(child, parent_id):
            if r["id"] not in keep:
                db.execute('DELETE FROM "%s" WHERE id=?' % child.table, (r["id"],))
        for r in rows:
            if r.get("id"):
                self.child_update(child, r["id"], r)
            else:
                self.child_insert(child, parent_id, r)

    # ------------------------------------------------------------ display helpers
    def display(self, field, row):
        if isinstance(field, str):
            field = self.by_name[field]
        if field.kind == "ref":
            return row.get(field.name + "__label") or ""
        return field.display(row.get(field.name))

    def defaults(self, user):
        out = {}
        from .util import today_iso
        for f in self.form_fields:
            d = f.default
            if d == "@me":
                d = user["id"] if user else None
            elif d == "@today":
                d = today_iso()
            elif callable(d):
                d = d(user)
            if d is not None:
                out[f.name] = d
        return out
