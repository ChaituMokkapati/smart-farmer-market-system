import os
import smtplib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DB = Path(tempfile.gettempdir()) / "smart_farmer_test.db"

os.environ["DATABASE_PATH"] = str(TEST_DB)
os.environ["MAIL_SUPPRESS_SEND"] = "true"
os.environ["EXPOSE_TEST_OTP"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_EMAIL"] = "admin_test@gmail.com"
os.environ["ADMIN_PASSWORD"] = "AdminPass#2026"
os.environ["PRESERVE_ENV_VARS"] = "true"

from app import app, resolve_server_runtime  # noqa: E402
from database import get_db_connection, init_db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402


class TestMarketSystem(unittest.TestCase):
    def setUp(self):
        if TEST_DB.exists():
            TEST_DB.unlink()

        app.config["TESTING"] = True
        self.client = app.test_client()
        init_db()
        self.unique = str(int(time.time() * 1000000))

    def tearDown(self):
        if TEST_DB.exists():
            TEST_DB.unlink()

    def test_homepage_redirects_to_login_for_anonymous_user(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_registration_redirects_to_login(self):
        response = self.client.post(
            "/register",
            data={
                "username": f"testfarmer_{self.unique}",
                "email": f"testfarmer_{self.unique}@gmail.com",
                "password": "password123",
                "role": "farmer",
                "full_name": "Test Farmer",
                "city": "Hyderabad",
                "state": "Telangana",
                "district": "Hyderabad",
                "pincode": "500001",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_login_redirects_to_verify_and_accepts_generated_otp(self):
        email = f"testuser{self.unique}@gmail.com"
        self.client.post(
            "/register",
            data={
                "username": f"testuser_{self.unique}",
                "email": email,
                "password": "password123",
                "role": "customer",
                "full_name": "Test User",
                "city": "Hyderabad",
                "state": "Telangana",
                "district": "Hyderabad",
                "pincode": "500001",
            },
            follow_redirects=False,
        )

        response = self.client.post(
            "/login",
            data={"email": email, "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/verify", response.headers["Location"])

        otp_response = self.client.post("/request_otp", data={"email": email})
        otp_data = otp_response.get_json()
        self.assertTrue(otp_data["success"])
        self.assertIsNone(otp_data["error_code"])
        self.assertEqual(len(otp_data["otp"]), 6)

        verify_response = self.client.post(
            "/verify",
            data={"email": email, "otp": otp_data["otp"], "response_mode": "json"},
        )
        verify_data = verify_response.get_json()
        self.assertTrue(verify_data["success"])
        self.assertEqual("/my_orders", verify_data["redirect"])

    def test_admin_login_uses_env_credentials_and_returns_test_otp(self):
        response = self.client.post(
            "/admin/login",
            data={
                "action": "send_otp",
                "email": os.environ["ADMIN_EMAIL"],
                "password": os.environ["ADMIN_PASSWORD"],
            },
        )
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertIsNone(payload["error_code"])
        self.assertEqual(len(payload["otp"]), 6)

    def test_registration_rejects_fake_email_domain(self):
        response = self.client.post(
            "/register",
            data={
                "username": f"blocked_{self.unique}",
                "email": f"blocked_{self.unique}@example.com",
                "password": "password123",
                "role": "customer",
                "full_name": "Blocked User",
                "city": "Hyderabad",
                "state": "Telangana",
                "district": "Hyderabad",
                "pincode": "500001",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/register", response.headers["Location"])

    def test_request_otp_rejects_fake_domain_for_existing_user(self):
        conn = get_db_connection()
        conn.execute(
            """
            INSERT INTO users (username, email, password, role, full_name, city, state, district, pincode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"legacy_{self.unique}",
                f"legacy_{self.unique}@example.com",
                generate_password_hash("password123"),
                "customer",
                "Legacy User",
                "Hyderabad",
                "Telangana",
                "Hyderabad",
                "500001",
            ),
        )
        conn.commit()
        conn.close()

        email = f"legacy_{self.unique}@example.com"
        self.client.post("/login", data={"email": email, "password": "password123"}, follow_redirects=False)
        response = self.client.post("/request_otp", data={"email": email})
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])
        self.assertEqual("invalid_email_domain", payload["error_code"])

    def test_admin_login_returns_error_code_on_mail_failure(self):
        with patch("app.send_email", side_effect=smtplib.SMTPAuthenticationError(535, b"bad auth")):
            response = self.client.post(
                "/admin/login",
                data={
                    "action": "send_otp",
                    "email": os.environ["ADMIN_EMAIL"],
                    "password": os.environ["ADMIN_PASSWORD"],
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["success"])
        self.assertEqual("smtp_auth_failed", payload["error_code"])

    def test_server_runtime_honors_env_port_and_debug_reload(self):
        with patch.dict(
            os.environ,
            {
                "HOST": "0.0.0.0",
                "PORT": "5099",
                "FLASK_DEBUG": "true",
            },
            clear=False,
        ):
            runtime = resolve_server_runtime()

        self.assertEqual("0.0.0.0", runtime["host"])
        self.assertEqual(5099, runtime["port"])
        self.assertTrue(runtime["debug"])
        self.assertTrue(runtime["use_reloader"])

    def test_server_runtime_defaults_to_local_production_style(self):
        with patch.dict(
            os.environ,
            {
                "HOST": "",
                "PORT": "",
                "FLASK_DEBUG": "false",
            },
            clear=False,
        ):
            runtime = resolve_server_runtime()

        self.assertEqual("127.0.0.1", runtime["host"])
        self.assertEqual(5000, runtime["port"])
        self.assertFalse(runtime["debug"])
        self.assertFalse(runtime["use_reloader"])


if __name__ == "__main__":
    unittest.main()
