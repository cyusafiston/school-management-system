"""OPT-IN ONLY. Importing validates configuration but does not connect services.

Do not switch WSGI/Render to this module without approval and readiness review.
"""
from .settings import *
from .pilot import validate_environment

_pilot = validate_environment(os.environ)
DEBUG = False
ALLOWED_HOSTS = _pilot['hosts']
ACCOUNT_PUBLIC_ORIGIN = _pilot['origin']
CSRF_TRUSTED_ORIGINS = [ACCOUNT_PUBLIC_ORIGIN]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# Enable only after the TLS/proxy chain is independently verified.
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if IS_RENDER else None
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PASSWORD_RESET_TIMEOUT = 3600
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_TIMEOUT = 15
MEDIA_ROOT = _pilot['media']
MEDIA_URL = '/private-documents/'  # No public route exists at this prefix.
STORAGES = {
    'default': {'BACKEND': 'core.private_storage.PrivateDocumentStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MIDDLEWARE = [*MIDDLEWARE, 'tenants.audit.AuditMiddleware', 'tenants.pilot_middleware.TenantWriteGuardMiddleware']
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact_http': {'()': 'tenants.audit.SafeOperationalFilter'}},
    'formatters': {'safe': {'format': '%(message)s'}},
    'handlers': {'safe_console': {'class': 'logging.StreamHandler', 'filters': ['redact_http'], 'formatter': 'safe'}},
    'loggers': {
        'sms': {'handlers': ['safe_console'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['safe_console'], 'level': 'WARNING', 'propagate': False},
        'django.security': {'handlers': ['safe_console'], 'level': 'WARNING', 'propagate': False},
        'django.server': {'handlers': ['safe_console'], 'level': 'WARNING', 'propagate': False},
        'tenants.admin_services': {'handlers': ['safe_console'], 'level': 'WARNING', 'propagate': False},
    },
}
