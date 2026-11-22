"""
dashboard.py - landing page redesigned for Process Pumps CRM.
Sections:
1. Visit Reports Awaiting Your Review (report visibility & access without approval gate)
2. Visits Follow-Up Due Today / Overdue (clear overdue vs today distinction, no Admin assignments)
3. Marketing Offer Status Updates (direct 'Received' / 'Quantity Confirmation' updates)
"""
from datetime import date
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from app.core import db, roles as R
from app.core.util import fmt_money, today_iso

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def home():
    user = g.user
    today = today_iso()

    # 1. Visit Reports Awaiting Your Review (All recent reports for visibility)
    visit_reports = db.q(
        "SELECT v.id, v.visit_date, v.customer_name, v.person_name, v.reason, v.remark, "
        "v.offer_id, u.full_name AS engineer_name, o.offer_no "
        "FROM visits v "
        "LEFT JOIN users u ON u.id = v.engineer_id "
        "LEFT JOIN offers o ON o.id = v.offer_id "
        "ORDER BY v.visit_date DESC, v.id DESC LIMIT 20"
    )

    # 2. Visits Follow-Up Due Today / Overdue
    # Admin must NOT have follow-up assignments
    followups_due = []
    if not R.is_admin(user):
        sql = (
            "SELECT o.id, o.offer_no, o.customer_id, o.rating, o.status, o.next_followup_date, "
            "o.quoted_value, o.assigned_engineer_id, "
            "c.name AS customer_name, u.full_name AS engineer_name "
            "FROM offers o "
            "LEFT JOIN customers c ON c.id = o.customer_id "
            "LEFT JOIN users u ON u.id = o.assigned_engineer_id "
            "WHERE o.is_latest = 1 AND o.status NOT IN ('Lost', 'Order Acquired') "
            "AND o.next_followup_date IS NOT NULL AND o.next_followup_date <= ? "
        )
        params = [today]
        if user["role"] in (R.APPLICATION, R.MARKETING):
            sql += " AND (o.assigned_engineer_id = ? OR o.assigned_engineer_id IS NULL)"
            params.append(user["id"])
        sql += " ORDER BY o.next_followup_date ASC, o.id DESC LIMIT 30"
        followups_due = db.q(sql, params)
        for f in followups_due:
            f["is_overdue"] = bool(f["next_followup_date"] and f["next_followup_date"] < today)

    # 3. Marketing: Offer Status Updates
    marketing_offers = []
    if R.is_marketing(user) or R.is_admin(user):
        marketing_offers = db.q(
            "SELECT o.id, o.offer_no, o.status, o.quoted_value, o.offer_date, "
            "c.name AS customer_name, u.full_name AS engineer_name "
            "FROM offers o "
            "LEFT JOIN customers c ON c.id = o.customer_id "
            "LEFT JOIN users u ON u.id = o.assigned_engineer_id "
            "WHERE o.is_latest = 1 AND o.status NOT IN ('Lost') "
            "ORDER BY o.offer_date DESC, o.id DESC LIMIT 40"
        )

    # Admin CRM activity overview
    admin_stats = None
    if R.is_admin(user):
        offers_stat = db.q1("SELECT COUNT(*) n, COALESCE(SUM(quoted_value),0) v FROM offers WHERE is_latest=1")
        open_offers = db.q1("SELECT COUNT(*) n FROM offers WHERE is_latest=1 AND status NOT IN ('Lost', 'Order Acquired')")
        visits_stat = db.q1("SELECT COUNT(*) n FROM visits")
        has_pm = db.q1("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payments_made'")
        pm_stat = db.q1("SELECT COUNT(*) n, COALESCE(SUM(amount),0) v FROM payments_made") if has_pm else {"n": 0, "v": 0}
        pr_stat = db.q1("SELECT COUNT(*) n, COALESCE(SUM(amount),0) v FROM payments")
        admin_stats = {
            "total_offers": offers_stat["n"],
            "total_quoted": fmt_money(offers_stat["v"]),
            "open_offers": open_offers["n"],
            "total_visits": visits_stat["n"],
            "payments_made": fmt_money(pm_stat["v"]),
            "payments_received": fmt_money(pr_stat["v"]),
        }

    return render_template(
        "dashboard.html",
        visit_reports=visit_reports,
        followups_due=followups_due,
        marketing_offers=marketing_offers,
        admin_stats=admin_stats,
        today=today,
    )


@bp.route("/update-offer-status", methods=["POST"])
def update_offer_status():
    if not g.user or g.user.get("role") not in (R.MARKETING, R.ADMIN):
        flash("You do not have permission to update offer status.", "error")
        return redirect(url_for("dashboard.home"))

    offer_id = request.form.get("offer_id")
    new_status = (request.form.get("status") or "").strip()
    remarks = (request.form.get("remarks") or "").strip()

    if new_status not in ("Received", "Quantity Confirmation"):
        flash("Invalid status selected. Must be 'Received' or 'Quantity Confirmation'.", "error")
        return redirect(url_for("dashboard.home"))

    offer = db.q1("SELECT * FROM offers WHERE id=?", (offer_id,))
    if not offer:
        flash("Offer not found.", "error")
        return redirect(url_for("dashboard.home"))

    old_status = offer.get("status")
    db.execute(
        "UPDATE offers SET status=?, updated_at=datetime('now','localtime'), updated_by=? WHERE id=?",
        (new_status, g.user["id"], offer_id)
    )

    body = f"Status updated from '{old_status}' to '{new_status}' by {g.user['full_name']} ({g.user['role'].title()})."
    if remarks:
        body += f" Remarks: {remarks}"
    db.execute(
        "INSERT INTO comments (entity, entity_id, user_id, body, created_at) VALUES ('offers', ?, ?, ?, datetime('now','localtime'))",
        (offer_id, g.user["id"], body)
    )

    flash(f"Offer {offer['offer_no']} status updated to '{new_status}'.", "ok")
    return redirect(url_for("dashboard.home"))
