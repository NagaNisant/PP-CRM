"""assignments - Phase 2: head / admin assign an engineer to visit or call a customer on a given day; engineer gives feedback."""
from app import choices as C
from app.core import roles as R
from app.core.fields import Choice, Date, Phone, Ref, Text, TextArea
from app.core.module import Action, Module, Widget
from app.core.util import SQL_TODAY, today_iso
from app.core.widgets import rows_widget

H = [R.HEAD]
ENG_PLUS = R.ENGINEERS + [R.HEAD]
SUGGEST = dict(url="/customers/suggest", fills={"customer_name": "cust_name", "contact_person": "person_name", "phone": "mobile"})

FIELDS = [
    Ref("assigned_to", "Engineer", module="users", where="role IN (%s) AND active=1" % R.sql_in(R.ENGINEERS), required=True, roles=H, section="Assignment"),
    Date("work_date", "Day to work on it", required=True, roles=H, default="@today"),
    Choice("kind", "Visit / call", choices=C.ASSIGNMENT_TYPES, required=True, roles=H, default="Visit"),
    Text("customer_name", "Customer", required=True, roles=H, suggest=SUGGEST),
    Text("contact_person", "Contact person", roles=H),
    Phone("phone", "Phone", roles=H),
    TextArea("purpose", "What needs to be done", required=True, roles=H),
    Choice("status", "Status", choices=C.ASSIGNMENT_STATUS, default="Assigned", roles=ENG_PLUS, badge=True, section="Engineer's feedback"),
    TextArea("feedback", "Feedback on the work carried out", roles=ENG_PLUS),
    Ref("assigned_by", "Assigned by", module="users", form=False),
]


def scope(user):
    if R.is_engineer(user):
        return "assigned_to = ?", [user["id"]]


def row_permission(action, user, row):
    return action != "edit" or not R.is_engineer(user) or row["assigned_to"] == user["id"]


def before_save(data, old, user):
    if not old:
        data["assigned_by"] = user["id"]


def row_class(row):
    if row["status"] == "Assigned":
        return "row-red" if row["work_date"] < today_iso() else "row-yellow" if row["work_date"] == today_iso() else None
    return "row-green" if row["status"] == "Done" else None


def complete(row, user, data):
    module.set(row["id"], status=data["status"], feedback=data["feedback"])
    return "Marked as %s - the head can see your feedback." % data["status"].lower()


def w_mine(user):
    return rows_widget(module, user, where="status = 'Assigned' AND work_date <= " + SQL_TODAY, order="work_date",
                       columns=["work_date", "kind", "customer_name", "purpose"], cls=row_class)


module = Module(
    "assignments", "Assignment", FIELDS, plural="Visit / call assignments", label_sql="{t}.customer_name || ' (' || {t}.work_date || ')'",
    access={"view": ENG_PLUS, "create": H, "edit": ENG_PLUS, "delete": H, "export": ENG_PLUS},
    scope=scope, row_permission=row_permission, before_save=before_save, comments=True, comment_roles=ENG_PLUS,
    list_fields=["work_date", "assigned_to", "kind", "customer_name", "purpose", "status", "feedback"],
    default_order="work_date DESC, id DESC", row_class=row_class, nav=("Field work", 20), new_label="Assign work",
    actions=[Action("complete", "Mark done / give feedback", complete, roles=ENG_PLUS, style="good",
                    when=lambda r, u: r["status"] == "Assigned",
                    fields=[Choice("status", "Outcome", choices=["Done", "Could not complete"], required=True, default="Done"),
                            TextArea("feedback", "Feedback on the work carried out", required=True)])],
    widgets=[Widget("assign_mine", "Work assigned to you (today / pending)", w_mine, roles=R.ENGINEERS, order=15)],
)
