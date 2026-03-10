from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import get_db_connection
import os
import random
import time
import stripe
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from twilio.rest import Client

app = Flask(__name__)
app.secret_key = 'smart_farmer_secret_key'

# Configuration for Image Uploads
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configuration for Email (Using mock/test settings)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com' # User needs to set this
app.config['MAIL_PASSWORD'] = 'your-password'       # User needs to set this
mail = Mail(app)

# Mock Stripe Keys for Demonstration
stripe.api_key = "sk_test_demo_12345"

# Twilio Credentials (Vatini Twilio Dashboard nunchi teeskovali)
TWILIO_ACCOUNT_SID = 'YOUR_ACCOUNT_SID'
TWILIO_AUTH_TOKEN = 'YOUR_AUTH_TOKEN'
TWILIO_PHONE_NUMBER = '+1234567890'

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    phone = request.form.get('phone')
    
    conn = get_db_connection()
    # Check if any user has this contact number
    user = conn.execute('SELECT * FROM users WHERE contact = ?', (phone,)).fetchone()
    conn.close()
    
    if user:
        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        session['temp_otp'] = otp
        session['otp_time'] = time.time()
        session['otp_phone'] = phone
        
        # --- SMS Gateway Integration (Twilio) ---
        try:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=f"Mee login OTP: {otp}. Idi 60 seconds matrame pani chestundi.",
                from_=TWILIO_PHONE_NUMBER,
                to=phone
            )
            return jsonify({
                'success': True, 
                'message': f'OTP sent successfully to {phone}!'
            })
        except Exception as e:
            print(f"Twilio Error: {e}")
            # Fallback for development if credentials are not yet set
            return jsonify({
                'success': True, 
                'message': f'OTP sent to {phone}! [DEV ONLY: Your OTP is {otp}]'
            })
        # ----------------------------------------
    else:
        return jsonify({'success': False, 'message': 'This phone number is not registered'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone')
        password = request.form['password']
        
        # 1. Verify credentials (Step 1)
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE contact = ? AND password = ?', (phone, password)).fetchone()
        conn.close()
        
        if not user:
            flash('Invalid phone number or password', 'error')
            return redirect(url_for('login'))

        # Valid credentials, move to verification step
        session['pre_auth_user_id'] = user['id']
        session['pre_auth_phone'] = phone
        return redirect(url_for('verify'))
            
    return render_template('auth.html', mode='login')

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if 'pre_auth_user_id' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        phone = request.form.get('phone')
        user_otp = request.form.get('otp')
        user_id = session.get('pre_auth_user_id')
        
        # 1. Verify OTP
        session_otp = session.get('temp_otp')
        otp_time = session.get('otp_time', 0)
        otp_phone = session.get('otp_phone')

        if not session_otp or otp_phone != phone:
            flash('Invalid OTP or Phone Number', 'error')
            return redirect(url_for('verify'))

        if time.time() - otp_time > 60:
            flash('OTP has expired. Please request a new one.', 'error')
            return redirect(url_for('verify'))

        if user_otp != session_otp:
            flash('Invalid OTP', 'error')
            return redirect(url_for('verify'))
        
        # Success! Finalize Login
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        
        session.pop('temp_otp', None)
        session.pop('otp_time', None)
        session.pop('otp_phone', None)
        session.pop('pre_auth_user_id', None)
        session.pop('pre_auth_phone', None)
        
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['has_visited'] = True
        
        if user['role'] == 'farmer':
            return redirect(url_for('farmer_dashboard'))
        elif user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('my_orders'))
            
    return render_template('auth.html', mode='verify', phone=session.get('pre_auth_phone'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'customer')
        full_name = request.form.get('full_name', '')
        contact = request.form.get('contact', '')
        city = request.form.get('city', '')
        state = request.form.get('state', '')
        district = request.form.get('district', '')
        pincode = request.form.get('pincode', '')
        
        if not username or not password:
            flash('Username and Password are required', 'error')
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, role, full_name, contact, city, state, district, pincode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (username, password, role, full_name, contact, city, state, district, pincode))
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username already exists', 'error')
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
        SELECT o.*, c.name as crop_name, u.full_name as customer_name, u.contact as customer_phone
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
        SELECT o.*, c.name as crop_name, c.image_url as crop_image, u.full_name as farmer_name
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
    order_id = request.form['order_id']
    conn = get_db_connection()
    order = conn.execute('''
        SELECT o.*, u.username as customer_email, u.full_name as customer_name, c.name as crop_name 
        FROM orders o 
        JOIN users u ON o.customer_id = u.id 
        JOIN crops c ON o.crop_id = c.id
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    
    if order:
        conn.execute('UPDATE orders SET status = "Paid" WHERE id = ?', (order_id,))
        conn.commit()
        
        # Send Email Notification (Simulated/Configured)
        try:
            msg = Message("Order Confirmed - Smart Farmer Market",
                          sender="noreply@market.com",
                          recipients=[order['customer_email'] + "@market.com"])
            msg.body = f"Hello {order['customer_name']},\n\nYour order for {order['crop_name']} has been confirmed. Total Paid: ₹{order['total_price']}\n\nThank you for shopping local!"
            # mail.send(msg) # Uncomment with real credentials
        except Exception as e:
            print(f"Mail failed: {e}")
            
    conn.close()
    flash('Payment successful! A confirmation email has been sent.', 'success')
    return redirect(url_for('my_orders'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        action = request.form.get('action') # 'send_otp' or 'verify'
        username = request.form.get('username')
        phone = request.form.get('phone')
        
        if action == 'send_otp':
            # Support both requested 'mahesh' and default 'admin' credentials
            if (username == 'mahesh' and phone == 'pujimahi') or (username == 'admin' and phone == 'admin'):
                otp = str(random.randint(100000, 999999))
                session['admin_temp_otp'] = otp
                session['admin_otp_time'] = time.time()
                session['admin_username'] = username
                
                # Mock SMS output to console
                print(f"ADMIN OTP FOR {username}: {otp}")
                return jsonify({
                    'success': True, 
                    'message': f'Identity partially verified. OTP generated! [DEV: {otp}]'
                })
            else:
                return jsonify({'success': False, 'message': 'Invalid Admin Credentials'})
        
        elif action == 'verify':
            user_otp = request.form.get('otp')
            session_otp = session.get('admin_temp_otp')
            otp_time = session.get('admin_otp_time', 0)
            
            if not session_otp or time.time() - otp_time > 60:
                return jsonify({'success': False, 'message': 'OTP expired or not found'})
            
            if user_otp == session_otp:
                session.pop('admin_temp_otp', None)
                session['user_id'] = 'admin_0'
                session['username'] = 'admin'
                session['role'] = 'admin'
                return jsonify({'success': True, 'redirect': url_for('admin_dashboard')})
            else:
                return jsonify({'success': False, 'message': 'Incorrect OTP'})
            
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
    app.run(debug=True)
