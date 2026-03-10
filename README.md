# Smart Farmer Market System

Flask-based marketplace for farmers, customers, and admins with email OTP authentication, local frontend assets, and SQLite storage.

## What changed

- Gmail SMTP is now the OTP delivery channel for customer, farmer, and admin sign-in.
- User OTP requests are limited to `3` per hour. Admin OTP requests are exempt.
- Admin credentials are created from `.env`; there are no hardcoded fallback credentials in code.
- Passwords are stored as Werkzeug hashes, and legacy plaintext passwords are upgraded during DB initialization.
- Tailwind, Font Awesome, Chart.js, and the UI fonts are vendored under `static/vendor/`.
- Old SMS/Twilio and Node demo files were removed from the runtime path.

## Project layout

```text
smart-farmer-market-system/
├── app.py
├── database.py
├── requirements.txt
├── templates/
├── static/
│   ├── css/
│   ├── js/
│   ├── uploads/
│   └── vendor/
├── test_app.py
├── .env.example
└── README.md
```

## Prerequisites

- Python 3.10+
- A Gmail account with an App Password enabled

## Setup

1. Clone the repository.

```powershell
git clone <your-repo-url>
cd smart-farmer-market-system
```

2. Create and activate a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

3. Install dependencies.

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Create `.env` from the example file.

```powershell
copy .env.example .env
```

5. Edit `.env` and set these values:

- `SECRET_KEY`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

6. Initialize the database.

```powershell
python database.py
```

7. Run the app in development mode.

```powershell
$env:FLASK_DEBUG="true"
python app.py
```

The app will start at [http://127.0.0.1:5000](http://127.0.0.1:5000).

For a production-style local run without auto-reload:

```powershell
$env:FLASK_DEBUG="false"
python app.py
```

## Production notes

- Set `SESSION_COOKIE_SECURE=true` behind HTTPS.
- Keep `.env` out of git. `.gitignore` already excludes it.
- `database.py` will create or update the admin account from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- OTP expiry is controlled with `OTP_EXPIRY_SECONDS`.
- User OTP rate limiting is controlled with `OTP_MAX_PER_HOUR`.

## OTP troubleshooting

- Use a real inbox address. Example or testing domains such as `example.com` are blocked for OTP delivery.
- The admin auth path reloads `.env` at runtime, so changed admin credentials can take effect immediately.
- When `FLASK_DEBUG=true`, local code and template edits reload automatically. When debug is off, route/template changes require a full process restart.
- The app now prints a startup summary with host, port, debug mode, admin email, and sender so stale runtime state is obvious in the terminal.
- If OTP send fails, the UI now shows the exact inline delivery error instead of leaving the screen stuck in a loading state.

## Default environment keys

`.env.example` includes the supported keys:

```env
SECRET_KEY=
FLASK_DEBUG=false
SESSION_COOKIE_SECURE=false
DATABASE_PATH=market.db
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=
MAIL_SUPPRESS_SEND=false
OTP_EXPIRY_SECONDS=300
OTP_MAX_PER_HOUR=3
EXPOSE_TEST_OTP=false
ADMIN_USERNAME=admin
ADMIN_FULL_NAME=System Administrator
ADMIN_EMAIL=
ADMIN_PASSWORD=
```

## Testing

Run the automated checks with:

```powershell
python test_app.py
```

The test suite uses a temporary SQLite database and suppresses outbound mail while still exposing OTP values to tests.

## Git-ready notes

- `.env`, SQLite DB files, uploads, logs, caches, and virtualenv folders are ignored.
- Vendored frontend assets are committed under `static/vendor/`, so the UI does not depend on live CDNs.
