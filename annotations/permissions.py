from rest_framework.permissions import BasePermission

from entitlements.services import user_has_book_entitlement, user_has_subscription
from library.models import BookVersion


class HasActiveBookEntitlementForAnnotation(BasePermission):
    """
    Protege o CRUD de anotações:
    - create: checa entitlement do book resolvido via book_version_id
    - retrieve/update/destroy: checa entitlement via obj.book_version.book_id
    A list será filtrada no queryset do ViewSet (pra não vazar por list).
    """

    message = 'Você não tem direito de acesso à esse livro.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if getattr(user, 'is_staff', False):
            return True

        action = getattr(view, 'action', None)

        # Para list/retrieve/update/destroy, a checagem forte fica no queryset e no object permission.
        if action != 'create':
            return True

        bv = request.data.get('book_version_id') or request.data.get('book_version')
        if not bv:
            return False

        try:
            bv_id = int(bv)
        except (TypeError, ValueError):
            return False

        try:
            book_id = BookVersion.objects.only('book_id').get(id=bv_id).book_id
        except BookVersion.DoesNotExist:
            return False

        if user_has_subscription(user):
            return True

        return user_has_book_entitlement(user, book_id)

    def has_object_permission(self, request, view, obj):
        user = request.user

        if getattr(user, 'is_staff', False):
            return True

        if user_has_subscription(user):
            return True

        book_id = getattr(obj.book_version, 'book_id', None)
        if not book_id:
            return False

        return user_has_book_entitlement(user, book_id)