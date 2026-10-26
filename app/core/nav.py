"""nav.py - builds the sidebar from the loaded modules (+ any extra items registered by custom modules)."""
from flask import current_app, url_for
from . import registry, roles as R


def add_item(label, endpoint, group, order=50, roles=R.ALL):
    registry.NAV.append(dict(label=label, endpoint=endpoint, group=group, order=order, roles=roles))


def build(user):
    items = []
    for m in registry.all_modules():
        if m.nav and m.allowed("view", user):
            items.append(dict(label=m.plural, url=url_for(m.key + ".index"), group=m.nav[0], order=m.nav[1]))
    for n in registry.NAV:
        if R.has_role(user, n["roles"]):
            items.append(dict(label=n["label"], url=url_for(n["endpoint"]), group=n["group"], order=n["order"]))
    groups = []
    for g in current_app.config["NAV_GROUPS"]:
        mine = sorted([i for i in items if i["group"] == g], key=lambda i: (i["order"], i["label"]))
        if mine:
            groups.append((g, mine))
    return groups
