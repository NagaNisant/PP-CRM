"""tour_expenses - Phase 2: TA/DA claim with bills (PDF) -> head/admin approve -> assigned to Accounts for filing."""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Computed, Date, File, Money, Ref, Text, TextArea
from app.core.module import Action, Child, Module, Widget
from app.core.util import today_iso
from app.core.widgets import rows_widget

H = [R.HEAD]
TOTAL_SQL = ("(SELECT COALESCE(SUM(COALESCE(l.boarding_lodging,0) + COALESCE(l.communication,0) + COALESCE(l.conveyance,0)"
             " + COALESCE(l.misc,0)),0) FROM tour_expenses_lines l WHERE l.tour_expenses_id = t.id)")

FIELDS = [
    Ref("engineer_id", "Claimant", module="users", where="active=1", default="@me", roles=H),
    Date("claim_date", "Bill date", required=True, default="@today"),
    Date("tour_from", "Tour from", required=True),
    Date("tour_to", "Tour to", required=True),
    TextArea("purpose", "Purpose of tour", required=True),
    Computed("total", "Total claimed", sql=TOTAL_SQL, value="money", list=True, summary=True),
    Choice("status", "Status", choices=C.EXPENSE_STATUS, default="Submitted", roles=[], badge=True, section="Approval & filing"),
    Money("passed_amount", "Passed for Rs.", roles=[], summary=True),
    Text("approval_remarks", "Approval remarks", roles=[]),
    Ref("approved_by", "Approved / rejected by", module="users", form=False),
    Date("approved_on", "Decision date", roles=[]),
    Text("filing_ref", "Accounts filing reference", roles=[]),
    Date("filed_on", "Filed on", roles=[]),
]

LINES = Child("lines", "Expense lines (as per the TA/DA format)", [
    Date("line_date", "Date", required=True),
    Text("place", "Travel duration & place", required=True),
    Money("boarding_lodging", "Boarding & lodging", min=0),
    Money("communication", "P&T / calls / courier", min=0),
    Money("conveyance", "Train / bus / plane / bike", min=0),
    Money("misc", "Misc (entertainment, cooly...)", min=0),
    File("bill_pdf", "Bill (PDF)"),
], min_rows=1, add_label="Add expense line")


def scope(user):
    if R.is_engineer(user):
        return "engineer_id = ?", [user["id"]]
    if user["role"] == R.ACCOUNTS:                         # accounts only see what has been approved for them
        return "status IN ('Approved - with Accounts', 'Filed')", []


def row_permission(action, user, row):
    if action == "edit" and R.is_engineer(user):
        return row["engineer_id"] == user["id"] and row["status"] in ("Submitted", "Rejected")
    return True


def validate(data, old, user):
    from app.core.module import ValidationError
    if data["tour_to"] < data["tour_from"]:
        raise ValidationError({"tour_to": "'Tour to' cannot be before 'Tour from'"})


# ----- workflow ---------------------------------------------------------------
def approve(row, user, data):
    module.set(row["id"], status="Approved - with Accounts", passed_amount=data["passed_amount"], approval_remarks=data.get("remarks"),
               approved_by=user["id"], approved_on=today_iso())
    return "Approved for Rs. %s and assigned to Accounts for filing." % data["passed_amount"]


def reject(row, user, data):
    module.set(row["id"], status="Rejected", approval_remarks=data["remarks"], approved_by=user["id"], approved_on=today_iso())
    return "Claim sent back to the engineer."


def resubmit(row, user, data):
    module.set(row["id"], status="Submitted")
    return "Claim re-submitted for approval."


def file_it(row, user, data):
    module.set(row["id"], status="Filed", filing_ref=data.get("filing_ref"), filed_on=today_iso())
    return "Claim marked as filed."


def w_approval(user):
    return rows_widget(module, user, where="status = 'Submitted'", order="claim_date",
                       columns=["claim_date", "engineer_id", "purpose", "total"])


def w_filing(user):
    return rows_widget(module, user, where="status = 'Approved - with Accounts'", order="approved_on",
                       columns=["approved_on", "engineer_id", "purpose", "passed_amount"])


module = Module(
    "tour_expenses", "Tour expense claim", FIELDS, children=[LINES], plural="Tour expense claims",
    label_sql="'Claim #' || {t}.id || ' - ' || COALESCE((SELECT full_name FROM users u WHERE u.id = {t}.engineer_id),'')",
    access={"view": R.ENGINEERS + [R.HEAD, R.ACCOUNTS], "create": R.ENGINEERS + [R.HEAD], "edit": R.ENGINEERS + [R.HEAD],
            "delete": [], "export": [R.HEAD, R.ACCOUNTS]},
    scope=scope, row_permission=row_permission, validate=validate, comments=True,
    comment_roles=R.ENGINEERS + [R.HEAD, R.ACCOUNTS],
    list_fields=["claim_date", "engineer_id", "tour_from", "tour_to", "purpose", "total", "status", "passed_amount"],
    default_order="claim_date DESC, id DESC", nav=("Field work", 30), new_label="New claim",
    actions=[
        Action("approve", "Approve & send to Accounts", approve, roles=H, style="good", when=lambda r, u: r["status"] == "Submitted",
               fields=[Money("passed_amount", "Passed for Rs.", required=True), Text("remarks", "Remarks")],
               prefill=lambda r, u: {"passed_amount": r["total"]}),
        Action("reject", "Reject", reject, roles=H, style="danger", when=lambda r, u: r["status"] == "Submitted",
               fields=[Text("remarks", "Reason for rejection", required=True)]),
        Action("resubmit", "Re-submit", resubmit, roles=R.ENGINEERS, when=lambda r, u: r["status"] == "Rejected"),
        Action("file", "Mark as filed", file_it, roles=[R.ACCOUNTS, R.HEAD], style="primary",
               when=lambda r, u: r["status"] == "Approved - with Accounts", fields=[Text("filing_ref", "Filing reference / voucher no")]),
    ],
    widgets=[
        Widget("exp_approve", "Expense claims awaiting your approval", w_approval, roles=[R.HEAD], order=30),
        Widget("exp_file", "Approved claims to be filed", w_filing, roles=[R.ACCOUNTS], order=30),
    ],
)
