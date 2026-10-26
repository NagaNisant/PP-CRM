"""
offers - Phase 1: offers submitted to customers, revisions (0972 -> 0972A), assignment to engineers,
rating A-D, reminders and the monthly view for head / admin.
"""
from flask import url_for
from app import choices as C
from app.core import db, roles as R
from app.core.fields import (Bool, Choice, Computed, Date, File, Int, Money, Ref, Text)
from app.core.module import Action, Module, Related, ValidationError, Widget
from app.core.util import SQL_TODAY, next_revision, split_offer_no, today_iso, yesterday_iso
from app.core.widgets import rows_widget
from app.modules.customers.module import customer_block, customer_values, resolve_customer

ENGINEER_SQL = "role IN (%s) AND active=1" % R.sql_in(R.ENGINEERS)

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
    Choice("moc", "Metallic / Non metallic", choices=C.MOC, required=True),
    Int("quantity", "Quantity", min=1, required=True),
    Money("quoted_value", "Quoted value", required=True, min=0, summary=True),
    Choice("currency", "Currency of quote", choices=C.CURRENCIES, required=True, default="INR"),
    File("offer_pdf", "Offer (PDF)", required=True),

    Ref("assigned_engineer_id", "Assigned engineer", module="users", where=ENGINEER_SQL,
        roles=[R.HEAD], section="Follow-up status"),
    Choice("rating", "Rating", choices=C.RATINGS, roles=[], badge=True, help="Engineers set this when adding a follow-up."),
    Choice("status", "Status", choices=C.OFFER_STATUSES, default="Open", roles=[R.HEAD], badge=True),
    Date("next_followup_date", "Next follow-up", roles=[]),
    Bool("is_latest", "Current version", form=False, default=1),

    Computed("month", "Month", sql="strftime('%Y-%m', t.offer_date)", list=False),
    Computed("followup_count", "Follow-ups", sql="(SELECT COUNT(*) FROM followups f WHERE f.offer_id = t.id)", value="int", list=False),
    Computed("last_followup", "Last follow-up", sql="(SELECT MAX(f.followup_date) FROM followups f WHERE f.offer_id = t.id)", value="date", list=False),
]


# ---------------------------------------------------------------- scope & hooks
def scope(user):
    if R.is_engineer(user):
        return "assigned_engineer_id = ? OR created_by = ?", [user["id"], user["id"]]


def row_permission(action, user, row):
    return action != "edit" or not R.is_engineer(user) or user["id"] in (row.get("assigned_engineer_id"), row.get("created_by"))


def prepare(data, old, user):
    if not old and R.is_engineer(user) and not data.get("assigned_engineer_id"):
        data["assigned_engineer_id"] = user["id"]          # an engineer entering an offer owns it


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
    if row["status"] == "Open" and row["is_latest"] and row["next_followup_date"] and row["next_followup_date"] <= today_iso():
        return "row-red" if row["next_followup_date"] < today_iso() else "row-yellow"


# ---------------------------------------------------------------- revision action
def make_revision(row, user, data):
    rev = next_revision(row["revision"] or "")
    cols = {f.name: row.get(f.name) for f in module.stored_fields}
    cols.update(offer_no=row["base_no"] + rev, revision=rev, is_latest=1, offer_pdf=None, offer_date=today_iso())
    new_id = module.insert(cols, user["id"])
    db.execute("UPDATE offers SET is_latest=0 WHERE base_no=? AND id != ?", (row["base_no"], new_id))
    return ("Revision %s created. Update the price if needed and attach the revised offer PDF." % (row["base_no"] + rev),
            url_for("offers.edit", id=new_id))


# ---------------------------------------------------------------- dashboard / digest widgets
COLS = ["offer_no", "customer_id", "quoted_value", "rating", "next_followup_date"]


def w_followups(user):
    return rows_widget(module, user, order="next_followup_date", columns=COLS,
                       where="is_latest=1 AND status='Open' AND next_followup_date <= " + SQL_TODAY,
                       cls=lambda r: "row-red" if r["next_followup_date"] < today_iso() else "row-yellow")


def w_first_followup(user):
    return rows_widget(module, user, columns=["offer_no", "customer_id", "quoted_value", "offer_date"], order="offer_date",
                       where="is_latest=1 AND status='Open' AND next_followup_date IS NULL AND assigned_engineer_id IS NOT NULL")


def w_new_yesterday(user):
    return rows_widget(module, user, columns=["offer_no", "customer_id", "region", "quoted_value", "assigned_engineer_id"],
                       where="is_latest=1 AND offer_date = date('now','localtime','-1 day')")


def w_month(user):
    r = db.q1("SELECT COUNT(*) n, COALESCE(SUM(quoted_value),0) v, "
              "SUM(status='Open') open_n, SUM(status='Open' AND rating='A') a, SUM(status='Order Acquired') oa "
              "FROM offers WHERE is_latest=1 AND strftime('%Y-%m', offer_date) = strftime('%Y-%m','now','localtime')")
    from app.core.util import fmt_money
    return {"stats": [("offers this month", r["n"]), ("quoted value", fmt_money(r["v"])), ("still open", r["open_n"] or 0),
                      ("open & rated A", r["a"] or 0), ("orders acquired", r["oa"] or 0)]}


ENG_PLUS = R.ENGINEERS + [R.HEAD]

module = Module(
    "offers", "Offer", FIELDS, plural="Offers", label_sql="{t}.offer_no || ' - ' || COALESCE((SELECT name FROM customers c WHERE c.id = {t}.customer_id), '')",
    access={"view": [R.HEAD, *R.ENGINEERS, R.DESIGN], "create": ENG_PLUS, "edit": ENG_PLUS, "delete": [],
            "export": [R.HEAD, *R.ENGINEERS]},
    scope=scope, row_permission=row_permission,
    list_fields=["offer_no", "offer_date", "customer_id", "region", "item_type", "moc", "quantity", "quoted_value",
                 "currency", "rating", "status", "assigned_engineer_id", "next_followup_date", "offer_pdf", "is_latest"],
    default_filters={"is_latest": "1"}, default_order="offer_date DESC, id DESC",
    prepare=prepare, validate=validate, before_save=before_save, extra_values=extra_values, panel=panel,
    row_class=row_class, nav=("Sales", 10),
    actions=[Action("revise", "Create revision", make_revision, roles=ENG_PLUS, when=lambda r, u: bool(r["is_latest"]),
                    confirm="Create the next revision of this offer?")],
    related=[Related("followups", "offer_id", "Follow-up history", add_label="Add follow-up / rate this offer")],
    widgets=[
        Widget("offers_due", "Offer follow-ups due today / overdue", w_followups, roles=ENG_PLUS, order=10),
        Widget("offers_first", "Offers waiting for a first follow-up date", w_first_followup, roles=R.ENGINEERS, order=11),
        Widget("offers_new", "New offers submitted yesterday", w_new_yesterday, roles=ENG_PLUS, order=12),
        Widget("offers_month", "This month at a glance", w_month, roles=[R.HEAD], digest=False, order=5),
    ],
    intro="Offers submitted to customers. Use the filters in the header row; the Excel button exports exactly what you see.",
)
