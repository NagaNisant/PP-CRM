"""
import_payments.py - loads the legacy 'Payment Details' workbook (one sheet per year) into
customers / work orders / invoices / payments.   python manage.py import-payments "Payment Details.xlsx"

Column map (row 1 headers): A WO, B customer, C PO no, D PO date, E payment terms, F region, G inspection,
H packing slip date, J invoice no, K invoice date, L invoice value, M/N/O advance (info, amount, date),
P/Q/R balance payment (info, amount, date), T transporter, U LR no, V LR type, W LR date, X delivery date,
AB retention, AC-AF BG details, AG remarks.   Rows with an empty column A belong to the previous work order.
Edit COLS below if the sheet layout changes.
"""
import re
import openpyxl
from app.core import db, registry
from app.core.util import parse_date
from app.modules.work_orders.module import refresh_lock

COLS = dict(wo=0, customer=1, po_no=2, po_date=3, terms=4, region=5, inspection=6, slip=7, inv_no=9, inv_date=10,
            value=11, adv_info=12, adv_amt=13, adv_date=14, bal_info=15, bal_amt=16, bal_date=17, transporter=19,
            lr_no=20, lr_type=21, lr_date=22, delivery=23, retention=27, bg_type=28, bg_no=29, bg_date=30,
            bg_expiry=31, remarks=32)


def num(v):
    try:
        return float(str(v).replace(",", "").strip()) if v not in (None, "") else None
    except ValueError:
        return None


def text(v):
    return str(v).strip() if v not in (None, "") else None


def iso(v):
    d = parse_date(v) if v not in (None, "") else None
    return d.isoformat() if d else None


def parse_terms(terms):
    t = (terms or "").lower()
    m = re.search(r"(\d+)\s*(?:days|day)", t)
    days = int(m.group(1)) if m else 0
    basis = "Date of delivery" if re.search(r"deliver|receipt|dispatch", t) else "Invoice date"
    return days, basis


def run(path):
    wb = openpyxl.load_workbook(path, data_only=False)
    cust_m, wo_m, inv_m, pay_m = (registry.get(k) for k in ("customers", "work_orders", "invoices", "payments"))
    stats = dict(customers=0, work_orders=0, invoices=0, payments=0, skipped=0)
    touched = set()
    for ws in wb:
        ctx = None
        for row in ws.iter_rows(min_row=2, values_only=True):
            row = list(row) + [None] * (35 - len(row))
            g = lambda k: row[COLS[k]]
            if not text(g("wo")) and not text(g("inv_no")):
                continue
            if text(g("wo")):
                name = text(g("customer")) or "Unknown customer"
                cust = db.q1("SELECT id FROM customers WHERE lower(trim(name))=lower(?)", (name,))
                if not cust:
                    cid = cust_m.insert({"name": name, "region": text(g("region"))}); stats["customers"] += 1
                else:
                    cid = cust["id"]
                oa = text(g("wo"))
                wo = db.q1("SELECT id FROM work_orders WHERE oa_no=?", (oa,))
                if wo:
                    wid = wo["id"]
                else:
                    days, basis = parse_terms(text(g("terms")))
                    wid = wo_m.insert({"customer_id": cid, "oa_no": oa, "wo_no": oa, "office": "Head Office", "po_no": text(g("po_no")),
                                       "po_date": iso(g("po_date")), "payment_terms": text(g("terms")), "credit_days": days,
                                       "credit_basis": basis, "region": text(g("region")),
                                       "inspection": "Yes" if (text(g("inspection")) or "").lower().startswith("y") else "No",
                                       "dispatch_enabled": 1, "locked": 0})
                    stats["work_orders"] += 1
                ctx = wid
            if ctx is None or not text(g("inv_no")):
                stats["skipped"] += 1
                continue
            touched.add(ctx)
            if db.q1("SELECT id FROM invoices WHERE work_order_id=? AND invoice_no=?", (ctx, text(g("inv_no")))):
                stats["skipped"] += 1
                continue
            value = num(g("value"))
            iid = inv_m.insert({"work_order_id": ctx, "invoice_type": "Tax invoice", "invoice_no": text(g("inv_no")),
                                "invoice_date": iso(g("inv_date")), "net_value": value, "gross_value": value,
                                "packing_slip_date": iso(g("slip")), "transporter": text(g("transporter")),
                                "lr_no": text(g("lr_no")), "lr_type": text(g("lr_type")), "lr_date": iso(g("lr_date")),
                                "delivery_date": iso(g("delivery")), "retention_value": num(g("retention")),
                                "bg_type": text(g("bg_type")), "bg_number": text(g("bg_no")), "bg_date": iso(g("bg_date")),
                                "bg_expiry": iso(g("bg_expiry")), "remarks": text(g("remarks"))})
            stats["invoices"] += 1
            for kind, a, d, info in (("Advance", "adv_amt", "adv_date", "adv_info"), ("Balance", "bal_amt", "bal_date", "bal_info")):
                amt = num(g(a))
                if amt:
                    i = g(info)
                    pay_m.insert({"invoice_id": iid, "kind": kind, "amount": amt, "received_date": iso(g(d)),
                                  "deduction": num(i) if num(i) is not None else None,
                                  "mode": None if num(i) is not None else text(i)})
                    stats["payments"] += 1
    for wid in touched:                      # PO value unknown in the sheet -> use invoiced total so supply status works
        db.execute("UPDATE work_orders SET po_value_net=(SELECT SUM(net_value) FROM invoices WHERE work_order_id=?), "
                   "po_value_gross=(SELECT SUM(gross_value) FROM invoices WHERE work_order_id=?) WHERE id=? AND po_value_net IS NULL",
                   (wid, wid, wid))
        refresh_lock(wid)
    db.get_db().commit()
    print("Imported:", stats)
    print("Note: engineer / offer links and contact persons are not in the sheet - complete them on the order screens.")
