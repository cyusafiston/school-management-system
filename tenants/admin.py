
from django.contrib import admin, messages
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline

from .models import School, SchoolMembership


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
    )

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

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        if change and "status" in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected schools")
    def approve_schools(self, request, queryset):
        count = queryset.update(
            status=School.Status.APPROVED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{count} school(s) approved.",
            messages.SUCCESS,
        )

    @admin.action(description="Reject selected schools")
    def reject_schools(self, request, queryset):
        count = queryset.update(
            status=School.Status.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{count} school(s) rejected.",
            messages.SUCCESS,
        )

    @admin.action(description="Suspend selected schools")
    def suspend_schools(self, request, queryset):
        count = queryset.update(
            status=School.Status.SUSPENDED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{count} school(s) suspended.",
            messages.SUCCESS,
        )


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
