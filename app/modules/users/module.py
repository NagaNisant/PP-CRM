"""users - staff accounts. Login is the e-mail address (Phase 1). Admin only."""
from app import choices as C
from app.core import db, roles as R
from app.core.auth import hash_password
from app.core.fields import Bool, Choice, Email, MultiChoice, Password, Phone, Text
from app.core.module import Module, ValidationError

FIELDS = [
    Text("full_name", "Full name", required=True),
    Email("email", "E-mail (used to log in)", required=True, unique=True),
    Choice("role", "Role", choices=R.ROLE_CHOICES, required=True),
    Phone("phone", "Mobile"),
    MultiChoice("regions", "Regions handled", choices=C.REGIONS,
                help="Engineers get the payment-collection reminders for these regions."),
    Bool("active", "Active", default=True),
    Password("password", "Password", stored=False, help="On edit, leave blank to keep the current password."),
    Text("password_hash", hidden=True),
]


def validate(data, old, user):
    if not old and not data.get("password"):
        raise ValidationError({"password": "A password is required for a new user"})


def before_save(data, old, user):
    if data.get("password"):
        data["password_hash"] = hash_password(data["password"])


def before_delete(row, user):
    if row["id"] == user["id"]:
        raise ValidationError("You cannot delete your own account - deactivate it from another admin account instead.")
    if db.q1("SELECT 1 FROM offers WHERE assigned_engineer_id=? OR created_by=? LIMIT 1", (row["id"], row["id"])):
        raise ValidationError("This user has records. Untick 'Active' instead of deleting.")


module = Module(
    "users", "User", FIELDS, plural="Users", label_sql="{t}.full_name", default_order="full_name",
    access={"view": [], "create": [], "edit": [], "delete": [], "export": []},     # admin only
    list_fields=["full_name", "email", "role", "regions", "active"],
    validate=validate, before_save=before_save, before_delete=before_delete, nav=("Admin", 90),
)
