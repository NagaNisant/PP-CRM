"""
Module discovery.  Every sub-folder of app/modules that contains a module.py is loaded:

    module   = Module(...)     -> a CRUD entity (list / form / detail / Excel ...)  [or a list of them]
    register = fn(app)         -> optional: add your own blueprint / routes / nav items

To add a feature: create app/modules/<name>/module.py.  To remove one: delete the folder.
"""
import importlib
import importlib.util
import pkgutil
from pathlib import Path

from app.core import registry
from app.core.crud import make_blueprint
from app.core.module import Module


def discover(app):
    loaded = []
    for info in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not info.ispkg:
            continue
        if importlib.util.find_spec("app.modules.%s.module" % info.name) is None:
            continue
        mod = importlib.import_module("app.modules.%s.module" % info.name)
        loaded.append(mod)
        defs = getattr(mod, "module", None)
        for m in (defs if isinstance(defs, (list, tuple)) else [defs] if defs else []):
            registry.add_module(m)
    for mod in loaded:                      # blueprints after ALL modules are registered (refs may cross modules)
        defs = getattr(mod, "module", None)
        for m in (defs if isinstance(defs, (list, tuple)) else [defs] if defs else []):
            app.register_blueprint(make_blueprint(m))
        if hasattr(mod, "register"):
            mod.register(app)
    return loaded


def template_dirs():
    return [str(p) for p in Path(__file__).parent.glob("*/templates") if p.is_dir()]
