"""scheduler.py - tiny background thread that fires the digest once a day at DIGEST_HOUR:DIGEST_MINUTE.
Prefer cron / Task Scheduler running `python manage.py send-digests` in production with many workers."""
import threading
import time
from datetime import datetime


def start(app):
    def loop():
        while True:
            time.sleep(30)
            now = datetime.now()
            cfg = app.config
            start = cfg["DIGEST_HOUR"] * 60 + cfg["DIGEST_MINUTE"]
            minutes = now.hour * 60 + now.minute
            if start <= minutes < start + 180:      # fire within 3 hours after the set time (e.g. server was down at 7:00)
                try:
                    with app.app_context():
                        from . import digest
                        digest.send_all()
                except Exception:       # never kill the thread
                    app.logger.exception("digest failed")
    threading.Thread(target=loop, daemon=True, name="digest-scheduler").start()
