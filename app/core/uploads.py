"""uploads.py - PDF / image attachments stored on disk under UPLOAD_DIR/<table>/."""
import os
import uuid
from pathlib import Path
from flask import current_app
from werkzeug.utils import secure_filename


def allowed(filename, accept):
    return os.path.splitext(filename or "")[1].lower() in accept


def save(file_storage, table):
    folder = Path(current_app.config["UPLOAD_DIR"]) / table
    folder.mkdir(parents=True, exist_ok=True)
    name = "%s_%s" % (uuid.uuid4().hex[:10], secure_filename(file_storage.filename) or "file")
    file_storage.save(folder / name)
    return "%s/%s" % (table, name)


def abs_path(rel):
    base = Path(current_app.config["UPLOAD_DIR"]).resolve()
    p = (base / rel).resolve()
    if base not in p.parents:
        raise ValueError("bad path")
    return p


def download_name(rel):
    return rel.split("/")[-1].split("_", 1)[-1]
