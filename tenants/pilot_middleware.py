"""Serialize tenant writes with lifecycle changes in the opt-in pilot profile."""
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.urls import resolve, Resolver404
from .access import require_school_context
from .models import School


class TenantWriteGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public = {'login', 'logout', 'register_school', 'password_reset', 'password_reset_done',
                  'password_reset_confirm', 'password_reset_complete', 'health_live'}
        try:
            route = resolve(request.path_info).url_name
        except Resolver404:
            return self.get_response(request)
        user = request.user
        if (request.method in ('GET', 'HEAD', 'OPTIONS') or route in public or
                not user.is_authenticated or user.is_superuser):
            return self.get_response(request)
        context = require_school_context(user)
        with transaction.atomic():
            school = School.objects.select_for_update().get(pk=context.school.pk)
            # Read membership again after acquiring the lifecycle lock.
            if school.status != 'approved':
                raise PermissionDenied('School access is unavailable.')
            require_school_context(user)
            response = self.get_response(request)
            if response.status_code >= 400:
                transaction.set_rollback(True)
            return response
