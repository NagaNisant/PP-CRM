"""visits - Phase 2: engineers log customer visits in real time; head / admin review and comment."""
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Date, Email, Phone, Ref, Text, TextArea
from app.core.module import Action, Module, Widget
from app.core.widgets import rows_widget

SUGGEST = dict(url="/customers/suggest", fills={
    "customer_name": "cust_name", "address": "cust_address", "person_name": "person_name",
    "designation": "designation", "mobile": "mobile", "email": "email"})

FIELDS = [
    Date("visit_date", "Visit date", required=True, default="@today"),
    Ref("engineer_id", "Engineer", module="users", where="active=1", default="@me", roles=[R.HEAD]),
    Text("customer_name", "Customer name", required=True, suggest=SUGGEST, section="Customer visited"),
    TextArea("address", "Customer address", required=True),
    Text("person_name", "Person visited", required=True, section="Person met"),
    Text("designation", "Designation"),
    Phone("mobile", "Mobile no"),
    Email("email", "E-mail id"),
    Text("reason", "Reason of visit", required=True, section="Visit report"),
    TextArea("remark", "Remark / conclusion of visit", required=True),
    Date("next_followup_date", "Next date of follow-up"),
    Choice("followup_mode", "Mode of follow-up required", choices=C.FOLLOWUP_MODES),
    Choice("review_status", "Review status", choices=C.VISIT_REVIEW, default="Pending", roles=[], badge=True, section="Head / admin review"),
]


def scope(user):
    if R.is_engineer(user):
        return "engineer_id = ?", [user["id"]]


def row_permission(action, user, row):
    if action == "edit" and R.is_engineer(user):         # engineers fix their own report until it is reviewed
        return row["engineer_id"] == user["id"] and row["review_status"] == "Pending"
    return True


def review(row, user, data):
    db.execute("UPDATE visits SET review_status=? WHERE id=?", (data["review_status"], row["id"]))
    if data.get("comment"):
        db.execute("INSERT INTO comments(entity,entity_id,user_id,body,created_at) VALUES('visits',?,?,?,datetime('now'))",
                   (row["id"], user["id"], data["comment"]))
    return "Review saved."


def w_review(user):
    return rows_widget(module, user, where="review_status = 'Pending'", order="visit_date",
                       columns=["visit_date", "engineer_id", "customer_name", "reason"])


def w_action(user):
    return rows_widget(module, user, where="review_status = 'Action required'", order="visit_date",
                       columns=["visit_date", "customer_name", "reason", "next_followup_date"], cls="row-yellow")


module = Module(
    "visits", "Visit report", FIELDS, plural="Visit reports", label_sql="{t}.customer_name || ' (' || {t}.visit_date || ')'",
    access={"view": [R.HEAD, *R.ENGINEERS], "create": R.ENGINEERS + [R.HEAD], "edit": R.ENGINEERS + [R.HEAD],
            "delete": [], "export": [R.HEAD, *R.ENGINEERS]},
    scope=scope, row_permission=row_permission, comments=True, comment_roles=[R.HEAD, *R.ENGINEERS],
    list_fields=["visit_date", "engineer_id", "customer_name", "person_name", "reason", "remark", "next_followup_date", "review_status"],
    default_order="visit_date DESC, id DESC", nav=("Field work", 10), new_label="Enter visit",
    actions=[Action("review", "Review", review, roles=[R.HEAD], style="primary", fields=[
        Choice("review_status", "Review outcome", choices=["Reviewed", "Action required"], required=True),
        TextArea("comment", "Comments / further work to be done")])],
    widgets=[
        Widget("visits_review", "Visit reports awaiting your review", w_review, roles=[R.HEAD], order=20, digest=False),
        Widget("visits_action", "Visits where the head asked for action", w_action, roles=R.ENGINEERS, order=21),
    ],
)
