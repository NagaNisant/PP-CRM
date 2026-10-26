"""End-to-end smoke test: python -m pytest -q  (or python tests/test_smoke.py)"""
import io
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import create_app
from app.core import db, digest
from app.core.auth import hash_password


def pdf(name="a.pdf"):
    return (io.BytesIO(b"%PDF-1.4 test"), name)


def make_app():
    d = tempfile.mkdtemp()
    return create_app({"DATABASE": d + "/t.db", "UPLOAD_DIR": d + "/u", "OUTBOX_DIR": d + "/o", "TESTING": True,
                       "ENABLE_SCHEDULER": False})


class Client:
    def __init__(self, app, email):
        self.c = app.test_client()
        self.c.post("/login", data={"email": email, "password": "Passw0rd!"}, headers={})
        # first POST has no csrf -> 400; set token then login
        with self.c.session_transaction() as s:
            s["_csrf"] = "tok"
        r = self.c.post("/login", data={"email": email, "password": "Passw0rd!", "_csrf": "tok"})
        assert r.status_code == 302, (email, r.status_code)
        with self.c.session_transaction() as s:      # login clears the session -> set a fresh token
            s["_csrf"] = "tok"

    def get(self, url, ok=200):
        r = self.c.get(url, follow_redirects=True)
        assert r.status_code == ok, (url, r.status_code, r.data[:300])
        return r

    def post(self, url, data=None, ok=(302,)):
        data = dict(data or {}, _csrf="tok")
        r = self.c.post(url, data=data, content_type="multipart/form-data")
        assert r.status_code in ok, (url, r.status_code, r.data.decode()[:1500])
        return r


