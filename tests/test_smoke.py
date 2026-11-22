"""
Comprehensive test suite for PP-CRM modifications and feature updates.
Tests:
- Admin, Application, and Marketing roles and access control.
- Metallic, Non-Metallic, and Both Metallic and Non-Metallic offer creation.
- Inline customer creation and duplicate prevention.
- Automatic draft saving, draft retrieval, and discard/submit cleanup.
- Compulsory follow-up fields (all mandatory except optional Rating).
- Admin excluded from follow-up workflow / assignments.
- Marketing workflow: view all offers, cannot create/edit offers, can add follow-ups, can submit visit reports.
- Marketing dashboard offer status updates ('Received', 'Quantity Confirmation').
- Visit reports: engineer list first, drill-down to engineer reports, review status removed.
- Accounts: Payment Made, Payment Received, Receivables as of Today.
- Verification that deleted modules (assignments, tour_expenses, work_orders) are gone.
"""
import io
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import create_app
from app.core import db, nav, registry, roles as R
from app.core.auth import hash_password


def pdf(name="test.pdf"):
    return (io.BytesIO(b"%PDF-1.4 test document content"), name)


def make_app():
    d = tempfile.mkdtemp()
    return create_app({
        "DATABASE": d + "/test_pumpcrm.db",
        "UPLOAD_DIR": d + "/uploads",
        "OUTBOX_DIR": d + "/outbox",
        "TESTING": True,
        "ENABLE_SCHEDULER": False
    })


class Client:
    def __init__(self, app, email, password="Passw0rd!"):
        self.c = app.test_client()
        with self.c.session_transaction() as s:
            s["_csrf"] = "tok"
        r = self.c.post("/login", data={"email": email, "password": password, "_csrf": "tok"})
        assert r.status_code == 302, (email, r.status_code)
        with self.c.session_transaction() as s:
            s["_csrf"] = "tok"

    def get(self, url, ok=200):
        r = self.c.get(url, follow_redirects=True)
        assert r.status_code == ok, (url, r.status_code, r.data[:400])
        return r

    def post(self, url, data=None, ok=(302,)):
        data = dict(data or {}, _csrf="tok")
        r = self.c.post(url, data=data, content_type="multipart/form-data")
        assert r.status_code in ok, (url, r.status_code, r.data.decode(errors="ignore")[:1500])
        return r

    def post_json(self, url, data=None, ok=(200,)):
        data = dict(data or {}, _csrf="tok")
        r = self.c.post(url, data=data, headers={"X-Requested-With": "XMLHttpRequest"})
        assert r.status_code in ok, (url, r.status_code, r.data.decode(errors="ignore")[:1500])
        return r


