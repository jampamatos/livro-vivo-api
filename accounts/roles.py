from __future__ import annotations

from .models import Profile


def _get_profile(user) -> Profile | None:
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    if profile is not None:
        return profile
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def get_user_role(user) -> str | None:
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'superuser'

    profile = _get_profile(user)
    if profile is None:
        return None
    return profile.role


def user_is_owner_or_superuser(user) -> bool:
    role = get_user_role(user)
    return role in {'superuser', Profile.Role.OWNER}


def user_is_moderator_or_above(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    role = get_user_role(user)
    return role in {Profile.Role.MODERATOR, Profile.Role.OWNER}
