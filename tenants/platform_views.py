from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .models import School
from .platform_services import require_operator, transition_school


@login_required
@require_http_methods(['GET', 'POST'])
def schools(request):
    require_operator(request.user)
    if request.method == 'POST':
        if request.POST.get('confirm') != 'yes':
            return HttpResponseBadRequest('Confirm the school lifecycle action.')
        raw = request.POST.get('school_id', '')
        if not raw.isdecimal():
            return HttpResponseBadRequest('Select a school.')
        school = get_object_or_404(School, pk=int(raw))
        try:
            transition_school(actor=request.user, school_id=school.pk,
                action=request.POST.get('action'), request=request)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
        else:
            messages.success(request, 'School status updated. Historical records were preserved.')
        return redirect('platform_schools')
    return render(request, 'tenants/platform_schools.html', {'schools': School.objects.select_related('created_by', 'reviewed_by')})