def test_everything():
    app = make_app()
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # 1. SETUP USERS: EXACTLY 3 DESIGNATIONS
    with app.app_context():
        # Confirm roles defined
        assert set(R.ROLE_LABELS.keys()) == {R.ADMIN, R.APPLICATION, R.MARKETING}

        for email, name, role in [
            ("admin@process-pumps.com", "Admin User", "admin"),
            ("app@process-pumps.com", "App Engineer", "application"),
            ("mkt@process-pumps.com", "Marketing Exec", "marketing"),
        ]:
            db.execute(
                "INSERT INTO users(full_name,email,role,active,password_hash) VALUES(?,?,?,?,?)",
                (name, email, role, 1, hash_password("Passw0rd!"))
            )
        db.get_db().commit()

    admin = Client(app, "admin@process-pumps.com")
    app_eng = Client(app, "app@process-pumps.com")
    mkt = Client(app, "mkt@process-pumps.com")

    # 2. VERIFY DELETED MODULES ARE REMOVED
    for url in ("/assignments/", "/tour-expenses/", "/work-orders/"):
        assert admin.c.get(url).status_code in (404, 403), f"{url} should not exist"
        assert app_eng.c.get(url).status_code in (404, 403), f"{url} should not exist"
        assert mkt.c.get(url).status_code in (404, 403), f"{url} should not exist"

    # Confirm Customer tab is removed from navigation
    with app.test_request_context():
        for u in (admin, app_eng, mkt):
            # Read user row
            user_row = db.q1("SELECT * FROM users WHERE email=?", (
                "admin@process-pumps.com" if u == admin else "app@process-pumps.com" if u == app_eng else "mkt@process-pumps.com",
            ))
            nav_groups = nav.build(user_row)
            all_labels = [item["label"] for group, items in nav_groups for item in items]
            assert "Customers" not in all_labels, "Customer tab must be removed from navigation"
            assert "Orders" not in [g for g, _ in nav_groups], "Orders group must be removed from navigation"

    # 3. OFFER CREATION & PERMISSIONS
    # Marketing CANNOT create offers (HTTP 403)
    assert mkt.c.get("/offers/new").status_code == 403, "Marketing should not access /offers/new"
    mkt.post("/offers/new", {"offer_no": "9999"}, ok=(403,))

    # Application CAN access /offers/new
    app_eng.get("/offers/new")

    # 3.1 DRAFT AUTO-SAVING
    # Save a draft for Application user
    draft_data = {
        "cust_name": "Bharat Petroleum Corp",
        "cust_address": "Refinery Road, Mahul, Mumbai",
        "person_name": "Rajesh Kumar",
        "designation": "Chief Engineer",
        "mobile": "9876543210",
        "email": "rajesh.k@bpcl.in",
        "offer_no": "0801",
        "offer_date": today,
        "region": "Maharashtra",
        "item_type": "Pump",
        "moc": "Both Metallic and Non-Metallic",
        "quantity": "4",
        "quoted_value": "4500000",
        "currency": "INR",
    }
    r = app_eng.post_json("/offers/save-draft", draft_data)
    res_json = json.loads(r.data.decode())
    assert res_json.get("ok") is True
    assert "saved_at" in res_json

    # Verify draft is in database table offer_drafts
    with app.app_context():
        user_app = db.q1("SELECT id FROM users WHERE email='app@process-pumps.com'")
        saved_draft = db.q1("SELECT * FROM offer_drafts WHERE user_id=?", (user_app["id"],))
        assert saved_draft is not None
        assert "Bharat Petroleum" in saved_draft["data"]
        # Verify drafts are NOT in the offers table
        assert db.q1("SELECT COUNT(*) n FROM offers WHERE offer_no='0801'")["n"] == 0

    # Loading /offers/new retrieves the draft
    r_new = app_eng.get("/offers/new")
    assert b"Bharat Petroleum Corp" in r_new.data, "Draft customer name should be restored"
    assert b"0801" in r_new.data, "Draft offer no should be restored"

    # Discard draft
    r_disc = app_eng.post_json("/offers/discard-draft")
    assert r_disc.status_code == 200
    with app.app_context():
        assert db.q1("SELECT COUNT(*) n FROM offer_drafts WHERE user_id=?", (user_app["id"],))["n"] == 0

    # 3.2 OFFER CREATION WITH METALLIC & NON-METALLIC (SIMULTANEOUSLY)
    # Also tests inline customer creation and duplicate prevention
    offer_payload_both = dict(draft_data, offer_no="0801", moc="Both Metallic and Non-Metallic", offer_pdf=pdf())
    app_eng.post("/offers/new", offer_payload_both)

    with app.app_context():
        o1 = db.q1("SELECT * FROM offers WHERE offer_no='0801'")
        assert o1 is not None
        assert o1["moc"] == "Both Metallic and Non-Metallic"
        assert o1["assigned_engineer_id"] == user_app["id"]  # Application author auto-assigned
        # Confirm customer created
        cust = db.q1("SELECT * FROM customers WHERE name='Bharat Petroleum Corp'")
        assert cust is not None
        # Confirm draft cleared after submission
        assert db.q1("SELECT COUNT(*) n FROM offer_drafts WHERE user_id=?", (user_app["id"],))["n"] == 0

    # Create offer with Metallic only
    offer_payload_met = dict(draft_data, offer_no="0802", moc="Metallic only", cust_name="bharat petroleum corp", offer_pdf=pdf())
    app_eng.post("/offers/new", offer_payload_met)
    with app.app_context():
        o2 = db.q1("SELECT * FROM offers WHERE offer_no='0802'")
        assert o2["moc"] == "Metallic only"
        # Verify duplicate customer was NOT created
        assert db.q1("SELECT COUNT(*) n FROM customers WHERE lower(name)='bharat petroleum corp'")["n"] == 1

    # Create offer with Non-Metallic only
    offer_payload_non = dict(draft_data, offer_no="0803", moc="Non-Metallic only", offer_pdf=pdf())
    app_eng.post("/offers/new", offer_payload_non)
    with app.app_context():
        o3 = db.q1("SELECT * FROM offers WHERE offer_no='0803'")
        assert o3["moc"] == "Non-Metallic only"

    # 4. MARKETING ACCESS TO OFFERS
    # Marketing can view ALL offers
    mkt_list = mkt.get("/offers/").data.decode()
    assert "0801" in mkt_list
    assert "0802" in mkt_list
    assert "0803" in mkt_list

    # Marketing can view offer details
    mkt_view = mkt.get(f"/offers/{o1['id']}").data.decode()
    assert "Both Metallic and Non-Metallic" in mkt_view
    assert "Bharat Petroleum Corp" in mkt_view

    # Marketing CANNOT edit offer original details
    assert mkt.c.get(f"/offers/{o1['id']}/edit").status_code == 403

    # 5. FOLLOW-UP MODULE MODIFICATIONS
    # 5.1 Mandatory fields validation: all fields compulsory EXCEPT rating
    # Attempt submit with missing next_followup_date -> fails
    r_fail = app_eng.post(
        "/followups/new",
        {"offer_id": o1["id"], "followup_date": today, "mode": "Phone call", "notes": "Price discussion", "status": "Open"},
        ok=(200,)
    )
    assert b"required" in r_fail.data.lower()

    # Attempt submit with missing notes -> fails
    r_fail2 = app_eng.post(
        "/followups/new",
        {"offer_id": o1["id"], "followup_date": today, "mode": "Phone call", "status": "Open", "next_followup_date": tomorrow},
        ok=(200,)
    )
    assert b"required" in r_fail2.data.lower()

    # Submit follow-up WITHOUT rating (rating is optional!) -> SUCCEEDS
    five_days_ago = (date.today() - timedelta(days=5)).isoformat()
    app_eng.post(
        "/followups/new",
        {
            "offer_id": o1["id"],
            "followup_date": five_days_ago,
            "mode": "Email",
            "notes": "Sent revised technical specs and terms",
            "rating": "",  # OPTIONAL: Left blank
            "status": "Open",
            "next_followup_date": yesterday,  # OVERDUE follow-up
        }
    )
    with app.app_context():
        o1_updated = db.q1("SELECT next_followup_date, status FROM offers WHERE id=?", (o1["id"],))
        assert o1_updated["next_followup_date"] == yesterday

    # 5.2 Marketing users MUST be able to add and update follow-ups
    mkt.post(
        "/followups/new",
        {
            "offer_id": o2["id"],
            "followup_date": today,
            "mode": "Visit",
            "notes": "Customer requested demo and price breakdown",
            "rating": "B",
            "status": "Open",
            "next_followup_date": today,  # DUE TODAY follow-up
        }
    )
    with app.app_context():
        o2_updated = db.q1("SELECT next_followup_date, rating, status FROM offers WHERE id=?", (o2["id"],))
        assert o2_updated["next_followup_date"] == today
        assert o2_updated["rating"] == "B"

    # 6. VISIT REPORTS MODULE
    # 6.1 Engineer submits a visit report (review_status removed)
    mkt.post(
        "/visits/new",
        {
            "visit_date": today,
            "customer_name": "Bharat Petroleum Corp",
            "address": "Mahul, Mumbai",
            "person_name": "Rajesh Kumar",
            "designation": "Chief Engineer",
            "mobile": "9876543210",
            "email": "rajesh.k@bpcl.in",
            "reason": "Annual pump maintenance consultation",
            "remark": "Satisfied with existing performance, requested expansion quote",
            "next_followup_date": tomorrow,
            "followup_mode": "Phone call",
            "offer_id": o1["id"],
        }
    )

    with app.app_context():
        v = db.q1("SELECT * FROM visits WHERE customer_name='Bharat Petroleum Corp'")
        assert v is not None
        # Confirm review_status workflow is gone
        assert "review_status" not in registry.get("visits").by_name

    # 6.2 Main Visit Reports page displays ONLY a list of engineers
    visits_main = admin.get("/visits/").data.decode()
    assert "Marketing Exec" in visits_main, "Engineer who submitted visit should appear in engineer list"
    assert "View Reports" in visits_main
    # Individual reports must not be listed directly on the initial page
    assert "Annual pump maintenance consultation" not in visits_main

    # 6.3 Clicking engineer displays their reports
    with app.app_context():
        user_mkt = db.q1("SELECT id FROM users WHERE email='mkt@process-pumps.com'")
    eng_reports = admin.get(f"/visits/?engineer_id={user_mkt['id']}").data.decode()
    assert "Annual pump maintenance consultation" in eng_reports
    assert "Bharat Petroleum Corp" in eng_reports

    # 6.4 Viewing individual report shows all details
    v_detail = admin.get(f"/visits/{v['id']}").data.decode()
    assert "Chief Engineer" in v_detail
    assert "Satisfied with existing performance" in v_detail
    assert "review_status" not in v_detail

    # 7. DASHBOARD REDESIGN
    # 7.1 Displays "Visit Reports Awaiting Your Review"
    dash_admin = admin.get("/").data.decode()
    assert "Visit Reports Awaiting Your Review" in dash_admin
    assert "Bharat Petroleum Corp" in dash_admin

    # 7.2 Displays "Visits Follow-Up Due Today / Overdue" (Role aware: not assigned to Admin)
    dash_mkt = mkt.get("/").data.decode()
    assert "Visits Follow-Up Due Today / Overdue" in dash_mkt
    # Admin does NOT have follow-up assignments
    assert "Visits Follow-Up Due Today / Overdue" not in dash_admin

    # Overdue vs Today distinguished
    dash_app = app_eng.get("/").data.decode()
    assert "OVERDUE" in dash_app or "row-red" in dash_app
    assert "DUE TODAY" in dash_mkt or "row-yellow" in dash_mkt

    # 7.3 Marketing Offer Status Updates
    # Marketing dashboard has the update status section
    assert "Offer Status Updates" in dash_mkt
    assert "Received" in dash_mkt
    assert "Quantity Confirmation" in dash_mkt

    # Marketing updates offer status to 'Received'
    mkt.post(
        "/update-offer-status",
        {"offer_id": o1["id"], "status": "Received", "remarks": "PO received via email"}
    )
    with app.app_context():
        o1_status = db.q1("SELECT status FROM offers WHERE id=?", (o1["id"],))
        assert o1_status["status"] == "Received"
        # Confirm comment / history logged
        cmt = db.q1("SELECT * FROM comments WHERE entity='offers' AND entity_id=?", (o1["id"],))
        assert cmt is not None
        assert "Received" in cmt["body"]

    # Marketing updates another offer status to 'Quantity Confirmation'
    mkt.post(
        "/update-offer-status",
        {"offer_id": o2["id"], "status": "Quantity Confirmation", "remarks": "Client confirmed 3 pumps"}
    )
    with app.app_context():
        o2_status = db.q1("SELECT status FROM offers WHERE id=?", (o2["id"],))
        assert o2_status["status"] == "Quantity Confirmation"

    # 8. ACCOUNTS MODULE (ADMIN ONLY)
    # Payment Made
    admin.get("/payments-made/")
    admin.post(
        "/payments-made/new",
        {
            "payment_date": today,
            "paid_to": "Steel Authority of India Ltd",
            "category": "Raw Material",
            "amount": "250000",
            "mode": "RTGS",
            "reference_no": "RTGS-9908123",
            "remarks": "Advance for SS316 raw castings",
        }
    )
    with app.app_context():
        pm = db.q1("SELECT * FROM payments_made WHERE paid_to='Steel Authority of India Ltd'")
        assert pm is not None
        assert pm["amount"] == 250000

    # Payment Received
    admin.get("/payments/")
    admin.post(
        "/payments/new",
        {
            "received_date": today,
            "customer_id": cust["id"],
            "kind": "Advance",
            "amount": "150000",
            "mode": "NEFT",
            "reference_no": "NEFT-12345",
            "remarks": "Advance payment received",
        }
    )
    with app.app_context():
        pr = db.q1("SELECT * FROM payments WHERE amount=150000")
        assert pr is not None

    # Receivables as of Today
    rec_page = admin.get("/reports/outstanding").data.decode()
    assert "Receivables as of Today" in rec_page or "Receivable as of" in rec_page

    # Non-admin users cannot access accounts
    assert app_eng.c.get("/payments-made/").status_code == 403
    assert app_eng.c.get("/reports/outstanding").status_code == 403
    assert mkt.c.get("/payments-made/").status_code == 403
    assert mkt.c.get("/reports/outstanding").status_code == 403

    print("\n=======================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("Every requirement, designation, and workflow verified.")
    print("=======================================================\n")


if __name__ == "__main__":
    test_everything()
