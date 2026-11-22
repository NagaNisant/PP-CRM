"""
invoices - dispatches, invoices, and payment tracking backing Receivables as of Today.
Internal records kept for backward compatibility and calculation of receivables.
"""
from flask import flash
from app import choices as C
from app.core import db, roles as R
from app.core.fields import (Choice, Computed, Date, File, Int, Money, Ref, Text, TextArea)
from app.core.module import Module, ValidationError
from config import Config

SOON = Config.DUE_SOON_DAYS
STATUSES = ["Received", "Overdue / due now", "Due within a week", "Not yet due", "Awaiting delivery"]

AMOUNT = "COALESCE(t.gross_value, t.net_value, 0)"
RECEIVED = "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = t.id), 0)"
BASE_DATE = "COALESCE(t.delivery_date, t.grn_date, t.pod_date, t.lr_date, t.packing_slip_date, t.invoice_date)"
DUE = "CASE WHEN t.due_date IS NOT NULL THEN t.due_date WHEN (%s) IS NULL THEN NULL ELSE date((%s), '+30 days') END" % (BASE_DATE, BASE_DATE)
TODAY = "date('now','localtime')"
STATUS_SQL = """CASE WHEN %s - %s <= 0.5 THEN 'Received'
                     WHEN (%s) IS NULL THEN 'Awaiting delivery'
                     WHEN (%s) <= %s THEN 'Overdue / due now'
                     WHEN (%s) <= date('now','localtime','+%d days') THEN 'Due within a week'
                     ELSE 'Not yet due' END""" % (AMOUNT, RECEIVED, DUE, DUE, TODAY, DUE, SOON)

FIELDS = [
    Ref("customer_id", "Customer", module="customers"),
    Int("work_order_id", hidden=True),

    Choice("invoice_type", "Invoice type", choices=C.INVOICE_TYPES, required=True, default="Tax invoice", section="Invoice"),
    Text("invoice_no", "Invoice no", required=True),
    Date("invoice_date", "Invoice date", required=True),
    Date("due_date", "Payment due date"),
    Money("net_value", "Invoice value (net)", required=True, min=0, summary=True),
    Money("gross_value", "Invoice value (gross)", required=True, min=0, summary=True),
    File("invoice_pdf", "Invoice (PDF)"),
    Choice("supply_type", "Full / part supply", choices=C.SUPPLY_TYPES, default="Full supply"),

    Date("packing_slip_date", "Packing slip date", section="Delivery & transport"),
    Text("transporter", "Transporter"),
    Text("lr_no", "LR no"),
    Date("lr_date", "LR date"),
    Date("delivery_date", "Date of delivery of material"),
    TextArea("remarks", "Remarks"),

    # ---- computed columns ----
    Computed("customer_name", "Customer", list=True,
             sql="COALESCE((SELECT c.name FROM customers c WHERE c.id = t.customer_id), "
                 "(SELECT c.name FROM customers c JOIN work_orders w ON w.customer_id = c.id WHERE w.id = t.work_order_id), '')"),
    Computed("received", "Total received", sql=RECEIVED, value="money", list=True, summary=True),
    Computed("outstanding", "Balance outstanding", sql="%s - %s" % (AMOUNT, RECEIVED), value="money", list=True, summary=True),
    Computed("payment_status", "Payment status", sql=STATUS_SQL, value="choice", choices=STATUSES, list=True, badge=True),
]


def row_class(row):
    return {"Received": "row-green", "Due within a week": "row-yellow", "Overdue / due now": "row-red"}.get(row.get("payment_status"))


module = Module(
    "invoices", "Invoice", FIELDS, plural="Invoices",
    label_sql="{t}.invoice_no",
    access={"view": [], "create": [], "edit": [], "delete": [], "export": []},  # Admin only
    row_class=row_class,
    list_fields=["customer_name", "invoice_no", "invoice_date", "gross_value", "received", "outstanding", "due_date", "payment_status"],
    default_order="invoice_date DESC, id DESC", nav=None,
    intro="Invoices backing receivables calculations.",
)
from app.core.module import Related
module.related.append(Related("payments", "invoice_id", "Payments received", add_label="Record payment",
                              columns=["received_date", "kind", "amount", "mode", "reference_no"]))
