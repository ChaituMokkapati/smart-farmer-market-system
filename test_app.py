import unittest
from app import app
from database import init_db, get_db_connection
import os

class TestMarketSystem(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        init_db()

    def test_homepage(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_registration(self):
        response = self.client.post('/register', data={
            'username': 'testfarmer',
            'password': 'password123',
            'role': 'farmer',
            'full_name': 'Test Farmer',
            'contact': '1234567890'
        }, follow_redirects=True)
        self.assertIn(b'Registration successful', response.data)

    def test_login(self):
        # First register
        self.client.post('/register', data={
            'username': 'testuser',
            'password': 'password123',
            'role': 'customer',
            'full_name': 'Test User',
            'contact': '1234567890'
        })
        # Then login
        response = self.client.post('/login', data={
            'username': 'testuser',
            'password': 'password123'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
