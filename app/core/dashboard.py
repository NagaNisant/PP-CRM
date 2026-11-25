"""
dashboard.py - landing page redesigned for Process Pumps CRM.
Sections (in order):
1. Dashboard Analytics: Simple column section (Offer Ratings A, B, C, D - Total Offers - Total Value),
   clicking any rating row/column opens another page showing all offers contributing to that rating.
2. Visits Follow-Up Due Today / Overdue.
3. Recent Customer Visit Reports.
"""
from datetime import date
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from app.core import db, roles as R
from app.core.util import fmt_money, today_iso

bp = Blueprint("dashboard", __name__)


def compute_analytics(user):
    scope_sql = "o.is_latest = 1"
    params = []
    if R.is_marketing(user):
        scope_sql += " AND o.assigned_engineer_id = ?"
        params.append(user["id"])

    ratings = {}
    for r in ["A", "B", "C", "D"]:
        s = db.q1(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(o.quoted_value), 0) AS v FROM offers o WHERE o.rating = ? AND {scope_sql}",
            [r] + params
        )
        ratings[r] = {
            "key": r,
            "label": f"Offer Rating ({r})",
            "short_label": f"Rating {r}",
            "count": s["n"],
            "total_value": s["v"],
            "total_value_fmt": fmt_money(s["v"]),
            "url": url_for("dashboard.analytics_offers", rating=r),
        }

    return ratings


@bp.route("/")
def home():
    user = g.user
    today = today_iso()

    # 1. Analytics calculation (role-aware: marketing sees only assigned offers)
    ratings_dict = compute_analytics(user)
    ratings_list = [ratings_dict[r] for r in ["A", "B", "C", "D"]]

    # 2. Follow-Ups Due Today / Overdue
    followups_sql = (
        "SELECT o.id, o.offer_no, o.customer_id, o.rating, o.status, o.next_followup_date, "
        "o.quoted_value, o.assigned_engineer_id, "
        "c.name AS customer_name, u.full_name AS engineer_name "
        "FROM offers o "
        "LEFT JOIN customers c ON c.id = o.customer_id "
        "LEFT JOIN users u ON u.id = o.assigned_engineer_id "
        "WHERE o.is_latest = 1 AND o.status NOT IN ('Lost', 'Order Acquired') "
        "AND o.next_followup_date IS NOT NULL AND o.next_followup_date <= ? "
    )
    followups_params = [today]
    if R.is_marketing(user):
        followups_sql += " AND o.assigned_engineer_id = ?"
        followups_params.append(user["id"])
    followups_sql += " ORDER BY o.next_followup_date ASC, o.id DESC LIMIT 40"
    followups_due = db.q(followups_sql, followups_params)
    for f in followups_due:
        f["is_overdue"] = bool(f["next_followup_date"] and f["next_followup_date"] < today)
        if f.get("status") in ("Open", "LIVE"):
            f["status"] = "LIVE"

    # 3. Recent Customer Visit Reports
    visit_reports = db.q(
        "SELECT v.id, v.visit_date, v.customer_name, v.person_name, v.reason, v.remark, "
        "v.offer_id, v.report_file, u.full_name AS engineer_name, o.offer_no "
        "FROM visits v "
        "LEFT JOIN users u ON u.id = v.engineer_id "
        "LEFT JOIN offers o ON o.id = v.offer_id "
        "ORDER BY v.visit_date DESC, v.id DESC LIMIT 20"
    )

    return render_template(
        "dashboard.html",
        ratings_list=ratings_list,
        ratings_dict=ratings_dict,
        followups_due=followups_due,
        visit_reports=visit_reports,
        today=today,
    )


@bp.route("/analytics/offers")
def analytics_offers():
    if not g.user:
        return redirect(url_for("auth.login"))
    user = g.user
    rating = (request.args.get("rating") or "A").upper()
    if rating not in ("A", "B", "C", "D"):
        rating = "A"

    scope_sql = "o.is_latest = 1"
    params = []
    if R.is_marketing(user):
        scope_sql += " AND o.assigned_engineer_id = ?"
        params.append(user["id"])

    s = db.q1(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(o.quoted_value), 0) AS v FROM offers o WHERE o.rating = ? AND {scope_sql}",
        [rating] + params
    )
    offers = db.q(
        f"""SELECT o.id, o.offer_no, o.offer_date, o.region, o.item_type, o.moc, o.quantity,
                   o.quoted_value, o.currency, o.rating, o.status,
                   c.name AS customer_name, u.full_name AS engineer_name
            FROM offers o
            LEFT JOIN customers c ON c.id = o.customer_id
            LEFT JOIN users u ON u.id = o.assigned_engineer_id
            WHERE o.rating = ? AND {scope_sql}
            ORDER BY o.offer_date DESC, o.id DESC""",
        [rating] + params
    )
    for o in offers:
        if o.get("status") in ("Open", "LIVE"):
            o["status"] = "LIVE"

    rating_data = {
        "rating": rating,
        "label": f"Offer Rating ({rating})",
        "count": s["n"],
        "total_value": s["v"],
        "total_value_fmt": fmt_money(s["v"]),
        "filter_arg": f"f_rating={rating}",
        "offers": offers,
    }

    return render_template(
        "analytics_offers.html",
        rating_data=rating_data,
        rating=rating,
    )

