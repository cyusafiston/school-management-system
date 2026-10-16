from pathlib import Path
import os
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .access import require_school_context, require_school_role
from .platform_services import require_operator


@require_GET
def liveness(request):
    return JsonResponse({'status': 'alive'})


@login_required
@require_GET
def readiness(request):
    require_operator(request.user)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            database = cursor.fetchone() == (1,)
    except Exception:
        database = False
    root = Path(settings.MEDIA_ROOT)
    storage = root.is_dir() and os.access(root, os.R_OK | os.W_OK)
    ready = database and storage
    response = JsonResponse({'status': 'ready' if ready else 'not_ready',
        'database': database, 'storage_accessible': storage}, status=200 if ready else 503)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_GET
def setup_checklist(request):
    from core.models import Term, ClassStream, Subject, ClassSubject, TeacherAssignment, StudentProfile
    from .models import SchoolMembership
    context = require_school_context(request.user)
    require_school_role(context, 'administrator')
    school = context.school
    term = Term.objects.filter(school=school, academic_year__school=school, is_current=True).first()
    steps = [
        ('Current academic year and term', bool(term), 'admin_periods'),
        ('Classes', ClassStream.objects.filter(school=school).exists(), 'academic_setup'),
        ('Subjects', Subject.objects.filter(school=school).exists(), 'academic_setup'),
        ('Current-year curriculum', bool(term and ClassSubject.objects.filter(school=school,
            academic_year=term.academic_year, class_stream__school=school, subject__school=school).exists()), 'curriculum_management'),
        ('Active teacher', SchoolMembership.objects.filter(school=school, role='teacher', is_active=True, user__is_active=True).exists(), 'admin_staff'),
        ('Current-term teacher assignments', bool(term and TeacherAssignment.objects.filter(school=school,
            term=term, current_class__school=school, subject__school=school).exists()), 'teacher_assignment_management'),
        ('Enrolled students', bool(term and StudentProfile.objects.filter(school=school,
            enrollments__school=school, enrollments__term=term, enrollments__status='Active').exists()), 'admin_students'),
    ]
    return render(request, 'tenants/setup_checklist.html', {'school': school, 'steps': steps,
        'complete': all(item[1] for item in steps)})
