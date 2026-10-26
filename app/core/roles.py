"""
roles.py - the ONE place that defines user roles and role groups.
Modules refer to the groups below in their `access=` dictionaries.
Admin is implicitly allowed everything, so it never needs listing.
"""
ADMIN, HEAD, APPLICATION, MARKETING, ACCOUNTS, DESIGN = (
    "admin", "head", "application", "marketing", "accounts", "design")

ROLE_LABELS = {
    ADMIN: "Admin", HEAD: "Head of dept", APPLICATION: "Application",
    MARKETING: "Marketing", ACCOUNTS: "Accounts", DESIGN: "Design",
}
ROLE_CHOICES = list(ROLE_LABELS.items())          # (value, label)

ALL = "*"                                          # everybody who is logged in
ENGINEERS = [MARKETING, APPLICATION]               # field engineers (get assignments, visits, reminders)
APPROVERS = [HEAD]                                 # head (+ admin) review / approve / assign
ACCOUNTS_TEAM = [ACCOUNTS]
OFFICE_STAFF = [HEAD, MARKETING, APPLICATION]      # may create offers, orders, customers


def role_of(user):
    return (user or {}).get("role")


def is_admin(user):
    return role_of(user) == ADMIN


def is_engineer(user):
    return role_of(user) in ENGINEERS


def has_role(user, roles):
    """True if user's role is in roles (admin always passes; roles == ALL passes everyone)."""
    if not user:
        return False
    if user.get("role") == ADMIN or roles == ALL:
        return True
    return user.get("role") in (roles or [])


def sql_in(roles):
    return ",".join("'%s'" % r for r in roles)


def user_regions(user):
    return [r for r in (user.get("regions") or "").split(",") if r]
