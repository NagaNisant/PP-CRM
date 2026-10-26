"""digest.py - builds and sends the 7:00 AM activity e-mail (follow-ups, new enquiries, payments)."""
from datetime import date
from flask import current_app, render_template
from . import db
from .mailer import send_mail
from .widgets import widgets_for


def build(user):
    return widgets_for(user, digest_only=True)


def send_all(force=False):
    """Send today's digest to every active user in DIGEST_ROLES. Returns number of mails sent."""
    cfg = current_app.config
    today = date.today().isoformat()
    if not force and db.get_meta("digest_last_sent") == today:
        return 0
    db.set_meta("digest_last_sent", today)          # claim the day first (safe with several workers)
    db.get_db().commit()
    marks = ",".join("?" * len(cfg["DIGEST_ROLES"]))
    users = db.q("SELECT * FROM users WHERE active=1 AND role IN (%s)" % marks, cfg["DIGEST_ROLES"])
    sent = 0
    for u in users:
        sections = build(u)
        if not sections and not cfg["DIGEST_SEND_EMPTY"]:
            continue
        html = render_template("email/digest.html", user=u, sections=sections, today=today)
        send_mail(u["email"], "%s - your work list for %s" % (cfg["APP_TITLE"], date.today().strftime("%d-%m-%Y")), html)
        sent += 1
    return sent
