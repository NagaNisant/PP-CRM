"""
work_orders - Phase 3: order entry (customer PO -> OA / WO) and the Phase 4 "start dispatch & accounts" button.
Also hosts two helpers other modules import: refresh_lock() and wo_scope().
"""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import (Bool, Choice, Computed, Date, File, Int, Money, Ref, Text, TextArea, Phone, Email)
from app.core.module import Action, Module, Related, ValidationError, Widget
from app.core.util import now_iso, today_iso
from app.core.widgets import rows_widget
from app.modules.customers.module import customer_block, customer_values, resolve_customer

ENGINEER_SQL = "role IN (%s) AND active=1" % R.sql_in(R.ENGINEERS)
DISPATCH_TEAM = [R.ACCOUNTS, R.HEAD]

INV_NET = "(SELECT COALESCE(SUM(i.net_value),0) FROM invoices i WHERE i.work_order_id = t.id)"
INV_GROSS = "(SELECT COALESCE(SUM(COALESCE(i.gross_value, i.net_value, 0)),0) FROM invoices i WHERE i.work_order_id = t.id)"
RECEIVED = ("(SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN invoices i ON i.id = p.invoice_id "
            "WHERE i.work_order_id = t.id)")

FIELDS = [
    *customer_block("Customer & person who placed the order"),
    Ref("customer_id", "Customer", module="customers", form=False),
    Int("contact_id", hidden=True),

    Text("end_user", "End user", section="End user"),
    Text("end_user_contact", "End user contact name"),
    Email("end_user_email", "End user e-mail"),
    Phone("end_user_mobile", "End user mobile"),

    Ref("offer_id", "Relevant offer", module="offers", where="t.is_latest = 1", required=True, section="Order details",
        help="Region and engineer are taken from the offer if left blank."),
    Choice("region", "Region", choices=C.REGIONS, required=True),
    Ref("engineer_id", "Engineer", module="users", where=ENGINEER_SQL, required=True),
    Text("po_no", "Customer PO no", required=True),
    Date("po_date", "Customer PO date", required=True),
    TextArea("payment_terms", "Payment terms (as per PO)", required=True),
    Int("credit_days", "Credit days", required=True, min=0, default=30,
        help="Drives the payment reminders. 0 = payable immediately."),
    Choice("credit_basis", "Credit days counted from", choices=C.CREDIT_BASES, required=True, default="Date of delivery"),
    Text("price_basis", "Price basis", required=True, placeholder="e.g. Ex-works Bangalore"),
    Text("packing_forwarding", "Packing & forwarding", placeholder="e.g. 2% extra"),
    Choice("inspection", "Inspection clause", choices=C.YES_NO, required=True),
    Money("po_value_gross", "PO value (gross)", required=True, min=0, summary=True),
    Money("po_value_net", "PO value (net)", required=True, min=0, summary=True),

    Choice("office", "Order booked at", choices=C.OFFICES, required=True, default="Head Office", section="Order numbers",
           help="Head office: OA no and work-order no are the same."),
    Text("oa_no", "OA no", required=True, unique=True),
    Text("wo_no", "WO number", help="Branch office only; head office copies the OA no."),

    Date("delivery_date", "Date of delivery", section="Delivery"),
    TextArea("delivery_address", "Delivery address"),
    File("oa_pdf", "OA copy (PDF)", required=True),

    Bool("dispatch_enabled", "Dispatch & accounts started", form=False, filter=True),
    Date("dispatch_started_on", hidden=True),
    Bool("locked", "Locked (paid in full)", form=False),

    Computed("offer_no", "Offer no", sql="(SELECT o.offer_no FROM offers o WHERE o.id = t.offer_id)"),
    Computed("invoiced_net", "Invoiced (net)", sql=INV_NET, value="money", summary=True),
    Computed("invoiced_gross", "Invoiced (gross)", sql=INV_GROSS, value="money"),
    Computed("received", "Payment received", sql=RECEIVED, value="money", summary=True),
    Computed("outstanding", "Outstanding", sql="%s - %s" % (INV_GROSS, RECEIVED), value="money", summary=True),
    Computed("supply_status", "Supply", value="choice", choices=["Not dispatched", "Part supply", "Full supply", "PO value not set"],
             sql="""CASE WHEN COALESCE(t.po_value_net,0) = 0 THEN 'PO value not set'
                         WHEN %s = 0 THEN 'Not dispatched'
                         WHEN %s >= t.po_value_net - 0.5 THEN 'Full supply' ELSE 'Part supply' END""" % (INV_NET, INV_NET)),
]


# ---------------------------------------------------------------- helpers used by other modules
def wo_scope(user, alias="w"):
    """SQL limiting work orders for engineers: their own orders + every order in their regions."""
    if not R.is_engineer(user):
        return None, []
    regs = R.user_regions(user)
    sql = "%s.engineer_id = ?" % alias
    params = [user["id"]]
    if regs:
        sql += " OR %s.region IN (%s)" % (alias, ",".join("?" * len(regs)))
        params += regs
    return sql, params


