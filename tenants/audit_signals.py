"""Record security-sensitive ORM changes under an authenticated request actor."""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from core.models import Grade, Homework, Payment, StudentEnrollment
from .models import SchoolMembership
from .audit import actor_context, audit_event


@receiver(post_save)
def record_security_change(sender, instance, created, raw=False, **kwargs):
    if raw or sender not in (SchoolMembership, Grade, Homework, Payment, StudentEnrollment):
        return
    actor = actor_context.get()
    if not actor or not getattr(actor, 'is_authenticated', False):
        return
    changes = {field: getattr(instance, field) for field in ('status', 'role', 'is_active', 'is_voided') if hasattr(instance, field)}
    audit_event('record.created' if created else 'record.updated', actor=actor,
        school_id=instance.school_id, model=sender.__name__, object_id=instance.pk, changes=changes)


@receiver(post_delete, sender=Homework)
@receiver(post_delete, sender=SchoolMembership)
def record_security_delete(sender, instance, **kwargs):
    actor = actor_context.get()
    if actor and getattr(actor, 'is_authenticated', False):
        audit_event('record.deleted', actor=actor, school_id=instance.school_id,
            model=sender.__name__, object_id=instance.pk)


from django.contrib.auth.signals import user_login_failed, user_logged_in, user_logged_out

@receiver(user_login_failed)
def failed_login(sender, **kwargs):
    # Deliberately ignore the credentials dictionary and request URL.
    audit_event('auth.login_failed')


@receiver(user_logged_in)
def successful_login(sender, user, **kwargs):
    audit_event('auth.login', actor=user, model='User', object_id=user.pk)


@receiver(user_logged_out)
def successful_logout(sender, user, **kwargs):
    if user and user.pk:
        audit_event('auth.logout', actor=user, model='User', object_id=user.pk)
