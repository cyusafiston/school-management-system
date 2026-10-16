"""Synthetic-only, loopback-only PostgreSQL test configuration; never DATABASE_URL."""
from .settings_academic_test import *
from django.core.exceptions import ImproperlyConfigured

if os.environ.get('SMS_SYNTHETIC_POSTGRES_ONLY') != 'yes':
    raise ImproperlyConfigured('Explicit SMS_SYNTHETIC_POSTGRES_ONLY=yes acknowledgment required.')
_test_host = os.environ.get('SMS_TEST_PGHOST', '127.0.0.1')
if _test_host not in ('127.0.0.1', '::1'):
    raise ImproperlyConfigured('Only numeric loopback hosts are allowed for synthetic PostgreSQL tests.')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'sms_pilot_synthetic',
    'USER': os.environ.get('SMS_TEST_PGUSER', 'sms_pilot_test'),
    'PASSWORD': os.environ.get('SMS_TEST_PGPASSWORD', ''),
    'HOST': _test_host, 'PORT': os.environ.get('SMS_TEST_PGPORT', '15432'),
    'CONN_MAX_AGE': 0,
    'OPTIONS': {'connect_timeout': 5, 'options': '-c statement_timeout=15000 -c lock_timeout=10000'},
    'TEST': {'NAME': 'test_sms_pilot_synthetic'},
}}
DATABASE_ROUTERS = []
