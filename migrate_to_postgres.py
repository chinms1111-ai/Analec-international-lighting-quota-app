"""
One-time script to copy data from your local pricing.db (SQLite) into your
new Render Postgres database.

WHEN TO RUN THIS: once, after you've created the Postgres database on Render
and added its connection string as the DATABASE_URL environment variable
locally (not on Render — locally, just for running this script).

HOW:
  1. On Render: create a Postgres database (New + -> PostgreSQL).
  2. On the Postgres service's Info page, copy the "External Database URL".
  3. Run this script from your project folder with that URL set as DATABASE_URL:

       # Windows PowerShell
       $env:DATABASE_URL="postgresql://user:pass@host/dbname"
       python migrate_to_postgres.py

       # Windows CMD
       set DATABASE_URL=postgresql://user:pass@host/dbname
       python migrate_to_postgres.py

  4. Then add that SAME connection string as the DATABASE_URL environment
     variable on your Render WEB SERVICE (not just the Postgres service) and
     redeploy. Your live app will then read/write the Postgres database.

This script only READS your local pricing.db - it never modifies it. It's
safe to run more than once (it skips rows that already exist by id).
"""
import os
import sqlite3
import sys
from datetime import datetime

if not os.environ.get('DATABASE_URL'):
    print("ERROR: Set the DATABASE_URL environment variable to your Render Postgres")
    print("external connection string before running this script. See the")
    print("instructions at the top of this file.")
    sys.exit(1)

# Import app AFTER checking DATABASE_URL so the app connects to Postgres, not sqlite.
import app as appmodule  # noqa: E402
from sqlalchemy import text  # noqa: E402

SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'pricing.db')

if not os.path.exists(SQLITE_PATH):
    print(f"ERROR: Could not find {SQLITE_PATH}. Run this from your project folder.")
    sys.exit(1)


def fetch_all(table):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
    except sqlite3.OperationalError:
        conn.close()
        return []
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def reset_sequence(db, table):
    try:
        db.session.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
        ))
    except Exception as e:
        print(f"  (could not reset id sequence for {table}: {e})")


def main():
    db = appmodule.db

    with appmodule.app.app_context():
        print("Creating tables in Postgres (if they don't already exist)...")
        db.create_all()
        appmodule.migrate_schema()

        # --- Settings (single row) ---
        settings_rows = fetch_all('settings')
        if settings_rows:
            row = settings_rows[0]
            s = appmodule.Settings.query.first()
            if not s:
                s = appmodule.Settings()
                db.session.add(s)
            for field in ['business_name', 'tagline', 'address', 'phone',
                          'bank_name', 'account_number', 'account_name',
                          'quote_validity_days']:
                if field in row and row[field] is not None:
                    setattr(s, field, row[field])
            db.session.commit()
            print("Settings migrated.")

        # --- Items ---
        count = 0
        for row in fetch_all('item'):
            if appmodule.Item.query.get(row['id']):
                continue
            it = appmodule.Item(
                id=row['id'],
                category=row.get('category', ''),
                name=row.get('name', ''),
                brand=row.get('brand') or '',
                unit=row.get('unit', ''),
                cost_price=row.get('cost_price') or 0,
                markup_pct=row.get('markup_pct') or 0,
                notes=row.get('notes') or '',
                quantity_on_hand=row.get('quantity_on_hand') or 0,
                low_stock_threshold=row.get('low_stock_threshold') or 5,
            )
            db.session.add(it)
            count += 1
        db.session.commit()
        print(f"{count} item(s) migrated.")

        # --- Customers ---
        count = 0
        for row in fetch_all('customer'):
            if appmodule.Customer.query.get(row['id']):
                continue
            c = appmodule.Customer(
                id=row['id'],
                name=row.get('name', ''),
                phone=row.get('phone') or '',
                address=row.get('address') or '',
                notes=row.get('notes') or '',
                created_at=parse_dt(row.get('created_at')) or datetime.utcnow(),
            )
            db.session.add(c)
            count += 1
        db.session.commit()
        print(f"{count} customer(s) migrated.")

        # --- Quotes ---
        count = 0
        for row in fetch_all('quote'):
            if appmodule.Quote.query.get(row['id']):
                continue
            q = appmodule.Quote(
                id=row['id'],
                quote_ref=row.get('quote_ref', ''),
                client_name=row.get('client_name', ''),
                customer_id=row.get('customer_id'),
                project_site=row.get('project_site') or '',
                discount_pct=row.get('discount_pct') or 0,
                status=row.get('status') or 'pending',
                stock_deducted=bool(row.get('stock_deducted') or 0),
                created_at=parse_dt(row.get('created_at')) or datetime.utcnow(),
            )
            db.session.add(q)
            count += 1
        db.session.commit()
        print(f"{count} quote(s) migrated.")

        # --- Quote lines ---
        count = 0
        for row in fetch_all('quote_line'):
            if appmodule.QuoteLine.query.get(row['id']):
                continue
            l = appmodule.QuoteLine(
                id=row['id'],
                quote_id=row['quote_id'],
                item_id=row.get('item_id'),
                item_name=row.get('item_name', ''),
                unit=row.get('unit', ''),
                qty=row.get('qty') or 1,
                unit_price=row.get('unit_price') or 0,
            )
            db.session.add(l)
            count += 1
        db.session.commit()
        print(f"{count} quote line(s) migrated.")

        # Reset Postgres auto-increment counters so future inserts don't collide
        # with the ids we just copied over.
        print("Resetting id sequences...")
        for table in ['item', 'customer', 'quote', 'quote_line', 'settings']:
            reset_sequence(db, table)
        db.session.commit()

    print("\nDone. Your Postgres database now has your existing data.")
    print("Next: add this same DATABASE_URL to your Render WEB SERVICE's")
    print("environment variables and redeploy.")


if __name__ == '__main__':
    main()