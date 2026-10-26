"""
widgets.py - dashboard cards + the daily e-mail digest share the same Widget objects.

A widget function returns either
    {"columns": [...], "rows": [{"cells": [...], "url": "/offers/3", "cls": "row-red"}]}
or  {"stats": [("Label", "value"), ...]}
Use rows_widget() to build the first form straight from a module query.
"""
from . import registry, roles as R
from .util import record_url


def rows_widget(module, user, where, columns, params=(), limit=15, order=None, cls=None, link_module=None, id_field="id"):
    link_module = link_module or module
    res = module.query(user, where=where, params=params, order=order, per_page=limit, page=1)
    rows = []
    for r in res["rows"]:
        rows.append({
            "cells": [module.display(c, r) for c in columns],
            "url": record_url(link_module.key, r[id_field]),
            "cls": cls(r) if callable(cls) else cls,
        })
    return {"columns": [module.by_name[c].label for c in columns], "rows": rows,
            "total": res["total"], "more": max(res["total"] - len(rows), 0)}


def widgets_for(user, digest_only=False):
    out = []
    for w in sorted(registry.WIDGETS, key=lambda w: w.order):
        if digest_only and not w.digest:
            continue
        if not R.has_role(user, w.roles):
            continue
        data = w.fn(user)
        if data and (data.get("rows") or data.get("stats")):
            out.append({"key": w.key, "title": w.title, "css": w.css, "data": data})
    return out
