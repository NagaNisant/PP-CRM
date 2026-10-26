"""
reports - management views that are not plain lists:
  /reports/offers       monthly offers + active offers by rating / region / engineer / status  (head, admin)
  /reports/outstanding  true receivable as of today by region or customer                       (accounts, head, admin, engineers: own regions)
"""
import calendar
from collections import OrderedDict
from datetime import date

from flask import Blueprint, g, render_template, request

from app import choices as C
from app.core import db, nav, registry, roles as R
from app.core.excel import xlsx_response
from app.core.util import fmt_money

bp = Blueprint("reports", __name__, url_prefix="/reports")

GROUPS = OrderedDict([("rating", "Rating"), ("region", "Region"), ("engineer", "Engineer"), ("status", "Status")])


def _key(row, group):
    if group == "engineer":
        return row.get("assigned_engineer_id__label") or "Unassigned"
    return row.get(group) or "(blank)"


def _pivot(rows, group):
    out = OrderedDict()
    for r in sorted(rows, key=lambda r: str(_key(r, group))):
        k = _key(r, group)
        n, v = out.get(k, (0, 0.0))
        out[k] = (n + 1, v + (r["quoted_value"] or 0))
    return [dict(label=k, count=n, value=v) for k, (n, v) in out.items()]


@bp.route("/offers")
def offers():
    if not R.has_role(g.user, [R.HEAD]):
        return render_template("error.html", code=403, message="Not allowed."), 403
    offers_m = registry.get("offers")
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    group = request.args.get("group", "rating")
    y, m = int(month[:4]), int(month[5:7])
    start, end = "%04d-%02d-01" % (y, m), "%04d-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1])
    extra, params = "", []
    for col, arg in (("rating", "rating"), ("region", "region"), ("assigned_engineer_id", "engineer")):
        if request.args.get(arg):
            extra += " AND %s = ?" % col
            params.append(request.args[arg])
    in_month = offers_m.query(g.user, where="is_latest=1 AND offer_date BETWEEN ? AND ?" + extra, params=[start, end] + params)["rows"]
    active = offers_m.query(g.user, where="is_latest=1 AND status='Open'" + extra, params=params)["rows"]
    engineers = db.q("SELECT id, full_name FROM users WHERE role IN (%s) AND active=1 ORDER BY full_name" % R.sql_in(R.ENGINEERS))
    month_tbl, active_tbl = _pivot(in_month, group), _pivot(active, group)
    if request.args.get("xlsx"):
        rows = [["Offers in " + month, r["label"], r["count"], r["value"]] for r in month_tbl] + \
               [["Active offers", r["label"], r["count"], r["value"]] for r in active_tbl]
        return xlsx_response("offer-summary-%s.xlsx" % month, ["Set", GROUPS[group], "Offers", "Quoted value"], rows, sheet="Offer summary")
    return render_template("reports/offers.html", month=month, group=group, groups=GROUPS, ratings=C.RATINGS, regions=C.REGIONS,
                           engineers=engineers, args=request.args, month_tbl=month_tbl, active_tbl=active_tbl,
                           month_total=(len(in_month), sum(r["quoted_value"] or 0 for r in in_month)),
                           active_total=(len(active), sum(r["quoted_value"] or 0 for r in active)),
                           start=start, end=end, fmt=fmt_money)


@bp.route("/outstanding")
def outstanding():
    if not R.has_role(g.user, [R.ACCOUNTS, R.HEAD, *R.ENGINEERS]):
        return render_template("error.html", code=403, message="Not allowed."), 403
    by = request.args.get("by", "region")
    future = request.args.get("future") == "1"
    inv = registry.get("invoices")
    rows = inv.query(g.user, where="outstanding > 0.5")["rows"]
    keyname = "customer_name" if by == "customer" else "region"
    table = OrderedDict()
    for r in sorted(rows, key=lambda r: str(r[keyname] or "")):
        k = r[keyname] or "(blank)"
        d = table.setdefault(k, dict(label=k, invoices=0, invoiced=0.0, receivable=0.0, future=0.0))
        if r["payment_status"] == "Overdue / due now":       # TRUE receivable: only what is due on or before today
            d["invoices"] += 1
            d["invoiced"] += r["gross_value"] or r["net_value"] or 0
            d["receivable"] += r["outstanding"]
        else:
            d["future"] += r["outstanding"]
    table = [d for d in table.values() if d["receivable"] or (future and d["future"])]
    totals = dict(receivable=sum(d["receivable"] for d in table), future=sum(d["future"] for d in table),
                  invoices=sum(d["invoices"] for d in table))
    if request.args.get("xlsx"):
        head = ["Customer" if by == "customer" else "Region", "Invoices due", "Receivable as of %s" % date.today().strftime("%d-%m-%Y")]
        if future:
            head.append("Not yet due (information only)")
        data = [[d["label"], d["invoices"], d["receivable"]] + ([d["future"]] if future else []) for d in table]
        data.append(["TOTAL", totals["invoices"], totals["receivable"]] + ([totals["future"]] if future else []))
        return xlsx_response("receivable-by-%s.xlsx" % by, head, data, sheet="Receivable", title="True receivable as of %s" % date.today().strftime("%d-%m-%Y"))
    return render_template("reports/outstanding.html", by=by, future=future, table=table, totals=totals, fmt=fmt_money,
                           today=date.today())


def register(app):
    app.register_blueprint(bp)
    nav.add_item("Offer summary", "reports.offers", "Reports", 10, roles=[R.HEAD])
    nav.add_item("Receivable as of today", "reports.outstanding", "Reports", 20, roles=[R.ACCOUNTS, R.HEAD, *R.ENGINEERS])