def refresh_lock(wo_id):
    """Lock the WO (heads/admin only can then edit) once fully supplied AND every invoice is paid without shortage."""
    wo = db.q1("SELECT po_value_net, dispatch_enabled FROM work_orders WHERE id=?", (wo_id,))
    if not wo:
        return
    inv = db.q1("SELECT COUNT(*) c, COALESCE(SUM(net_value),0) n FROM invoices WHERE work_order_id=?", (wo_id,))
    unpaid = db.q1("SELECT COUNT(*) c FROM invoices i WHERE i.work_order_id=? AND COALESCE(i.gross_value, i.net_value, 0) - "
                   "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.id),0) > 0.5", (wo_id,))
    full = bool(wo["po_value_net"]) and inv["n"] >= wo["po_value_net"] - 0.5
    locked = int(bool(wo["dispatch_enabled"] and inv["c"] and full and unpaid["c"] == 0))
    db.execute("UPDATE work_orders SET locked=? WHERE id=?", (locked, wo_id))


# ---------------------------------------------------------------- hooks
def scope(user):
    sql, params = wo_scope(user, "work_orders_scope")
    if sql:
        regs = R.user_regions(user)
        s = "engineer_id = ?" + (" OR region IN (%s)" % ",".join("?" * len(regs)) if regs else "")
        return s, [user["id"]] + regs


def row_permission(action, user, row):
    if action in ("edit", "delete") and row["locked"]:
        return user["role"] == R.HEAD
    return True


def prepare(data, old, user):
    if data.get("offer_id"):
        o = db.q1("SELECT region, assigned_engineer_id FROM offers WHERE id=?", (data["offer_id"],))
        if o:
            data["region"] = data.get("region") or o["region"]
            data["engineer_id"] = data.get("engineer_id") or o["assigned_engineer_id"]
    if data.get("office") == "Head Office":
        data["wo_no"] = data.get("oa_no")


def validate(data, old, user):
    if data.get("office") == "Branch Office" and not data.get("wo_no"):
        raise ValidationError({"wo_no": "Enter the WO number (branch office OA and WO numbers differ)"})
    if data.get("po_value_gross") and data.get("po_value_net") and data["po_value_net"] > data["po_value_gross"]:
        raise ValidationError({"po_value_net": "Net value cannot exceed gross value"})


def before_save(data, old, user):
    data["customer_id"], data["contact_id"] = resolve_customer(data, user["id"], data.get("region"))
    if not old:
        data["dispatch_enabled"] = 0
        data["locked"] = 0


def after_save(row, old, user):
    if row["offer_id"]:
        db.execute("UPDATE offers SET status='Order Acquired', next_followup_date=NULL WHERE id=?", (row["offer_id"],))
    refresh_lock(row["id"])


def start_dispatch(row, user, data):
    module.set(row["id"], dispatch_enabled=1, dispatch_started_on=today_iso())
    return "Dispatch & accounts activity started - you can now add packing slip / invoice details."


def w_pending_dispatch(user):
    return rows_widget(module, user, where="dispatch_enabled = 0 AND delivery_date IS NOT NULL", order="delivery_date",
                       columns=["wo_no", "customer_id", "po_no", "delivery_date", "po_value_net"])


module = Module(
    "work_orders", "Work order", FIELDS, plural="Orders / Work orders",
    label_sql="{t}.wo_no || ' - ' || COALESCE((SELECT name FROM customers c WHERE c.id = {t}.customer_id), '')",
    access={"view": [R.HEAD, *R.ENGINEERS, R.DESIGN, R.ACCOUNTS], "create": R.OFFICE_STAFF, "edit": R.OFFICE_STAFF,
            "delete": [], "export": [R.HEAD, R.ACCOUNTS]},
    scope=scope, row_permission=row_permission, prepare=prepare, validate=validate, before_save=before_save,
    after_save=after_save, extra_values=customer_values, comments=True,
    comment_roles=[R.HEAD, *R.ENGINEERS, R.ACCOUNTS],
    list_fields=["wo_no", "oa_no", "customer_id", "po_no", "po_date", "region", "engineer_id", "po_value_net", "supply_status",
                 "outstanding", "dispatch_enabled", "locked"],
    default_order="po_date DESC, id DESC", nav=("Orders", 10), new_label="Enter order",
    row_class=lambda r: "row-green" if r["locked"] else None,
    actions=[Action("start_dispatch", "Start dispatch & accounts", start_dispatch, roles=DISPATCH_TEAM, style="primary",
                    when=lambda r, u: not r["dispatch_enabled"],
                    confirm="Start dispatch and accounts activity for this work order?")],
    related=[Related("invoices", "work_order_id", "Dispatch, invoices & payments", add_label="Add dispatch / invoice",
                     columns=["invoice_no", "invoice_date", "gross_value", "supply_type", "received", "outstanding", "due_date", "payment_status"],
                     when=lambda r, u: bool(r["dispatch_enabled"]))],
    widgets=[Widget("wo_pending", "Orders with a delivery date - dispatch not started", w_pending_dispatch, roles=DISPATCH_TEAM, order=40)],
)
