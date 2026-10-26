"""
invoices - Phase 4: packing slip, invoice, LR, e-way bill, GRN, POD for each dispatch of a work order,
the payment master (Excel), due dates and the red / yellow / green colour coding.
All due-date logic is in the SQL expressions below - change reminder rules here only.
"""
from flask import flash
from app import choices as C
from app.core import db, roles as R
from app.core.fields import (Choice, Computed, Date, File, Int, Money, Ref, Text, TextArea)
from app.core.module import Module, ValidationError, Widget
from app.core.widgets import rows_widget
from app.modules.work_orders.module import refresh_lock, wo_scope
from config import Config

SOON = Config.DUE_SOON_DAYS
STATUSES = ["Received", "Overdue / due now", "Due within a week", "Not yet due", "Awaiting delivery"]


def WO(col):
    return "(SELECT w.%s FROM work_orders w WHERE w.id = t.work_order_id)" % col


AMOUNT = "COALESCE(t.gross_value, t.net_value, 0)"
RECEIVED = "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = t.id), 0)"
BASE_DATE = """CASE %s WHEN 'Date of delivery' THEN t.delivery_date WHEN 'GRN date' THEN t.grn_date
               WHEN 'POD date' THEN t.pod_date WHEN 'Date of dispatch (LR)' THEN COALESCE(t.lr_date, t.packing_slip_date)
               ELSE t.invoice_date END""" % WO("credit_basis")
DUE = "CASE WHEN (%s) IS NULL THEN NULL ELSE date((%s), '+' || COALESCE(%s, 0) || ' days') END" % (BASE_DATE, BASE_DATE, WO("credit_days"))
TODAY = "date('now','localtime')"
STATUS_SQL = """CASE WHEN %s - %s <= 0.5 THEN 'Received'
                     WHEN (%s) IS NULL THEN 'Awaiting delivery'
                     WHEN (%s) <= %s THEN 'Overdue / due now'
                     WHEN (%s) <= date('now','localtime','+%d days') THEN 'Due within a week'
                     ELSE 'Not yet due' END""" % (AMOUNT, RECEIVED, DUE, DUE, TODAY, DUE, SOON)

FIELDS = [
    Ref("work_order_id", "Work order", module="work_orders", where="t.dispatch_enabled = 1", required=True),

    Choice("invoice_type", "Invoice type", choices=C.INVOICE_TYPES, required=True, default="Tax invoice", section="Packing slip & invoice"),
    Date("packing_slip_date", "Packing slip date"),
    File("packing_slip_scan", "Packing slip scan", accept=(".pdf", ".jpg", ".jpeg", ".png")),
    Text("invoice_no", "Invoice no", required=True),
    Date("invoice_date", "Invoice date", required=True),
    Money("net_value", "Invoice value (net)", required=True, min=0, summary=True),
    Money("gross_value", "Invoice value (gross)", required=True, min=0, summary=True),
    File("invoice_pdf", "Invoice (PDF)"),
    Choice("supply_type", "Full / part supply", choices=C.SUPPLY_TYPES, required=True,
           help="Left blank, it is worked out from the work-order value vs. invoices raised."),

    Text("transporter", "Transporter", section="Transport & documents"),
    Text("lr_no", "LR no"),
    Date("lr_date", "LR date"),
    Text("lr_type", "LR type / documents", placeholder="e.g. To pay, DD & CC attached"),
    File("lr_pdf", "LR (PDF)"),
    Text("eway_no", "E-way bill (E-Sugam) no"),
    Date("eway_date", "E-way bill date"),
    File("eway_pdf", "E-way bill (PDF)"),

    Date("delivery_date", "Date of delivery of material", section="Delivery, GRN & POD"),
    Text("grn_no", "GRN no (where applicable)"),
    Date("grn_date", "GRN date"),
    Date("pod_date", "POD received on"),
    Text("pod_details", "POD details"),
    File("pod_snapshot", "POD snapshot", accept=(".pdf", ".jpg", ".jpeg", ".png")),

    Money("retention_value", "Retention value", min=0, section="Retention & guarantee"),
    Choice("bg_type", "BG type", choices=C.BG_TYPES),
    Text("bg_number", "BG number"),
    Date("bg_date", "BG date"),
    Date("bg_expiry", "BG expiry date"),
    TextArea("remarks", "Remarks"),

    # ---- auto-filled from the work order / payments (read-only, filterable, exported) ----
    Computed("wo_no", "Work order", sql=WO("wo_no"), list=True),
    Computed("customer_name", "Customer", list=True,
             sql="(SELECT c.name FROM customers c WHERE c.id = %s)" % WO("customer_id")),
    Computed("po_no", "PO no", sql=WO("po_no"), list=True),
    Computed("po_date", "PO date", sql=WO("po_date"), value="date"),
    Computed("payment_terms", "Payment terms", sql=WO("payment_terms")),
    Computed("inspection", "Inspection", sql=WO("inspection")),
    Computed("oa_no", "OA no", sql=WO("oa_no")),
    Computed("offer_no", "Offer no", sql="(SELECT o.offer_no FROM offers o WHERE o.id = %s)" % WO("offer_id")),
    Computed("region", "Region", sql=WO("region"), value="choice", choices=C.REGIONS, list=True),
    Computed("engineer_id", "Engineer id", sql=WO("engineer_id"), value="int", filter=False, export=False),
    Computed("engineer_name", "Engineer", sql="(SELECT u.full_name FROM users u WHERE u.id = %s)" % WO("engineer_id")),
    Computed("wo_net_value", "WO value (net)", sql=WO("po_value_net"), value="money"),
    Computed("advance_received", "Advance received", value="money",
             sql="COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = t.id AND p.kind='Advance'),0)"),
    Computed("balance_received", "Balance payments received", value="money",
             sql="COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = t.id AND p.kind!='Advance'),0)"),
    Computed("received", "Total received", sql=RECEIVED, value="money", list=True, summary=True),
    Computed("outstanding", "Balance outstanding", sql="%s - %s" % (AMOUNT, RECEIVED), value="money", list=True, summary=True),
    Computed("due_date", "Payment due on", sql=DUE, value="date", list=True),
    Computed("payment_status", "Payment status", sql=STATUS_SQL, value="choice", choices=STATUSES, list=True, badge=True),
]


