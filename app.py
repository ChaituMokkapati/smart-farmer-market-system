import logging
import os
import random
import smtplib
import socket
import time

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database import get_db_connection, init_db
from translations import DEFAULT_LANGUAGE, LANGUAGE_OPTIONS, TRANSLATIONS

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_runtime_config():
    preserve_env = (os.getenv("PRESERVE_ENV_VARS") or "").strip().lower() in {"1", "true", "yes", "on"}
    load_dotenv(ENV_PATH, override=not preserve_env)
    debug_enabled = env_flag("FLASK_DEBUG", False)
    secret_key = os.getenv("SECRET_KEY") or app.config.get("SECRET_KEY") or os.urandom(32).hex()
    app.config.update(
        SECRET_KEY=secret_key,
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env_flag("SESSION_COOKIE_SECURE", False),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=env_flag("MAIL_USE_TLS", True),
        MAIL_USE_SSL=env_flag("MAIL_USE_SSL", False),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),
        MAIL_PASSWORD=(os.getenv("MAIL_PASSWORD", "") or "").replace(" ", ""),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME", ""),
        MAIL_SUPPRESS_SEND=env_flag("MAIL_SUPPRESS_SEND", False),
        OTP_EXPIRY_SECONDS=int(os.getenv("OTP_EXPIRY_SECONDS", "300")),
        OTP_MAX_PER_HOUR=int(os.getenv("OTP_MAX_PER_HOUR", "3")),
        EXPOSE_TEST_OTP=env_flag("EXPOSE_TEST_OTP", False),
        ADMIN_EMAIL=(os.getenv("ADMIN_EMAIL") or "").strip().lower(),
        TEMPLATES_AUTO_RELOAD=debug_enabled,
    )
    app.secret_key = secret_key
    app.jinja_env.auto_reload = debug_enabled


load_runtime_config()
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
mail = Mail(app)
logger = logging.getLogger(__name__)
BLOCKED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "invalid",
    "localhost",
    "test",
    "test.com",
    "test.local",
}
OTP_SCOPE_CONFIG = {
    "user": {"session_key_prefix": "", "audience_label": "login"},
    "admin": {"session_key_prefix": "admin_", "audience_label": "admin login"},
    "password_reset": {"session_key_prefix": "password_reset_", "audience_label": "password reset"},
}
STATUS_TRANSLATION_KEYS = {
    "pending": "status.pending",
    "Paid": "status.paid",
    "Order Confirmed": "status.order_confirmed",
    "Packed": "status.packed",
    "Shipped": "status.shipped",
    "Out for Delivery": "status.out_for_delivery",
    "Delivered": "status.delivered",
    "Cancelled": "status.cancelled",
    "Completed": "status.completed",
    "Order Placed": "status.order_placed",
    "Standard": "status.standard",
    "Verified": "status.verified",
}
ROLE_TRANSLATION_KEYS = {
    "admin": "role.admin",
    "farmer": "role.farmer",
    "customer": "role.customer",
}


def normalize_language(language_code):
    if not language_code:
        return DEFAULT_LANGUAGE
    normalized = language_code.strip().lower()
    return normalized if any(normalized == code for code, _ in LANGUAGE_OPTIONS) else DEFAULT_LANGUAGE


def get_current_language():
    return normalize_language(session.get("lang"))


def translate(key, default=None, language=None, **kwargs):
    language_code = normalize_language(language or get_current_language())
    localized_catalog = TRANSLATIONS.get(language_code, {})
    template = localized_catalog.get(key, default or key)
    try:
        return template.format(**kwargs) if kwargs else template
    except Exception:
        return template


def get_language_options():
    return [{"code": code, "label": label} for code, label in LANGUAGE_OPTIONS]


def translate_status(value):
    return translate(STATUS_TRANSLATION_KEYS.get(value, ""), default=value) if value else value


def translate_role(value):
    return translate(ROLE_TRANSLATION_KEYS.get(value, ""), default=value.title() if value else value) if value else value


def get_otp_scope_config(scope):
    return OTP_SCOPE_CONFIG.get(scope, OTP_SCOPE_CONFIG["user"])


def get_otp_session_prefix(scope):
    return get_otp_scope_config(scope)["session_key_prefix"]


def clear_session_otp(scope):
    prefix = get_otp_session_prefix(scope)
    session.pop(f"{prefix}temp_otp", None)
    session.pop(f"{prefix}otp_time", None)
    session.pop(f"{prefix}otp_email", None)


def clear_password_reset_session():
    clear_session_otp("password_reset")
    session.pop("password_reset_user_id", None)
    session.pop("password_reset_email", None)
    session.pop("password_reset_verified", None)


def sanitize_next_url(target):
    if not target:
        return url_for("index")
    cleaned = target.strip()
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        return url_for("index")
    return cleaned


class MailDeliveryError(Exception):
    def __init__(self, error_code, user_message, status_code=500, detail=None):
        super().__init__(user_message)
        self.error_code = error_code
        self.user_message = user_message
        self.status_code = status_code
        self.detail = detail or user_message


