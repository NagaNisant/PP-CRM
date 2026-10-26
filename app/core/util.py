"""util.py - small shared helpers (dates, money, revision letters, URLs)."""
import re
from datetime import date, datetime, timedelta

SQL_TODAY = "date('now','localtime')"


def today():
    return date.today()


def today_iso():
    return date.today().isoformat()


def yesterday_iso():
    return (date.today() - timedelta(days=1)).isoformat()


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_date(text):
    """Accept ISO and the common Indian formats; returns a date or None."""
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def fmt_date(value, pattern="%d-%m-%Y"):
    d = parse_date(value) if value else None
    return d.strftime(pattern) if d else ""


def fmt_money(value, decimals=2):
    """Indian digit grouping: 12,34,567.50 (drops .00)."""
    if value in (None, ""):
        return ""
    value = float(value)
    s = f"{abs(value):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = head + "," + tail
    out = whole + ("." + frac if frac and set(frac) != {"0"} else "")
    return ("-" if value < 0 else "") + out


def next_revision(rev):
    """'' -> A -> B ... Z -> AA (offer 0972 -> 0972A -> 0972B)."""
    if not rev:
        return "A"
    chars = list(rev)
    i = len(chars) - 1
    while i >= 0:
        if chars[i] == "Z":
            chars[i] = "A"
            i -= 1
        else:
            chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
    return "A" + "".join(chars)


def split_offer_no(offer_no):
    """'0972A' -> ('0972', 'A').  Offer numbers must end with digits + optional revision letters."""
    m = re.match(r"^(.*\d)([A-Za-z]{0,3})$", (offer_no or "").strip())
    return (m.group(1), m.group(2).upper()) if m else (None, None)


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def record_url(module_key, record_id=None, external=False):
    from flask import current_app
    path = "/" + module_key.replace("_", "-") + ("/%s" % record_id if record_id else "/")
    return current_app.config["BASE_URL"].rstrip("/") + path if external else path