def scope(user):
    sql, params = wo_scope(user, "w")
    if sql:
        regs = R.user_regions(user)
        s = "engineer_id = ?" + (" OR region IN (%s)" % ",".join("?" * len(regs)) if regs else "")
        return s, [user["id"]] + regs


def _locked(wo_id):
    r = db.q1("SELECT locked FROM work_orders WHERE id=?", (wo_id,))
    return bool(r and r["locked"])


def row_permission(action, user, row):
    if action in ("edit", "delete") and _locked(row["work_order_id"]):
        return user["role"] == R.HEAD
    return True


def prepare(data, old, user):
    wo = db.q1("SELECT po_value_net FROM work_orders WHERE id=?", (data.get("work_order_id"),))
    if wo and wo["po_value_net"] and not data.get("supply_type") and data.get("net_value") is not None:
        before = db.q1("SELECT COALESCE(SUM(net_value),0) s FROM invoices WHERE work_order_id=? AND id != ?",
                       (data["work_order_id"], old["id"] if old else 0))["s"]
        data["supply_type"] = "Full supply" if before + data["net_value"] >= wo["po_value_net"] - 0.5 else "Part supply"


def validate(data, old, user):
    if data.get("gross_value") is not None and data.get("net_value") is not None and data["gross_value"] < data["net_value"]:
        raise ValidationError({"gross_value": "Gross value cannot be less than net value"})
    if not _wo_started(data["work_order_id"]):
        raise ValidationError({"work_order_id": "Start dispatch & accounts on the work order first"})
    if _locked(data["work_order_id"]) and user["role"] not in (R.HEAD, R.ADMIN):
        raise ValidationError({"work_order_id": "This work order is locked - only the head / admin can change it"})
    dup = db.q1("SELECT id FROM invoices WHERE work_order_id=? AND invoice_no=? AND id != ?",
                (data["work_order_id"], data["invoice_no"], old["id"] if old else 0))
    if dup:
        raise ValidationError({"invoice_no": "This invoice no is already recorded for the work order"})


def _wo_started(wo_id):
    r = db.q1("SELECT dispatch_enabled FROM work_orders WHERE id=?", (wo_id,))
    return bool(r and r["dispatch_enabled"])


def after_save(row, old, user):
    refresh_lock(row["work_order_id"])
    wo = db.q1("SELECT po_value_net FROM work_orders WHERE id=?", (row["work_order_id"],))
    inv = db.q1("SELECT COALESCE(SUM(net_value),0) s FROM invoices WHERE work_order_id=?", (row["work_order_id"],))["s"]
    if wo and wo["po_value_net"]:
        full = inv >= wo["po_value_net"] - 0.5
        if full and row["supply_type"] == "Part supply":
            flash("Invoices now cover the full WO value - you marked this as part supply, please check.", "warning")
        elif not full and row["supply_type"] == "Full supply":
            flash("Invoices (%.2f) are still below the WO value (%.2f) - this looks like a part supply; "
                  "add the next invoice when the balance is dispatched." % (inv, wo["po_value_net"]), "warning")


