"""
visits - engineers log customer visits.
Simplified to display an engineer list first, drill-down to engineer-specific reports,
and with all review status / approval workflows completely removed.
"""
from flask import render_template
from app import choices as C
from app.core import db, roles as R
from app.core.fields import Choice, Computed, Date, Email, Phone, Ref, Text, TextArea
from app.core.module import Module

SUGGEST = dict(url="/customers/suggest", fills={
    "customer_name": "cust_name", "address": "cust_address", "person_name": "person_name",
    "designation": "designation", "mobile": "mobile", "email": "email"})

FIELDS = [
    Date("visit_date", "Visit date", required=True, default="@today"),
    Ref("engineer_id", "Engineer", module="users", where="active=1", default="@me"),
    Ref("offer_id", "Relevant offer", module="offers", where="t.is_latest = 1", required=False),
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
    Computed("offer_no", "Offer no", sql="(SELECT o.offer_no FROM offers o WHERE o.id = t.offer_id)"),
]


def scope(user):
    # Authorized users can view visit reports across the CRM
    return None, []


def row_permission(action, user, row):
    if action == "edit":
        if R.is_admin(user):
            return True
        return row.get("engineer_id") == user["id"]
    return True


def before_save(data, old, user):
    if not old and not data.get("engineer_id"):
        data["engineer_id"] = user["id"]


def index_handler(req, user):
    """
    Main Visit Reports page displays ONLY a list of engineers who have submitted visit reports.
    Clicking an engineer drills down to all visit reports submitted by that engineer.
    """
    engineer_id = req.args.get("engineer_id")
    can_create = module.can("create", user)

    if engineer_id:
        engineer = db.q1("SELECT * FROM users WHERE id=?", (engineer_id,))
        if not engineer:
            from flask import abort
            abort(404)
        reports = db.q(
            "SELECT v.*, u.full_name as engineer_name, o.offer_no "
            "FROM visits v "
            "LEFT JOIN users u ON u.id = v.engineer_id "
            "LEFT JOIN offers o ON o.id = v.offer_id "
            "WHERE v.engineer_id=? "
            "ORDER BY v.visit_date DESC, v.id DESC",
            (engineer_id,)
        )
        return render_template("visits/engineer_reports.html", engineer=engineer, reports=reports, can_create=can_create)
    else:
        engineers = db.q(
            "SELECT u.id, u.full_name, u.email, u.role, "
            "COUNT(v.id) as report_count, "
            "MAX(v.visit_date) as last_visit_date "
            "FROM visits v "
            "JOIN users u ON u.id = v.engineer_id "
            "GROUP BY u.id, u.full_name, u.email, u.role "
            "ORDER BY last_visit_date DESC, u.full_name ASC"
        )
        return render_template("visits/engineers.html", engineers=engineers, can_create=can_create)


module = Module(
    "visits", "Visit report", FIELDS, plural="Visit reports", label_sql="{t}.customer_name || ' (' || {t}.visit_date || ')'",
    access={"view": R.ALL, "create": [R.APPLICATION, R.MARKETING], "edit": [R.APPLICATION, R.MARKETING],
            "delete": [], "export": R.ALL},
    scope=scope, row_permission=row_permission, before_save=before_save,
    comments=True, comment_roles=R.ALL,
    list_fields=["visit_date", "engineer_id", "customer_name", "person_name", "reason", "remark", "next_followup_date"],
    default_order="visit_date DESC, id DESC", nav=("Field work", 10), new_label="Enter visit",
    actions=[],
    widgets=[],
    intro="Customer visit reports submitted by engineers.",
)
module.index_handler = index_handler
