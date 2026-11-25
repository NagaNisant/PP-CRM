"""
payments_made - track money paid out by the company (vendors, expenses, taxes, utilities).
Retained under Accounts module: Payment Made.
"""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Date, File, Money, Text, TextArea
from app.core.module import Module

PAYMENT_MADE_CATEGORIES = [
    "Vendor / Supplier",
    "Raw Material",
    "Services & Maintenance",
    "Salary & Wages",
    "Rent & Utilities",
    "Statutory & Taxes",
    "Logistics & Transport",
    "Office & Administrative",
    "Other",
]

FIELDS = [
    Date("payment_date", "Payment date", required=True, default="@today"),
    Text("paid_to", "Paid to (Vendor / Payee)", required=True),
    Choice("category", "Payment category", choices=PAYMENT_MADE_CATEGORIES, required=True),
    Money("amount", "Amount paid (INR)", required=True, min=0.01, summary=True),
    Choice("mode", "Payment mode", choices=C.PAYMENT_MODES, required=True, default="NEFT"),
    Text("reference_no", "Cheque / UTR / Reference no"),
    TextArea("remarks", "Description / Purpose"),
    File("receipt_pdf", "Receipt / Voucher (PDF/Image)", accept=(".pdf", ".jpg", ".jpeg", ".png")),
]

module = Module(
    "payments_made", "Payment made", FIELDS, plural="Payment Made",
    label_sql="{t}.paid_to || ' - Rs. ' || {t}.amount || ' (' || {t}.payment_date || ')'",
    access={"view": [], "create": [], "edit": [], "delete": [], "export": []},
    list_fields=["payment_date", "paid_to", "category", "amount", "mode", "reference_no", "receipt_pdf"],
    default_order="payment_date DESC, id DESC", nav=None, new_label="Record payment made",
    intro="Track payments made by the company to vendors, suppliers, and for statutory/operational expenses.",
)
