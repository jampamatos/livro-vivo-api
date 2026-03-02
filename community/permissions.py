from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.exceptions import PermissionDenied

from accounts.roles import user_is_moderator_or_above, user_is_owner_or_superuser
from .services import user_is_banned_from_community


class IsStaffOrReadOnlyAuthed(BasePermission):
    """
    - GET/HEAD/OPTIONS> precisa estar autenticado
    - Write: apenas staff
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and (
            request.user.is_staff or user_is_owner_or_superuser(request.user)
        ))

class IsOwnerOrStaff(BasePermission):
    """
    Object-level: autor do objeto (obj.author) ou staff
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(
            user and user.is_authenticated and (
                getattr(obj, 'author_id', None) == user.id
                or user.is_staff
                or user_is_owner_or_superuser(user)
            )
        )


class IsModeratorOrAbove(BasePermission):
    def has_permission(self, request, view):
        return bool(user_is_moderator_or_above(request.user))


class IsNotCommunityBanned(BasePermission):
    message = 'Seu acesso à comunidade foi suspenso pela moderação.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return True
        if user_is_moderator_or_above(user):
            return True
        if user_is_banned_from_community(user):
            raise PermissionDenied(self.message)
        return True
