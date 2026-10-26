"""followups - engineers log each follow-up on an offer, set the next date and rate it A-D (Phase 1)."""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Date, Ref, Text, TextArea
from app.core.module import Module, ValidationError

FIELDS = [
    Ref("offer_id", "Offer", module="offers", required=True, where="t.is_latest = 1"),
    Date("followup_date", "Follow-up date", required=True, default="@today"),
    Choice("mode", "Mode of follow-up", choices=C.FOLLOWUP_MODES, required=True),
    TextArea("notes", "Discussion / update", required=True),
    Choice("rating", "Rating", choices=C.RATINGS, required=True, badge=True),
    Choice("status", "Offer status", choices=C.OFFER_STATUSES, required=True, default="Open", badge=True),
    Date("next_followup_date", "Next follow-up on", help="Required while the offer is Open."),
    Ref("engineer_id", "By", module="users", form=False),
]


def prefill(args, user):
    """When opened from an offer, start from that offer's current rating / status."""
    o = db.q1("SELECT rating, status FROM offers WHERE id=?", (args.get("offer_id"),))
    return {"rating": o["rating"], "status": o["status"]} if o else {}


def scope(user):
    if R.is_engineer(user):
        return ("offer_id IN (SELECT id FROM offers WHERE assigned_engineer_id = ? OR created_by = ?)",
                [user["id"], user["id"]])


def validate(data, old, user):
    if data["status"] == "Open" and not data.get("next_followup_date"):
        raise ValidationError({"next_followup_date": "Enter the next follow-up date (or close the offer)"})
    if data.get("next_followup_date") and data["next_followup_date"] < data["followup_date"]:
        raise ValidationError({"next_followup_date": "Next follow-up cannot be before this follow-up"})


def before_save(data, old, user):
    if not old:
        data["engineer_id"] = user["id"]


def after_save(row, old, user):
    """Push the latest rating / status / next date onto the offer so lists and reminders stay current."""
    open_ = row["status"] == "Open"
    db.execute("UPDATE offers SET rating=?, status=?, next_followup_date=?, updated_at=datetime('now') WHERE id=?",
               (row["rating"], row["status"], row["next_followup_date"] if open_ else None, row["offer_id"]))


module = Module(
    "followups", "Follow-up", FIELDS, plural="Follow-ups", label_sql="{t}.followup_date",
    access={"view": [R.HEAD, *R.ENGINEERS], "create": R.ENGINEERS + [R.HEAD], "edit": [R.HEAD], "delete": [], "export": [R.HEAD]},
    scope=scope, list_fields=["followup_date", "offer_id", "mode", "notes", "rating", "status", "next_followup_date", "engineer_id"],
    default_order="followup_date DESC, id DESC", prefill=prefill, validate=validate, before_save=before_save,
    after_save=after_save, nav=("Sales", 20),
)
