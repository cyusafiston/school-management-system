"""Pure validation for opt-in pilot settings. Never connects to any service."""
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from django.core.exceptions import ImproperlyConfigured


def validate_environment(env):
    def require(name):
        value = env.get(name, '').strip()
        if not value:
            raise ImproperlyConfigured(f'{name} must be configured for the pilot.')
        return value
    secret = require('DJANGO_SECRET_KEY')
    if len(secret) < 50 or secret.startswith('fallback-'):
        raise ImproperlyConfigured('Use a dedicated random pilot secret of at least 50 characters.')
    if env.get('DEBUG', 'False').lower() != 'false':
        raise ImproperlyConfigured('Pilot DEBUG must be False.')
    origin = require('ACCOUNT_PUBLIC_ORIGIN')
    parsed = urlparse(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ImproperlyConfigured('ACCOUNT_PUBLIC_ORIGIN must be a single HTTPS origin.')
    hosts = [value.strip() for value in require('ALLOWED_HOSTS').split(',') if value.strip()]
    if not hosts or any('*' in host or '/' in host or ':' in host for host in hosts) or parsed.hostname not in hosts:
        raise ImproperlyConfigured('Use explicit ALLOWED_HOSTS including the account origin host.')
    db = urlparse(require('DATABASE_URL'))
    if db.scheme not in ('postgres', 'postgresql') or not db.hostname or not db.path.strip('/'):
        raise ImproperlyConfigured('Pilot DATABASE_URL must identify an approved PostgreSQL database.')
    if parse_qs(db.query, keep_blank_values=True).get('sslmode') != ['verify-full']:
        raise ImproperlyConfigured('Pilot PostgreSQL must verify TLS identity (sslmode=verify-full).')
    media = Path(require('PILOT_PRIVATE_MEDIA_ROOT'))
    if not media.is_absolute() or media == Path('/'):
        raise ImproperlyConfigured('Private media requires an absolute dedicated mounted-volume path.')
    if env.get('PILOT_DURABLE_MEDIA_CONFIRMED') != 'yes':
        raise ImproperlyConfigured('Confirm private media uses an approved persistent mount, not ephemeral disk.')
    require('EMAIL_HOST')
    require('EMAIL_HOST_USER')
    require('EMAIL_HOST_PASSWORD')
    sender = require('DEFAULT_FROM_EMAIL')
    from email.utils import parseaddr
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    try:
        address = parseaddr(sender)[1]
        validate_email(address)
        if address.lower().endswith('.local'):
            raise ValidationError('Local sender')
    except ValidationError:
        raise ImproperlyConfigured('Configure a deliverable verified sender.') from None
    tls = env.get('EMAIL_USE_TLS', 'True').lower() == 'true'
    ssl = env.get('EMAIL_USE_SSL', 'False').lower() == 'true'
    if tls == ssl:
        raise ImproperlyConfigured('Choose exactly one SMTP encryption mode: TLS or SSL.')
    try:
        if not 1 <= int(env.get('EMAIL_PORT', '587')) <= 65535:
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured('EMAIL_PORT must be a valid port.') from None
    return {'hosts': hosts, 'origin': origin.rstrip('/'), 'media': str(media)}
