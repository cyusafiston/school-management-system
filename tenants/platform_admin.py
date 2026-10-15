
"""Platform-only access policy for Django's existing admin site."""

from django.contrib import admin


def platform_admin_has_permission(request):
    """Allow only authenticated, active platform superusers."""
    user = request.user

    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_superuser
        and user.is_staff
    )


def configure_platform_admin():
    """Apply the platform-only policy to the existing Django admin site."""
    admin.site.has_permission = platform_admin_has_permission