def normalize_mail_exception(exc):
    if isinstance(exc, MailDeliveryError):
        return exc
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return MailDeliveryError(
            "smtp_auth_failed",
            translate(
                "mail.smtp_auth_failed",
                default="OTP email delivery is unavailable right now. Check the Gmail SMTP credentials in .env.",
            ),
            status_code=500,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return MailDeliveryError(
            "recipient_rejected",
            translate(
                "mail.recipient_rejected",
                default="That email address cannot receive OTP messages. Use a real inbox address.",
            ),
            status_code=400,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return MailDeliveryError(
            "sender_rejected",
            translate(
                "mail.sender_rejected",
                default="The sender email is being rejected by Gmail. Check MAIL_DEFAULT_SENDER and MAIL_USERNAME.",
            ),
            status_code=500,
            detail=str(exc),
        )
    if isinstance(exc, (socket.timeout, TimeoutError, smtplib.SMTPServerDisconnected, OSError)):
        return MailDeliveryError(
            "smtp_timeout",
            translate(
                "mail.smtp_timeout",
                default="OTP delivery timed out. Please try again in a moment.",
            ),
            status_code=502,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPException):
        return MailDeliveryError(
            "smtp_error",
            translate(
                "mail.smtp_error",
                default="OTP email delivery failed. Please try again.",
            ),
            status_code=502,
            detail=str(exc),
        )
    return MailDeliveryError(
        "mail_delivery_failed",
        translate(
            "mail.delivery_failed",
            default="We could not send the OTP email right now. Please try again.",
        ),
        status_code=500,
        detail=str(exc),
    )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def prepare_auth_runtime(sync_admin=False):
    load_runtime_config()
    if sync_admin:
        init_db()


def normalize_email(email):
    return (email or "").strip().lower()


def get_email_domain(email):
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[1]


def is_blocked_email_domain(email):
    domain = get_email_domain(email)
    return bool(domain) and (domain in BLOCKED_EMAIL_DOMAINS or domain.endswith(".invalid"))


def json_success(message, *, extra=None, status=200):
    payload = {"success": True, "message": message, "error_code": None}
    if extra:
        payload.update(extra)
    return jsonify(payload), status


def json_error(message, error_code, *, status=400, extra=None):
    payload = {"success": False, "message": message, "error_code": error_code}
    if extra:
        payload.update(extra)
    return jsonify(payload), status


def resolve_server_runtime():
    host = (os.getenv("HOST") or os.getenv("FLASK_RUN_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port_value = (os.getenv("PORT") or os.getenv("FLASK_RUN_PORT") or "5000").strip()
    try:
        port = int(port_value)
    except ValueError:
        port = 5000

    debug_enabled = env_flag("FLASK_DEBUG", False)
    use_reloader = env_flag("FLASK_USE_RELOADER", debug_enabled)
    return {
        "host": host,
        "port": port,
        "debug": debug_enabled,
        "use_reloader": use_reloader,
    }


def print_startup_summary(runtime):
    logger.info(
        "Smart Farmer startup host=%s port=%s debug=%s reloader=%s admin=%s sender=%s suppress_send=%s",
        runtime["host"],
        runtime["port"],
        runtime["debug"],
        runtime["use_reloader"],
        app.config.get("ADMIN_EMAIL") or "(unset)",
        app.config.get("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME") or "(unset)",
        app.config.get("MAIL_SUPPRESS_SEND"),
    )


def verify_password(stored_password, candidate_password):
    if not stored_password:
        return False
    if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:"):
        return check_password_hash(stored_password, candidate_password)
    return stored_password == candidate_password


def smtp_ready():
    return bool(app.config.get("MAIL_USERNAME") and app.config.get("MAIL_PASSWORD"))


def send_email(recipient, subject, body):
    if app.config.get("MAIL_SUPPRESS_SEND"):
        return

    if not smtp_ready():
        raise MailDeliveryError(
            "smtp_not_configured",
            translate(
                "mail.not_configured",
                default="OTP email delivery is not configured. Check the Gmail SMTP settings in .env.",
            ),
            status_code=500,
        )

    message = Message(
        subject=subject,
        sender=app.config["MAIL_DEFAULT_SENDER"] or app.config["MAIL_USERNAME"],
        recipients=[recipient],
    )
    message.body = body
    try:
        mail.send(message)
    except Exception as exc:
        raise normalize_mail_exception(exc) from exc


def record_order_update(conn, order_id, status, location=""):
    conn.execute(
        'INSERT INTO order_updates (order_id, status, location) VALUES (?, ?, ?)',
        (order_id, status, location or ''),
    )


def get_order_notification_context(conn, order_id):
    return conn.execute(
        '''
        SELECT
            o.*,
            c.name AS crop_name,
            c.farmer_id AS farmer_id,
            customer.full_name AS customer_name,
            customer.email AS customer_email,
            farmer.full_name AS farmer_name,
            farmer.email AS farmer_email
        FROM orders o
        JOIN crops c ON o.crop_id = c.id
        JOIN users customer ON o.customer_id = customer.id
        JOIN users farmer ON c.farmer_id = farmer.id
        WHERE o.id = ?
        ''',
        (order_id,),
    ).fetchone()


def try_send_email(recipient, subject, body, context_label):
    try:
        send_email(recipient, subject, body)
    except Exception:
        logger.exception("Mail failed for %s (%s)", recipient, context_label)


def notify_farmer_new_order(order):
    if not order or not order['farmer_email']:
        return

    try_send_email(
        order['farmer_email'],
        "New Order Request - Smart Farmer Market",
        (
            f"Hello {order['farmer_name']},\n\n"
            f"You have received a new order request for {order['crop_name']}.\n"
            f"Customer: {order['customer_name']}\n"
            f"Quantity: {order['quantity']} kg\n"
            f"Order value: Rs. {order['total_price']:.2f}\n"
            f"Estimated delivery: {order['estimated_delivery']}\n\n"
            "Please review the order in your farmer dashboard and approve it when ready."
        ),
        f"new-order-{order['id']}",
    )


def notify_customer_farmer_approved(order):
    if not order or not order['customer_email']:
        return

    try_send_email(
        order['customer_email'],
        "Farmer Approved Your Order - Smart Farmer Market",
        (
            f"Hello {order['customer_name']},\n\n"
            f"The farmer has approved your order for {order['crop_name']}.\n"
            f"Farmer: {order['farmer_name']}\n"
            f"Quantity: {order['quantity']} kg\n"
            f"Order value: Rs. {order['total_price']:.2f}\n\n"
            "You can track the latest status from your customer dashboard."
        ),
        f"farmer-approved-{order['id']}",
    )


def purge_old_otp_requests(conn, scope, email):
    cutoff = int(time.time()) - 3600
    conn.execute(
        "DELETE FROM otp_requests WHERE requested_at < ? OR (scope = ? AND email = ? AND requested_at < ?)",
        (cutoff, scope, email, cutoff),
    )


def otp_limit_remaining(conn, email, scope="user"):
    if scope == "admin":
        return None

    cutoff = int(time.time()) - 3600
    purge_old_otp_requests(conn, scope, email)
    count = conn.execute(
        "SELECT COUNT(*) FROM otp_requests WHERE email = ? AND scope = ? AND requested_at >= ?",
        (email, scope, cutoff),
    ).fetchone()[0]
    return max(app.config["OTP_MAX_PER_HOUR"] - count, 0)


def register_otp_request(conn, email, scope="user"):
    conn.execute(
        "INSERT INTO otp_requests (email, scope, requested_at) VALUES (?, ?, ?)",
        (email, scope, int(time.time())),
    )
    conn.commit()


def send_otp_email(email, otp, audience_label):
    expiry_minutes = max(app.config["OTP_EXPIRY_SECONDS"] // 60, 1)
    send_email(
        email,
        "Your Smart Farmer OTP",
        (
            f"Your Smart Farmer {audience_label} OTP is {otp}.\n\n"
            f"It expires in {expiry_minutes} minute(s). "
            "If you did not request this sign-in, ignore this email."
        ),
    )


def issue_session_otp(email, scope="user"):
    scope_config = get_otp_scope_config(scope)
    if is_blocked_email_domain(email):
        return json_error(
            translate(
                "otp.invalid_email_domain",
                default="Use a real email inbox. Example or test domains cannot receive OTP emails.",
            ),
            "invalid_email_domain",
            status=400,
        )

    conn = get_db_connection()
    remaining = otp_limit_remaining(conn, email, scope)
    if scope != "admin" and remaining <= 0:
        conn.close()
        return json_error(
            translate(
                "otp.rate_limited",
                default="OTP request limit reached. You can request up to 3 codes per hour.",
                limit=app.config["OTP_MAX_PER_HOUR"],
            ),
            "otp_rate_limited",
            status=429,
            extra={"remaining_requests": 0},
        )

    otp = f"{random.randint(0, 999999):06d}"

    try:
        send_otp_email(email, otp, scope_config["audience_label"])
    except Exception as exc:
        exc = normalize_mail_exception(exc)
        logger.error("OTP email delivery failed for %s [%s]: %s", email, exc.error_code, exc.detail)
        conn.close()
        return json_error(exc.user_message, exc.error_code, status=exc.status_code)

    session_key_prefix = scope_config["session_key_prefix"]
    session[f"{session_key_prefix}temp_otp"] = otp
    session[f"{session_key_prefix}otp_time"] = time.time()
    session[f"{session_key_prefix}otp_email"] = email

    register_otp_request(conn, email, scope)
    remaining_after_send = otp_limit_remaining(conn, email, scope)
    conn.close()
    extra = {"otp": None, "remaining_requests": remaining_after_send}
    if app.config["TESTING"] or app.config["EXPOSE_TEST_OTP"]:
        extra["otp"] = otp
    return json_success(
        translate("otp.sent", default="OTP sent to {email}. Check your inbox.", email=email),
        extra=extra,
    )


def validate_session_otp(email, user_otp, scope="user"):
    prefix = get_otp_session_prefix(scope)
    session_otp = session.get(f"{prefix}temp_otp")
    otp_time = session.get(f"{prefix}otp_time", 0)
    otp_email = session.get(f"{prefix}otp_email")

    if not session_otp or otp_email != email:
        return "otp_not_requested"
    if time.time() - otp_time > app.config["OTP_EXPIRY_SECONDS"]:
        return "otp_expired"
    if user_otp != session_otp:
        return "invalid_otp"
    return None


@app.context_processor
def inject_template_config():
    return {
        "current_language": get_current_language(),
        "language_options": get_language_options(),
        "otp_expiry_seconds": app.config["OTP_EXPIRY_SECONDS"],
        "otp_expiry_minutes": max(app.config["OTP_EXPIRY_SECONDS"] // 60, 1),
        "t": translate,
        "t_role": translate_role,
        "t_status": translate_status,
    }


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


init_db()

# --- Routes ---

@app.route('/')
def index():
    if 'user_id' in session:
        if session['role'] == 'farmer':
            return redirect(url_for('farmer_dashboard'))
        elif session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('marketplace'))
    return redirect(url_for('login'))


@app.route('/set_language', methods=['POST'])
def set_language():
    session["lang"] = normalize_language(request.form.get("language"))
    return redirect(sanitize_next_url(request.form.get("next")))

@app.route('/marketplace')
def marketplace():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    query = request.args.get('query', '')
    state = request.args.get('state', '')
    district = request.args.get('district', '')
    category = request.args.get('category', '')
    
    conn = get_db_connection()
    
    # Base SQL
    sql = '''
        SELECT c.*, u.full_name as farmer_name, u.city as farmer_city, u.is_verified, 
               c.state, c.district, c.village, c.pincode
        FROM crops c JOIN users u ON c.farmer_id = u.id 
        WHERE 1=1
    '''
    params = []
    
    if query:
        sql += ' AND (c.name LIKE ? OR c.description LIKE ?)'
        params.extend(['%' + query + '%', '%' + query + '%'])
    if state:
        sql += ' AND c.state = ?'
        params.append(state)
    if district:
        sql += ' AND c.district = ?'
        params.append(district)
    if category:
        sql += ' AND c.category = ?'
        params.append(category)
        
    crops = conn.execute(sql, params).fetchall()
    
    # Static data for filters as requested
    categories = ["Vegetables", "Fruits", "Grains", "Rice Varieties", "Pulses", "Spices", "Dairy Products", "Milk", "Eggs", "Meat", "Honey", "Organic Products", "Farming Products"]
    states = ["Telangana", "Andhra Pradesh", "Karnataka", "Tamil Nadu", "Maharashtra", "Kerala", "Odisha"]
    
    # Personalization tracking
    welcome_message = (
        translate("marketplace.kicker.welcome_back", default="Welcome Back to the network")
        if session.get('has_visited')
        else translate("marketplace.kicker.welcome", default="Welcome to the network")
    )
    session['has_visited'] = True
    
    conn.close()
    return render_template('index.html', 
                          crops=crops, query=query, 
                          state=state, district=district,
                          category=category, 
                          categories=categories, states=states, 
                          welcome_message=welcome_message)

@app.route('/request_otp', methods=['POST'])
def request_otp():
    prepare_auth_runtime()
    email = normalize_email(request.form.get('email'))

    if not email or email != session.get('pre_auth_email'):
        return json_error(
            translate("otp.login_required", default="Start from login before requesting an OTP."),
            'login_required',
            status=400,
            extra={'otp': None},
        )

    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE id = ? AND lower(email) = ?',
        (session.get('pre_auth_user_id'), email),
    ).fetchone()
    conn.close()

    if not user:
        return json_error(
            translate("otp.email_not_registered", default="This email is not registered"),
            'email_not_registered',
            status=404,
            extra={'otp': None},
        )

    return issue_session_otp(email, scope="user")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        prepare_auth_runtime()
        email = normalize_email(request.form.get('email'))
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE lower(email) = ?', (email,)).fetchone()
        conn.close()

        if not user or not verify_password(user['password'], password):
            flash(translate("auth.flash.invalid_credentials", default='Invalid email or password'), 'error')
            return redirect(url_for('login'))

        session['pre_auth_user_id'] = user['id']
        session['pre_auth_email'] = email
        return redirect(url_for('verify'))
            
    return render_template('auth.html', mode='login', form_action=url_for('login'))

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    prepare_auth_runtime()
    if 'pre_auth_user_id' not in session:
        flash(translate("auth.flash.login_first", default='Please login first'), 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        expects_json = (request.form.get('response_mode') == 'json')
        email = normalize_email(request.form.get('email'))
        user_otp = (request.form.get('otp') or '').strip().replace(' ', '')
        user_id = session.get('pre_auth_user_id')

        otp_error = validate_session_otp(email, user_otp, scope="user")
        if otp_error == 'otp_not_requested':
            if expects_json:
                return json_error(
                    translate("otp.request_fresh", default='Request a fresh OTP before verifying.'),
                    'otp_not_requested',
                    status=400,
                )
            flash(translate("otp.invalid_login_combo", default='Invalid OTP or email'), 'error')
            return redirect(url_for('verify'))
        if otp_error == 'otp_expired':
            if expects_json:
                return json_error(
                    translate("otp.expired", default='OTP has expired. Request a new code.'),
                    'otp_expired',
                    status=400,
                )
            flash(translate("otp.expired", default='OTP has expired. Request a new code.'), 'error')
            return redirect(url_for('verify'))
        if otp_error == 'invalid_otp':
            if expects_json:
                return json_error(
                    translate("otp.invalid", default='Incorrect OTP. Enter the latest code from your inbox.'),
                    'invalid_otp',
                    status=400,
                )
            flash(translate("otp.invalid", default='Incorrect OTP. Enter the latest code from your inbox.'), 'error')
            return redirect(url_for('verify'))
        
        # Success! Finalize Login
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        
        clear_session_otp("user")
        session.pop('pre_auth_user_id', None)
        session.pop('pre_auth_email', None)
        clear_password_reset_session()
        
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['email'] = user['email']
        session['role'] = user['role']
        session['has_visited'] = True

        if user['role'] == 'farmer':
            destination = url_for('farmer_dashboard')
        elif user['role'] == 'admin':
            destination = url_for('admin_dashboard')
        else:
            destination = url_for('my_orders')

        if expects_json:
            return json_success('OTP verified successfully.', extra={'redirect': destination})
        return redirect(destination)
            
    return render_template(
        'auth.html',
        mode='verify',
        email=session.get('pre_auth_email'),
        form_action=url_for('verify'),
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        prepare_auth_runtime()
        username = request.form.get('username')
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password')
        role = request.form.get('role', 'customer')
        full_name = request.form.get('full_name', '')
        city = request.form.get('city', '')
        state = request.form.get('state', '')
        district = request.form.get('district', '')
        pincode = request.form.get('pincode', '')
        
        if not username or not email or not password:
            flash(translate("auth.flash.required_fields", default='Username, email, and password are required'), 'error')
            return redirect(url_for('register'))

        if is_blocked_email_domain(email):
            flash(
                translate(
                    "auth.flash.real_email_required",
                    default='Use a real email inbox. Example or test domains are blocked for OTP delivery.',
                ),
                'error',
            )
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (username, email, password, role, full_name, city, state, district, pincode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (username, email, generate_password_hash(password), role, full_name, city, state, district, pincode)
            )
            conn.commit()
            flash(translate("auth.flash.register_success", default='Registration successful! Please login.'), 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(translate("auth.flash.username_exists", default='Username or email already exists'), 'error')
        finally:
            conn.close()

    return render_template('auth.html', mode='register', form_action=url_for('register'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        prepare_auth_runtime()
        email = normalize_email(request.form.get('email'))
        if not email:
            flash(
                translate(
                    "auth.flash.reset_email_required",
                    default='Enter your registered email to reset your password.',
                ),
                'error',
            )
            return redirect(url_for('forgot_password'))

        conn = get_db_connection()
        user = conn.execute('SELECT id, email FROM users WHERE lower(email) = ?', (email,)).fetchone()
        conn.close()

        if not user:
            flash(
                translate(
                    "auth.flash.reset_email_not_found",
                    default='No account was found for that email address.',
                ),
                'error',
            )
            return redirect(url_for('forgot_password'))

        clear_password_reset_session()
        session['password_reset_user_id'] = user['id']
        session['password_reset_email'] = email
        session['password_reset_verified'] = False
        return redirect(url_for('verify_reset_otp'))

    return render_template('auth.html', mode='forgot_password', form_action=url_for('forgot_password'))


@app.route('/request_password_reset_otp', methods=['POST'])
def request_password_reset_otp():
    prepare_auth_runtime()
    email = normalize_email(request.form.get('email'))

    if not email or email != session.get('password_reset_email') or not session.get('password_reset_user_id'):
        return json_error(
            translate(
                "otp.reset_required",
                default='Start the password reset flow before requesting a new OTP.',
            ),
            'password_reset_required',
            status=400,
            extra={'otp': None},
        )

    conn = get_db_connection()
    user = conn.execute(
        'SELECT id FROM users WHERE id = ? AND lower(email) = ?',
        (session.get('password_reset_user_id'), email),
    ).fetchone()
    conn.close()

    if not user:
        return json_error(
            translate("otp.email_not_registered", default='This email is not registered'),
            'email_not_registered',
            status=404,
            extra={'otp': None},
        )

    return issue_session_otp(email, scope="password_reset")


@app.route('/reset_password/verify', methods=['GET', 'POST'])
def verify_reset_otp():
    prepare_auth_runtime()
    if not session.get('password_reset_user_id') or not session.get('password_reset_email'):
        flash(
            translate(
                "otp.reset_required",
                default='Start the password reset flow before requesting a new OTP.',
            ),
            'error',
        )
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        expects_json = (request.form.get('response_mode') == 'json')
        email = normalize_email(request.form.get('email'))
        user_otp = (request.form.get('otp') or '').strip().replace(' ', '')

        otp_error = validate_session_otp(email, user_otp, scope="password_reset")
        if otp_error == 'otp_not_requested':
            if expects_json:
                return json_error(
                    translate("otp.request_fresh", default='Request a fresh OTP before verifying.'),
                    'otp_not_requested',
                    status=400,
                )
            flash(translate("otp.invalid_login_combo", default='Invalid OTP or email'), 'error')
            return redirect(url_for('verify_reset_otp'))
        if otp_error == 'otp_expired':
            if expects_json:
                return json_error(
                    translate("otp.expired", default='OTP has expired. Request a new code.'),
                    'otp_expired',
                    status=400,
                )
            flash(translate("otp.expired", default='OTP has expired. Request a new code.'), 'error')
            return redirect(url_for('verify_reset_otp'))
        if otp_error == 'invalid_otp':
            if expects_json:
                return json_error(
                    translate("otp.invalid", default='Incorrect OTP. Enter the latest code from your inbox.'),
                    'invalid_otp',
                    status=400,
                )
            flash(translate("otp.invalid", default='Incorrect OTP. Enter the latest code from your inbox.'), 'error')
            return redirect(url_for('verify_reset_otp'))

        clear_session_otp("password_reset")
        session['password_reset_verified'] = True
        destination = url_for('reset_password')
        if expects_json:
            return json_success('OTP verified successfully.', extra={'redirect': destination})
        return redirect(destination)

    return render_template(
        'auth.html',
        mode='reset_verify',
        email=session.get('password_reset_email'),
        form_action=url_for('verify_reset_otp'),
    )


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    prepare_auth_runtime()
    if not session.get('password_reset_user_id') or not session.get('password_reset_email'):
        flash(
            translate(
                "otp.reset_required",
                default='Start the password reset flow before requesting a new OTP.',
            ),
            'error',
        )
        return redirect(url_for('forgot_password'))
    if not session.get('password_reset_verified'):
        flash(
            translate(
                "auth.flash.reset_verified_required",
                default='Complete OTP verification before setting a new password.',
            ),
            'error',
        )
        return redirect(url_for('verify_reset_otp'))

    if request.method == 'POST':
        new_password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not new_password or not confirm_password:
            flash(
                translate(
                    "auth.flash.reset_passwords_required",
                    default='Both the new password and confirmation are required.',
                ),
                'error',
            )
            return redirect(url_for('reset_password'))
        if new_password != confirm_password:
            flash(
                translate(
                    "auth.flash.reset_passwords_match",
                    default='The new password and confirmation must match.',
                ),
                'error',
            )
            return redirect(url_for('reset_password'))
        if len(new_password) < 8:
            flash(
                translate(
                    "auth.flash.reset_password_length",
                    default='The new password must be at least 8 characters long.',
                ),
                'error',
            )
            return redirect(url_for('reset_password'))

        conn = get_db_connection()
        conn.execute(
            'UPDATE users SET password = ? WHERE id = ?',
            (generate_password_hash(new_password), session.get('password_reset_user_id')),
        )
        conn.commit()
        conn.close()

        clear_password_reset_session()
        flash(
            translate(
                "auth.flash.reset_success",
                default='Password updated successfully. Login now with your new password.',
            ),
            'success',
        )
        return redirect(url_for('login'))

    return render_template(
        'auth.html',
        mode='reset_password',
        email=session.get('password_reset_email'),
        form_action=url_for('reset_password'),
    )

@app.route('/logout')
def logout():
    has_visited = session.get('has_visited', False)
    selected_language = get_current_language()
    session.clear()
    session['has_visited'] = has_visited # Keep visit history after logout
    session['lang'] = selected_language
    return redirect(url_for('index'))

# --- Farmer Routes ---

@app.route('/farmer/dashboard')
def farmer_dashboard():
    if 'role' not in session or session['role'] != 'farmer':
        return redirect(url_for('login'))

    conn = get_db_connection()
    crops = conn.execute('SELECT * FROM crops WHERE farmer_id = ?', (session['user_id'],)).fetchall()
    
    # Fetch orders for this farmer's crops
    orders = conn.execute('''
        SELECT o.*, c.name as crop_name, u.full_name as customer_name, u.email as customer_email
        FROM orders o
        JOIN crops c ON o.crop_id = c.id
        JOIN users u ON o.customer_id = u.id
        WHERE c.farmer_id = ?
        ORDER BY o.order_date DESC
    ''', (session['user_id'],)).fetchall()
    
    user = conn.execute('SELECT is_verified FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return render_template('farmer.html', crops=crops, orders=orders, is_verified=user['is_verified'])

@app.route('/farmer/update_order_status', methods=['POST'])
def farmer_update_order():
    if 'role' not in session or session['role'] != 'farmer':
        return redirect(url_for('login'))
        
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    location = request.form.get('location', '')
    
    conn = get_db_connection()
    # Verify the order belongs to this farmer's crop
    order = conn.execute('''
        SELECT
            o.*,
            c.name AS crop_name,
            customer.full_name AS customer_name,
            customer.email AS customer_email,
            farmer.full_name AS farmer_name
        FROM orders o
        JOIN crops c ON o.crop_id = c.id
        JOIN users customer ON o.customer_id = customer.id
        JOIN users farmer ON c.farmer_id = farmer.id
        WHERE o.id = ? AND c.farmer_id = ?
    ''', (order_id, session['user_id'])).fetchone()
    
    if order:
        conn.execute('UPDATE orders SET status = ?, current_location = ? WHERE id = ?', (new_status, location, order_id))
        record_order_update(conn, order_id, new_status, location)
        conn.commit()

        if new_status == 'Order Confirmed' and order['status'] != 'Order Confirmed':
            notify_customer_farmer_approved(
                {
                    **dict(order),
                    'status': new_status,
                    'current_location': location,
                }
            )

        flash(f'Order #{order_id} status updated to {new_status}', 'success')
    else:
        flash('Order not found or unauthorized', 'error')
        
    conn.close()
    return redirect(url_for('farmer_dashboard'))

@app.route('/admin/toggle_verification/<int:user_id>')
def toggle_verification(user_id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user = conn.execute('SELECT is_verified FROM users WHERE id = ?', (user_id,)).fetchone()
    if user:
        new_status = 0 if user['is_verified'] else 1
        conn.execute('UPDATE users SET is_verified = ? WHERE id = ?', (new_status, user_id))
        conn.commit()
        flash('Farmer verification status updated!', 'success')
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/farmer/add_crop', methods=['POST'])
def add_crop():
    if 'role' not in session or session['role'] != 'farmer':
        return jsonify({'error': 'Unauthorized'}), 403

    name = request.form['name']
    category = request.form.get('category', 'Others')
    quantity = request.form['quantity']
    price = request.form['price']
    harvest_date = request.form.get('harvest_date', '')
    state = request.form.get('state', '')
    district = request.form.get('district', '')
    village = request.form.get('village', '')
    pincode = request.form.get('pincode', '')
    description = request.form['description']
    quality = request.form.get('quality', 'Standard')
    
    # helper for size check
    def is_file_too_large(file):
        if not file: return False
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        return size > 2 * 1024 * 1024

    # Handle Crop Image
    image_url = ''
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '':
            if is_file_too_large(file):
                flash('Crop image too large (Max 2MB)', 'error')
                return redirect(url_for('farmer_dashboard'))
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            image_url = 'uploads/' + filename

    # Handle Quality Proof
    proof_url = ''
    if 'quality_proof' in request.files:
        pfile = request.files['quality_proof']
        if pfile and pfile.filename != '':
            if is_file_too_large(pfile):
                flash('Quality proof too large (Max 2MB)', 'error')
                return redirect(url_for('farmer_dashboard'))
            pfilename = secure_filename('proof_' + pfile.filename)
            pfile_path = os.path.join(app.config['UPLOAD_FOLDER'], pfilename)
            pfile.save(pfile_path)
            proof_url = 'uploads/' + pfilename

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO crops (farmer_id, name, category, quantity, price, harvest_date, state, district, village, pincode, description, image_url, quality, quality_proof) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (session['user_id'], name, category, quantity, price, harvest_date, state, district, village, pincode, description, image_url, quality, proof_url))
    conn.commit()
    conn.close()

    flash('Crop added successfully!', 'success')
    return redirect(url_for('farmer_dashboard'))

@app.route('/farmer/edit_crop/<int:id>', methods=['GET', 'POST'])
def edit_crop(id):
    if 'role' not in session or (session['role'] != 'farmer' and session['role'] != 'admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        quantity = request.form['quantity']
        price = request.form['price']
        description = request.form['description']

        if session['role'] == 'farmer':
            conn.execute('UPDATE crops SET name=?, quantity=?, price=?, description=? WHERE id=? AND farmer_id=?',
                         (name, quantity, price, description, id, session['user_id']))
        else:
            conn.execute('UPDATE crops SET name=?, quantity=?, price=?, description=? WHERE id=?',
                         (name, quantity, price, description, id))
        conn.commit()
        conn.close()
        flash('Crop updated successfully!', 'success')
        return redirect(url_for('farmer_dashboard'))

    crop = conn.execute('SELECT * FROM crops WHERE id=? AND farmer_id=?', (id, session['user_id'])).fetchone()
    conn.close()
    if not crop:
        flash('Crop not found or unauthorized', 'error')
        return redirect(url_for('farmer_dashboard'))
    return render_template('edit_crop.html', crop=crop)

@app.route('/farmer/delete_crop/<int:id>')
def delete_crop(id):
    if 'role' not in session or (session['role'] != 'farmer' and session['role'] != 'admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    if session['role'] == 'farmer':
        conn.execute('DELETE FROM crops WHERE id=? AND farmer_id=?', (id, session['user_id']))
    else:
        conn.execute('DELETE FROM crops WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash('Crop deleted successfully!', 'info')
    return redirect(request.referrer or url_for('index'))

@app.route('/farmer/profile/<int:id>')
def farmer_profile(id):
    conn = get_db_connection()
    farmer = conn.execute('SELECT * FROM users WHERE id = ? AND role = "farmer"', (id,)).fetchone()
    if not farmer:
        conn.close()
        flash('Farmer not found', 'error')
        return redirect(url_for('index'))
    
    crops = conn.execute('SELECT * FROM crops WHERE farmer_id = ?', (id,)).fetchall()
    reviews = conn.execute('''
        SELECT r.*, u.full_name as customer_name 
        FROM reviews r 
        JOIN users u ON r.customer_id = u.id 
        WHERE r.farmer_id = ?
        ORDER BY r.created_at DESC
    ''', (id,)).fetchall()
    
    avg_rating_row = conn.execute('SELECT AVG(rating) FROM reviews WHERE farmer_id = ?', (id,)).fetchone()
    avg_rating = avg_rating_row[0] if avg_rating_row else 0
    conn.close()
    return render_template('farmer_profile.html', farmer=farmer, crops=crops, reviews=reviews, avg_rating=avg_rating)

@app.route('/submit_review', methods=['POST'])
def submit_review():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    order_id = request.form['order_id']
    farmer_id = request.form['farmer_id']
    rating = request.form['rating']
    comment = request.form['comment']
    
    conn = get_db_connection()
    conn.execute('INSERT INTO reviews (order_id, customer_id, farmer_id, rating, comment) VALUES (?, ?, ?, ?, ?)',
                 (order_id, session['user_id'], farmer_id, rating, comment))
    conn.commit()
    conn.close()
    flash('Review submitted! Thank you for your feedback.', 'success')
    return redirect(url_for('my_orders'))

@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    crop_id = request.form['crop_id']
    quantity = float(request.form['quantity'])

    conn = get_db_connection()
    crop = conn.execute('SELECT * FROM crops WHERE id = ?', (crop_id,)).fetchone()
    customer = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    farmer = conn.execute('SELECT * FROM users WHERE id = ?', (crop['farmer_id'],)).fetchone()

    if crop and crop['quantity'] >= quantity:
        total_price = quantity * crop['price']
        
        # Calculate Estimated Delivery
        days = 5 # Default
        if farmer['state'] == customer['state']:
            days = 3
            if farmer['city'] == customer['city']:
                days = 1
        
        est_date = (time.time() + (days * 24 * 3600))
        est_delivery_str = time.strftime('%d %b, %Y', time.localtime(est_date))
        
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (customer_id, crop_id, quantity, total_price, estimated_delivery, current_location) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session['user_id'], crop_id, quantity, total_price, est_delivery_str, farmer['city'] or farmer['state']))
        
        order_id = cursor.lastrowid
        
        record_order_update(conn, order_id, 'Order Placed', farmer['city'] or farmer['state'])
        
        conn.execute('UPDATE crops SET quantity = quantity - ? WHERE id = ?', (quantity, crop_id))
        conn.commit()
        notify_farmer_new_order(get_order_notification_context(conn, order_id))
        flash('Order placed! Proceed to payment.', 'success')
        conn.close()
        return redirect(url_for('checkout', order_id=order_id))
    else:
        flash('Requested quantity not available', 'error')
        conn.close()
        return redirect(url_for('index'))

@app.route('/my_orders')
def my_orders():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    # Fetch all orders with details
    all_orders = conn.execute('''
        SELECT o.*, c.name as crop_name, c.image_url as crop_image, u.full_name as farmer_name, u.id as farmer_id
        FROM orders o
        JOIN crops c ON o.crop_id = c.id
        JOIN users u ON c.farmer_id = u.id
        WHERE o.customer_id = ?
        ORDER BY o.order_date DESC
    ''', (session['user_id'],)).fetchall()
    
    active_orders = []
    order_history = []
    
    for order in all_orders:
        order_dict = dict(order)
        # Fetch tracking updates for this order
        updates = conn.execute('SELECT * FROM order_updates WHERE order_id = ? ORDER BY update_date ASC', (order['id'],)).fetchall()
        order_dict['tracking'] = [dict(u) for u in updates]
        
        if order['status'] in ['Delivered', 'Cancelled']:
            order_history.append(order_dict)
        else:
            active_orders.append(order_dict)
            
    conn.close()
    return render_template('customer_orders.html', active_orders=active_orders, order_history=order_history)

@app.route('/cancel_order/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    # Check if order belongs to the user and is in a cancellable state
    order = conn.execute('SELECT * FROM orders WHERE id = ? AND customer_id = ?', (order_id, session['user_id'])).fetchone()
    
    if order:
        if order['status'] in ['pending', 'Paid', 'Order Confirmed']:
            conn.execute('UPDATE orders SET status = "Cancelled" WHERE id = ?', (order_id,))
            record_order_update(conn, order_id, 'Cancelled', 'System')
            conn.commit()
            flash('Order has been cancelled successfully.', 'success')
        else:
            flash('Cannot cancel an order that has already been shipped or completed.', 'error')
    else:
        flash('Order not found or unauthorized.', 'error')
        
    conn.close()
    return redirect(url_for('my_orders'))

@app.route('/checkout/<int:order_id>')
def checkout(order_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    order = conn.execute('''
        SELECT o.*, c.name as crop_name
        FROM orders o
        JOIN crops c ON o.crop_id = c.id
        WHERE o.id = ? AND o.customer_id = ?
    ''', (order_id, session['user_id'])).fetchone()
    conn.close()

    if not order:
        flash('Order not found', 'error')
        return redirect(url_for('index'))
    return render_template('checkout.html', order=order)

@app.route('/confirm_payment', methods=['POST'])
def confirm_payment():
    load_runtime_config()
    order_id = request.form['order_id']
    conn = get_db_connection()
    order = conn.execute('''
        SELECT o.*, u.email as customer_email, u.full_name as customer_name, c.name as crop_name 
        FROM orders o 
        JOIN users u ON o.customer_id = u.id 
        JOIN crops c ON o.crop_id = c.id
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    
    if order:
        conn.execute('UPDATE orders SET status = "Paid" WHERE id = ?', (order_id,))
        record_order_update(conn, order_id, 'Paid', order['current_location'] or 'Payment confirmed')
        conn.commit()

        try:
            send_email(
                order['customer_email'],
                "Order Confirmed - Smart Farmer Market",
                (
                    f"Hello {order['customer_name']},\n\n"
                    f"Your order for {order['crop_name']} has been confirmed. "
                    f"Total paid: Rs. {order['total_price']}\n\n"
                    "Thank you for shopping local!"
                ),
            )
        except Exception:
            logger.exception("Mail failed for order %s", order_id)

    conn.close()
    flash('Payment successful! A confirmation email has been queued.', 'success')
    return redirect(url_for('my_orders'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    prepare_auth_runtime(sync_admin=True)
    if request.method == 'POST':
        action = request.form.get('action')
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password')

        try:
            if action == 'send_otp':
                conn = get_db_connection()
                admin_user = conn.execute(
                    "SELECT * FROM users WHERE role = 'admin' AND lower(email) = ?",
                    (email,),
                ).fetchone()
                conn.close()

                if not admin_user or not verify_password(admin_user['password'], password):
                    return json_error('Invalid admin credentials', 'invalid_credentials', status=401, extra={'otp': None})

                session['pre_auth_admin_id'] = admin_user['id']
                return issue_session_otp(email, scope="admin")

            if action == 'verify':
                user_otp = (request.form.get('otp') or '').strip().replace(' ', '')
                session_otp = session.get('admin_temp_otp')
                otp_time = session.get('admin_otp_time', 0)
                session_email = session.get('admin_otp_email')

                if not session.get('pre_auth_admin_id'):
                    return json_error('Validate admin credentials first.', 'admin_pre_auth_required', status=400, extra={'otp': None})

                if not session_otp or time.time() - otp_time > app.config['OTP_EXPIRY_SECONDS']:
                    return json_error('OTP expired or not found', 'otp_expired', status=400, extra={'otp': None})

                if email != session_email:
                    return json_error('Admin email mismatch', 'email_mismatch', status=400, extra={'otp': None})

                if user_otp == session_otp:
                    session.pop('admin_temp_otp', None)
                    session.pop('admin_otp_time', None)
                    session.pop('admin_otp_email', None)
                    conn = get_db_connection()
                    admin_user = conn.execute(
                        "SELECT * FROM users WHERE id = ? AND role = 'admin'",
                        (session.pop('pre_auth_admin_id', None),),
                    ).fetchone()
                    conn.close()

                    if not admin_user:
                        return json_error('Admin account was not found.', 'admin_not_found', status=404, extra={'otp': None})

                    session['user_id'] = admin_user['id']
                    session['username'] = admin_user['username']
                    session['email'] = email
                    session['role'] = 'admin'
                    return json_success('OTP verified successfully.', extra={'redirect': url_for('admin_dashboard'), 'otp': None})

                return json_error('Incorrect OTP', 'invalid_otp', status=400, extra={'otp': None})

            return json_error('Unsupported admin action.', 'invalid_action', status=400, extra={'otp': None})
        except Exception:
            logger.exception("Admin OTP flow failed for action=%s email=%s", action, email)
            return json_error(
                'Admin authentication is unavailable right now. Please try again.',
                'admin_login_failed',
                status=500,
                extra={'otp': None},
            )
            
    return render_template('admin_login.html')

# --- Admin Routes ---

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Unauthorized access', 'error')
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    
    # Users, Orders, and Crops
    users = conn.execute('SELECT * FROM users').fetchall()
    crops = conn.execute('''
        SELECT c.*, u.full_name as farmer_name 
        FROM crops c 
        JOIN users u ON c.farmer_id = u.id
    ''').fetchall()
    orders = conn.execute('''
        SELECT o.*, u.full_name as customer_name, c.name as crop_name
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        JOIN crops c ON o.crop_id = c.id
    ''').fetchall()
    
    # Analytics
    total_farmers = conn.execute('SELECT COUNT(*) FROM users WHERE role="farmer"').fetchone()[0]
    total_crops = conn.execute('SELECT COUNT(*) FROM crops').fetchone()[0]
    total_orders = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    total_revenue = conn.execute('SELECT SUM(total_price) FROM orders WHERE status="Paid"').fetchone()[0] or 0
    
    # Charts Data
    category_counts = conn.execute('SELECT category, COUNT(*) FROM crops GROUP BY category').fetchall()
    
    # Revenue Trend (Last 7 days)
    revenue_trend = conn.execute('''
        SELECT strftime('%Y-%m-%d', order_date), SUM(total_price) 
        FROM orders 
        WHERE status="Paid" 
        GROUP BY strftime('%Y-%m-%d', order_date) 
        ORDER BY order_date DESC LIMIT 7
    ''').fetchall()
    
    conn.close()
    return render_template('admin_dashboard_v2.html', 
                          users=users, 
                          crops=crops,
                          orders=orders, 
                          total_farmers=total_farmers,
                          total_crops=total_crops,
                          total_orders=total_orders,
                          total_revenue=total_revenue,
                          category_counts=category_counts,
                          revenue_trend=revenue_trend)

@app.route('/admin/update_order/<int:id>', methods=['POST'])
def admin_update_order(id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    status = request.form['status']
    conn = get_db_connection()
    conn.execute('UPDATE orders SET status = ? WHERE id = ?', (status, id))
    order = get_order_notification_context(conn, id)
    if order:
        record_order_update(conn, id, status, order['current_location'] or 'Admin dashboard')
    conn.commit()
    conn.close()
    flash(f'Order #{id} status updated to {status}', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:id>')
def delete_user(id):
    if 'role' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    conn.execute('DELETE FROM users WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('User deleted successfully', 'info')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
    prepare_auth_runtime(sync_admin=True)
    runtime = resolve_server_runtime()
    print_startup_summary(runtime)
    app.run(
        host=runtime["host"],
        port=runtime["port"],
        debug=runtime["debug"],
        use_reloader=runtime["use_reloader"],
    )
