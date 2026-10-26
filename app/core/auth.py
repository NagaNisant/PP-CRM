"""auth.py - e-mail login, sessions, CSRF protection, change password."""
import secrets
from flask import (Blueprint, abort, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from . import db

bp = Blueprint("auth", __name__)
PUBLIC_ENDPOINTS = {"auth.login", "static"}


def hash_password(pw):
    return generate_password_hash(pw)


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@bp.before_app_request
def load_user_and_guard():
    g.user = None
    uid = session.get("uid")
    if uid:
        u = db.q1("SELECT * FROM users WHERE id=? AND active=1", (uid,))
        if u:
            u.pop("password_hash", None)
            g.user = u
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not sent or sent != session.get("_csrf"):
            abort(400, "Security token missing or expired - please reload the page and try again.")
    if request.endpoint and request.endpoint not in PUBLIC_ENDPOINTS and g.user is None:
        return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        u = db.q1("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,))
        if u and check_password_hash(u["password_hash"] or "", request.form.get("password", "")):
            session.clear()
            session["uid"] = u["id"]
            session.permanent = True
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard.home"))
        flash("Wrong e-mail or password.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        row = db.q1("SELECT password_hash FROM users WHERE id=?", (g.user["id"],))
        new = request.form.get("new_password", "")
        if not check_password_hash(row["password_hash"] or "", request.form.get("current_password", "")):
            flash("Current password is wrong.", "error")
        elif len(new) < 8 or new != request.form.get("confirm_password"):
            flash("New password must be at least 8 characters and match the confirmation.", "error")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), g.user["id"]))
            flash("Password changed.", "ok")
            return redirect(url_for("dashboard.home"))
    return render_template("profile.html")
