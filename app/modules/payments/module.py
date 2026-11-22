"""
payments - money received against an invoice or directly from customers (Advance / Balance / Retention).
Retained under Accounts module: Payment Received.
"""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Computed, Date, Money, Ref, Text
from app.core.module import Module, ValidationError

FIELDS = [
    Date("received_date", "Received on", required=True, default="@today"),
    Ref("customer_id", "Customer", module="customers"),
    Ref("invoice_id", "Invoice", module="invoices"),
    Choice("kind", "Type of payment", choices=C.PAYMENT_KINDS, required=True, default="Balance"),
    Money("amount", "Amount received", required=True, min=0.01, summary=True),
    Choice("mode", "Mode", choices=C.PAYMENT_MODES),
    Text("reference_no", "Cheque / UTR / reference no"),
    Money("deduction", "TDS / other deduction", min=0, help="Information only - not counted as received."),
    Text("remarks", "Remarks"),
    Computed("customer_name", "Customer", list=True,
             sql="COALESCE((SELECT c.name FROM customers c WHERE c.id = t.customer_id), "
                 "(SELECT c.name FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE i.id = t.invoice_id), "
                 "(SELECT c.name FROM customers c JOIN work_orders w ON w.customer_id = c.id JOIN invoices i ON i.work_order_id = w.id WHERE i.id = t.invoice_id), '')"),
]


def prepare(data, old, user):
    if data.get("invoice_id") and not data.get("customer_id"):
        inv = db.q1("SELECT customer_id FROM invoices WHERE id=?", (data["invoice_id"],))
        if inv and inv.get("customer_id"):
            data["customer_id"] = inv["customer_id"]


module = Module(
    "payments", "Payment received", FIELDS, plural="Payment Received",
    label_sql="{t}.received_date || ' - Rs. ' || {t}.amount",
    access={"view": [], "create": [], "edit": [], "delete": [], "export": []},  # Admin only
    prepare=prepare,
    list_fields=["received_date", "customer_name", "invoice_id", "kind", "amount", "mode", "reference_no"],
    default_order="received_date DESC, id DESC", nav=("Accounts", 20), new_label="Record payment received",
    intro="Track payments received from customers.",
)
