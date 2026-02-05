from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsStaffOrReadOnlyAuthed(BasePermission):
    """
    - GET/HEAD/OPTIONS> precisa estar autenticado
    - Write: apenas staff
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)

class IsOwnerOrStaff(BasePermission):
    """
    Object-level: autor do objeto (obj.author) ou staff
    """
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and (getattr(obj, 'author_id', None) == user.id or user.is_staff))