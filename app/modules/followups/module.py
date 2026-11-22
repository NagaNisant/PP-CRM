"""
followups - engineers log each follow-up on an offer, set the next date and rate it A-D.
All fields compulsory except Rating (which is optional).
"""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Date, Ref, Text, TextArea
from app.core.module import Module, ValidationError

FIELDS = [
    Ref("offer_id", "Offer", module="offers", required=True, where="t.is_latest = 1"),
    Date("followup_date", "Follow-up date", required=True, default="@today"),
    Choice("mode", "Mode of follow-up", choices=C.FOLLOWUP_MODES, required=True),
    TextArea("notes", "Discussion / update", required=True),
    Choice("rating", "Rating", choices=C.RATINGS, required=False, badge=True, help="Optional rating (A-D)"),
    Choice("status", "Offer status", choices=C.OFFER_STATUSES, required=True, default="Open", badge=True),
    Date("next_followup_date", "Next follow-up on", required=True, help="Compulsory next follow-up date."),
    Ref("engineer_id", "By", module="users", form=False),
]


def prefill(args, user):
    """When opened from an offer, start from that offer's current rating / status."""
    o = db.q1("SELECT rating, status, next_followup_date FROM offers WHERE id=?", (args.get("offer_id"),))
    return {"rating": o["rating"], "status": o["status"], "next_followup_date": o.get("next_followup_date")} if o else {}


def scope(user):
    # Both Application and Marketing can view all follow-up history across the CRM
    return None, []


def validate(data, old, user):
    missing = {}
    if not data.get("offer_id"):
        missing["offer_id"] = "Offer is required"
    if not data.get("followup_date"):
        missing["followup_date"] = "Follow-up date is required"
    if not data.get("mode"):
        missing["mode"] = "Mode of follow-up is required"
    if not (data.get("notes") or "").strip():
        missing["notes"] = "Discussion / update notes are required"
    if not data.get("status"):
        missing["status"] = "Offer status is required"
    if not data.get("next_followup_date"):
        missing["next_followup_date"] = "Next follow-up date is required"
    if missing:
        raise ValidationError(missing)

    if data.get("next_followup_date") and data.get("followup_date") and data["next_followup_date"] < data["followup_date"]:
        raise ValidationError({"next_followup_date": "Next follow-up date cannot be before this follow-up date"})


def before_save(data, old, user):
    if not old:
        data["engineer_id"] = user["id"]


def after_save(row, old, user):
    """Push the latest rating / status / next date onto the offer so lists and reminders stay current."""
    db.execute(
        "UPDATE offers SET rating=?, status=?, next_followup_date=?, updated_at=datetime('now') WHERE id=?",
        (row.get("rating"), row.get("status"), row.get("next_followup_date"), row["offer_id"])
    )


module = Module(
    "followups", "Follow-up", FIELDS, plural="Follow-ups", label_sql="{t}.followup_date",
    access={"view": R.ALL, "create": [R.APPLICATION, R.MARKETING], "edit": [R.APPLICATION, R.MARKETING],
            "delete": [], "export": R.ALL},
    scope=scope, list_fields=["followup_date", "offer_id", "mode", "notes", "rating", "status", "next_followup_date", "engineer_id"],
    default_order="followup_date DESC, id DESC", prefill=prefill, validate=validate, before_save=before_save,
    after_save=after_save, nav=("Sales", 20),
)
