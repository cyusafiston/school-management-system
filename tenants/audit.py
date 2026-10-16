"""Allowlisted security events: no passwords, tokens, URLs, names or email bodies."""
import json
import logging
from contextvars import ContextVar

from django.db import transaction

actor_context = ContextVar('audit_actor', default=None)
logger = logging.getLogger('sms.security')
FIELDS = {'status', 'role', 'is_active', 'is_voided', 'school_id', 'user_id'}


def audit_event(event, *, actor=None, school_id=None, model='', object_id=None, changes=None):
    actor = actor or actor_context.get()
    data = {'event': event, 'actor_id': getattr(actor, 'pk', None), 'school_id': school_id,
            'model': model, 'object_id': object_id}
    if changes:
        data['changes'] = {k: v for k, v in changes.items() if k in FIELDS}
    # Existing Django admin log provides transactional, database-backed history.
    if actor and actor.pk:
        from django.contrib.admin.models import LogEntry, CHANGE
        LogEntry.objects.create(user_id=actor.pk, object_id=str(object_id or ''),
            object_repr=f'{model}:{object_id}', action_flag=CHANGE,
            change_message=json.dumps(data, sort_keys=True))
    transaction.on_commit(lambda: logger.info(json.dumps(data, sort_keys=True)))


class SafeOperationalFilter(logging.Filter):
    """Prevent Django request/exception representations from exposing reset URLs."""
    def filter(self, record):
        if record.name.startswith(('django.request', 'django.security', 'django.server')):
            record.msg = 'HTTP security/error event; inspect redacted monitoring and request ID.'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
            record.__dict__.pop('request', None)
        return True


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import time
        import uuid
        start = time.monotonic()
        request_id = uuid.uuid4().hex
        user = getattr(request, 'user', None)
        token = actor_context.set(user if getattr(user, 'is_authenticated', False) else None)
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = request_id
            match = getattr(request, 'resolver_match', None)
            logging.getLogger('sms.operations').info(json.dumps({
                'event': 'http_response', 'request_id': request_id,
                'route': getattr(match, 'url_name', None), 'status': response.status_code,
                'duration_ms': round((time.monotonic()-start)*1000),
            }, sort_keys=True))
            return response
        finally:
            actor_context.reset(token)
