from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.db import OperationalError, ProgrammingError
from django.db.models import Q


OWNER_GROUP_NAME = 'Livro Vivo - Dono'

OWNER_PERMISSION_APP_LABELS = {
    'accounts',
    'annotations',
    'caselaw',
    'community',
    'courses',
    'entitlements',
    'library',
    'templates_bank',
}
OWNER_PERMISSION_ACTIONS = {'add', 'change', 'view'}


def _owner_permissions_queryset():
    codename_filter = Q()
    for action in OWNER_PERMISSION_ACTIONS:
        codename_filter |= Q(codename__startswith=f'{action}_')
    return Permission.objects.filter(
        codename_filter,
        content_type__app_label__in=OWNER_PERMISSION_APP_LABELS,
    )


def ensure_owner_group() -> Group | None:
    try:
        group, _ = Group.objects.get_or_create(name=OWNER_GROUP_NAME)
        group.permissions.set(_owner_permissions_queryset())
        return group
    except (OperationalError, ProgrammingError):
        return None


def sync_role_groups_for_user(user, *, role: str):
    from .models import Profile

    owner_group = ensure_owner_group()
    if owner_group is None:
        return

    if role == Profile.Role.OWNER:
        user.groups.add(owner_group)
    else:
        user.groups.remove(owner_group)


def sync_existing_owner_profiles():
    from .models import Profile

    owner_group = ensure_owner_group()
    if owner_group is None:
        return

    owner_profiles = Profile.objects.select_related('user').filter(role=Profile.Role.OWNER)
    for profile in owner_profiles.iterator():
        profile.user.groups.add(owner_group)
