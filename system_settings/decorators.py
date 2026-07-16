from functools import wraps

from django.http import HttpResponseForbidden

from accounts.permissions import is_leadership


def leadership_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not is_leadership(request.user):
            return HttpResponseForbidden('Not allowed')
        return view_func(request, *args, **kwargs)

    return wrapped
