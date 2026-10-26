"""
db.py - SQLite access + automatic schema sync.

Tables are created / extended automatically from the Field definitions in each
module.py, so adding a field to a module never needs a separate migration.
One transaction per request: committed on success, rolled back on error.
"""
import sqlite3
from flask import current_app, g

CORE_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL, entity_id INTEGER NOT NULL,
    user_id INTEGER, body TEXT NOT NULL, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity, entity_id);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def _teardown(exc):
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.rollback() if exc else conn.commit()
        finally:
            conn.close()


def init_app(app):
    app.teardown_appcontext(_teardown)


def q(sql, params=()):
    return [dict(r) for r in get_db().execute(sql, params).fetchall()]


def q1(sql, params=()):
    r = get_db().execute(sql, params).fetchone()
    return dict(r) if r else None


def execute(sql, params=()):
    return get_db().execute(sql, params)


def get_meta(key, default=None):
    r = q1("SELECT value FROM meta WHERE key=?", (key,))
    return r["value"] if r else default


def set_meta(key, value):
    execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# --------------------------------------------------------------- schema sync
def ensure_table(table, columns, indexes=()):
    """columns: list of (name, sql_type). Creates the table or adds missing columns."""
    db = get_db()
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        cols = ", ".join('"%s" %s' % c for c in columns)
        db.execute('CREATE TABLE "%s" (id INTEGER PRIMARY KEY AUTOINCREMENT, %s)' % (table, cols))
    else:
        have = {r["name"] for r in db.execute('PRAGMA table_info("%s")' % table)}
        for name, typ in columns:
            if name not in have:
                db.execute('ALTER TABLE "%s" ADD COLUMN "%s" %s' % (table, name, typ))
    for col in indexes:
        db.execute('CREATE INDEX IF NOT EXISTS "idx_%s_%s" ON "%s"("%s")' % (table, col, table, col))


def sync_schema(modules):
    db = get_db()
    db.executescript(CORE_DDL)
    for m in modules:
        for table, columns, indexes in m.ddl():
            ensure_table(table, columns, indexes)
    db.commit()
