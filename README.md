# 🌽 Smart Farmer Market System

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.0-green.svg)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A sophisticated, full-stack agricultural marketplace designed to empower local farmers by connecting them directly with customers. This platform eliminates middlemen, ensures fair pricing for farmers, and provides fresh produce for consumers.

---

## ✨ Key Features

### 🚜 For Farmers
- **Advanced Dashboard**: Track inventory, sales, and verification status at a glance.
- **Product Management**: Full CRUD (Create, Read, Update, Delete) for crops with image upload support.
- **Verification System**: Get "Verified" by admins to build trust with customers.
- **Public Profile**: A dedicated profile page showing crop history and customer reviews.

### 🛒 For Customers
- **Hyper-Local Search**: Filter fresh produce by city and specific crop names.
- **Pro Checkout**: A seamless, Stripe-inspired secure payment experience.
- **Order Tracking**: Real-time status updates (Pending -> Paid -> Shipped).
- **Reputation System**: Leave star ratings and feedback for farmers after purchase.

### 🛡️ For Admins
- **Command Center**: Manage users, monitor all transactions, and oversee system health.
- **Verification Portal**: Vet and verify farmers to maintain platform quality.
- **Status Control**: Manually override order statuses if necessary.

---

## 🛠️ Technical Stack

- **Backend**: Python 3.10+ / Flask
- **Frontend**: HTML5, CSS3 (Premium Glassmorphism), JavaScript (ES6)
- **Database**: SQLite3
- **Payment Gateway**: Stripe (Integration Ready)
- **Mailing**: Flask-Mail (Configured for SMTP)

---

## 🚀 Getting Started

### 📦 Prerequisites
- Python 3.8 or higher
- Git

### 🔧 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/smart-farmer-market.git
   cd smart-farmer-market
   ```

2. **Create a Virtual Environment**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # On Windows
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize the Database**
   ```bash
   python database.py
   ```

5. **Run the Application**
   ```bash
   python app.py
   ```

The application will be available at `http://127.0.0.1:5000`.

---

## 🧪 Testing

Run the included verification suite to ensure all components are functional:
```bash
python test_app.py
```

---

## 📁 Project Structure

```text
smart-farmer-market/
├── static/               # CSS, JS, and Images
│   ├── css/              # Premium Design System
│   ├── js/               # Interactivity & Validation
│   └── uploads/          # User-uploaded crop images
├── templates/            # Jinja2 HTML Templates
├── app.py                # Main Flask Logic & Routes
├── database.py           # Schema & DB Initialization
├── market.db             # SQLite Database (Auto-generated)
├── requirements.txt      # Project Dependencies
└── Procfile              # Deployment Configuration
```

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.

---

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request
