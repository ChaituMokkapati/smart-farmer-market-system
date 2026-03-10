import sqlite3
import os

DB_PATH = 'market.db'

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Create farmers if they don't exist
    farmers = [
        ('farmer_john', 'pass123', 'farmer', 'John Doe', '1234567890', 'San Francisco', 1),
        ('farmer_mary', 'pass123', 'farmer', 'Mary Jane', '0987654321', 'Los Angeles', 1)
    ]
    
    farmer_ids = []
    for f in farmers:
        cursor.execute("SELECT id FROM users WHERE username = ?", (f[0],))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO users (username, password, role, full_name, contact, city, is_verified) VALUES (?, ?, ?, ?, ?, ?, ?)", f)
            farmer_ids.append(cursor.lastrowid)
        else:
            farmer_ids.append(row[0])
            
    # 2. Add diverse products with full location hierarchy
    crops = [
        (farmer_ids[0], 'Sona Masuri Rice', 'Rice Varieties', 500, 55, '2026-03-01', 'Telangana', 'Hyderabad', 'Gachibowli', '500032', 'Premium quality aged Sona Masuri rice.', 'uploads/rice.png'),
        (farmer_ids[0], 'Organic Red Chilli', 'Vegetables', 100, 120, '2026-03-05', 'Andhra Pradesh', 'Guntur', 'Amaravati', '522001', 'Sun-dried premium Guntur chillies.', 'uploads/chilli.png'),
        (farmer_ids[0], 'Basmati Rice (Aged)', 'Rice Varieties', 300, 95, '2026-02-15', 'Telangana', 'Nizamabad', 'Armoor', '503224', 'Aromatic long-grain basmati rice.', 'uploads/basmati.png'),
        (farmer_ids[1], 'Fresh Buffalo Milk', 'Milk & Dairy', 50, 70, '2026-03-09', 'Andhra Pradesh', 'Krishna', 'Vijayawada', '520001', 'Pure farm fresh milk delivered daily.', 'uploads/milk.png'),
        (farmer_ids[1], 'Cold Pressed Peanut Oil', 'Oil Products', 30, 180, '2026-03-02', 'Telangana', 'Mahbubnagar', 'Jadcherla', '509301', 'Traditional stone-crushed peanut oil.', 'uploads/oil.png'),
        (farmer_ids[1], 'Desi Ghee', 'Milk & Dairy', 20, 650, '2026-03-01', 'Andhra Pradesh', 'Anantapur', 'Dharmavaram', '515671', 'Pure cow ghee made with traditional methods.', 'uploads/ghee.png'),
        # New Additions
        (farmer_ids[0], 'Black Gram (Minapa)', 'Pulses', 200, 110, '2026-03-05', 'Telangana', 'Warangal', 'Hanamkonda', '506001', 'High protein black gram, locally grown.', 'uploads/pulses.png'),
        (farmer_ids[0], 'Neelam Mangoes', 'Fruits', 150, 60, '2026-03-08', 'Andhra Pradesh', 'Chittoor', 'Madanapalle', '517325', 'Sweet and fiber-less Neelam mangoes.', 'uploads/mango.png'),
        (farmer_ids[1], 'Organic Curd', 'Milk & Dairy', 40, 45, '2026-03-09', 'Andhra Pradesh', 'Visakhapatnam', 'Ankapalle', '531001', 'Thick and creamy organic farm curd.', 'uploads/curd.png'),
        (farmer_ids[1], 'Fresh Malai Paneer', 'Milk & Dairy', 15, 380, '2026-03-10', 'Telangana', 'Rangareddy', 'Chevella', '501503', 'Soft and fresh malai paneer from farm milk.', 'uploads/paneer.png'),
        (farmer_ids[0], 'Nizamabad Turmeric', 'Grains', 100, 160, '2026-03-04', 'Telangana', 'Nizamabad', 'Armoor', '503224', 'High curcumin turmeric powder.', 'uploads/turmeric.png'),
        (farmer_ids[1], 'Sunflower Oil', 'Oil Products', 60, 155, '2026-03-06', 'Andhra Pradesh', 'Kurnool', 'Nandyal', '518501', 'Refined local sunflower oil.', 'uploads/sunflower_oil.png')
    ]
    
    for c in crops:
        cursor.execute("SELECT id FROM crops WHERE name = ? AND farmer_id = ?", (c[1], c[0]))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO crops (farmer_id, name, category, quantity, price, harvest_date, state, district, village, pincode, description, image_url) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', c)
            
    conn.commit()
    conn.close()
    print("Marketplace seeded with diverse products and full location hierarchy!")

if __name__ == '__main__':
    seed()
