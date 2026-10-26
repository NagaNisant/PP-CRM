# Process Pumps CRM

Offers → follow-ups → visits → orders → dispatch → payments, in one Flask app (SQLite, no external services).

## Run it

```bash
pip install -r requirements.txt
python manage.py init-db          # creates tables + first admin (admin@process-pumps.com / ChangeMe@123)
python run.py                     # http://localhost:5000
python tests/test_smoke.py        # end-to-end test of all four phases
```
Add users under **Admin → Users**. Settings (SMTP, 7:00 AM digest time, reminder window…) are in `config.py` / env vars.
Daily e-mail: the built-in scheduler sends at 07:00; with several workers use cron instead: `0 7 * * * python manage.py send-digests`.
Without `SMTP_HOST` mails are written to `instance/outbox/` so you can inspect them.
Legacy data: `python manage.py import-payments "Payment Details.xlsx"`.

## Where do I change X?  (always ONE file)

| I want to…                                             | Edit only                                   |
|--------------------------------------------------------|---------------------------------------------|
| add / rename / remove a field, make it mandatory       | that entity's `app/modules/<name>/module.py` (tables update automatically on restart) |
| change a dropdown list (regions, ratings, MOC…)        | `app/choices.py`                            |
| change who can see / create / edit / export anything   | `access={...}` in that module's `module.py`; role groups in `app/core/roles.py` |
| change payment colours / due-date rules                | `app/modules/invoices/module.py` (SQL at top) + `DUE_SOON_DAYS` in `config.py` |
| change what the 7 AM mail / dashboard shows            | the `Widget(...)` in the relevant `module.py` |
| change the digest time, SMTP, company name             | `config.py`                                 |
| change look & feel                                     | `app/static/css/app.css`                    |
| change how a field *type* renders in forms             | `app/templates/_macros.html`                |
| add a new screen / entity                              | new folder `app/modules/<name>/module.py` (auto-discovered) |

## Structure
```
config.py                    all settings
manage.py / run.py           CLI / server
app/choices.py               every dropdown list
app/core/                    framework - written once
    fields.py                field types + validation        module.py   Module / Action / Widget classes
    crud.py                  list, form, detail, actions     db.py       SQLite + auto schema sync
    roles.py                 roles & groups                  excel.py    Excel export
    auth.py                  login, CSRF                     digest.py   7 AM e-mail
app/modules/                 one folder per business entity (each = ONE module.py)
    users customers offers followups                (Phase 1)
    visits assignments tour_expenses                (Phase 2)
    work_orders                                     (Phase 3)
    invoices payments reports                       (Phase 4)
app/templates, app/static    shared HTML / CSS / JS
```

## Rules implemented (and assumptions)
* **Offers** need customer name, address, contact person, designation, mobile, e-mail; customers are matched case-insensitively so no duplicates are created; typing suggests existing customers. Revisions: `0972 → 0972A → 0972B` ("Create revision" button; older versions are kept, only the latest shows by default).
* Head/admin assign the engineer; engineers set rating A–D and next follow-up date (Follow-up log). Engineers see only their own offers.
* Dashboard + 7 AM mail: follow-ups due, new offers submitted yesterday, payments to follow up, assigned work.
* **Excel**: every list has per-column filters and an Excel button that exports exactly the filtered view. Full customer master: admin only. (Offers export is open to head and engineers (own rows); change `export=` in `offers/module.py` if you want admin-only.)
* **Orders**: head office → WO no = OA no automatically; branch office → WO no entered separately. Saving an order marks the offer *Order Acquired*.
* **Dispatch**: the *Start dispatch & accounts* button (accounts / head / admin) on the order unlocks invoices. Multiple invoices per order = part supply; full/part is suggested automatically and compared with the order value.
* **Payment colours**: green received · yellow due within 7 days · red due now / overdue. Due date = credit days (set per order from the PO terms) counted from delivery / invoice / GRN / POD / LR date. Payments are recorded against an invoice (record advances against the proforma invoice).
* **Receivable report** counts only invoices already due today – later instalments are never projected.
* An order is **locked** automatically when fully supplied and every invoice is paid in full; then only head/admin can edit.
* Assumption: "Application" and "Marketing" roles are both field engineers; "Design" can view offers/orders.
