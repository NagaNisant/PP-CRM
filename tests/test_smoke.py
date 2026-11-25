"""
Comprehensive test suite for PP-CRM modifications and feature updates.
Tests:
1. User Permissions – Offers & Follow-ups:
   - Admin, Application, and Marketing have identical functionality for creating, editing, viewing, and managing offers and follow-ups.
   - Any role-based restrictions on these features are removed.
2. Reports:
   - Review Report option removed entirely.
   - Marketing engineers can create and upload reports.
   - Admin and Application users can only view reports, not create or edit them (HTTP 403).
3. Follow-ups & Offer Status:
   - Remove Assign Follow-up option and related functionality.
   - Display offer status as LIVE wherever applicable.
4. Dashboard Analytics:
   - Offer Rating (A): Total number of offers and combined total value.
   - Clickable metrics displaying the complete list of offers contributing to that metric.
5. Offer Visibility:
   - Admin and Application see ALL offers in the same layout, with same analytics & filtering.
   - Marketing sees only offers assigned to them.
   - Dashboard analytics reflect only offers visible to each user.
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

        user_admin = db.q1("SELECT id FROM users WHERE email='admin@process-pumps.com'")
        user_app = db.q1("SELECT id FROM users WHERE email='app@process-pumps.com'")
        user_mkt = db.q1("SELECT id FROM users WHERE email='mkt@process-pumps.com'")

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
            user_row = db.q1("SELECT * FROM users WHERE email=?", (
                "admin@process-pumps.com" if u == admin else "app@process-pumps.com" if u == app_eng else "mkt@process-pumps.com",
            ))
            nav_groups = nav.build(user_row)
            all_labels = [item["label"] for group, items in nav_groups for item in items]
            assert "Customers" not in all_labels, "Customer tab must be removed from navigation"
            assert "Orders" not in [g for g, _ in nav_groups], "Orders group must be removed from navigation"

    # 3. REQUIREMENT 1: IDENTICAL USER PERMISSIONS FOR OFFERS & FOLLOW-UPS
    # Admin, Application, and Marketing ALL have full access to /offers/new
    assert admin.c.get("/offers/new").status_code == 200, "Admin can access /offers/new"
    assert app_eng.c.get("/offers/new").status_code == 200, "Application can access /offers/new"
    assert mkt.c.get("/offers/new").status_code == 200, "Marketing can access /offers/new"

    # 3.1 DRAFT AUTO-SAVING (Works identically for all roles)
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
        "rating": "A",
        "status": "LIVE",
    }
    r = app_eng.post_json("/offers/save-draft", draft_data)
    res_json = json.loads(r.data.decode())
    assert res_json.get("ok") is True

    # Loading /offers/new retrieves the draft
    r_new = app_eng.get("/offers/new")
    assert b"Bharat Petroleum Corp" in r_new.data, "Draft customer name should be restored"
    assert b"0801" in r_new.data, "Draft offer no should be restored"

    # Discard draft
    r_disc = app_eng.post_json("/offers/discard-draft")
    assert r_disc.status_code == 200

    # 3.2 APPLICATION CREATES OFFER o1 (Rating A, assigned to app_eng)
    offer_payload_1 = dict(
        draft_data,
        offer_no="0801",
        rating="A",
        status="LIVE",
        assigned_engineer_id=str(user_app["id"]),
        offer_pdf=pdf(),
    )
    app_eng.post("/offers/new", offer_payload_1)

    with app.app_context():
        o1 = db.q1("SELECT * FROM offers WHERE offer_no='0801'")
        assert o1 is not None
        assert o1["moc"] == "Both Metallic and Non-Metallic"
        assert o1["assigned_engineer_id"] == user_app["id"]

    # 3.3 MARKETING CREATES OFFER o2 (Rating A, assigned to mkt)
    offer_payload_2 = dict(
        draft_data,
        offer_no="0802",
        moc="Metallic only",
        cust_name="Hindustan Petroleum Corp",
        rating="A",
        status="LIVE",
        quoted_value="3500000",
        assigned_engineer_id=str(user_mkt["id"]),
        offer_pdf=pdf(),
    )
    mkt.post("/offers/new", offer_payload_2)

    with app.app_context():
        o2 = db.q1("SELECT * FROM offers WHERE offer_no='0802'")
        assert o2 is not None
        assert o2["assigned_engineer_id"] == user_mkt["id"]

    # 3.4 ADMIN CREATES OFFER o3 (Rating B, assigned to app_eng)
    offer_payload_3 = dict(
        draft_data,
        offer_no="0803",
        moc="Non-Metallic only",
        cust_name="Indian Oil Corp",
        rating="B",
        status="LIVE",
        quoted_value="2000000",
        assigned_engineer_id=str(user_app["id"]),
        offer_pdf=pdf(),
    )
    admin.post("/offers/new", offer_payload_3)

    with app.app_context():
        o3 = db.q1("SELECT * FROM offers WHERE offer_no='0803'")
        assert o3 is not None
        assert o3["rating"] == "B"

    # 3.5 MARKETING CAN EDIT THEIR ASSIGNED OFFER AND CREATE REVISION
    # Marketing can edit o2 (omitting offer_pdf keeps the existing uploaded PDF)
    payload_edit = {k: v for k, v in offer_payload_2.items() if k != "offer_pdf"}
    payload_edit["quoted_value"] = "3600000"
    mkt.post(f"/offers/{o2['id']}/edit", payload_edit)
    with app.app_context():
        assert db.q1("SELECT quoted_value FROM offers WHERE id=?", (o2["id"],))["quoted_value"] == 3600000

    # Marketing can create revisions
    rev_res = mkt.post(f"/offers/{o2['id']}/action/revise")
    assert rev_res.status_code == 302
    with app.app_context():
        o2_rev = db.q1("SELECT * FROM offers WHERE offer_no='0802A'")
        assert o2_rev is not None
        assert o2_rev["is_latest"] == 1
        assert o2_rev["assigned_engineer_id"] == user_mkt["id"]

    # 4. REQUIREMENT 5: OFFER VISIBILITY
    # Admin and Application must see ALL offers
    admin_list = admin.get("/offers/").data.decode()
    assert "0801" in admin_list
    assert "0802A" in admin_list
    assert "0803" in admin_list

    app_list = app_eng.get("/offers/").data.decode()
    assert "0801" in app_list
    assert "0802A" in app_list
    assert "0803" in app_list

    # Marketing users must see ONLY offers assigned to them
    mkt_list = mkt.get("/offers/").data.decode()
    assert "0802A" in mkt_list, "Marketing should see offer assigned to them"
    assert "0801" not in mkt_list, "Marketing should NOT see offer assigned to app_eng"
    assert "0803" not in mkt_list, "Marketing should NOT see offer assigned to app_eng"

    # Marketing cannot access offer detail for unassigned offer (HTTP 404)
    assert mkt.c.get(f"/offers/{o1['id']}").status_code == 404
    assert mkt.c.get(f"/offers/{o3['id']}").status_code == 404

    # Marketing CAN access offer detail for assigned offer
    assert mkt.c.get(f"/offers/{o2_rev['id']}").status_code == 200

    # 5. REQUIREMENT 3: FOLLOW-UPS & OFFER STATUS (LIVE)
    # Status displayed as LIVE wherever applicable
    assert "LIVE" in mkt_list
    assert "LIVE" in app_list
    assert "LIVE" in admin_list

    # 5.1 Mandatory fields validation on follow-ups (All fields compulsory except optional rating)
    r_fail = app_eng.post(
        "/followups/new",
        {"offer_id": o1["id"], "followup_date": today, "mode": "Phone call", "notes": "Price discussion", "status": "LIVE"},
        ok=(200,)
    )
    assert b"required" in r_fail.data.lower()

    # 5.2 Admin, Application, and Marketing can all log follow-ups
    # Application logs follow-up on o1
    five_days_ago = (date.today() - timedelta(days=5)).isoformat()
    app_eng.post(
        "/followups/new",
        {
            "offer_id": o1["id"],
            "followup_date": five_days_ago,
            "mode": "Email",
            "notes": "Sent revised specs",
            "rating": "A",
            "status": "LIVE",
            "next_followup_date": yesterday,  # OVERDUE
        }
    )
    # Marketing logs follow-up on o2_rev
    mkt.post(
        "/followups/new",
        {
            "offer_id": o2_rev["id"],
            "followup_date": today,
            "mode": "Visit",
            "notes": "Demo conducted",
            "rating": "A",
            "status": "LIVE",
            "next_followup_date": today,  # DUE TODAY
        }
    )
    # Admin logs follow-up on o3
    admin.post(
        "/followups/new",
        {
            "offer_id": o3["id"],
            "followup_date": today,
            "mode": "Phone call",
            "notes": "Price negotiation completed",
            "rating": "B",
            "status": "LIVE",
            "next_followup_date": tomorrow,
        }
    )

    with app.app_context():
        o1_db = db.q1("SELECT status, rating, next_followup_date FROM offers WHERE id=?", (o1["id"],))
        assert o1_db["status"] == "LIVE"
        assert o1_db["next_followup_date"] == yesterday

        o2_rev_db = db.q1("SELECT status, rating, next_followup_date FROM offers WHERE id=?", (o2_rev["id"],))
        assert o2_rev_db["status"] == "LIVE"
        assert o2_rev_db["next_followup_date"] == today

    # Verify NO 'Assign Follow-up' option exists in followups or offers
    f_form = app_eng.get("/followups/new?offer_id=" + str(o1["id"])).data.decode()
    assert "Assign Follow-up" not in f_form
    assert "assign_followup" not in f_form

    # 6. REQUIREMENT 2: REPORTS (VISIT REPORTS)
    # 6.1 Marketing engineers CAN create and upload reports
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
            "remark": "Requested expansion quote",
            "report_file": pdf("site_report.pdf"),
            "next_followup_date": tomorrow,
            "followup_mode": "Phone call",
            "offer_id": o2_rev["id"],
        }
    )
    with app.app_context():
        v = db.q1("SELECT * FROM visits WHERE customer_name='Bharat Petroleum Corp'")
        assert v is not None
        assert v["report_file"] is not None, "Report file must be uploaded"
        # Confirm review_status is completely removed
        assert "review_status" not in registry.get("visits").by_name

    # 6.2 Admin and Application users can ONLY VIEW reports, NOT create or edit them (HTTP 403)
    assert admin.c.get("/visits/new").status_code == 403, "Admin cannot access /visits/new"
    assert app_eng.c.get("/visits/new").status_code == 403, "Application cannot access /visits/new"
    assert admin.c.get(f"/visits/{v['id']}/edit").status_code == 403, "Admin cannot edit reports"
    assert app_eng.c.get(f"/visits/{v['id']}/edit").status_code == 403, "Application cannot edit reports"

    # Admin and Application CAN view reports
    assert admin.c.get(f"/visits/{v['id']}").status_code == 200, "Admin can view reports"
    assert app_eng.c.get(f"/visits/{v['id']}").status_code == 200, "Application can view reports"

    # Confirm Review Report option is removed entirely
    v_detail = admin.get(f"/visits/{v['id']}").data.decode()
    assert "Review Report" not in v_detail
    assert "Review report" not in v_detail
    assert "review_status" not in v_detail

    # 6.3 Admin and Application users CAN make comments on visit reports
    admin.post(f"/visits/{v['id']}/comment", {"body": "Admin approved next steps."})
    app_eng.post(f"/visits/{v['id']}/comment", {"body": "Application engineer confirmed pump specs."})
    with app.app_context():
        v_comments = db.q("SELECT * FROM comments WHERE entity='visits' AND entity_id=?", (v["id"],))
        assert len(v_comments) == 2, "Admin and Application comments should be saved"
        assert any("Admin approved" in c["body"] for c in v_comments)
        assert any("pump specs" in c["body"] for c in v_comments)

    # 7. REQUIREMENT 4 & 5: DASHBOARD ANALYTICS & VISIBILITY
    # 7.1 Dashboard analytics: simple column for A, B, C, D (Offer Rating - Total Offers - Total Value)
    dash_admin = admin.get("/").data.decode()
    assert "Dashboard Analytics" in dash_admin
    assert "Offer Rating (A)" in dash_admin
    assert "Offer Rating (B)" in dash_admin
    assert "Offer Rating (C)" in dash_admin
    assert "Offer Rating (D)" in dash_admin
    assert "Total Offers" in dash_admin
    assert "Total Value" in dash_admin

    # 7.2 Clicking the column opens another page of contributing offers under that rating
    page_admin_a = admin.get("/analytics/offers?rating=A").data.decode()
    assert "Offers Contributing to: Offer Rating (A)" in page_admin_a
    assert "0801" in page_admin_a
    assert "0802A" in page_admin_a
    assert "Quoted Value" in page_admin_a
    assert "Customer" in page_admin_a
    assert "LIVE" in page_admin_a

    page_admin_b = admin.get("/analytics/offers?rating=B").data.decode()
    assert "Offers Contributing to: Offer Rating (B)" in page_admin_b
    assert "0803" in page_admin_b

    # 7.3 Dashboard analytics for Marketing (Only offers assigned to marketing user)
    dash_mkt = mkt.get("/").data.decode()
    assert "Dashboard Analytics" in dash_mkt
    assert "Offer Rating (A)" in dash_mkt

    page_mkt_a = mkt.get("/analytics/offers?rating=A").data.decode()
    assert "Offers Contributing to: Offer Rating (A)" in page_mkt_a
    assert "0802A" in page_mkt_a, "Marketing should see assigned offer 0802A"
    assert "0801" not in page_mkt_a, "Marketing should NOT see offer 0801 assigned to app_eng"

    page_mkt_b = mkt.get("/analytics/offers?rating=B").data.decode()
    assert "0803" not in page_mkt_b, "Marketing should NOT see offer 0803 assigned to app_eng"
    assert "No offers found" in page_mkt_b

    # 7.4 Offer Status Updates REMOVED from dashboard tab
    assert "Offer Status Updates" not in dash_admin, "Offer Status Updates must NOT be on dashboard"
    assert "Offer Status Updates" not in dash_mkt, "Offer Status Updates must NOT be on dashboard for mkt"

    # 7.5 Edit Offer: get-offer-data API
    # Admin can fetch any offer
    resp_data = admin.get(f"/offers/get-offer-data?id={o1['id']}")
    assert resp_data.status_code == 200
    j = json.loads(resp_data.data)
    assert j["ok"] is True
    assert j["data"]["offer_no"] == "0801"
    assert "cust_name" in j["data"]

    # Also fetch by offer_no
    resp_data2 = admin.get("/offers/get-offer-data?offer_no=0802A")
    j2 = json.loads(resp_data2.data)
    assert j2["ok"] is True
    assert j2["data"]["offer_no"] == "0802A"

    # Marketing can only fetch their own offers
    resp_mkt_own = mkt.get(f"/offers/get-offer-data?id={o2_rev['id']}")
    j_mkt = json.loads(resp_mkt_own.data)
    assert j_mkt["ok"] is True, "Marketing can fetch their assigned offer"

    resp_mkt_other = mkt.get(f"/offers/get-offer-data?id={o1['id']}")
    j_mkt2 = json.loads(resp_mkt_other.data)
    assert j_mkt2["ok"] is False, "Marketing cannot fetch offer assigned to another user"

    # 7.6 Edit Offer page
    edit_page = admin.get(f"/offers/edit-offer?id={o1['id']}")
    assert edit_page.status_code == 200
    edit_html = edit_page.data.decode()
    assert "Edit Offer" in edit_html
    assert "0801" in edit_html  # offer_no should be pre-filled

    # Test edit-offer page without id (selector only)
    edit_page_blank = admin.get("/offers/edit-offer")
    assert edit_page_blank.status_code == 200
    assert "Edit Offer" in edit_page_blank.data.decode()

    # 7.7 Status choices on edit and new offer forms include all required statuses
    new_page = admin.get("/offers/new").data.decode()
    for st in ["LIVE", "Received", "Quantity Confirmation", "Order Acquired", "Lost", "On Hold"]:
        assert st in new_page, f"Status '{st}' must be in /offers/new"

    edit_page_html = admin.get(f"/offers/edit-offer?id={o1['id']}").data.decode()
    for st in ["LIVE", "Received", "Quantity Confirmation", "Order Acquired", "Lost", "On Hold"]:
        assert st in edit_page_html, f"Status '{st}' must be in /offers/edit-offer"

    # 7.8 Edit Offer via POST (update status to Received)
    admin.post("/offers/edit-offer", {
        "_offer_id": str(o1["id"]),
        "offer_no": "0801",
        "offer_date": today,
        "region": "Maharashtra",
        "cust_name": "Bharat Petroleum Corp",
        "cust_address": "Refinery Road, Mahul, Mumbai",
        "person_name": "Rajesh Kumar",
        "designation": "Chief Engineer",
        "mobile": "9876543210",
        "email": "rajesh.k@bpcl.in",
        "item_type": "Pump",
        "moc": "Both Metallic and Non-Metallic",
        "quantity": "4",
        "quoted_value": "4500000",
        "currency": "INR",
        "offer_pdf": pdf(),
        "status": "Received",
        "rating": "A",
    })
    with app.app_context():
        updated = db.q1("SELECT status FROM offers WHERE id=?", (o1["id"],))
        assert updated["status"] == "Received", "Offer status should be updated to Received via edit"

    # 7.9 Edit Offer button is visible in offers list
    list_page = admin.get("/offers/").data.decode()
    assert "Edit Offer" in list_page, "Edit Offer button should be in offers list header"
    assert "edit-offer" in list_page, "Edit offer links should be in offers list"

    # 8. ENTIRE ACCOUNTS SECTION REMOVED FOR ALL USERS
    # Confirm Accounts is not in navigation for ANY user
    with app.test_request_context():
        for u in (admin, app_eng, mkt):
            user_row = db.q1("SELECT * FROM users WHERE email=?", (
                "admin@process-pumps.com" if u == admin else "app@process-pumps.com" if u == app_eng else "mkt@process-pumps.com",
            ))
            nav_groups = nav.build(user_row)
            all_groups = [g for g, _ in nav_groups]
            assert "Accounts" not in all_groups, f"Accounts must be removed from navigation for {user_row['role']}"

    # Confirm accounts overview / payments made / payments received are removed from dashboard
    assert "Accounts Overview" not in dash_admin
    assert "payments_received" not in dash_admin
    assert "payments_made" not in dash_admin

    print("\n=======================================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("Permissions, Reports, Follow-ups, Analytics, and Visibility verified.")
    print("=======================================================\n")


if __name__ == "__main__":
    test_everything()
