"""
config.py - every deployment setting lives here (override with environment variables).
Dropdown lists live in app/choices.py, role permissions in app/core/roles.py.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = Path(os.environ.get("PUMPCRM_INSTANCE", BASE_DIR / "instance"))


def _bool(name, default):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


class Config:
    # ---- branding -------------------------------------------------------
    COMPANY_NAME = "Process Pumps (I) Pvt Ltd"
    APP_TITLE = "Process Pumps CRM"

    # ---- security / storage --------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-before-going-live")
    DATABASE = os.environ.get("DATABASE", str(INSTANCE_DIR / "pumpcrm.db"))
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(INSTANCE_DIR / "uploads"))
    OUTBOX_DIR = os.environ.get("OUTBOX_DIR", str(INSTANCE_DIR / "outbox"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", 25)) * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # ---- display --------------------------------------------------------
    DATE_DISPLAY = "%d-%m-%Y"
    PAGE_SIZE = 50
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")  # used in e-mail links
    NAV_GROUPS = ["Sales", "Field work", "Orders", "Accounts", "Reports", "Admin"]

    # ---- payment reminders (Phase 4) -----------------------------------
    DUE_SOON_DAYS = 7          # "payment due in a week" -> yellow

    # ---- daily e-mail digest (Phase 1: 7:00 AM) ------------------------
    ENABLE_SCHEDULER = _bool("ENABLE_SCHEDULER", True)
    DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", 7))
    DIGEST_MINUTE = int(os.environ.get("DIGEST_MINUTE", 0))
    DIGEST_ROLES = ["marketing", "application", "accounts", "head", "admin"]
    DIGEST_SEND_EMPTY = False  # skip people who have nothing pending

    # ---- SMTP (if SMTP_HOST is empty, mails are written to OUTBOX_DIR) --
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_TLS = _bool("SMTP_TLS", True)
    MAIL_FROM = os.environ.get("MAIL_FROM", "crm@process-pumps.com")

    # ---- first-run admin (created by `python manage.py init-db`) -------
    DEFAULT_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@process-pumps.com")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe@123")
