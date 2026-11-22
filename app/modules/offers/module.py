"""
offers - Phase 1: offers submitted to customers, revisions (0972 -> 0972A), assignment to engineers,
rating A-D, draft saving, and full access for Application & Marketing & Admin.
"""
import json
from flask import flash, jsonify, redirect, request, url_for
from app import choices as C
from app.core import db, roles as R
from app.core.fields import (Bool, Choice, Computed, Date, File, Int, Money, Ref, Text)
from app.core.module import Action, Module, Related, ValidationError, Widget
from app.core.util import SQL_TODAY, next_revision, now_iso, split_offer_no, today_iso, yesterday_iso
from app.core.widgets import rows_widget
from app.modules.customers.module import customer_block, customer_values, resolve_customer

ENGINEER_SQL = "role IN ('application', 'marketing') AND active=1"

FIELDS = [
    *customer_block(),
    Ref("customer_id", "Customer", module="customers", form=False),
    Int("contact_id", hidden=True),

    Text("offer_no", "Offer no", required=True, unique=True, section="Offer", max_length=30,
         help="Revisions are created with the 'Create revision' button (0972 -> 0972A)."),
    Text("base_no", hidden=True),
    Text("revision", "Rev", form=False, list=False),
    Date("offer_date", "Offer date", required=True, default="@today"),
    Choice("region", "Region", choices=C.REGIONS, required=True),
    Text("enquiry_no", "Enquiry / RFQ no", section="Enquiry"),
    Date("enquiry_date", "Enquiry date"),
    Choice("enquiry_mode", "Enquiry mode", choices=C.ENQUIRY_MODES),

    Choice("item_type", "Pump / Spare / Both", choices=C.ITEM_TYPES, required=True, section="Scope & price"),
    Choice("moc", "Metallic / Non-Metallic", choices=C.MOC, required=True),
    Int("quantity", "Quantity", min=1, required=True),
    Money("quoted_value", "Quoted value", required=True, min=0, summary=True),
    Choice("currency", "Currency of quote", choices=C.CURRENCIES, required=True, default="INR"),
    File("offer_pdf", "Offer (PDF)", required=True),

    Ref("assigned_engineer_id", "Assigned engineer", module="users", where=ENGINEER_SQL,
        roles=[R.APPLICATION], section="Follow-up status"),
    Choice("rating", "Rating", choices=C.RATINGS, roles=[], badge=True, help="Engineers set this when adding a follow-up."),
    Choice("status", "Status", choices=C.OFFER_STATUSES, default="Open", roles=[R.APPLICATION], badge=True),
    Date("next_followup_date", "Next follow-up", roles=[]),
    Bool("is_latest", "Current version", form=False, default=1),

    Computed("month", "Month", sql="strftime('%Y-%m', t.offer_date)", list=False),
    Computed("followup_count", "Follow-ups", sql="(SELECT COUNT(*) FROM followups f WHERE f.offer_id = t.id)", value="int", list=False),
    Computed("last_followup", "Last follow-up", sql="(SELECT MAX(f.followup_date) FROM followups f WHERE f.offer_id = t.id)", value="date", list=False),
]


# ---------------------------------------------------------------- scope & hooks
def scope(user):
    # Admin, Application, and Marketing can view EVERY offer created in the CRM
    return None, []


def row_permission(action, user, row):
    # Marketing cannot edit original offer creation details
    if action == "edit" and R.is_marketing(user):
        return False
    return True


def prepare(data, old, user):
    if not old and user.get("role") == R.APPLICATION and not data.get("assigned_engineer_id"):
        data["assigned_engineer_id"] = user["id"]


def validate(data, old, user):
    base, rev = split_offer_no(data["offer_no"])
    if not base:
        raise ValidationError({"offer_no": "Offer no must end with digits, optionally followed by revision letters (0972, 0972A)"})
    if data.get("enquiry_date") and data.get("offer_date") and data["offer_date"] < data["enquiry_date"]:
        raise ValidationError({"offer_date": "Offer date cannot be before the enquiry date"})


def before_save(data, old, user):
    data["base_no"], data["revision"] = split_offer_no(data["offer_no"])
    data["customer_id"], data["contact_id"] = resolve_customer(data, user["id"], data.get("region"))
    if not old:
        data["is_latest"] = 1
        db.execute("UPDATE offers SET is_latest=0 WHERE base_no=?", (data["base_no"],))


def after_save(row, old, user):
    # When an offer is submitted/saved, clear any active draft for this user
    if not old:
        db.execute("DELETE FROM offer_drafts WHERE user_id=?", (user["id"],))


def extra_values(row):
    return customer_values(row)


def panel(ctx, user):
    if not ctx.get("base_no"):
        return None
    revs = db.q("SELECT offer_no, is_latest FROM offers WHERE base_no=? ORDER BY id", (ctx["base_no"],))
    if len(revs) < 2:
        return None
    return [("Revision history", "  >  ".join(r["offer_no"] + (" (current)" if r["is_latest"] else "") for r in revs))]


