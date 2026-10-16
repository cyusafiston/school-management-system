
from django.contrib import admin, messages
from unfold.admin import ModelAdmin, TabularInline

from .models import School, SchoolMembership
from .platform_services import transition_school
from django.core.exceptions import ValidationError


class SchoolMembershipInline(TabularInline):
    model = SchoolMembership
    extra = 0

    fields = ("user", "role", "is_active", "joined_at")
    readonly_fields = ("joined_at",)


@admin.register(School)
class SchoolAdmin(ModelAdmin):
    list_display = (
        "name",
        "slug",
        "status",
        "email",
        "created_at",
        "reviewed_at",
    )

    list_filter = ("status", "created_at")
    search_fields = ("name", "slug", "email")
    ordering = ("-created_at",)

    readonly_fields = (
        "status",
        "created_by",
        "reviewed_by",
        "created_at",
        "reviewed_at",
    )

    prepopulated_fields = {"slug": ("name",)}

    inlines = [SchoolMembershipInline]

    actions = (
        "approve_schools",
        "reject_schools",
        "suspend_schools",
        "reactivate_schools",
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False  # Use the validated public application workflow.

    def has_delete_permission(self, request, obj=None):
        return False  # Suspend rather than erase school history.

    def lifecycle(self, request, queryset, action):
        for school_id in queryset.values_list('pk', flat=True):
            try:
                transition_school(actor=request.user, school_id=school_id, action=action, request=request)
            except ValidationError as exc:
                self.message_user(request, ' '.join(exc.messages), messages.ERROR)
            else:
                self.message_user(request, 'School lifecycle action completed.', messages.SUCCESS)

    @admin.action(description="Approve pending schools")
    def approve_schools(self, request, queryset):
        self.lifecycle(request, queryset, 'approve')

    @admin.action(description="Reject pending schools")
    def reject_schools(self, request, queryset):
        self.lifecycle(request, queryset, 'reject')

    @admin.action(description="Suspend approved schools")
    def suspend_schools(self, request, queryset):
        self.lifecycle(request, queryset, 'suspend')

    @admin.action(description="Reactivate suspended schools")
    def reactivate_schools(self, request, queryset):
        self.lifecycle(request, queryset, 'reactivate')


@admin.register(SchoolMembership)
class SchoolMembershipAdmin(ModelAdmin):
    list_display = (
        "user",
        "school",
        "role",
        "is_active",
        "joined_at",
    )

    list_filter = ("role", "is_active", "school")
    search_fields = (
        "user__username",
        "user__email",
        "school__name",
    )

    readonly_fields = ("joined_at",)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser
