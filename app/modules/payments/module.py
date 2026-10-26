"""payments - Phase 4: money received against an invoice (advance / balance / retention)."""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Computed, Date, Money, Ref, Text
from app.core.module import Module, ValidationError
from app.modules.work_orders.module import refresh_lock, wo_scope

FIELDS = [
    Ref("invoice_id", "Invoice", module="invoices", required=True),
    Choice("kind", "Type of payment", choices=C.PAYMENT_KINDS, required=True, default="Balance"),
    Money("amount", "Amount received", required=True, min=0.01, summary=True),
    Date("received_date", "Received on", required=True, default="@today"),
    Choice("mode", "Mode", choices=C.PAYMENT_MODES),
    Text("reference_no", "Cheque / UTR / reference no"),
    Money("deduction", "TDS / other deduction", min=0, help="Information only - not counted as received."),
    Text("remarks", "Remarks"),
    Computed("customer_name", "Customer", list=True,
             sql="(SELECT c.name FROM customers c JOIN work_orders w ON w.customer_id = c.id JOIN invoices i ON i.work_order_id = w.id WHERE i.id = t.invoice_id)"),
]


def scope(user):
    sql, params = wo_scope(user, "w")
    if sql:
        return ("invoice_id IN (SELECT i.id FROM invoices i JOIN work_orders w ON w.id = i.work_order_id WHERE %s)" % sql, params)


def _wo_of(invoice_id):
    r = db.q1("SELECT work_order_id FROM invoices WHERE id=?", (invoice_id,))
    return r["work_order_id"] if r else None


def row_permission(action, user, row):
    wo = _wo_of(row["invoice_id"])
    r = db.q1("SELECT locked FROM work_orders WHERE id=?", (wo,))
    if action in ("edit", "delete") and r and r["locked"]:
        return user["role"] == R.HEAD
    return True


def validate(data, old, user):
    wo = _wo_of(data["invoice_id"])
    r = db.q1("SELECT locked FROM work_orders WHERE id=?", (wo,))
    if r and r["locked"] and user["role"] not in (R.HEAD, R.ADMIN):
        raise ValidationError({"invoice_id": "This work order is locked (paid in full) - only the head / admin can change it"})


def after_save(row, old, user):
    refresh_lock(_wo_of(row["invoice_id"]))
    if old and old["invoice_id"] != row["invoice_id"]:
        refresh_lock(_wo_of(old["invoice_id"]))


def after_delete(row, user):
    refresh_lock(_wo_of(row["invoice_id"]))


module = Module(
    "payments", "Payment", FIELDS, plural="Payments received", label_sql="{t}.received_date || ' - ' || {t}.amount",
    access={"view": [R.HEAD, R.ACCOUNTS, *R.ENGINEERS], "create": [R.ACCOUNTS, R.HEAD], "edit": [R.ACCOUNTS, R.HEAD],
            "delete": [R.ACCOUNTS, R.HEAD], "export": [R.ACCOUNTS, R.HEAD]},
    scope=scope, row_permission=row_permission, validate=validate, after_save=after_save, after_delete=after_delete,
    list_fields=["received_date", "customer_name", "invoice_id", "kind", "amount", "mode", "reference_no"],
    default_order="received_date DESC, id DESC", nav=("Accounts", 20), new_label="Record payment",
)