def after_delete(row, user):
    refresh_lock(row["work_order_id"])


def panel(ctx, user):
    """Auto-fill block: what the accounts team sees about the order while entering an invoice."""
    wo_id = ctx.get("work_order_id")
    w = db.q1("SELECT w.*, c.name cname, c.address caddr, o.offer_no, u.full_name eng FROM work_orders w "
              "LEFT JOIN customers c ON c.id=w.customer_id LEFT JOIN offers o ON o.id=w.offer_id "
              "LEFT JOIN users u ON u.id=w.engineer_id WHERE w.id=?", (wo_id,)) if wo_id else None
    if not w:
        return None
    from app.core.util import fmt_date, fmt_money
    return [("Customer", "%s, %s" % (w["cname"], w["caddr"] or "")), ("PO no / date", "%s / %s" % (w["po_no"], fmt_date(w["po_date"]))),
            ("Payment terms", w["payment_terms"]), ("Price terms", w["price_basis"]),
            ("Packing & forwarding", w["packing_forwarding"] or "-"), ("Offer no", w["offer_no"]), ("Region", w["region"]),
            ("Engineer", w["eng"]), ("OA no", w["oa_no"]), ("WO value (net)", fmt_money(w["po_value_net"])),
            ("Credit", "%s days from %s" % (w["credit_days"], w["credit_basis"]))]


def row_class(row):
    return {"Received": "row-green", "Due within a week": "row-yellow", "Overdue / due now": "row-red"}.get(row["payment_status"])


COLS = ["customer_name", "invoice_no", "outstanding", "due_date", "payment_status"]


def w_collect(user):
    return rows_widget(module, user, columns=COLS, order="due_date", cls=row_class,
                       where="payment_status IN ('Overdue / due now', 'Due within a week')")


def w_receivable(user):
    res = module.query(user, where="payment_status = 'Overdue / due now'")
    from app.core.util import fmt_money
    total = sum(x["outstanding"] for x in res["rows"])
    return {"stats": [("invoices due now", res["total"]), ("receivable today", fmt_money(total))]}


ALL_VIEW = [R.HEAD, R.ACCOUNTS, *R.ENGINEERS]

module = Module(
    "invoices", "Dispatch / invoice", FIELDS, plural="Payment master (dispatch & invoices)",
    label_sql="{t}.invoice_no || ' / ' || COALESCE((SELECT w.wo_no FROM work_orders w WHERE w.id = {t}.work_order_id), '')",
    access={"view": ALL_VIEW, "create": [R.ACCOUNTS, R.HEAD], "edit": [R.ACCOUNTS, R.HEAD], "delete": [],
            "export": [R.ACCOUNTS, R.HEAD, *R.ENGINEERS]},
    scope=scope, row_permission=row_permission, prepare=prepare, validate=validate, after_save=after_save,
    after_delete=after_delete, panel=panel, row_class=row_class, comments=True, comment_roles=ALL_VIEW,
    list_fields=["wo_no", "customer_name", "po_no", "region", "invoice_no", "invoice_date", "gross_value", "supply_type",
                 "received", "outstanding", "due_date", "payment_status"],
    export_fields=["wo_no", "customer_name", "po_no", "po_date", "payment_terms", "region", "inspection", "packing_slip_date",
                   "invoice_no", "invoice_date", "net_value", "gross_value", "supply_type", "advance_received", "balance_received",
                   "outstanding", "transporter", "lr_no", "lr_type", "lr_date", "delivery_date", "grn_no", "grn_date",
                   "pod_date", "retention_value", "bg_type", "bg_number", "bg_date", "bg_expiry", "due_date",
                   "payment_status", "remarks"],
    default_order="invoice_date DESC, id DESC", nav=("Accounts", 10), new_label="Add dispatch / invoice",
    related=[],
    widgets=[
        Widget("pay_collect", "Payments to follow up (due / overdue / due this week)", w_collect, roles=ALL_VIEW, order=8),
        Widget("pay_receivable", "Receivable as of today", w_receivable, roles=[R.ACCOUNTS, R.HEAD], digest=False, order=6),
    ],
    intro="The master sheet: colour coding - green payment received, yellow due within a week, red due now / overdue.",
)
from app.core.module import Related
module.related.append(Related("payments", "invoice_id", "Payments received", add_label="Record payment",
                              columns=["received_date", "kind", "amount", "mode", "reference_no"]))
