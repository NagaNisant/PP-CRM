"""dashboard.py - landing page: the reminders every user sees when opening their page."""
from flask import Blueprint, g, render_template
from .widgets import widgets_for

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def home():
    return render_template("dashboard.html", widgets=widgets_for(g.user))
