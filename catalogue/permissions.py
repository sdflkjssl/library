from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import UserProfile


def is_reader(user):
    return (
        user.is_authenticated
        and hasattr(user, "profile")
        and user.profile.role == UserProfile.Role.READER
    )


def is_librarian(user):
    return (
        user.is_authenticated
        and (
            user.is_superuser
            or (
                hasattr(user, "profile")
                and user.profile.role == UserProfile.Role.LIBRARIAN
            )
        )
    )


def role_required(predicate):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")
            if not predicate(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


reader_required = role_required(is_reader)
librarian_required = role_required(is_librarian)