def row_class(row):
    if row.get("status") == "Open" and row.get("is_latest") and row.get("next_followup_date") and row.get("next_followup_date") <= today_iso():
        return "row-red" if row.get("next_followup_date") < today_iso() else "row-yellow"


def prefill(args, user):
    # If opening /offers/new, check if a saved draft exists for this user
    if not args.get("id"):
        row = db.q1("SELECT data FROM offer_drafts WHERE user_id=?", (user["id"],))
        if row and row.get("data"):
            try:
                d = json.loads(row["data"])
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
    return {}


# ---------------------------------------------------------------- revision action
def make_revision(row, user, data):
    rev = next_revision(row["revision"] or "")
    cols = {f.name: row.get(f.name) for f in module.stored_fields}
    cols.update(offer_no=row["base_no"] + rev, revision=rev, is_latest=1, offer_pdf=None, offer_date=today_iso())
    new_id = module.insert(cols, user["id"])
    db.execute("UPDATE offers SET is_latest=0 WHERE base_no=? AND id != ?", (row["base_no"], new_id))
    return ("Revision %s created. Update the price if needed and attach the revised offer PDF." % (row["base_no"] + rev),
            url_for("offers.edit", id=new_id))


# ---------------------------------------------------------------- custom routes (drafts)
def routes(bp):
    from flask import g

    @bp.route("/save-draft", methods=["POST"])
    def save_draft():
        if not g.user or not module.can("create", g.user):
            return jsonify({"ok": False, "error": "Not permitted"}), 403
        data = {}
        for k in request.form:
            if k not in ("_csrf", "_next"):
                data[k] = request.form[k]
        db.execute(
            "INSERT INTO offer_drafts (user_id, data, updated_at) VALUES (?, ?, datetime('now', 'localtime')) "
            "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (g.user["id"], json.dumps(data))
        )
        db.get_db().commit()
        r = db.q1("SELECT updated_at FROM offer_drafts WHERE user_id=?", (g.user["id"],))
        saved_at = r["updated_at"] if r else now_iso()
        return jsonify({"ok": True, "saved_at": saved_at})

    @bp.route("/get-draft")
    def get_draft():
        if not g.user:
            return jsonify({"ok": False, "error": "Not logged in"}), 401
        r = db.q1("SELECT data, updated_at FROM offer_drafts WHERE user_id=?", (g.user["id"],))
        if not r or not r.get("data"):
            return jsonify({"ok": False, "has_draft": False})
        return jsonify({"ok": True, "has_draft": True, "data": json.loads(r["data"]), "updated_at": r["updated_at"]})

    @bp.route("/discard-draft", methods=["POST"])
    def discard_draft():
        if not g.user:
            return jsonify({"ok": False}), 401
        db.execute("DELETE FROM offer_drafts WHERE user_id=?", (g.user["id"],))
        db.get_db().commit()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"ok": True})
        flash("Draft discarded.", "ok")
        return redirect(url_for("offers.new"))


# ---------------------------------------------------------------- widgets
COLS = ["offer_no", "customer_id", "quoted_value", "rating", "next_followup_date"]


def w_followups(user):
    if R.is_admin(user):
        return None  # Admin should not have follow-up assignments
    where = "is_latest=1 AND status='Open' AND next_followup_date <= " + SQL_TODAY
    if R.is_engineer(user):
        where += " AND (assigned_engineer_id = %d OR created_by = %d)" % (user["id"], user["id"])
    return rows_widget(module, user, order="next_followup_date", columns=COLS, where=where,
                       cls=lambda r: "row-red" if r["next_followup_date"] < today_iso() else "row-yellow")


module = Module(
    "offers", "Offer", FIELDS, plural="Offers", label_sql="{t}.offer_no || ' - ' || COALESCE((SELECT name FROM customers c WHERE c.id = {t}.customer_id), '')",
    access={"view": R.ALL, "create": [R.APPLICATION], "edit": [R.APPLICATION], "delete": [],
            "export": R.ALL},
    scope=scope, row_permission=row_permission,
    list_fields=["offer_no", "offer_date", "customer_id", "region", "item_type", "moc", "quantity", "quoted_value",
                 "currency", "rating", "status", "assigned_engineer_id", "next_followup_date", "offer_pdf", "is_latest"],
    default_filters={"is_latest": "1"}, default_order="offer_date DESC, id DESC",
    prefill=prefill, prepare=prepare, validate=validate, before_save=before_save, after_save=after_save,
    extra_values=extra_values, panel=panel, row_class=row_class, routes=routes, nav=("Sales", 10),
    actions=[Action("revise", "Create revision", make_revision, roles=[R.APPLICATION], when=lambda r, u: bool(r["is_latest"]),
                    confirm="Create the next revision of this offer?")],
    related=[Related("followups", "offer_id", "Follow-up history", add_label="Add follow-up / rate this offer")],
    widgets=[],
    intro="Offers submitted to customers. Use the filters in the header row; the Excel button exports exactly what you see.",
)
