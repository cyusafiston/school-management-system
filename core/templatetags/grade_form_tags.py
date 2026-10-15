from django import template

register = template.Library()


@register.filter
def grade_cat_value(student, submitted_marks):
    key = f"cat_{student.pk}"
    if submitted_marks is not None and key in submitted_marks:
        return submitted_marks.get(key, "")
    grade = getattr(student, "grade", None)
    return grade.cat_marks if grade is not None else ""


@register.filter
def grade_exam_value(student, submitted_marks):
    key = f"exam_{student.pk}"
    if submitted_marks is not None and key in submitted_marks:
        return submitted_marks.get(key, "")
    grade = getattr(student, "grade", None)
    return grade.exam_marks if grade is not None else ""
