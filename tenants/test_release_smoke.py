from django.test import SimpleTestCase, override_settings
from django.urls import reverse, resolve


@override_settings(ALLOWED_HOSTS=["localhost", "testserver"])
class ReleaseSmokeTests(SimpleTestCase):

    def test_school_registration_route_exists(self):
        match = resolve("/register-school/")
        self.assertIsNotNone(match.func)

    def test_anonymous_admin_access_redirects_to_login(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_login_route_exists(self):
        match = resolve("/login/")
        self.assertIsNotNone(match.func)
