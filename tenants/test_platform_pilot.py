"""Platform lifecycle and isolated pilot infrastructure regressions."""
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.test import Client, TestCase, SimpleTestCase, override_settings, RequestFactory
from django.urls import reverse

from core.private_storage import PrivateDocumentStorage
from config.pilot import validate_environment
from tenants.audit import AuditMiddleware, SafeOperationalFilter, actor_context
from tenants.models import School, SchoolMembership
from tenants.platform_services import transition_school


class PlatformOnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = get_user_model().objects.create_superuser(username='operator', email='operator@example.com')

    def application(self, **extra):
        return {'school_name': 'Pilot Academy', 'username': 'initial-admin',
            'email': 'owner@example.com', 'first_name': 'Initial', 'last_name': 'Administrator',
            'password1': 'StrongInitialPassword2026!', 'password2': 'StrongInitialPassword2026!', **extra}

    def register(self, **extra):
        self.client.logout()
        response = self.client.post(reverse('register_school'), self.application(**extra))
        self.assertEqual(response.status_code, 302)
        return School.objects.get(created_by__username=extra.get('username', 'initial-admin'))

    def lifecycle(self, school, action):
        self.client.force_login(self.operator)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('platform_schools'), {'school_id': school.pk, 'action': action, 'confirm': 'yes'})

    def test_registration_is_pending_and_initial_admin_cannot_escalate(self):
        school = self.register(status='approved', role='superuser', is_staff='True', is_superuser='True')
        user = school.created_by
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password('StrongInitialPassword2026!'))
        self.assertNotEqual(user.password, 'StrongInitialPassword2026!')
        self.assertEqual(school.status, 'pending')
        membership = SchoolMembership.objects.get(user=user)
        self.assertEqual(membership.role, 'administrator')
        self.client.force_login(user)
        for route in ('school_home', 'academic_setup', 'admin_staff', 'admin_students', 'school_setup_checklist'):
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)
            self.assertIn(self.client.post(reverse(route), {}).status_code, (403, 405))
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_requires_unique_valid_email_and_strong_matching_password(self):
        for changes in ({'email': ''}, {'email': 'bad'}, {'password1': '123', 'password2': '123'},
                        {'password2': 'different'}, {'email': 'operator@example.com'}):
            response = self.client.post(reverse('register_school'), self.application(**changes))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertEqual(School.objects.count(), 0)

    def test_duplicate_username_does_not_create_partial_school_or_membership(self):
        self.register()
        self.client.logout()
        response = self.client.post(reverse('register_school'), self.application(email='other@example.com'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(SchoolMembership.objects.count(), 1)

    def test_approval_records_actor_and_enables_first_setup(self):
        school = self.register()
        self.assertEqual(self.lifecycle(school, 'approve').status_code, 302)
        school.refresh_from_db()
        self.assertEqual(school.status, 'approved')
        self.assertEqual(school.reviewed_by, self.operator)
        self.assertIsNotNone(school.reviewed_at)
        self.assertTrue(LogEntry.objects.filter(change_message__contains='school.approve').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.client.force_login(school.created_by)
        response = self.client.get(reverse('school_setup_checklist'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['complete'])
        self.assertEqual(len(response.context['steps']), 7)
        self.assertEqual(self.client.get(reverse('academic_setup')).status_code, 200)

    def test_suspension_and_reactivation_preserve_inactive_memberships(self):
        school = self.register()
        self.lifecycle(school, 'approve')
        membership = SchoolMembership.objects.get(school=school)
        self.client.force_login(school.created_by)
        self.assertEqual(self.client.get(reverse('school_home')).status_code, 200)
        self.lifecycle(school, 'suspend')
        self.client.force_login(school.created_by)
        self.assertEqual(self.client.get(reverse('school_home')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_periods'), {'name': '2026-2027'}).status_code, 403)
        membership.is_active = False
        membership.save()
        self.lifecycle(school, 'reactivate')
        membership.refresh_from_db()
        self.assertFalse(membership.is_active)
        self.client.force_login(school.created_by)
        self.assertEqual(self.client.get(reverse('school_home')).status_code, 403)
        self.assertEqual(SchoolMembership.objects.filter(school=school).count(), 1)

    def test_invalid_transitions_never_change_review_audit(self):
        school = self.register()
        for action in ('reactivate', 'suspend', 'unknown'):
            with self.assertRaises(ValidationError):
                transition_school(actor=self.operator, school_id=school.pk, action=action)
        school.refresh_from_db()
        self.assertEqual(school.status, 'pending')
        self.assertIsNone(school.reviewed_at)
        transition_school(actor=self.operator, school_id=school.pk, action='reject')
        with self.assertRaises(ValidationError):
            transition_school(actor=self.operator, school_id=school.pk, action='approve')

    def test_approval_requires_valid_initial_administrator(self):
        school = self.register()
        membership = SchoolMembership.objects.get(school=school)
        membership.role = 'teacher'
        membership.save()
        with self.assertRaises(ValidationError):
            transition_school(actor=self.operator, school_id=school.pk, action='approve')
        membership.role = 'administrator'
        membership.save()
        user = school.created_by
        user.is_staff = True
        user.save()
        with self.assertRaises(ValidationError):
            transition_school(actor=self.operator, school_id=school.pk, action='approve')
        school.refresh_from_db()
        self.assertEqual(school.status, 'pending')

    def test_only_active_staff_superuser_can_review_or_change_status(self):
        school = self.register()
        self.client.force_login(school.created_by)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(reverse('platform_schools'), {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            transition_school(actor=school.created_by, school_id=school.pk, action='approve')
        self.operator.is_staff = False
        self.operator.save()
        with self.assertRaises(PermissionDenied):
            transition_school(actor=self.operator, school_id=school.pk, action='approve')

    def test_operator_cannot_enter_school_portals(self):
        school = self.register()
        self.lifecycle(school, 'approve')
        for name in ('school_home', 'school_setup_checklist', 'admin_students', 'teacher_dashboard', 'accountant_dashboard'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_lifecycle_requires_post_confirmation_and_csrf(self):
        school = self.register()
        self.client.force_login(self.operator)
        self.client.get(reverse('platform_schools'), {'school_id': school.pk, 'action': 'approve'})
        self.assertEqual(self.client.post(reverse('platform_schools'), {'school_id': school.pk, 'action': 'approve'}).status_code, 400)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        self.assertEqual(client.post(reverse('platform_schools'), {'school_id': school.pk, 'action': 'approve', 'confirm': 'yes'}).status_code, 403)
        school.refresh_from_db()
        self.assertEqual(school.status, 'pending')

    def test_unknown_membership_role_denied_at_landing_page(self):
        school = self.register()
        self.lifecycle(school, 'approve')
        SchoolMembership.objects.filter(school=school).update(role='operator')
        self.client.force_login(school.created_by)
        self.assertEqual(self.client.get(reverse('school_home')).status_code, 403)

    @override_settings(ACCOUNT_PUBLIC_ORIGIN='https://portal.example.com')
    def test_approval_mail_uses_canonical_origin_not_request_host(self):
        school = self.register()
        self.lifecycle(school, 'approve')
        self.assertIn('https://portal.example.com/reset/', mail.outbox[0].body)
        self.assertNotIn('http://testserver', mail.outbox[0].body)
        self.client.logout()
        self.client.post(reverse('password_reset'), {'email': school.created_by.email})
        self.assertIn('https://portal.example.com/reset/', mail.outbox[-1].body)

    def test_suspended_school_invalidates_previously_issued_recovery_link(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        school = self.register()
        self.lifecycle(school, 'approve')
        user = school.created_by
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        self.lifecycle(school, 'suspend')
        self.client.logout()
        response = self.client.get(reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])

    def test_school_lifecycle_is_isolated(self):
        first = self.register()
        second = self.register(username='second-admin', email='second@example.com')
        self.lifecycle(first, 'approve')
        self.lifecycle(second, 'approve')
        self.lifecycle(first, 'suspend')
        self.client.force_login(second.created_by)
        self.assertEqual(self.client.get(reverse('school_home')).status_code, 200)
        self.assertEqual(self.client.get(reverse('platform_schools')).status_code, 403)

    def test_platform_admin_cannot_edit_status_or_delete_school_directly(self):
        from tenants.admin import SchoolAdmin
        from django.contrib import admin
        model_admin = SchoolAdmin(School, admin.site)
        request = RequestFactory().get('/admin/')
        request.user = self.operator
        self.assertIn('status', model_admin.get_readonly_fields(request))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


class PrivateStorageTests(SimpleTestCase):
    def test_private_files_persist_across_instances_and_do_not_offer_urls(self):
        with TemporaryDirectory() as root:
            first = PrivateDocumentStorage(location=root)
            name = first.save('schools/1/document.pdf', ContentFile(b'private bytes'))
            second = PrivateDocumentStorage(location=root)
            with second.open(name, 'rb') as handle:
                self.assertEqual(handle.read(), b'private bytes')
            self.assertEqual(Path(root, name).stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                second.url(name)
            second.delete(name)
            self.assertFalse(first.exists(name))

    def test_traversal_and_symlink_escape_rejected(self):
        with TemporaryDirectory() as root, TemporaryDirectory() as outside:
            storage = PrivateDocumentStorage(location=root)
            with self.assertRaises(SuspiciousFileOperation):
                storage.save('../escape.pdf', ContentFile(b'x'))
            Path(root, 'escape').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(SuspiciousFileOperation):
                storage.open('escape/secret.pdf')


class PilotConfigurationTests(SimpleTestCase):
    def env(self, **changes):
        return {'DJANGO_SECRET_KEY': 'pilot-only-synthetic-secret-'*3, 'DEBUG': 'False',
            'ACCOUNT_PUBLIC_ORIGIN': 'https://portal.example.com', 'ALLOWED_HOSTS': 'portal.example.com',
            'DATABASE_URL': 'postgresql://test@db.example.invalid/synthetic?sslmode=verify-full',
            'PILOT_PRIVATE_MEDIA_ROOT': '/isolated/private', 'PILOT_DURABLE_MEDIA_CONFIRMED': 'yes',
            'EMAIL_HOST': 'smtp.example.invalid', 'EMAIL_HOST_USER': 'synthetic',
            'EMAIL_HOST_PASSWORD': 'synthetic-never-used', 'DEFAULT_FROM_EMAIL': 'no-reply@example.com', **changes}

    def test_valid_pilot_environment_validates_without_connections(self):
        with patch('socket.create_connection', side_effect=AssertionError('Network forbidden')):
            self.assertEqual(validate_environment(self.env())['origin'], 'https://portal.example.com')

    def test_missing_values_and_insecure_settings_fail_closed_without_secret_output(self):
        for key in ('DJANGO_SECRET_KEY', 'ACCOUNT_PUBLIC_ORIGIN', 'ALLOWED_HOSTS', 'DATABASE_URL',
                    'PILOT_PRIVATE_MEDIA_ROOT', 'EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL'):
            with self.assertRaises(ImproperlyConfigured):
                validate_environment(self.env(**{key: ''}))
        for changes in ({'DEBUG': 'True'}, {'DJANGO_SECRET_KEY': 'short'}, {'ALLOWED_HOSTS': '*'},
                {'DATABASE_URL': 'sqlite:///db.sqlite3'}, {'DATABASE_URL': 'postgresql://a@host/db?sslmode=require'},
                {'DATABASE_URL': 'postgresql://a@host/db?sslmode=verify-full&sslmode='},
                {'ACCOUNT_PUBLIC_ORIGIN': 'http://portal.example.com'}, {'ACCOUNT_PUBLIC_ORIGIN': 'https://portal.example.com/path'},
                {'PILOT_DURABLE_MEDIA_CONFIRMED': 'no'}, {'PILOT_PRIVATE_MEDIA_ROOT': 'relative'},
                {'EMAIL_USE_TLS': 'True', 'EMAIL_USE_SSL': 'True'}, {'EMAIL_PORT': 'invalid'}):
            with self.assertRaises(ImproperlyConfigured) as captured:
                validate_environment(self.env(**changes))
            self.assertNotIn('synthetic-never-used', str(captured.exception))

    def test_postgres_test_settings_require_acknowledgment_and_loopback(self):
        import runpy
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_module('config.settings_postgres_pilot_test')
        with patch.dict(os.environ, {'SMS_SYNTHETIC_POSTGRES_ONLY': 'yes', 'SMS_TEST_PGHOST': 'production.example.com'}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_module('config.settings_postgres_pilot_test')
        with patch.dict(os.environ, {'SMS_SYNTHETIC_POSTGRES_ONLY': 'yes'}, clear=True):
            data = runpy.run_module('config.settings_postgres_pilot_test')
            self.assertEqual(data['DATABASES']['default']['TEST']['NAME'], 'test_sms_pilot_synthetic')
            self.assertEqual(data['DATABASES']['default']['HOST'], '127.0.0.1')

    def test_operational_filter_redacts_token_url_request_and_exception(self):
        record = logging.LogRecord('django.request', logging.ERROR, '', 0,
            'Error GET /reset/uid/SECRET-TOKEN/?password=secret', (), (ValueError, ValueError('SECRET-TOKEN'), None))
        record.request = 'private request'
        SafeOperationalFilter().filter(record)
        self.assertNotIn('SECRET-TOKEN', record.getMessage())
        self.assertIsNone(record.exc_info)
        self.assertFalse(hasattr(record, 'request'))

    def test_smtp_encryption_authentication_and_delivery_without_logging_token(self):
        from tenants.admin_services import deliver_account_mail
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                EMAIL_HOST='smtp.example.invalid', EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
                EMAIL_HOST_USER='test-user', EMAIL_HOST_PASSWORD='test-password', EMAIL_TIMEOUT=2):
            with patch('smtplib.SMTP') as smtp, self.assertNoLogs('tenants.admin_services'):
                with patch('socket.create_connection', side_effect=AssertionError('External connection forbidden')):
                    self.assertTrue(deliver_account_mail('Setup', 'SECRET-TOKEN', 'recipient@example.com'))
                smtp.return_value.starttls.assert_called_once()
                smtp.return_value.login.assert_called_once_with('test-user', 'test-password')
                smtp.return_value.sendmail.assert_called_once()

    def test_delivery_failures_do_not_log_exception_body_or_token(self):
        from tenants.admin_services import deliver_account_mail
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'):
            with patch('tenants.admin_services.send_mail', side_effect=RuntimeError('SECRET-TOKEN PASSWORD')):
                with self.assertLogs('tenants.admin_services', level='WARNING') as logs:
                    self.assertFalse(deliver_account_mail('Setup', 'SECRET-TOKEN', 'recipient@example.com'))
        self.assertNotIn('SECRET-TOKEN', str(logs.output))
        self.assertNotIn('PASSWORD', str(logs.output))


class OperationalTests(TestCase):
    def test_health_endpoints_expose_no_configuration_and_readiness_is_operator_only(self):
        response = self.client.get(reverse('health_live'))
        self.assertEqual(response.json(), {'status': 'alive'})
        self.assertEqual(self.client.get(reverse('platform_readiness')).status_code, 302)
        user = get_user_model().objects.create_user(username='regular')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('platform_readiness')).status_code, 403)
        user.is_staff = user.is_superuser = True
        user.save()
        with TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            response = self.client.get(reverse('platform_readiness'))
            self.assertEqual(response.json(), {'status': 'ready', 'database': True, 'storage_accessible': True})
            self.assertNotContains(response, root)

    def test_audit_middleware_logs_route_template_not_reset_token(self):
        from django.http import HttpResponse
        request = RequestFactory().get('/reset/uid/SECRET-TOKEN/?password=private')
        request.user = get_user_model().objects.create_user(username='test-audit')
        request.resolver_match = MagicMock(url_name='password_reset_confirm')
        with self.assertLogs('sms.operations', level='INFO') as logs:
            response = AuditMiddleware(lambda request: HttpResponse('ok'))(request)
        self.assertIn('X-Request-ID', response)
        self.assertNotIn('SECRET-TOKEN', str(logs.output))
        self.assertNotIn('password=private', str(logs.output))
        self.assertIsNone(actor_context.get())


class IsolatedSMTPTransportTests(SimpleTestCase):
    def test_account_mail_traverses_real_loopback_smtp_without_token_logs(self):
        import socketserver
        import threading
        from tenants.admin_services import deliver_account_mail
        messages = []
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                self.wfile.write(b'220 isolated-test ESMTP\r\n')
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    command = line.split(b' ', 1)[0].strip().upper()
                    if command in (b'EHLO', b'HELO', b'MAIL', b'RCPT', b'RSET'):
                        self.wfile.write(b'250 OK\r\n')
                    elif command == b'DATA':
                        self.wfile.write(b'354 End with dot\r\n')
                        data = []
                        while True:
                            part = self.rfile.readline()
                            if part in (b'.\r\n', b''):
                                break
                            data.append(part)
                        messages.append(b''.join(data))
                        self.wfile.write(b'250 Accepted\r\n')
                    elif command == b'QUIT':
                        self.wfile.write(b'221 Goodbye\r\n')
                        return
                    else:
                        self.wfile.write(b'502 Unsupported\r\n')
        with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                        EMAIL_HOST='127.0.0.1', EMAIL_PORT=server.server_address[1],
                        EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='', EMAIL_USE_TLS=False,
                        EMAIL_USE_SSL=False, EMAIL_TIMEOUT=3):
                    with self.assertNoLogs('tenants.admin_services'):
                        self.assertTrue(deliver_account_mail('Synthetic setup', 'SYNTHETIC-ONLY-TOKEN', 'test@example.invalid'))
                self.assertEqual(len(messages), 1)
                self.assertIn(b'SYNTHETIC-ONLY-TOKEN', messages[0])
            finally:
                server.shutdown()
                thread.join(timeout=3)


class OptInProfileTests(SimpleTestCase):
    def test_pilot_profile_security_checks_without_service_connections(self):
        import subprocess
        import sys
        env = PilotConfigurationTests().env()
        env.update({'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(settings.BASE_DIR),
                    'DJANGO_SETTINGS_MODULE': 'config.settings_pilot'})
        code = '''import django
django.setup()
from django.conf import settings
from django.core.checks import run_checks, Tags
assert not settings.DEBUG
assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
assert settings.CSRF_TRUSTED_ORIGINS == ['https://portal.example.com']
assert settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend'
assert settings.STORAGES['default']['BACKEND'] == 'core.private_storage.PrivateDocumentStorage'
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
checks=run_checks(tags=[Tags.security], include_deployment_checks=True)
assert not [check for check in checks if check.id not in ('security.W005','security.W021')], [check.id for check in checks]
print('PASS opt-in security profile; no database, storage or SMTP connections made.')
'''
        result = subprocess.run([sys.executable, '-c', code], env=env, cwd=settings.BASE_DIR,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS opt-in security profile', result.stdout)


class TenantWriteGuardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='guard-admin')
        self.school = School.objects.create(name='Guard school', status='approved')
        SchoolMembership.objects.create(school=self.school, user=self.user, role='administrator')
        self.request = RequestFactory().post(reverse('admin_students'), {})
        self.request.user = self.user

    def test_failed_response_rolls_back_tenant_mutation(self):
        from core.models import AcademicYear
        from django.http import HttpResponseBadRequest
        from tenants.pilot_middleware import TenantWriteGuardMiddleware
        def view(request):
            AcademicYear.objects.create(school=self.school, name='2026-2027')
            return HttpResponseBadRequest('Rejected')
        self.assertEqual(TenantWriteGuardMiddleware(view)(self.request).status_code, 400)
        self.assertFalse(AcademicYear.objects.filter(school=self.school).exists())

    def test_status_is_rechecked_after_acquiring_school_lock(self):
        from tenants.access import require_school_context
        from tenants.pilot_middleware import TenantWriteGuardMiddleware
        def stale_context(user):
            context = require_school_context(user)
            School.objects.filter(pk=self.school.pk).update(status='suspended')
            return context
        view = MagicMock()
        with patch('tenants.pilot_middleware.require_school_context', stale_context):
            with self.assertRaises(PermissionDenied):
                TenantWriteGuardMiddleware(view)(self.request)
        view.assert_not_called()

    def test_authentication_events_do_not_record_credentials(self):
        from django.contrib.auth.signals import user_login_failed
        with self.assertLogs('sms.security', level='INFO') as logs, self.captureOnCommitCallbacks(execute=True):
            user_login_failed.send(sender=type(self), credentials={'username': 'SECRET-NAME', 'password': 'SECRET-PASSWORD'})
        self.assertIn('auth.login_failed', str(logs.output))
        self.assertNotIn('SECRET-NAME', str(logs.output))
        self.assertNotIn('SECRET-PASSWORD', str(logs.output))
