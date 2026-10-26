"""mailer.py - send via SMTP, or drop .eml files in OUTBOX_DIR when SMTP_HOST is not configured."""
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from flask import current_app


def send_mail(to, subject, html, text=""):
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], to, subject
    msg.set_content(text or "Please view this e-mail in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    if cfg["SMTP_HOST"]:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as s:
            if cfg["SMTP_TLS"]:
                s.starttls()
            if cfg["SMTP_USER"]:
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
        return "sent"
    out = Path(cfg["OUTBOX_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    name = "%s_%s.eml" % (datetime.now().strftime("%Y%m%d_%H%M%S_%f"), to.replace("@", "_at_"))
    (out / name).write_bytes(bytes(msg))
    return "saved to outbox"
