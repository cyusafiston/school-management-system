"""
Isolated settings for Academic Setup tests.

Never connect to the live Render PostgreSQL database.
"""

from .settings import *

# Override production database settings completely.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {
            "NAME": ":memory:",
        },
    }
}

# Prevent accidental database routing to another connection.
DATABASE_ROUTERS = []

# Use a local test-only secret.
SECRET_KEY = "academic-setup-local-test-only-secret-key"

# Never send email during tests.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable external cache dependencies.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Test client host.
ALLOWED_HOSTS = ["testserver", "localhost"]

DEBUG = False
