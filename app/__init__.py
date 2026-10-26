"""Application factory."""
from pathlib import Path

from flask import Flask, g, render_template
from jinja2 import ChoiceLoader, FileSystemLoader

from config import Config, INSTANCE_DIR
from .core import auth, dashboard, db, nav, registry, roles as R, scheduler
from .core.util import fmt_date, fmt_money, slug, record_url
from . import modules


def create_app(overrides=None):
    app = Flask(__name__, instance_path=str(INSTANCE_DIR))
    app.config.from_object(Config)
    app.config.update(overrides or {})
    for key in ("UPLOAD_DIR", "OUTBOX_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    modules.discover(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.jinja_loader = ChoiceLoader([app.jinja_loader] + [FileSystemLoader(d) for d in modules.template_dirs()])

    with app.app_context():
        db.sync_schema(registry.all_modules())

    @app.context_processor
    def inject():
        c = app.config
        return dict(
            csrf_token=auth.csrf_token, app_title=c["APP_TITLE"], company=c["COMPANY_NAME"],
            nav_groups=nav.build(g.user) if g.get("user") else [], ROLE_LABELS=R.ROLE_LABELS,
            has_role=R.has_role, registry=registry, record_url=record_url,
        )

    app.jinja_env.filters["money"] = fmt_money
    app.jinja_env.filters["date"] = lambda v: fmt_date(v, app.config["DATE_DISPLAY"])
    app.jinja_env.filters["slug"] = slug

    for code, text in ((403, "You do not have permission to do that."), (404, "Page not found."), (400, None)):
        app.register_error_handler(code, lambda e, code=code, text=text: (
            render_template("error.html", code=code, message=text or getattr(e, "description", "Bad request")), code))

    if app.config["ENABLE_SCHEDULER"] and not app.config.get("TESTING"):
        scheduler.start(app)
    return app
