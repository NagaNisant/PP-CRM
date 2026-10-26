"""registry.py - the set of loaded modules, widgets and nav items."""
MODULES = {}      # key -> Module
BY_TABLE = {}     # table -> (Module, Child|None)
WIDGETS = []
NAV = []          # extra (non-CRUD) nav items


def add_module(m):
    MODULES[m.key] = m
    BY_TABLE[m.table] = (m, None)
    for c in m.children:
        BY_TABLE[c.table] = (m, c)
    WIDGETS.extend(m.widgets)


def get(key):
    return MODULES[key]


def all_modules():
    return list(MODULES.values())
