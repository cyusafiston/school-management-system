from django import template

register = template.Library()

@register.filter(name='get_item')
def get_item(dictionary, key):
    if dictionary and key:
        return dictionary.get(int(key)) or dictionary.get(str(key))
    return None