def test_everything():
    app = make_app()
    with app.app_context():
        for email, name, role, regions in [("admin@x.com", "Admin", "admin", None), ("head@x.com", "Head", "head", None),
                                           ("eng@x.com", "Ravi Engineer", "marketing", "Karnataka"),
                                           ("acc@x.com", "Accounts Girl", "accounts", None)]:
            db.execute("INSERT INTO users(full_name,email,role,active,regions,password_hash) VALUES(?,?,?,?,?,?)",
                       (name, email, role, 1, regions, hash_password("Passw0rd!")))
        db.get_db().commit()
    admin, head, eng, acc = (Client(app, e) for e in ("admin@x.com", "head@x.com", "eng@x.com", "acc@x.com"))

    # ---- Phase 1: offer entry; missing mandatory customer data is rejected
    r = eng.post("/offers/new", {"offer_no": "0972"}, ok=(200,))
    assert b"required" in r.data
    today = date.today().isoformat()
    base = {"cust_name": "Acme Pumps Ltd", "cust_address": "Plot 4, Peenya, Bengaluru", "person_name": "Suresh",
            "designation": "Purchase Manager", "mobile": "9845012345", "email": "suresh@acme.com",
            "offer_no": "0972", "offer_date": today, "region": "Karnataka", "item_type": "Pump", "moc": "Metallic",
            "quantity": "2", "quoted_value": "1250000", "currency": "INR", "offer_pdf": pdf()}
    eng.post("/offers/new", base)
    # same customer again (different case / spacing) must NOT create a duplicate
    eng.post("/offers/new", dict(base, offer_no="0973", cust_name="  acme pumps  ltd", person_name="Suresh", offer_pdf=pdf()))
    with app.app_context():
        assert db.q1("SELECT COUNT(*) n FROM customers")["n"] == 1
        assert db.q1("SELECT COUNT(*) n FROM customers_contacts")["n"] == 1
        o = db.q1("SELECT * FROM offers WHERE offer_no='0972'")
        assert o["assigned_engineer_id"] and o["is_latest"] == 1
    # duplicate offer no rejected
    eng.post("/offers/new", dict(base, offer_pdf=pdf()), ok=(200,))
    # follow-up with rating + next date
    nxt = (date.today() - timedelta(days=1)).isoformat()
    eng.post("/followups/new", {"offer_id": o["id"], "followup_date": today, "mode": "Phone call", "notes": "Discussed price",
                                "rating": "A", "status": "Open", "next_followup_date": today})
    with app.app_context():
        o = db.q1("SELECT * FROM offers WHERE offer_no='0972'")
        assert o["rating"] == "A" and o["next_followup_date"] == today
    # reminder visible on dashboard
    assert b"0972" in eng.get("/").data
    # revision 0972 -> 0972A
    eng.post("/offers/%d/action/revise" % o["id"])
    with app.app_context():
        assert db.q1("SELECT is_latest FROM offers WHERE offer_no='0972A'")["is_latest"] == 1
        assert db.q1("SELECT is_latest FROM offers WHERE offer_no='0972'")["is_latest"] == 0
    # head assigns engineer
    for u in ("/offers/", "/offers/%d" % o["id"], "/customers/", "/followups/"):
        eng.get(u)
    # filters + excel
    assert b"0973" in eng.get("/offers/?_f=1&f_region=Karnataka&f_offer_no=097").data
    x = eng.c.get("/offers/export.xlsx?_f=1")
    assert x.status_code == 200 and x.data[:2] == b"PK"
    assert eng.c.get("/customers/export.xlsx").status_code == 403           # master DB: admin only
    assert admin.c.get("/customers/export.xlsx").status_code == 200
    assert b"Acme" in eng.get("/customers/suggest?q=acm&field=cust_name").data
    head.get("/reports/offers")
    assert head.c.get("/reports/offers?xlsx=1").status_code == 200

    # ---- Phase 2: visits, assignments, tour expense
    eng.post("/visits/new", {"visit_date": today, "customer_name": "Acme Pumps Ltd", "address": "Peenya", "person_name": "Suresh",
                             "reason": "Technical discussion", "remark": "Will confirm order"})
    head.post("/visits/1/action/review", {"review_status": "Action required", "comment": "Send revised offer"})
    assert b"Send revised offer" in eng.get("/visits/1").data
    head.post("/assignments/new", {"assigned_to": 3, "work_date": today, "kind": "Visit", "customer_name": "Acme", "purpose": "Collect PO"})
    eng.post("/assignments/1/edit", {"status": "Done", "feedback": "PO collected"})
    eng.post("/tour_expenses/new".replace("_", "-"), {"claim_date": today, "tour_from": today, "tour_to": today, "purpose": "Customer visit",
             "lines-0-line_date": today, "lines-0-place": "Mysuru", "lines-0-boarding_lodging": "1500", "lines-0-conveyance": "800",
             "lines-0-bill_pdf": pdf("bill.pdf")})
    with app.app_context():
        assert db.q1("SELECT total FROM (SELECT (SELECT SUM(boarding_lodging+conveyance) FROM tour_expenses_lines) total)")["total"] == 2300
    head.post("/tour-expenses/1/action/approve", {"passed_amount": "2300"})
    acc.post("/tour-expenses/1/action/file", {"filing_ref": "V-17"})
    assert b"Filed" in acc.get("/tour-expenses/1").data

    # ---- Phase 3: work order (head office -> WO = OA)
    wo = {"cust_name": "Acme Pumps Ltd", "cust_address": "Plot 4", "person_name": "Suresh", "designation": "PM",
          "mobile": "9845012345", "email": "suresh@acme.com", "offer_id": o["id"], "po_no": "PO/77", "po_date": today,
          "payment_terms": "30 days from delivery", "credit_days": "30", "credit_basis": "Date of delivery",
          "price_basis": "Ex-works", "inspection": "No", "po_value_gross": "1475000", "po_value_net": "1250000",
          "office": "Head Office", "oa_no": "OA-100", "oa_pdf": pdf("oa.pdf")}
    eng.post("/work-orders/new", wo)
    with app.app_context():
        w = db.q1("SELECT * FROM work_orders")
        assert w["wo_no"] == "OA-100" and w["region"] == "Karnataka" and w["engineer_id"] == 3
        assert db.q1("SELECT status FROM offers WHERE offer_no='0972'")["status"] == "Order Acquired"
    # invoices cannot exist before dispatch is started
    acc.post("/invoices/new", {"work_order_id": w["id"]}, ok=(200,))
    acc.post("/work-orders/%d/action/start_dispatch" % w["id"])

    # ---- Phase 4: invoice -> colours -> payments -> lock
    inv = {"work_order_id": w["id"], "invoice_type": "Tax invoice", "invoice_no": "INV-1", "invoice_date": today,
           "net_value": "1250000", "gross_value": "1475000", "lr_no": "LR9", "lr_date": today,
           "delivery_date": (date.today() - timedelta(days=40)).isoformat(), "invoice_pdf": pdf("i.pdf")}
    acc.post("/invoices/new", inv)
    with app.app_context():
        i = db.q1("SELECT * FROM invoices")
        assert i["supply_type"] == "Full supply"
        row = db.q1("SELECT * FROM (%s) q" % __import__("app.core.registry", fromlist=["x"]).get("invoices").inner_sql())
        assert row["due_date"] == (date.today() - timedelta(days=10)).isoformat(), row["due_date"]
        assert row["payment_status"] == "Overdue / due now" and row["outstanding"] == 1475000
    assert b"row-red" in acc.get("/invoices/").data
    assert b"INV-1" in eng.get("/").data                                   # engineer region reminder on dashboard
    assert acc.c.get("/reports/outstanding?xlsx=1").status_code == 200
    assert b"14,75,000" in acc.get("/reports/outstanding").data
    acc.post("/payments/new", {"invoice_id": i["id"], "kind": "Advance", "amount": "500000", "received_date": today, "mode": "RTGS"})
    with app.app_context():
        assert db.q1("SELECT locked FROM work_orders")["locked"] == 0
    acc.post("/payments/new", {"invoice_id": i["id"], "kind": "Balance", "amount": "975000", "received_date": today})
    with app.app_context():
        assert db.q1("SELECT locked FROM work_orders")["locked"] == 1       # paid in full & fully supplied
        assert db.q1("SELECT payment_status FROM (%s) q" % __import__("app.core.registry", fromlist=["x"]).get("invoices").inner_sql())["payment_status"] == "Received"
    eng.get("/work-orders/%d/edit" % w["id"], ok=403)                       # locked for engineers / office staff
    head.get("/work-orders/%d/edit" % w["id"])                              # head can still edit
    assert b"row-green" in acc.get("/invoices/").data
    assert acc.c.get("/invoices/export.xlsx").status_code == 200
    # PDFs downloadable
    assert acc.c.get("/invoices/%d/file/invoice_pdf" % i["id"]).data.startswith(b"%PDF")
    # comment by engineer on a payment follow-up
    eng.post("/invoices/%d/comment" % i["id"], {"body": "Customer promised release"})

    # ---- digest e-mail
    with app.app_context():
        n = digest.send_all(force=True)
        assert n >= 1
        assert list(Path(app.config["OUTBOX_DIR"]).glob("*.eml"))
    # every edit / detail / prefilled-new page renders
    for u in ("/customers/1", "/customers/1/edit", "/tour-expenses/1/edit", "/offers/%d/edit" % o["id"], "/invoices/%d" % i["id"],
              "/invoices/%d/edit" % i["id"], "/invoices/new?work_order_id=%d" % w["id"], "/followups/new?offer_id=%d" % o["id"],
              "/payments/new?invoice_id=%d" % i["id"], "/visits/1/edit", "/assignments/1"):
        admin.get(u)
    # permissions: engineer cannot open users admin
    eng.get("/users/", ok=403)
    admin.get("/users/")
    print("ALL OK")


if __name__ == "__main__":
    test_everything()
