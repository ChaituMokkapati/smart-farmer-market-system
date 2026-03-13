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

    def _create_user(
        self,
        username,
        email,
        role,
        full_name,
        city="Hyderabad",
        state="Telangana",
        district="Hyderabad",
        pincode="500001",
    ):
        conn = get_db_connection()
        cursor = conn.execute(
            """
            INSERT INTO users (username, email, password, role, full_name, city, state, district, pincode, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                username,
                email,
                generate_password_hash("password123"),
                role,
                full_name,
                city,
                state,
                district,
                pincode,
            ),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id

    def _set_session_user(self, user_id, role, username, email):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["role"] = role
            session["username"] = username
            session["email"] = email

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

    def test_language_switch_to_telugu_updates_login_page(self):
        response = self.client.post(
            "/set_language",
            data={"language": "te", "next": "/login"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual("/login", response.headers["Location"])

        page = self.client.get("/login")
        html = page.get_data(as_text=True)
        self.assertIn('lang="te"', html)
        self.assertIn("\u0c32\u0c3e\u0c17\u0c3f\u0c28\u0c4d", html)
        self.assertIn("\u0c24\u0c3f\u0c30\u0c3f\u0c17\u0c3f \u0c38\u0c4d\u0c35\u0c3e\u0c17\u0c24\u0c02", html)

    def test_forgot_password_flow_resets_password_after_otp(self):
        email = f"recover_{self.unique}@gmail.com"
        self._create_user(
            f"recover_{self.unique}",
            email,
            "customer",
            "Recover User",
        )

        response = self.client.post(
            "/forgot_password",
            data={"email": email},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/reset_password/verify", response.headers["Location"])

        otp_response = self.client.post("/request_password_reset_otp", data={"email": email})
        otp_data = otp_response.get_json()
        self.assertTrue(otp_data["success"])
        self.assertEqual(len(otp_data["otp"]), 6)

        verify_response = self.client.post(
            "/reset_password/verify",
            data={"email": email, "otp": otp_data["otp"], "response_mode": "json"},
        )
        verify_data = verify_response.get_json()
        self.assertTrue(verify_data["success"])
        self.assertEqual("/reset_password", verify_data["redirect"])

        reset_response = self.client.post(
            "/reset_password",
            data={"password": "NewPassword#123", "confirm_password": "NewPassword#123"},
            follow_redirects=False,
        )
        self.assertEqual(reset_response.status_code, 302)
        self.assertIn("/login", reset_response.headers["Location"])

        old_login = self.client.post(
            "/login",
            data={"email": email, "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(old_login.status_code, 302)
        self.assertIn("/login", old_login.headers["Location"])

        new_login = self.client.post(
            "/login",
            data={"email": email, "password": "NewPassword#123"},
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 302)
        self.assertIn("/verify", new_login.headers["Location"])

    def test_admin_dashboard_renders_telugu_copy(self):
        conn = get_db_connection()
        admin_user = conn.execute(
            "SELECT id, username, email FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.close()

        self._set_session_user(admin_user["id"], "admin", admin_user["username"], admin_user["email"])
        with self.client.session_transaction() as session:
            session["lang"] = "te"

        response = self.client.get("/admin/dashboard")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="te"', html)
        self.assertIn("\u0c05\u0c17\u0c4d\u0c30\u0c3f \u0c15\u0c2e\u0c3e\u0c02\u0c21\u0c4d \u0c30\u0c42\u0c2e\u0c4d", html)

    def test_admin_login_renders_telugu_copy(self):
        with self.client.session_transaction() as session:
            session["lang"] = "te"

        response = self.client.get("/admin/login")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('lang="te"', html)
        self.assertIn("\u0c38\u0c41\u0c30\u0c15\u0c4d\u0c37\u0c3f\u0c24 \u0c05\u0c21\u0c4d\u0c2e\u0c3f\u0c28\u0c4d \u0c2f\u0c3e\u0c15\u0c4d\u0c38\u0c46\u0c38\u0c4d", html)
        self.assertIn("\u0c15\u0c02\u0c1f\u0c4d\u0c30\u0c4b\u0c32\u0c4d \u0c30\u0c42\u0c2e\u0c4d\u200c\u0c32\u0c4b\u0c15\u0c3f \u0c2a\u0c4d\u0c30\u0c35\u0c47\u0c36\u0c3f\u0c02\u0c1a\u0c02\u0c21\u0c3f", html)

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

    def test_place_order_sends_farmer_email(self):
        farmer_id = self._create_user(
            f"farmer_{self.unique}",
            f"farmer_{self.unique}@gmail.com",
            "farmer",
            "Farmer One",
        )
        customer_id = self._create_user(
            f"customer_{self.unique}",
            f"customer_{self.unique}@gmail.com",
            "customer",
            "Customer One",
        )

        conn = get_db_connection()
        crop_id = conn.execute(
            """
            INSERT INTO crops (farmer_id, name, category, quantity, price, harvest_date, state, district, village, pincode, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farmer_id,
                "Tomato",
                "Vegetables",
                100,
                25,
                "2026-03-10",
                "Telangana",
                "Hyderabad",
                "Village A",
                "500001",
                "Fresh tomatoes",
            ),
        ).lastrowid
        conn.commit()
        conn.close()

        self._set_session_user(
            customer_id,
            "customer",
            f"customer_{self.unique}",
            f"customer_{self.unique}@gmail.com",
        )

        with patch("app.send_email") as send_email_mock:
            response = self.client.post(
                "/place_order",
                data={"crop_id": crop_id, "quantity": "4"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/checkout/", response.headers["Location"])
        send_email_mock.assert_called_once()
        self.assertEqual(f"farmer_{self.unique}@gmail.com", send_email_mock.call_args.args[0])
        self.assertIn("New Order Request", send_email_mock.call_args.args[1])

    def test_farmer_approval_sends_customer_email(self):
        farmer_username = f"farmer_{self.unique}"
        customer_username = f"customer_{self.unique}"
        farmer_email = f"farmer_{self.unique}@gmail.com"
        customer_email = f"customer_{self.unique}@gmail.com"

        farmer_id = self._create_user(farmer_username, farmer_email, "farmer", "Farmer One")
        customer_id = self._create_user(customer_username, customer_email, "customer", "Customer One")

        conn = get_db_connection()
        crop_id = conn.execute(
            """
            INSERT INTO crops (farmer_id, name, category, quantity, price, harvest_date, state, district, village, pincode, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farmer_id,
                "Chilli",
                "Spices",
                50,
                120,
                "2026-03-10",
                "Telangana",
                "Hyderabad",
                "Village B",
                "500001",
                "Dry red chilli",
            ),
        ).lastrowid
        order_id = conn.execute(
            """
            INSERT INTO orders (customer_id, crop_id, quantity, total_price, status, estimated_delivery, current_location)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                crop_id,
                2,
                240,
                "Paid",
                "14 Mar, 2026",
                "Hyderabad",
            ),
        ).lastrowid
        conn.commit()
        conn.close()

        self._set_session_user(farmer_id, "farmer", farmer_username, farmer_email)

        with patch("app.send_email") as send_email_mock:
            response = self.client.post(
                "/farmer/update_order_status",
                data={"order_id": order_id, "status": "Order Confirmed", "location": "Packing Shed"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/farmer/dashboard", response.headers["Location"])
        send_email_mock.assert_called_once()
        self.assertEqual(customer_email, send_email_mock.call_args.args[0])
        self.assertIn("Farmer Approved Your Order", send_email_mock.call_args.args[1])

        conn = get_db_connection()
        order = conn.execute("SELECT status, current_location FROM orders WHERE id = ?", (order_id,)).fetchone()
        tracking = conn.execute(
            "SELECT status, location FROM order_updates WHERE order_id = ? ORDER BY id DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        conn.close()

        self.assertEqual("Order Confirmed", order["status"])
        self.assertEqual("Packing Shed", order["current_location"])
        self.assertEqual("Order Confirmed", tracking["status"])
        self.assertEqual("Packing Shed", tracking["location"])


if __name__ == "__main__":
    unittest.main()
