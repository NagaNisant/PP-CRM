"""
customers - the customer database (Phase 1).

Also exports the reusable "customer block" used by offers and work orders:
  customer_block()  -> the form fields (name, address, contact person ...)
  resolve_customer() -> finds-or-creates the customer + contact so no duplicates are created
  customer_values()  -> reloads the block when a record is edited
"""
from app.core import db, roles as R
from app.core.excel import xlsx_response
from app.core.fields import Choice, Computed, Email, Int, Phone, Text, TextArea
from app.core.module import Child, Module
from app import choices as C

SUGGEST = dict(url="/customers/suggest", fills={k: k for k in (
    "cust_name", "cust_address", "person_name", "designation", "mobile", "landline", "email")})


def customer_block(section="Customer & contact person"):
    """Virtual (not stored on the record) fields; resolve_customer() turns them into customer + contact rows."""
    return [
        Text("cust_name", "Customer name", required=True, stored=False, section=section, suggest=SUGGEST,
             help="Start typing - existing customers are suggested so you do not create duplicates."),
        TextArea("cust_address", "Customer address", required=True, stored=False, section=section),
        Text("person_name", "Contact person", required=True, stored=False, section=section, suggest=SUGGEST),
        Text("designation", "Designation", required=True, stored=False, section=section),
        Phone("mobile", "Mobile no", required=True, stored=False, section=section),
        Phone("landline", "Landline no", stored=False, section=section),
        Email("email", "E-mail id", required=True, stored=False, section=section, suggest=SUGGEST),
    ]


def resolve_customer(data, user_id, region=None):
    """Find-or-create the customer and contact described by the block. Returns (customer_id, contact_id)."""
    name = " ".join((data.get("cust_name") or "").split())
    cust = db.q1("SELECT id FROM customers WHERE lower(trim(name)) = lower(?)", (name,))
    cid = cust["id"] if cust else module.insert(
        {"name": name, "address": data.get("cust_address"), "region": region}, user_id)
    contact = contacts_child()
    vals = {k: data.get(k) for k in ("person_name", "designation", "mobile", "landline", "email")}
    hit = db.q1('SELECT id FROM customers_contacts WHERE customers_id=? AND (lower(email)=lower(?) OR lower(person_name)=lower(?))',
                (cid, vals["email"] or "", vals["person_name"] or ""))
    if hit:
        module.child_update(contact, hit["id"], vals)
        return cid, hit["id"]
    return cid, module.child_insert(contact, cid, vals)


def customer_values(row):
    """Values for the virtual block of an existing record (row has customer_id / contact_id)."""
    out = {}
    c = db.q1("SELECT * FROM customers WHERE id=?", (row.get("customer_id"),))
    if c:
        out.update(cust_name=c["name"], cust_address=c["address"])
    k = db.q1("SELECT * FROM customers_contacts WHERE id=?", (row.get("contact_id"),))
    if k:
        out.update({x: k[x] for x in ("person_name", "designation", "mobile", "landline", "email")})
    return out


def contacts_child():
    return module.children[0]


FIELDS = [
    Text("name", "Customer name", required=True, unique=True),
    TextArea("address", "Address", required=True),
    Choice("region", "Region", choices=C.REGIONS),
    Computed("offer_count", "Offers", sql="(SELECT COUNT(*) FROM offers o WHERE o.customer_id = t.id)", value="int", list=True),
    Computed("order_count", "Orders", sql="(SELECT COUNT(*) FROM work_orders w WHERE w.customer_id = t.id)", value="int", list=True),
]

CONTACTS = Child("contacts", "Contact persons", [
    Text("person_name", "Name", required=True),
    Text("designation", "Designation", required=True),
    Phone("mobile", "Mobile", required=True),
    Phone("landline", "Landline"),
    Email("email", "E-mail", required=True),
], min_rows=1, add_label="Add contact person")


def prepare(data, old, user):
    if data.get("name"):
        data["name"] = " ".join(data["name"].split())


def export_override(user, args):
    """Master customer database: one Excel row per contact person (admin only - see access below)."""
    rows = db.q("SELECT c.name, c.address, c.region, k.person_name, k.designation, k.mobile, k.landline, k.email "
                "FROM customers c LEFT JOIN customers_contacts k ON k.customers_id = c.id ORDER BY c.name, k.id")
    headers = ["Customer", "Address", "Region", "Contact person", "Designation", "Mobile", "Landline", "E-mail"]
    return headers, [list(r.values()) for r in rows]


def routes(bp):
    from flask import jsonify, request

    @bp.route("/suggest")
    def suggest():
        q = (request.args.get("q") or "").strip()
        col = {"cust_name": "c.name", "cust_address": "c.address", "person_name": "k.person_name",
               "email": "k.email", "mobile": "k.mobile"}.get(request.args.get("field"), "c.name")
        rows = db.q('SELECT c.name, c.address, k.person_name, k.designation, k.mobile, k.landline, k.email '
                    'FROM customers c LEFT JOIN customers_contacts k ON k.customers_id = c.id '
                    'WHERE %s LIKE ? ORDER BY c.name LIMIT 12' % col, ("%" + q + "%",))
        return jsonify([dict(
            label=" - ".join(x for x in (r["name"], r["person_name"], r["email"]) if x),
            cust_name=r["name"], cust_address=r["address"], person_name=r["person_name"], designation=r["designation"],
            mobile=r["mobile"], landline=r["landline"], email=r["email"]) for r in rows])


module = Module(
    "customers", "Customer", FIELDS, children=[CONTACTS], plural="Customers",
    access={"view": R.ALL, "create": R.OFFICE_STAFF, "edit": R.OFFICE_STAFF, "delete": [], "export": []},
    list_fields=["name", "address", "region", "offer_count", "order_count"],
    default_order="name COLLATE NOCASE", prepare=prepare, export_override=export_override,
    routes=routes, nav=("Sales", 5),
    intro="The master customer database. Customers are created automatically when an offer is entered; "
          "only the admin can download the full database.",
)
