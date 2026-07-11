import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy

basedir = os.path.abspath(os.path.dirname(__file__))


def get_database_uri():
    """Use Postgres if DATABASE_URL is set (e.g. on Render), else fall back to
    the local pricing.db SQLite file for local development."""
    url = os.environ.get('DATABASE_URL', '').strip()
    if url:
        # Render (and some other hosts) hand out "postgres://", but SQLAlchemy 1.4+
        # requires the "postgresql://" scheme.
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        return url
    return 'sqlite:///' + os.path.join(basedir, 'pricing.db')


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

APP_PASSWORD = os.environ.get('APP_PASSWORD', 'sigma2026')

db = SQLAlchemy(app)


# ---------------- Models ----------------
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(120), default='Analec International Lighting')
    tagline = db.Column(db.String(200), default='Lighting, Cables & Electrical Supplies')
    address = db.Column(db.String(200), default='')
    phone = db.Column(db.String(50), default='')
    bank_name = db.Column(db.String(100), default='')
    account_number = db.Column(db.String(50), default='')
    account_name = db.Column(db.String(100), default='')
    quote_validity_days = db.Column(db.Integer, default=7)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    brand = db.Column(db.String(100), default='')
    unit = db.Column(db.String(50), nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0)
    markup_pct = db.Column(db.Float, nullable=False, default=0)  # stored as e.g. 0.20 for 20%
    notes = db.Column(db.String(250), default='')
    quantity_on_hand = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5)

    @property
    def selling_price(self):
        return round(self.cost_price * (1 + self.markup_pct) / 50) * 50  # rounds to nearest 50

    @property
    def is_low_stock(self):
        return self.quantity_on_hand <= self.low_stock_threshold


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50), default='')
    address = db.Column(db.String(200), default='')
    notes = db.Column(db.String(250), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    quotes = db.relationship('Quote', backref='customer')

    @property
    def total_business(self):
        return sum(q.grand_total for q in self.quotes)

    @property
    def quote_count(self):
        return len(self.quotes)


QUOTE_STATUSES = ['pending', 'accepted', 'declined', 'converted']
QUOTE_STATUS_LABELS = {
    'pending': 'Pending',
    'accepted': 'Accepted',
    'declined': 'Declined',
    'converted': 'Converted to Sale',
}


class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_ref = db.Column(db.String(30), unique=True, nullable=False)
    client_name = db.Column(db.String(150), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    project_site = db.Column(db.String(200), default='')
    discount_pct = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending', nullable=False)
    stock_deducted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    lines = db.relationship('QuoteLine', backref='quote', cascade='all, delete-orphan')

    @property
    def status_label(self):
        return QUOTE_STATUS_LABELS.get(self.status, self.status.title())

    @property
    def subtotal(self):
        return sum(l.line_total for l in self.lines)

    @property
    def discount_amount(self):
        return self.subtotal * (self.discount_pct or 0)

    @property
    def grand_total(self):
        return self.subtotal - self.discount_amount


class QuoteLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=True)
    item_name = db.Column(db.String(150), nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    qty = db.Column(db.Float, nullable=False, default=1)
    unit_price = db.Column(db.Float, nullable=False, default=0)

    @property
    def line_total(self):
        return self.qty * self.unit_price


# ---------------- Auth ----------------
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapped


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(request.args.get('next') or url_for('price_list'))
        flash('Wrong password. Try again.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------- Settings ----------------
def get_settings():
    s = Settings.query.first()
    if not s:
        s = Settings()
        db.session.add(s)
        db.session.commit()
    return s


@app.context_processor
def inject_settings():
    return dict(settings=get_settings())


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    s = get_settings()
    if request.method == 'POST':
        s.business_name = request.form.get('business_name', '').strip() or s.business_name
        s.tagline = request.form.get('tagline', '').strip()
        s.address = request.form.get('address', '').strip()
        s.phone = request.form.get('phone', '').strip()
        s.bank_name = request.form.get('bank_name', '').strip()
        s.account_number = request.form.get('account_number', '').strip()
        s.account_name = request.form.get('account_name', '').strip()
        try:
            s.quote_validity_days = int(request.form.get('quote_validity_days', 7))
        except ValueError:
            s.quote_validity_days = 7
        db.session.commit()
        flash('Settings saved.')
        return redirect(url_for('settings'))
    return render_template('settings.html', s=s)


# ---------------- Price List ----------------
@app.route('/')
@login_required
def home():
    return redirect(url_for('price_list'))


@app.route('/price-list')
@login_required
def price_list():
    items = Item.query.order_by(Item.category, Item.name).all()
    categories = {}
    for it in items:
        categories.setdefault(it.category, []).append(it)
    return render_template('price_list.html', categories=categories)


@app.route('/rate-sheet')
@login_required
def rate_sheet():
    items = Item.query.order_by(Item.category, Item.name).all()
    categories = {}
    for it in items:
        categories.setdefault(it.category, []).append(it)
    return render_template('rate_sheet.html', categories=categories)


@app.route('/price-list/add', methods=['GET', 'POST'])
@login_required
def item_add():
    if request.method == 'POST':
        it = Item(
            category=request.form['category'].strip(),
            name=request.form['name'].strip(),
            brand=request.form.get('brand', '').strip(),
            unit=request.form['unit'].strip(),
            cost_price=float(request.form.get('cost_price') or 0),
            markup_pct=float(request.form.get('markup_pct') or 0) / 100,
            notes=request.form.get('notes', '').strip(),
            quantity_on_hand=int(request.form.get('quantity_on_hand') or 0),
            low_stock_threshold=int(request.form.get('low_stock_threshold') or 5),
        )
        db.session.add(it)
        db.session.commit()
        flash(f'"{it.name}" added to price list.')
        return redirect(url_for('price_list'))
    return render_template('item_form.html', item=None)


@app.route('/price-list/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def item_edit(item_id):
    it = Item.query.get_or_404(item_id)
    if request.method == 'POST':
        it.category = request.form['category'].strip()
        it.name = request.form['name'].strip()
        it.brand = request.form.get('brand', '').strip()
        it.unit = request.form['unit'].strip()
        it.cost_price = float(request.form.get('cost_price') or 0)
        it.markup_pct = float(request.form.get('markup_pct') or 0) / 100
        it.notes = request.form.get('notes', '').strip()
        it.quantity_on_hand = int(request.form.get('quantity_on_hand') or 0)
        it.low_stock_threshold = int(request.form.get('low_stock_threshold') or 5)
        db.session.commit()
        flash(f'"{it.name}" updated.')
        return redirect(url_for('price_list'))
    return render_template('item_form.html', item=it)


@app.route('/price-list/delete/<int:item_id>', methods=['POST'])
@login_required
def item_delete(item_id):
    it = Item.query.get_or_404(item_id)
    db.session.delete(it)
    db.session.commit()
    flash(f'"{it.name}" removed.')
    return redirect(url_for('price_list'))


@app.route('/price-list/bulk-update', methods=['GET', 'POST'])
@login_required
def bulk_price_update():
    categories = sorted({it.category for it in Item.query.all()})
    if request.method == 'POST':
        category = request.form.get('category', '')
        try:
            pct = float(request.form.get('pct') or 0)
        except ValueError:
            pct = 0
        field = request.form.get('field', 'cost_price')  # 'cost_price' or 'markup_pct'

        if not category or pct == 0:
            flash('Choose a category and a non-zero percentage.')
            return redirect(url_for('bulk_price_update'))

        items = Item.query.filter_by(category=category).all()
        if not items:
            flash(f'No items found in "{category}".')
            return redirect(url_for('bulk_price_update'))

        for it in items:
            if field == 'markup_pct':
                it.markup_pct = round(it.markup_pct * (1 + pct / 100), 4)
            else:
                it.cost_price = round(it.cost_price * (1 + pct / 100), 2)
        db.session.commit()

        direction = 'increased' if pct > 0 else 'decreased'
        field_label = 'markup %' if field == 'markup_pct' else 'cost prices'
        flash(f'{field_label.capitalize()} for {len(items)} item(s) in "{category}" {direction} by {abs(pct)}%.')
        return redirect(url_for('price_list'))

    return render_template('bulk_update.html', categories=categories)


@app.route('/api/items')
@login_required
def api_items():
    items = Item.query.order_by(Item.category, Item.name).all()
    return jsonify([
        {
            'id': i.id, 'name': i.name, 'brand': i.brand, 'unit': i.unit, 'price': i.selling_price,
            'category': i.category, 'stock': i.quantity_on_hand,
        }
        for i in items
    ])


# ---------------- Customers ----------------
@app.route('/customers')
@login_required
def customers_list():
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('customers_list.html', customers=customers)


@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def customer_add():
    if request.method == 'POST':
        c = Customer(
            name=request.form['name'].strip(),
            phone=request.form.get('phone', '').strip(),
            address=request.form.get('address', '').strip(),
            notes=request.form.get('notes', '').strip(),
        )
        db.session.add(c)
        db.session.commit()
        flash(f'"{c.name}" added to customers.')
        return redirect(url_for('customers_list'))
    return render_template('customer_form.html', customer=None)


@app.route('/customers/<int:customer_id>')
@login_required
def customer_view(customer_id):
    c = Customer.query.get_or_404(customer_id)
    quotes = sorted(c.quotes, key=lambda q: q.created_at, reverse=True)
    return render_template('customer_view.html', c=c, quotes=quotes)


@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
@login_required
def customer_edit(customer_id):
    c = Customer.query.get_or_404(customer_id)
    if request.method == 'POST':
        c.name = request.form['name'].strip()
        c.phone = request.form.get('phone', '').strip()
        c.address = request.form.get('address', '').strip()
        c.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash(f'"{c.name}" updated.')
        return redirect(url_for('customer_view', customer_id=c.id))
    return render_template('customer_form.html', customer=c)


@app.route('/customers/delete/<int:customer_id>', methods=['POST'])
@login_required
def customer_delete(customer_id):
    c = Customer.query.get_or_404(customer_id)
    if c.quotes:
        flash(f'Cannot delete "{c.name}" — they have {len(c.quotes)} quote(s) on file. Remove those first.')
        return redirect(url_for('customer_view', customer_id=c.id))
    db.session.delete(c)
    db.session.commit()
    flash(f'"{c.name}" removed.')
    return redirect(url_for('customers_list'))


@app.route('/api/customers')
@login_required
def api_customers():
    customers = Customer.query.order_by(Customer.name).all()
    return jsonify([
        {'id': c.id, 'name': c.name, 'phone': c.phone, 'address': c.address}
        for c in customers
    ])


# ---------------- Quotes ----------------
def next_quote_ref():
    year = datetime.utcnow().strftime('%y')
    count = Quote.query.count() + 1
    return f'QT-{year}-{count:04d}'


@app.route('/quotes')
@login_required
def quotes_list():
    status_filter = request.args.get('status', '')
    query = Quote.query
    if status_filter in QUOTE_STATUSES:
        query = query.filter_by(status=status_filter)
    quotes = query.order_by(Quote.created_at.desc()).all()
    return render_template(
        'quotes_list.html',
        quotes=quotes,
        status_filter=status_filter,
        statuses=QUOTE_STATUSES,
        status_labels=QUOTE_STATUS_LABELS,
    )


@app.route('/quotes/new', methods=['GET', 'POST'])
@login_required
def quote_new():
    if request.method == 'POST':
        customer = None
        customer_id = request.form.get('customer_id', '').strip()
        new_customer_name = request.form.get('new_customer_name', '').strip()

        if customer_id:
            customer = Customer.query.get(int(customer_id))
        elif new_customer_name:
            customer = Customer(
                name=new_customer_name,
                phone=request.form.get('new_customer_phone', '').strip(),
                address=request.form.get('new_customer_address', '').strip(),
            )
            db.session.add(customer)
            db.session.flush()  # get customer.id before quote commit

        if not customer:
            flash('Select an existing customer or enter a new customer name.')
            return render_template('quote_new.html')

        q = Quote(
            quote_ref=next_quote_ref(),
            client_name=customer.name,
            customer_id=customer.id,
            project_site=request.form.get('project_site', '').strip(),
            discount_pct=float(request.form.get('discount_pct') or 0) / 100,
        )
        db.session.add(q)

        item_ids = request.form.getlist('item_id[]')
        qtys = request.form.getlist('qty[]')
        for item_id, qty in zip(item_ids, qtys):
            if not item_id or not qty:
                continue
            it = Item.query.get(int(item_id))
            if not it or float(qty) <= 0:
                continue
            line = QuoteLine(
                item_id=it.id,
                item_name=it.name,
                unit=it.unit,
                qty=float(qty),
                unit_price=it.selling_price,
            )
            q.lines.append(line)

        if not q.lines:
            db.session.rollback()
            flash('Add at least one item with a quantity before saving.')
            return render_template('quote_new.html')

        db.session.add(q)
        db.session.commit()
        flash(f'Quote {q.quote_ref} created.')
        return redirect(url_for('quote_view', quote_id=q.id))

    return render_template('quote_new.html')


@app.route('/quotes/<int:quote_id>')
@login_required
def quote_view(quote_id):
    q = Quote.query.get_or_404(quote_id)
    return render_template('quote_view.html', q=q, statuses=QUOTE_STATUSES, status_labels=QUOTE_STATUS_LABELS)


@app.route('/quotes/<int:quote_id>/status', methods=['POST'])
@login_required
def quote_status_update(quote_id):
    q = Quote.query.get_or_404(quote_id)
    new_status = request.form.get('status', '')
    if new_status in QUOTE_STATUSES:
        if new_status == 'converted' and not q.stock_deducted:
            for line in q.lines:
                if line.item_id:
                    it = Item.query.get(line.item_id)
                    if it:
                        it.quantity_on_hand = max(0, it.quantity_on_hand - int(line.qty))
            q.stock_deducted = True
        elif q.status == 'converted' and new_status != 'converted' and q.stock_deducted:
            # customer backed out after being marked converted — put stock back
            for line in q.lines:
                if line.item_id:
                    it = Item.query.get(line.item_id)
                    if it:
                        it.quantity_on_hand += int(line.qty)
            q.stock_deducted = False

        q.status = new_status
        db.session.commit()
        flash(f'Quote {q.quote_ref} marked as {q.status_label}.')
    return redirect(url_for('quote_view', quote_id=q.id))


@app.route('/quotes/<int:quote_id>/delete', methods=['POST'])
@login_required
def quote_delete(quote_id):
    q = Quote.query.get_or_404(quote_id)
    ref = q.quote_ref
    db.session.delete(q)
    db.session.commit()
    flash(f'Quote {ref} deleted.')
    return redirect(url_for('quotes_list'))


# ---------------- Seed data ----------------
SEED_ITEMS = [
    ("Cable", "1.5mm Cable Coil", "Coil", 15000, 0.20),
    ("Cable", "2.5mm Cable Coil", "Coil", 22000, 0.20),
    ("Cable", "4mm Cable Coil", "Coil", 35000, 0.18),
    ("Cable", "6mm Cable Coil", "Coil", 52000, 0.18),
    ("Distribution Boards", "Single-Phase DB 8-Way", "Piece", 8000, 0.25),
    ("Distribution Boards", "Single-Phase DB 12-Way", "Piece", 12000, 0.25),
    ("Distribution Boards", "Three-Phase DB", "Piece", 35000, 0.20),
    ("Switches", "1-Gang Switch", "Piece", 800, 0.30),
    ("Switches", "2-Gang Switch", "Piece", 1200, 0.30),
    ("Conduit", "20mm Conduit", "Piece (3m)", 600, 0.25),
    ("Conduit", "25mm Conduit", "Piece (3m)", 900, 0.25),
]


def migrate_schema():
    """Add new columns/tables to an existing pricing.db without wiping data."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()

    if 'quote' in existing_tables:
        quote_cols = [c['name'] for c in inspector.get_columns('quote')]
        with db.engine.connect() as conn:
            if 'customer_id' not in quote_cols:
                conn.execute(text('ALTER TABLE quote ADD COLUMN customer_id INTEGER'))
            if 'status' not in quote_cols:
                conn.execute(text("ALTER TABLE quote ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"))
                conn.execute(text("UPDATE quote SET status = 'pending' WHERE status IS NULL"))
            if 'stock_deducted' not in quote_cols:
                conn.execute(text('ALTER TABLE quote ADD COLUMN stock_deducted BOOLEAN DEFAULT 0'))
                conn.execute(text('UPDATE quote SET stock_deducted = 0 WHERE stock_deducted IS NULL'))
            conn.commit()

    if 'quote_line' in existing_tables:
        line_cols = [c['name'] for c in inspector.get_columns('quote_line')]
        with db.engine.connect() as conn:
            if 'item_id' not in line_cols:
                conn.execute(text('ALTER TABLE quote_line ADD COLUMN item_id INTEGER'))
            conn.commit()

    if 'item' in existing_tables:
        item_cols = [c['name'] for c in inspector.get_columns('item')]
        with db.engine.connect() as conn:
            if 'quantity_on_hand' not in item_cols:
                conn.execute(text('ALTER TABLE item ADD COLUMN quantity_on_hand INTEGER DEFAULT 0'))
                conn.execute(text('UPDATE item SET quantity_on_hand = 0 WHERE quantity_on_hand IS NULL'))
            if 'low_stock_threshold' not in item_cols:
                conn.execute(text('ALTER TABLE item ADD COLUMN low_stock_threshold INTEGER DEFAULT 5'))
                conn.execute(text('UPDATE item SET low_stock_threshold = 5 WHERE low_stock_threshold IS NULL'))
            if 'brand' not in item_cols:
                conn.execute(text("ALTER TABLE item ADD COLUMN brand VARCHAR(100) DEFAULT ''"))
                conn.execute(text("UPDATE item SET brand = '' WHERE brand IS NULL"))
            conn.commit()


def init_db():
    db.create_all()  # creates any brand-new tables (e.g. customer) that don't exist yet
    migrate_schema()  # patches older tables (e.g. quote) that already exist without new columns
    if Item.query.count() == 0:
        for cat, name, unit, cost, markup in SEED_ITEMS:
            db.session.add(Item(category=cat, name=name, unit=unit, cost_price=cost, markup_pct=markup))
        db.session.commit()
    get_settings()


with app.app_context():
    init_db()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
