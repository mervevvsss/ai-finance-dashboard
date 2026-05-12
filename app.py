from flask import Flask, request, jsonify, redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras
import json
import pandas as pd
import os

app = Flask(__name__)
app.secret_key = "ai_finance_dashboard_secret_key"

DATABASE_URL = os.getenv("DATABASE_URL")

DB_CONFIG = {
    "host": "localhost",
    "database": "ai_finance_dashboard",
    "user": "postgres",
    "password": "1234"
}

def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(**DB_CONFIG)

def fetch_all_dict(query, params=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def fetch_one_dict(query, params=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params or ())
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def fetch_one_value(query, params=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params or ())
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        return 0
    return row[0]


def execute_query(query, params=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params or ())
    conn.commit()
    cur.close()
    conn.close()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return func(*args, **kwargs)
    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        if session.get("role") != "admin":
            return redirect("/transactions")
        return func(*args, **kwargs)
    return wrapper


def get_date_filter_clause(range_value, alias="t"):
    if range_value == "7":
        return f" AND {alias}.transaction_date >= CURRENT_DATE - INTERVAL '7 days' "
    elif range_value == "30":
        return f" AND {alias}.transaction_date >= CURRENT_DATE - INTERVAL '30 days' "
    elif range_value == "90":
        return f" AND {alias}.transaction_date >= CURRENT_DATE - INTERVAL '90 days' "
    return ""


def get_range_title(range_value):
    if range_value == "7":
        return "Son 7 Gün"
    elif range_value == "30":
        return "Son 30 Gün"
    elif range_value == "90":
        return "Son 90 Gün"
    return "Tüm Zamanlar"


def get_lookup_data():
    main_categories = fetch_all_dict("""
        SELECT main_category_id, name, type
        FROM main_categories
        WHERE is_active = TRUE
        ORDER BY name;
    """)

    sub_categories = fetch_all_dict("""
        SELECT sub_category_id, main_category_id, name
        FROM sub_categories
        WHERE is_active = TRUE
        ORDER BY name;
    """)

    currencies = fetch_all_dict("""
        SELECT currency_id, code
        FROM currencies
        WHERE is_active = TRUE
        ORDER BY code;
    """)

    payment_methods = fetch_all_dict("""
        SELECT payment_method_id, name
        FROM payment_methods
        WHERE is_active = TRUE
        ORDER BY name;
    """)

    return main_categories, sub_categories, currencies, payment_methods


def get_all_budget_warnings(user_id):
    budgets = fetch_all_dict("""
        SELECT
            b.budget_id,
            b.user_id,
            b.main_category_id,
            b.amount AS budget_amount,
            b.start_date,
            b.end_date,
            mc.name AS category_name
        FROM budgets b
        JOIN main_categories mc ON b.main_category_id = mc.main_category_id
        WHERE b.user_id = %s
        ORDER BY b.end_date DESC;
    """, (user_id,))

    warnings = []

    for budget in budgets:
        spent_amount = fetch_one_value("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE user_id = %s
              AND main_category_id = %s
              AND transaction_type = 'expense'
              AND transaction_date BETWEEN %s AND %s;
        """, (
            budget["user_id"],
            budget["main_category_id"],
            budget["start_date"],
            budget["end_date"]
        ))

        spent_amount = float(spent_amount)
        budget_amount = float(budget["budget_amount"])

        if spent_amount > budget_amount:
            warnings.append({
                "category_name": budget["category_name"],
                "spent_amount": spent_amount,
                "budget_amount": budget_amount,
                "start_date": str(budget["start_date"]),
                "end_date": str(budget["end_date"])
            })

    return warnings


def get_budget_status_list(user_id):
    budgets = fetch_all_dict("""
        SELECT
            b.budget_id,
            b.user_id,
            b.main_category_id,
            b.amount AS budget_amount,
            b.start_date,
            b.end_date,
            mc.name AS category_name
        FROM budgets b
        JOIN main_categories mc ON b.main_category_id = mc.main_category_id
        WHERE b.user_id = %s
        ORDER BY b.end_date DESC;
    """, (user_id,))

    result = []

    for budget in budgets:
        spent_amount = fetch_one_value("""
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE user_id = %s
              AND main_category_id = %s
              AND transaction_type = 'expense'
              AND transaction_date BETWEEN %s AND %s;
        """, (
            budget["user_id"],
            budget["main_category_id"],
            budget["start_date"],
            budget["end_date"]
        ))

        spent_amount = float(spent_amount)
        budget_amount = float(budget["budget_amount"])
        remaining_amount = budget_amount - spent_amount
        usage_percent = (spent_amount / budget_amount) * 100 if budget_amount > 0 else 0

        if usage_percent >= 100:
            status = "danger"
            status_text = "Limit Aşıldı"
        elif usage_percent >= 80:
            status = "warning"
            status_text = "Limite Yaklaşıldı"
        else:
            status = "success"
            status_text = "Normal"

        result.append({
            "category_name": budget["category_name"],
            "budget_amount": budget_amount,
            "spent_amount": spent_amount,
            "remaining_amount": remaining_amount,
            "usage_percent": usage_percent,
            "status": status,
            "status_text": status_text,
            "start_date": str(budget["start_date"]),
            "end_date": str(budget["end_date"])
        })

    return result


def get_monthly_expense_prediction(user_id):
    rows = fetch_all_dict("""
        SELECT transaction_date, amount
        FROM transactions
        WHERE transaction_type = 'expense'
          AND user_id = %s
        ORDER BY transaction_date ASC;
    """, (user_id,))

    if not rows:
        return {
            "prediction": 0.0,
            "months_used": 0,
            "method": "Yeterli veri yok",
            "history": [],
            "trend": "Veri yok",
            "comment": "Tahmin üretmek için yeterli gider verisi bulunmuyor."
        }

    df = pd.DataFrame(rows)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["amount"] = pd.to_numeric(df["amount"])
    df["year_month"] = df["transaction_date"].dt.to_period("M")

    monthly = (
        df.groupby("year_month")["amount"]
        .sum()
        .reset_index()
        .sort_values("year_month")
    )

    last_months = monthly.tail(3).copy()

    if last_months.empty:
        return {
            "prediction": 0.0,
            "months_used": 0,
            "method": "Yeterli veri yok",
            "history": [],
            "trend": "Veri yok",
            "comment": "Tahmin üretmek için yeterli gider verisi bulunmuyor."
        }

    prediction = float(last_months["amount"].mean())
    months_used = len(last_months)

    history = []
    for _, row in last_months.iterrows():
        period_value = row["year_month"]
        history.append({
            "year": int(period_value.year),
            "month": int(period_value.month),
            "total_expense": float(row["amount"])
        })

    trend = "Stabil"
    comment = "Harcamalar son aylarda benzer seviyelerde seyrediyor."

    if len(last_months) >= 2:
        first_value = float(last_months.iloc[0]["amount"])
        last_value = float(last_months.iloc[-1]["amount"])
        change_percent = ((last_value - first_value) / first_value) * 100 if first_value > 0 else 0

        if change_percent > 10:
            trend = "Artış"
            comment = "Son aylarda giderlerde belirgin bir artış eğilimi görülüyor."
        elif change_percent < -10:
            trend = "Azalış"
            comment = "Son aylarda giderlerde düşüş eğilimi görülüyor."

    return {
        "prediction": prediction,
        "months_used": months_used,
        "method": "Pandas ile son 3 ay ortalaması",
        "history": history,
        "trend": trend,
        "comment": comment
    }


@app.route("/")
def home():
    dashboard_link = "/transactions" if "user_id" in session else "/login"
    return f"""
    <html>
        <head>
            <title>AI Finance Dashboard</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
            <div class="container py-5">
                <div class="card shadow border-0 rounded-4">
                    <div class="card-body p-5 text-center">
                        <div style="font-size: 56px;">💰</div>
                        <h1 class="fw-bold mt-3">AI Finance Dashboard</h1>
                        <p class="text-muted">Akıllı Harcama Takip Sistemi</p>
                        <a href="/login" class="btn btn-primary btn-lg me-2">Giriş Yap</a>
                        <a href="{dashboard_link}" class="btn btn-outline-dark btn-lg">Dashboard</a>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = fetch_one_dict("SELECT * FROM users WHERE email = %s AND is_active = TRUE", (email,))

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect("/admin/users")
            return redirect("/transactions")

        return "Hata: Email veya şifre hatalı!"

    return """
    <html>
        <head>
            <title>Giriş Yap</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: linear-gradient(135deg, #eef2ff, #f8fafc); min-height: 100vh; }
                .login-card { border: none; border-radius: 28px; box-shadow: 0 20px 50px rgba(0,0,0,0.08); }
                .form-control { border-radius: 14px; padding: 12px; }
                .login-btn { border-radius: 16px; padding: 13px; font-weight: 700; }
            </style>
        </head>
        <body>
            <div class="container py-5">
                <div class="row justify-content-center align-items-center" style="min-height: 85vh;">
                    <div class="col-md-6 col-lg-5">
                        <div class="card login-card">
                            <div class="card-body p-5">
                                <div class="text-center mb-4">
                                    <div style="font-size: 54px;">🔐</div>
                                    <h2 class="fw-bold mt-3">Giriş Yap</h2>
                                    <p class="text-muted">AI Finance Dashboard hesabına giriş yap.</p>
                                </div>

                                <form method="POST" action="/login">
                                    <div class="mb-3">
                                        <label class="form-label">Email</label>
                                        <input type="email" name="email" class="form-control" required>
                                    </div>

                                    <div class="mb-4">
                                        <label class="form-label">Şifre</label>
                                        <input type="password" name="password" class="form-control" required>
                                    </div>

                                    <div class="d-grid">
                                        <button type="submit" class="btn btn-primary login-btn">Giriş Yap</button>
                                    </div>
                                </form>

                                <div class="text-center mt-4">
                                    <a href="/forgot-password" class="text-decoration-none">Şifremi unuttum</a>
                                    <span class="mx-2">|</span>
                                    <a href="/register" class="text-decoration-none">Kayıt Ol</a>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")
        hashed_password = generate_password_hash(password)

        existing_user = fetch_one_dict("SELECT user_id FROM users WHERE email = %s", (email,))
        if existing_user:
            return "Bu email adresiyle kayıtlı kullanıcı zaten var."

        execute_query("""
            INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)
            VALUES (%s, %s, %s, 'user', TRUE, CURRENT_TIMESTAMP)
        """, (full_name, email, hashed_password))

        return redirect("/login")

    return """
    <html>
        <head>
            <title>Kayıt Ol</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body { background: linear-gradient(135deg, #eef2ff, #f8fafc); min-height: 100vh; }
                .register-card { border-radius: 28px; box-shadow: 0 20px 50px rgba(0,0,0,0.08); }
                .form-control { border-radius: 14px; padding: 12px; }
                .btn { border-radius: 14px; }
            </style>
        </head>
        <body>
            <div class="container py-5">
                <div class="row justify-content-center align-items-center" style="min-height: 85vh;">
                    <div class="col-md-6 col-lg-5">
                        <div class="card register-card">
                            <div class="card-body p-5">
                                <div class="text-center mb-4">
                                    <div style="font-size: 50px;">📝</div>
                                    <h2 class="fw-bold mt-2">Kayıt Ol</h2>
                                    <p class="text-muted">Yeni hesap oluştur</p>
                                </div>

                                <form method="POST" action="/register">
                                    <div class="mb-3">
                                        <label>Ad Soyad</label>
                                        <input type="text" name="full_name" class="form-control" required>
                                    </div>

                                    <div class="mb-3">
                                        <label>Email</label>
                                        <input type="email" name="email" class="form-control" required>
                                    </div>

                                    <div class="mb-4">
                                        <label>Şifre</label>
                                        <input type="password" name="password" class="form-control" required>
                                    </div>

                                    <div class="d-grid">
                                        <button class="btn btn-success">Kayıt Ol</button>
                                    </div>
                                </form>

                                <div class="text-center mt-4">
                                    <a href="/login">Zaten hesabın var mı? Giriş yap</a>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@app.route("/admin/users")
@admin_required
def admin_users():
    users = fetch_all_dict("""
        SELECT user_id, full_name, email, role, is_active, created_at
        FROM users
        ORDER BY user_id DESC;
    """)

    rows = ""
    for user in users:
        rows += f"""
        <tr>
            <td>{user["user_id"]}</td>
            <td>{user["full_name"]}</td>
            <td>{user["email"]}</td>
            <td><span class="badge bg-primary">{user["role"]}</span></td>
            <td>{user["is_active"]}</td>
            <td>{user["created_at"]}</td>
        </tr>
        """

    return f"""
    <html>
        <head>
            <title>Admin Panel</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ background: #f8fafc; }}
                .admin-header {{
                    background: linear-gradient(135deg, #111827, #1f2937);
                    color: white;
                    padding: 28px;
                    border-radius: 24px;
                }}
                .page-card {{
                    border: none;
                    border-radius: 24px;
                    box-shadow: 0 20px 45px rgba(0,0,0,0.08);
                }}
            </style>
        </head>
        <body>
            <div class="container py-5">
                <div class="admin-header mb-4 d-flex justify-content-between align-items-center">
                    <div>
                        <h2 class="mb-1">Admin Panel</h2>
                        <p class="mb-0">Kayıtlı kullanıcıları görüntüleme ekranı.</p>
                    </div>
                    <div>
                        <a href="/transactions" class="btn btn-outline-light me-2">Dashboard</a>
                        <a href="/logout" class="btn btn-danger">Çıkış Yap</a>
                    </div>
                </div>

                <div class="card page-card">
                    <div class="card-body p-4">
                        <h4 class="mb-3">Kullanıcı Listesi</h4>
                        <div class="table-responsive">
                            <table class="table table-hover align-middle">
                                <thead class="table-light">
                                    <tr>
                                        <th>ID</th>
                                        <th>Ad Soyad</th>
                                        <th>Email</th>
                                        <th>Rol</th>
                                        <th>Aktif mi?</th>
                                        <th>Kayıt Tarihi</th>
                                    </tr>
                                </thead>
                                <tbody>{rows}</tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


def render_transaction_form(action_url, button_text, page_title, form_title, transaction=None):
    main_categories, sub_categories, currencies, payment_methods = get_lookup_data()

    transaction = transaction or {
        "main_category_id": "",
        "sub_category_id": "",
        "currency_id": "",
        "payment_method_id": "",
        "transaction_type": "",
        "amount": "",
        "description": "",
        "transaction_date": ""
    }

    main_category_options = ""
    for category in main_categories:
        selected = "selected" if str(category["main_category_id"]) == str(transaction["main_category_id"]) else ""
        main_category_options += f'<option value="{category["main_category_id"]}" {selected}>{category["name"]}</option>'
    main_category_options += '<option value="new_category">+ Yeni kategori ekle</option>'

    currency_options = ""
    for currency in currencies:
        selected = "selected" if str(currency["currency_id"]) == str(transaction["currency_id"]) else ""
        currency_options += f'<option value="{currency["currency_id"]}" {selected}>{currency["code"]}</option>'

    payment_method_options = ""
    for method in payment_methods:
        selected = "selected" if str(method["payment_method_id"]) == str(transaction["payment_method_id"]) else ""
        payment_method_options += f'<option value="{method["payment_method_id"]}" {selected}>{method["name"]}</option>'

    subcategories_json = json.dumps(sub_categories, ensure_ascii=False)
    selected_sub_category = str(transaction["sub_category_id"])

    expense_selected = "selected" if transaction["transaction_type"] == "expense" else ""
    income_selected = "selected" if transaction["transaction_type"] == "income" else ""

    return f"""
    <html>
        <head>
            <title>{page_title}</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
            <div class="container py-5">
                <div class="card shadow border-0 rounded-4">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-4">
                            <h2 class="fw-bold mb-0">{form_title}</h2>
                            <a href="/transactions" class="btn btn-outline-dark">Dashboard'a Dön</a>
                        </div>

                        <div class="mb-3" id="categoryFormBox" style="display:none;">
                            <div class="alert alert-light border">
                                <h5>Yeni Ana Kategori Ekle</h5>
                                <form method="POST" action="/add-category">
                                    <input type="text" class="form-control mb-2" name="name" placeholder="Kategori adı" required>
                                    <select class="form-select mb-2" name="type" required>
                                        <option value="expense">Gider</option>
                                        <option value="income">Gelir</option>
                                    </select>
                                    <button type="submit" class="btn btn-success">Kaydet</button>
                                </form>
                            </div>
                        </div>

                        <div class="mb-3" id="subCategoryFormBox" style="display:none;">
                            <div class="alert alert-light border">
                                <h5>Yeni Alt Kategori Ekle</h5>
                                <form method="POST" action="/add-subcategory">
                                    <input type="hidden" id="hiddenMainCategoryId" name="main_category_id">
                                    <input type="text" class="form-control mb-2" name="name" placeholder="Alt kategori adı" required>
                                    <input type="text" class="form-control mb-2" id="selectedMainCategoryName" readonly>
                                    <button type="submit" class="btn btn-success">Kaydet</button>
                                </form>
                            </div>
                        </div>

                        <form method="POST" action="{action_url}" onsubmit="return validateTransactionForm()">
                            <div class="row">
                                <div class="col-md-6 mb-3">
                                    <label>Ana Kategori</label>
                                    <select id="mainCategory" class="form-select" name="main_category_id" required>
                                        <option value="">Seçiniz</option>
                                        {main_category_options}
                                    </select>
                                </div>

                                <div class="col-md-6 mb-3">
                                    <label>Alt Kategori</label>
                                    <select id="subCategory" class="form-select" name="sub_category_id" required>
                                        <option value="">Seçiniz</option>
                                    </select>
                                </div>

                                <div class="col-md-6 mb-3">
                                    <label>Para Birimi</label>
                                    <select class="form-select" name="currency_id" required>
                                        <option value="">Seçiniz</option>
                                        {currency_options}
                                    </select>
                                </div>

                                <div class="col-md-6 mb-3">
                                    <label>Ödeme Yöntemi</label>
                                    <select class="form-select" name="payment_method_id" required>
                                        <option value="">Seçiniz</option>
                                        {payment_method_options}
                                    </select>
                                </div>

                                <div class="col-md-6 mb-3">
                                    <label>İşlem Tipi</label>
                                    <select class="form-select" name="transaction_type" required>
                                        <option value="">Seçiniz</option>
                                        <option value="expense" {expense_selected}>Gider</option>
                                        <option value="income" {income_selected}>Gelir</option>
                                    </select>
                                </div>

                                <div class="col-md-6 mb-3">
                                    <label>Tutar</label>
                                    <input type="number" step="0.01" class="form-control" name="amount" value="{transaction["amount"]}" required>
                                </div>

                                <div class="col-12 mb-3">
                                    <label>Açıklama</label>
                                    <input type="text" class="form-control" name="description" value="{transaction["description"]}" required>
                                </div>

                                <div class="col-12 mb-4">
                                    <label>Tarih</label>
                                    <input type="date" class="form-control" name="transaction_date" value="{transaction["transaction_date"]}" required>
                                </div>
                            </div>

                            <button type="submit" class="btn btn-primary w-100 btn-lg">{button_text}</button>
                        </form>
                    </div>
                </div>
            </div>

            <script>
                const allSubcategories = {subcategories_json};
                const selectedSubCategory = "{selected_sub_category}";
                const mainCategorySelect = document.getElementById("mainCategory");
                const subCategorySelect = document.getElementById("subCategory");
                const categoryFormBox = document.getElementById("categoryFormBox");
                const subCategoryFormBox = document.getElementById("subCategoryFormBox");
                const hiddenMainCategoryId = document.getElementById("hiddenMainCategoryId");
                const selectedMainCategoryName = document.getElementById("selectedMainCategoryName");

                function updateSubcategories() {{
                    const selectedValue = mainCategorySelect.value;
                    const selectedText = mainCategorySelect.options[mainCategorySelect.selectedIndex]?.text || "";

                    subCategoryFormBox.style.display = "none";

                    if (selectedValue === "new_category") {{
                        categoryFormBox.style.display = "block";
                        subCategorySelect.innerHTML = '<option value="">Önce kategori ekleyiniz</option>';
                        return;
                    }}

                    categoryFormBox.style.display = "none";
                    subCategorySelect.innerHTML = '<option value="">Seçiniz</option>';

                    const selectedMainCategoryId = parseInt(selectedValue);
                    if (!selectedMainCategoryId) return;

                    const filtered = allSubcategories.filter(sub => sub.main_category_id === selectedMainCategoryId);

                    filtered.forEach(sub => {{
                        const option = document.createElement("option");
                        option.value = sub.sub_category_id;
                        option.textContent = sub.name;
                        if (String(sub.sub_category_id) === selectedSubCategory) option.selected = true;
                        subCategorySelect.appendChild(option);
                    }});

                    const newOption = document.createElement("option");
                    newOption.value = "new_subcategory";
                    newOption.textContent = "+ Yeni alt kategori ekle";
                    subCategorySelect.appendChild(newOption);

                    hiddenMainCategoryId.value = selectedMainCategoryId;
                    selectedMainCategoryName.value = selectedText;
                }}

                function handleSubCategoryChange() {{
                    subCategoryFormBox.style.display = subCategorySelect.value === "new_subcategory" ? "block" : "none";
                }}

                function validateTransactionForm() {{
                    if (mainCategorySelect.value === "new_category") {{
                        alert("Önce yeni ana kategoriyi kaydetmelisin.");
                        return false;
                    }}
                    if (subCategorySelect.value === "new_subcategory") {{
                        alert("Önce yeni alt kategoriyi kaydetmelisin.");
                        return false;
                    }}
                    return true;
                }}

                mainCategorySelect.addEventListener("change", updateSubcategories);
                subCategorySelect.addEventListener("change", handleSubCategoryChange);
                updateSubcategories();
            </script>
        </body>
    </html>
    """


@app.route("/form", methods=["GET", "POST"])
@login_required
def transaction_form():
    if request.method == "POST":
        execute_query("""
            INSERT INTO transactions
            (user_id, main_category_id, sub_category_id, currency_id, payment_method_id,
             transaction_type, amount, description, transaction_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            session["user_id"],
            request.form["main_category_id"],
            request.form["sub_category_id"],
            request.form["currency_id"],
            request.form["payment_method_id"],
            request.form["transaction_type"],
            request.form["amount"],
            request.form["description"],
            request.form["transaction_date"]
        ))
        return redirect("/transactions")

    return render_transaction_form(
        "/form",
        "İşlem Ekle",
        "Yeni İşlem Ekle",
        "Yeni İşlem Ekle"
    )


@app.route("/add-category", methods=["POST"])
@login_required
def add_category():
    execute_query("""
        INSERT INTO main_categories (name, type, is_active, created_at, updated_at)
        VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (request.form["name"], request.form["type"]))
    return redirect("/form")


@app.route("/add-subcategory", methods=["POST"])
@login_required
def add_subcategory():
    execute_query("""
        INSERT INTO sub_categories (main_category_id, name, is_active, created_at, updated_at)
        VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (request.form["main_category_id"], request.form["name"]))
    return redirect("/form")


@app.route("/budgets", methods=["GET", "POST"])
@login_required
def manage_budgets():
    user_id = session["user_id"]

    if request.method == "POST":
        execute_query("""
            INSERT INTO budgets (user_id, main_category_id, amount, start_date, end_date)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            user_id,
            request.form["main_category_id"],
            request.form["amount"],
            request.form["start_date"],
            request.form["end_date"]
        ))
        return redirect("/budgets")

    main_categories = fetch_all_dict("""
        SELECT main_category_id, name
        FROM main_categories
        WHERE is_active = TRUE
        ORDER BY name;
    """)

    budgets = fetch_all_dict("""
        SELECT b.budget_id, mc.name AS category_name, b.amount, b.start_date, b.end_date
        FROM budgets b
        JOIN main_categories mc ON b.main_category_id = mc.main_category_id
        WHERE b.user_id = %s
        ORDER BY b.budget_id DESC;
    """, (user_id,))

    category_options = ""
    for category in main_categories:
        category_options += f'<option value="{category["main_category_id"]}">{category["name"]}</option>'

    budget_rows = ""
    for budget in budgets:
        budget_rows += f"""
        <tr>
            <td>{budget["budget_id"]}</td>
            <td>{budget["category_name"]}</td>
            <td>{float(budget["amount"]):.2f}</td>
            <td>{budget["start_date"]}</td>
            <td>{budget["end_date"]}</td>
            <td><a href="/delete-budget/{budget["budget_id"]}" class="btn btn-sm btn-danger" onclick="return confirm('Bütçeyi silmek istediğine emin misin?')">Sil</a></td>
        </tr>
        """

    if not budget_rows:
        budget_rows = "<tr><td colspan='6' class='text-center text-muted'>Henüz bütçe kaydı yok.</td></tr>"

    return f"""
    <html>
        <head>
            <title>Bütçe Yönetimi</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
            <div class="container py-5">
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h2>Bütçe Yönetimi</h2>
                    <a href="/transactions" class="btn btn-dark">Dashboard'a Dön</a>
                </div>

                <div class="card shadow border-0 rounded-4 mb-4">
                    <div class="card-body p-4">
                        <form method="POST" action="/budgets">
                            <div class="row">
                                <div class="col-md-4 mb-3">
                                    <select class="form-select" name="main_category_id" required>
                                        <option value="">Kategori seç</option>
                                        {category_options}
                                    </select>
                                </div>
                                <div class="col-md-3 mb-3">
                                    <input type="number" step="0.01" class="form-control" name="amount" placeholder="Bütçe miktarı" required>
                                </div>
                                <div class="col-md-2 mb-3">
                                    <input type="date" class="form-control" name="start_date" required>
                                </div>
                                <div class="col-md-2 mb-3">
                                    <input type="date" class="form-control" name="end_date" required>
                                </div>
                                <div class="col-md-1 mb-3">
                                    <button class="btn btn-primary w-100">Ekle</button>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>

                <div class="card shadow border-0 rounded-4">
                    <div class="card-body p-4">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Kategori</th>
                                    <th>Miktar</th>
                                    <th>Başlangıç</th>
                                    <th>Bitiş</th>
                                    <th>İşlem</th>
                                </tr>
                            </thead>
                            <tbody>{budget_rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@app.route("/delete-budget/<int:budget_id>")
@login_required
def delete_budget(budget_id):
    execute_query(
        "DELETE FROM budgets WHERE budget_id = %s AND user_id = %s",
        (budget_id, session["user_id"])
    )
    return redirect("/budgets")


@app.route("/transactions-json", methods=["GET"])
@login_required
def get_transactions_json():
    user_id = session["user_id"]
    rows = fetch_all_dict("""
        SELECT t.transaction_id AS id,
               u.full_name AS user,
               mc.name AS main_category,
               t.amount,
               t.transaction_date AS date
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        JOIN main_categories mc ON t.main_category_id = mc.main_category_id
        WHERE t.user_id = %s
        ORDER BY t.transaction_id DESC;
    """, (user_id,))

    for row in rows:
        row["amount"] = float(row["amount"])
        row["date"] = str(row["date"])
    return jsonify(rows)


@app.route("/edit-transaction/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    user_id = session["user_id"]

    transaction_owner = fetch_one_dict("""
        SELECT transaction_id
        FROM transactions
        WHERE transaction_id = %s AND user_id = %s
    """, (transaction_id, user_id))

    if not transaction_owner:
        return redirect("/transactions")

    if request.method == "POST":
        execute_query("""
            UPDATE transactions
            SET main_category_id = %s,
                sub_category_id = %s,
                currency_id = %s,
                payment_method_id = %s,
                transaction_type = %s,
                amount = %s,
                description = %s,
                transaction_date = %s
            WHERE transaction_id = %s AND user_id = %s
        """, (
            request.form["main_category_id"],
            request.form["sub_category_id"],
            request.form["currency_id"],
            request.form["payment_method_id"],
            request.form["transaction_type"],
            request.form["amount"],
            request.form["description"],
            request.form["transaction_date"],
            transaction_id,
            user_id
        ))
        return redirect("/transactions")

    transaction = fetch_one_dict("""
        SELECT transaction_id, main_category_id, sub_category_id, currency_id,
               payment_method_id, transaction_type, amount, description, transaction_date
        FROM transactions
        WHERE transaction_id = %s AND user_id = %s
    """, (transaction_id, user_id))

    transaction["transaction_date"] = str(transaction["transaction_date"])

    return render_transaction_form(
        f"/edit-transaction/{transaction_id}",
        "Değişiklikleri Kaydet",
        "İşlem Düzenle",
        "İşlem Düzenle",
        transaction
    )


@app.route("/delete-transaction/<int:transaction_id>")
@login_required
def delete_transaction(transaction_id):
    execute_query(
        "DELETE FROM transactions WHERE transaction_id = %s AND user_id = %s",
        (transaction_id, session["user_id"])
    )
    return redirect("/transactions")


@app.route("/transactions", methods=["POST"])
@login_required
def create_transaction():
    data = request.get_json() or {}

    required_fields = [
        "main_category_id", "sub_category_id", "currency_id", "payment_method_id",
        "transaction_type", "amount", "description", "transaction_date"
    ]

    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({"error": "Eksik alanlar", "missing_fields": missing_fields}), 400

    execute_query("""
        INSERT INTO transactions
        (user_id, main_category_id, sub_category_id, currency_id, payment_method_id,
         transaction_type, amount, description, transaction_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        session["user_id"],
        data["main_category_id"],
        data["sub_category_id"],
        data["currency_id"],
        data["payment_method_id"],
        data["transaction_type"],
        data["amount"],
        data["description"],
        data["transaction_date"]
    ))

    return jsonify({"message": "Transaction eklendi"}), 201


@app.route("/transactions", methods=["GET"])
@login_required
def get_transactions():
    user_id = session["user_id"]
    range_value = request.args.get("range", "all")
    range_title = get_range_title(range_value)
    date_filter = get_date_filter_clause(range_value, "t")

    warnings = get_all_budget_warnings(user_id)
    budget_status_list = get_budget_status_list(user_id)
    prediction_data = get_monthly_expense_prediction(user_id)

    total_count = fetch_one_value(f"""
        SELECT COUNT(*)
        FROM transactions t
        WHERE t.user_id = %s {date_filter};
    """, (user_id,))

    total_expense = fetch_one_value(f"""
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        WHERE t.user_id = %s
          AND t.transaction_type = 'expense'
          {date_filter};
    """, (user_id,))

    total_income = fetch_one_value(f"""
        SELECT COALESCE(SUM(t.amount), 0)
        FROM transactions t
        WHERE t.user_id = %s
          AND t.transaction_type = 'income'
          {date_filter};
    """, (user_id,))

    net_balance = float(total_income) - float(total_expense)

    top_category_row = fetch_one_dict(f"""
        SELECT mc.name AS category_name, COALESCE(SUM(t.amount), 0) AS total_amount
        FROM transactions t
        JOIN main_categories mc ON t.main_category_id = mc.main_category_id
        WHERE t.user_id = %s
          AND t.transaction_type = 'expense'
          {date_filter}
        GROUP BY mc.name
        ORDER BY total_amount DESC
        LIMIT 1;
    """, (user_id,))

    top_category_name = top_category_row["category_name"] if top_category_row else "Veri yok"
    top_category_amount = float(top_category_row["total_amount"]) if top_category_row else 0.0

    rows = fetch_all_dict(f"""
        SELECT
            t.transaction_id,
            u.full_name,
            mc.name AS main_category,
            COALESCE(sc.name, '-') AS sub_category,
            c.code AS currency,
            pm.name AS payment_method,
            t.transaction_type,
            t.amount,
            t.description,
            t.transaction_date
        FROM transactions t
        JOIN users u ON t.user_id = u.user_id
        JOIN main_categories mc ON t.main_category_id = mc.main_category_id
        LEFT JOIN sub_categories sc ON t.sub_category_id = sc.sub_category_id
        JOIN currencies c ON t.currency_id = c.currency_id
        JOIN payment_methods pm ON t.payment_method_id = pm.payment_method_id
        WHERE t.user_id = %s
        {date_filter}
        ORDER BY t.transaction_id DESC;
    """, (user_id,))

    category_expense_rows = fetch_all_dict(f"""
        SELECT mc.name AS category_name, COALESCE(SUM(t.amount), 0) AS total_amount
        FROM transactions t
        JOIN main_categories mc ON t.main_category_id = mc.main_category_id
        WHERE t.user_id = %s
          AND t.transaction_type = 'expense'
          {date_filter}
        GROUP BY mc.name
        ORDER BY total_amount DESC;
    """, (user_id,))

    chart_labels = [row["category_name"] for row in category_expense_rows]
    chart_values = [float(row["total_amount"]) for row in category_expense_rows]

    table_rows = ""
    for row in rows:
        badge_class = "bg-danger" if row["transaction_type"] == "expense" else "bg-success"
        transaction_type_text = "Gider" if row["transaction_type"] == "expense" else "Gelir"
        table_rows += f"""
        <tr>
            <td>{row["transaction_id"]}</td>
            <td>{row["full_name"]}</td>
            <td>{row["main_category"]}</td>
            <td>{row["sub_category"]}</td>
            <td><span class="badge {badge_class}">{transaction_type_text}</span></td>
            <td>{float(row["amount"]):.2f} {row["currency"]}</td>
            <td>{row["payment_method"]}</td>
            <td>{row["description"]}</td>
            <td>{row["transaction_date"]}</td>
            <td>
                <a href="/edit-transaction/{row["transaction_id"]}" class="btn btn-sm btn-warning">Düzenle</a>
                <a href="/delete-transaction/{row["transaction_id"]}" class="btn btn-sm btn-danger" onclick="return confirm('İşlemi silmek istediğine emin misin?')">Sil</a>
            </td>
        </tr>
        """

    if not table_rows:
        table_rows = "<tr><td colspan='10' class='text-center text-muted'>Henüz işlem kaydı yok.</td></tr>"

    prediction_history_html = ""
    for item in prediction_data["history"]:
        prediction_history_html += f"<li>{item['month']:02d}/{item['year']} : {item['total_expense']:.2f}</li>"

    if not prediction_history_html:
        prediction_history_html = "<li>Geçmiş veri bulunmuyor</li>"

    warning_html = ""
    for item in warnings:
        warning_html += f"""
        <div class="alert alert-danger">
            <strong>{item["category_name"]}</strong> kategorisinde bütçe aşıldı.<br>
            Bütçe: {item["budget_amount"]:.2f} | Harcama: {item["spent_amount"]:.2f}
        </div>
        """

    budget_status_html = ""
    for item in budget_status_list:
        budget_status_html += f"""
        <div class="alert alert-{item["status"]}">
            <strong>{item["category_name"]}</strong> - {item["status_text"]}<br>
            Bütçe: {item["budget_amount"]:.2f} |
            Harcama: {item["spent_amount"]:.2f} |
            Kalan: {item["remaining_amount"]:.2f}<br>
            Kullanım: %{item["usage_percent"]:.2f}
        </div>
        """

    if not budget_status_html:
        budget_status_html = "<div class='alert alert-secondary'>Aktif bütçe kaydı bulunmuyor.</div>"

    chart_labels_json = json.dumps(chart_labels, ensure_ascii=False)
    chart_values_json = json.dumps(chart_values)

    return f"""
    <html>
        <head>
            <title>Finans Dashboard</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body class="bg-light">
            <div class="container py-5">

                <div class="d-flex justify-content-between align-items-center mb-4">
                    <div>
                        <h2 class="fw-bold">Finans Dashboard</h2>
                        <p class="text-muted">{range_title} | Kullanıcı: {session.get("full_name")}</p>
                    </div>
                    <div>
                        <a href="/form" class="btn btn-primary">Yeni İşlem Ekle</a>
                        <a href="/budgets" class="btn btn-outline-dark">Bütçe Yönetimi</a>
                        <a href="/logout" class="btn btn-danger">Çıkış</a>
                    </div>
                </div>

                {warning_html}

                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="card shadow border-0 rounded-4">
                            <div class="card-body text-center">
                                <h6>Toplam İşlem</h6>
                                <h3>{total_count}</h3>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-3">
                        <div class="card shadow border-0 rounded-4">
                            <div class="card-body text-center">
                                <h6>Toplam Gelir</h6>
                                <h3 class="text-success">{float(total_income):.2f}</h3>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-3">
                        <div class="card shadow border-0 rounded-4">
                            <div class="card-body text-center">
                                <h6>Toplam Gider</h6>
                                <h3 class="text-danger">{float(total_expense):.2f}</h3>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-3">
                        <div class="card shadow border-0 rounded-4">
                            <div class="card-body text-center">
                                <h6>Net Durum</h6>
                                <h3>{net_balance:.2f}</h3>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow border-0 rounded-4 mb-4">
                    <div class="card-body p-4">
                        <h4>En Fazla Harcama Yapılan Kategori</h4>
                        <p class="mb-0"><strong>{top_category_name}</strong> - {top_category_amount:.2f}</p>
                    </div>
                </div>

                <div class="card shadow border-0 rounded-4 mb-4">
                    <div class="card-body p-4">
                        <h4>AI Harcama Tahmini</h4>
                        <p><strong>Tahmini Gelecek Ay Harcaması:</strong> {prediction_data["prediction"]:.2f}</p>
                        <p><strong>Yöntem:</strong> {prediction_data["method"]}</p>
                        <p><strong>Trend:</strong> {prediction_data["trend"]}</p>
                        <p><strong>Yorum:</strong> {prediction_data["comment"]}</p>
                        <h6>Kullanılan Son Aylar</h6>
                        <ul>{prediction_history_html}</ul>
                    </div>
                </div>

                <div class="card shadow border-0 rounded-4 mb-4">
                    <div class="card-body p-4">
                        <h4>Bütçe Durumu</h4>
                        {budget_status_html}
                    </div>
                </div>

                <div class="mb-4">
                    <a href="/transactions?range=all" class="btn btn-outline-dark">Tüm Zamanlar</a>
                    <a href="/transactions?range=7" class="btn btn-outline-dark">Son 7 Gün</a>
                    <a href="/transactions?range=30" class="btn btn-outline-dark">Son 30 Gün</a>
                    <a href="/transactions?range=90" class="btn btn-outline-dark">Son 90 Gün</a>
                </div>

                <div class="card shadow border-0 rounded-4 mb-4">
                    <div class="card-body p-4">
                        <h4>Kategori Bazlı Gider Analizi</h4>
                        <canvas id="expenseChart"></canvas>
                    </div>
                </div>

                <div class="card shadow border-0 rounded-4">
                    <div class="card-body p-4">
                        <h4>İşlem Listesi</h4>
                        <div class="table-responsive">
                            <table class="table table-hover">
                                <thead>
                                    <tr>
                                        <th>ID</th>
                                        <th>Kullanıcı</th>
                                        <th>Ana Kategori</th>
                                        <th>Alt Kategori</th>
                                        <th>Tür</th>
                                        <th>Tutar</th>
                                        <th>Ödeme</th>
                                        <th>Açıklama</th>
                                        <th>Tarih</th>
                                        <th>İşlem</th>
                                    </tr>
                                </thead>
                                <tbody>{table_rows}</tbody>
                            </table>
                        </div>
                    </div>
                </div>

            </div>

            <script>
                const ctx = document.getElementById('expenseChart').getContext('2d');
                new Chart(ctx, {{
                    type: 'bar',
                    data: {{
                        labels: {chart_labels_json},
                        datasets: [{{
                            label: 'Toplam Gider',
                            data: {chart_values_json},
                            borderWidth: 1
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        scales: {{
                            y: {{ beginAtZero: true }}
                        }}
                    }}
                }});
            </script>
        </body>
    </html>
    """


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        new_password = request.form.get("password")

        from werkzeug.security import generate_password_hash
        hashed_password = generate_password_hash(new_password)

        user = fetch_one_dict("SELECT * FROM users WHERE email = %s", (email,))

        if not user:
            return "Bu email sistemde kayıtlı değil!"

        execute_query("""
            UPDATE users
            SET password_hash = %s
            WHERE email = %s
        """, (hashed_password, email))

        return "Şifre başarıyla güncellendi! <a href='/login'>Giriş yap</a>"

    return """
    <html>
        <head>
            <title>Şifremi Unuttum</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body class="bg-light">
            <div class="container py-5">
                <div class="card p-4 shadow">
                    <h3>Şifre Yenile</h3>
                    <form method="POST">
                        <input type="email" name="email" class="form-control mb-3" placeholder="Email" required>
                        <input type="password" name="password" class="form-control mb-3" placeholder="Yeni Şifre" required>
                        <button class="btn btn-primary">Şifreyi Güncelle</button>
                    </form>
                </div>
            </div>
        </body>
    </html>
    """
if __name__ == "__main__":
    app.run(debug=True)