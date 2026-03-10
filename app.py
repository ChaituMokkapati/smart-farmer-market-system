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
            "OTP email delivery is unavailable right now. Check the Gmail SMTP credentials in .env.",
            status_code=500,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return MailDeliveryError(
            "recipient_rejected",
            "That email address cannot receive OTP messages. Use a real inbox address.",
            status_code=400,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return MailDeliveryError(
            "sender_rejected",
            "The sender email is being rejected by Gmail. Check MAIL_DEFAULT_SENDER and MAIL_USERNAME.",
            status_code=500,
            detail=str(exc),
        )
    if isinstance(exc, (socket.timeout, TimeoutError, smtplib.SMTPServerDisconnected, OSError)):
        return MailDeliveryError(
            "smtp_timeout",
            "OTP delivery timed out. Please try again in a moment.",
            status_code=502,
            detail=str(exc),
        )
    if isinstance(exc, smtplib.SMTPException):
        return MailDeliveryError(
            "smtp_error",
            "OTP email delivery failed. Please try again.",
            status_code=502,
            detail=str(exc),
        )
    return MailDeliveryError(
        "mail_delivery_failed",
        "We could not send the OTP email right now. Please try again.",
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
            "OTP email delivery is not configured. Check the Gmail SMTP settings in .env.",
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
    if is_blocked_email_domain(email):
        return json_error(
            "Use a real email inbox. Example or test domains cannot receive OTP emails.",
            "invalid_email_domain",
            status=400,
        )

    conn = get_db_connection()
    remaining = otp_limit_remaining(conn, email, scope)
    if scope != "admin" and remaining <= 0:
        conn.close()
        return json_error(
            "OTP request limit reached. You can request up to 3 codes per hour.",
            "otp_rate_limited",
            status=429,
            extra={"remaining_requests": 0},
        )

    otp = f"{random.randint(0, 999999):06d}"

    try:
        send_otp_email(email, otp, "admin login" if scope == "admin" else "login")
    except Exception as exc:
        exc = normalize_mail_exception(exc)
        logger.error("OTP email delivery failed for %s [%s]: %s", email, exc.error_code, exc.detail)
        conn.close()
        return json_error(exc.user_message, exc.error_code, status=exc.status_code)

    session_key_prefix = "admin_" if scope == "admin" else ""
    session[f"{session_key_prefix}temp_otp"] = otp
    session[f"{session_key_prefix}otp_time"] = time.time()
    session[f"{session_key_prefix}otp_email"] = email

    register_otp_request(conn, email, scope)
    remaining_after_send = otp_limit_remaining(conn, email, scope)
    conn.close()
    extra = {"otp": None, "remaining_requests": remaining_after_send}
    if app.config["TESTING"] or app.config["EXPOSE_TEST_OTP"]:
        extra["otp"] = otp
    return json_success(f"OTP sent to {email}. Check your inbox.", extra=extra)


@app.context_processor
def inject_template_config():
    return {
        "otp_expiry_seconds": app.config["OTP_EXPIRY_SECONDS"],
        "otp_expiry_minutes": max(app.config["OTP_EXPIRY_SECONDS"] // 60, 1),
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
    welcome_msg = "Welcome Back" if session.get('has_visited') else "Welcome"
    session['has_visited'] = True
    
    conn.close()
    return render_template('index.html', 
                          crops=crops, query=query, 
                          state=state, district=district,
                          category=category, 
                          categories=categories, states=states, 
                          welcome_msg=welcome_msg)

@app.route('/request_otp', methods=['POST'])
def request_otp():
    prepare_auth_runtime()
    email = normalize_email(request.form.get('email'))

    if not email or email != session.get('pre_auth_email'):
        return json_error('Start from login before requesting an OTP.', 'login_required', status=400, extra={'otp': None})

    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE id = ? AND lower(email) = ?',
        (session.get('pre_auth_user_id'), email),
    ).fetchone()
    conn.close()

    if not user:
        return json_error('This email is not registered', 'email_not_registered', status=404, extra={'otp': None})

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
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))

        session['pre_auth_user_id'] = user['id']
        session['pre_auth_email'] = email
        return redirect(url_for('verify'))
            
    return render_template('auth.html', mode='login')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    prepare_auth_runtime()
    if 'pre_auth_user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        expects_json = (request.form.get('response_mode') == 'json')
        email = normalize_email(request.form.get('email'))
        user_otp = (request.form.get('otp') or '').strip().replace(' ', '')
        user_id = session.get('pre_auth_user_id')
        
        session_otp = session.get('temp_otp')
        otp_time = session.get('otp_time', 0)
        otp_email = session.get('otp_email')

        if not session_otp or otp_email != email:
            if expects_json:
                return json_error('Request a fresh OTP before verifying.', 'otp_not_requested', status=400)
            flash('Invalid OTP or email', 'error')
            return redirect(url_for('verify'))

        if time.time() - otp_time > app.config['OTP_EXPIRY_SECONDS']:
            if expects_json:
                return json_error('OTP has expired. Request a new code.', 'otp_expired', status=400)
            flash('OTP has expired. Please request a new one.', 'error')
            return redirect(url_for('verify'))

        if user_otp != session_otp:
            if expects_json:
                return json_error('Incorrect OTP. Enter the latest code from your inbox.', 'invalid_otp', status=400)
            flash('Invalid OTP', 'error')
            return redirect(url_for('verify'))
        
        # Success! Finalize Login
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        
        session.pop('temp_otp', None)
        session.pop('otp_time', None)
        session.pop('otp_email', None)
        session.pop('pre_auth_user_id', None)
        session.pop('pre_auth_email', None)
        
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
            
    return render_template('auth.html', mode='verify', email=session.get('pre_auth_email'))

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
            flash('Username, email, and password are required', 'error')
            return redirect(url_for('register'))

        if is_blocked_email_domain(email):
            flash('Use a real email inbox. Example or test domains are blocked for OTP delivery.', 'error')
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (username, email, password, role, full_name, city, state, district, pincode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (username, email, generate_password_hash(password), role, full_name, city, state, district, pincode)
            )
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists', 'error')
        finally:
            conn.close()

    return render_template('auth.html', mode='register')

@app.route('/logout')
def logout():
    has_visited = session.get('has_visited', False)
    session.clear()
    session['has_visited'] = has_visited # Keep visit history after logout
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
        SELECT o.* FROM orders o
        JOIN crops c ON o.crop_id = c.id
        WHERE o.id = ? AND c.farmer_id = ?
    ''', (order_id, session['user_id'])).fetchone()
    
    if order:
        conn.execute('UPDATE orders SET status = ?, current_location = ? WHERE id = ?', (new_status, location, order_id))
        # Add tracking update
        conn.execute('INSERT INTO order_updates (order_id, status, location) VALUES (?, ?, ?)',
                     (order_id, new_status, location))
        conn.commit()
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
        
        # Add initial tracking update
        conn.execute('INSERT INTO order_updates (order_id, status, location) VALUES (?, ?, ?)',
                     (order_id, 'Order Placed', farmer['city'] or farmer['state']))
        
        conn.execute('UPDATE crops SET quantity = quantity - ? WHERE id = ?', (quantity, crop_id))
        conn.commit()
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
        if order['status'] in ['pending', 'Paid', 'Confirmed']:
            conn.execute('UPDATE orders SET status = "Cancelled" WHERE id = ?', (order_id,))
            # Add tracking update
            conn.execute('INSERT INTO order_updates (order_id, status, location) VALUES (?, ?, ?)',
                         (order_id, 'Cancelled', 'System'))
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
