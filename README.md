# Electrical Business Pricing & Quote Tool

A shared web app for managing your price list and generating customer quotes.
Built with Flask + SQLite. Everyone who logs in sees the same price list and the same quote history.

## Features
- **Price List** — add/edit/delete items by category, cost price and markup % drive an auto-calculated selling price (rounded to the nearest ₦50).
- **New Quote** — pick items from a dropdown, enter quantity, prices and totals fill in automatically. Supports a discount %.
- **Quotes** — every saved quote gets a reference number (e.g. `QT-26-0001`) and stays in the shared history.
- **Printable Quote** — each quote has a clean client-facing layout with your business name, address, payment details, and a "Print / Save as PDF" button — no spreadsheet clutter.
- **Settings** — business name, tagline, address, phone, bank details, and quote validity period, all editable without touching code.
- **Shared password login** — one shared password protects the whole app, since cost prices and margins are sensitive.

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — default password is `sigma2026` (change this, see below).

## Changing the password

Set the `APP_PASSWORD` environment variable before running:
```bash
export APP_PASSWORD="your-new-password"
python app.py
```
On Render, add it under **Environment** in your service settings instead.

## Deploying to Render (same flow as your Pricewise project)

1. Push this folder to a new GitHub repo.
2. On Render: **New +** → **Web Service** → connect the repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Add environment variables:
   - `APP_PASSWORD` — the shared password your family will use
   - `SECRET_KEY` — any random string (keeps login sessions secure)
5. Deploy. Render gives you a live URL your parents can open on any phone or laptop browser.

**Note on the database:** this uses a local SQLite file (`pricing.db`), which works fine for one Render instance but Render's free tier disk isn't guaranteed to persist across redeploys. If the price list or quotes disappear after a redeploy, that's why — the fix at that point is switching to Render's free Postgres add-on, which I can help you set up whenever you're ready to scale past a single-file database.

## First-time setup checklist
1. Log in with the shared password.
2. Go to **Settings** → fill in real business name, address, phone, bank details.
3. Go to **Price List** → edit the 11 sample items to match real current prices, add more as needed.
4. Try **New Quote** → confirm the printed quote looks right before showing a real customer.
