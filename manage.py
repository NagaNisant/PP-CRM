"""
manage.py - command line helpers.

  python manage.py init-db                     create tables + first admin user
  python manage.py create-user EMAIL "Name" ROLE [PASSWORD]
  python manage.py send-digests [--force]      send the daily activity e-mails now (use with cron at 07:00)
  python manage.py import-payments FILE.xlsx   load the legacy 'Payment Details' workbook
"""
import getpass
import sys

from app import create_app
from app.core import db
from app.core.auth import hash_password


def init_db(app):
    from config import Config
    with app.app_context():
        if not db.q1("SELECT id FROM users LIMIT 1"):
            create_user(app, Config.DEFAULT_ADMIN_EMAIL, "Administrator", "admin", Config.DEFAULT_ADMIN_PASSWORD)
            print("First admin created:  %s / %s   (change it after logging in!)" % (Config.DEFAULT_ADMIN_EMAIL, Config.DEFAULT_ADMIN_PASSWORD))
        print("Database ready at", app.config["DATABASE"])


def create_user(app, email, name, role, password=None):
    with app.app_context():
        password = password or getpass.getpass("Password: ")
        db.execute("INSERT INTO users(full_name,email,role,active,password_hash,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                   (name, email.lower(), role, 1, hash_password(password)))
        db.get_db().commit()
        print("Created", email, "as", role)


def main(argv):
    if len(argv) < 2:
        return print(__doc__)
    app = create_app({"ENABLE_SCHEDULER": False})
    cmd = argv[1]
    if cmd == "init-db":
        init_db(app)
    elif cmd == "create-user":
        create_user(app, argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else None)
    elif cmd == "send-digests":
        with app.app_context():
            from app.core import digest
            print("digests sent:", digest.send_all(force="--force" in argv))
    elif cmd == "import-payments":
        from app.tools.import_payments import run
        with app.app_context():
            run(argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
