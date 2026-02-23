from rest_framework.permissions import BasePermission

from entitlements.services import active_entitlements_qs, user_has_subscription
from library.models import BookVersion


class HasActiveBookEntitlement(BasePermission):
    """
    Acesso liberado se o usuário tiver entitlement ativo
    - subscription (global) OU
    - book (escopado por book_id)
    """
    message = 'Você não tem direito de acesso à esse livro.'

    def _resolve_book_id(self, request, view) -> int | None:
        view_kwargs = getattr(view, "kwargs", {}) or {}
        book_id = view_kwargs.get("book_id")
        if book_id is not None:
            try:
                return int(book_id)
            except (TypeError, ValueError):
                return None

        qp = getattr(request, "query_params", {})
        if "book_id" in qp:
            try:
                return int(qp.get("book_id"))
            except (TypeError, ValueError):
                return None

        if "book_version_id" in qp:
            try:
                bvid = int(qp.get("book_version_id"))
            except (TypeError, ValueError):
                return None
            bv = BookVersion.objects.filter(id=bvid).only("id", "book_id").first()
            return bv.book_id if bv else None

        data = getattr(request, "data", {}) or {}
        if isinstance(data, dict):
            if "book_id" in data:
                try:
                    return int(data.get("book_id"))
                except (TypeError, ValueError):
                    return None
            if "book_version_id" in data:
                try:
                    bvid = int(data.get("book_version_id"))
                except (TypeError, ValueError):
                    return None
                bv = BookVersion.objects.filter(id=bvid).only("id", "book_id").first()
                return bv.book_id if bv else None

        return None

    def has_permission(self, request, view):
        """Permite acesso com entitlement ativo (ou staff)."""
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # staff/admin bypass (para teste)
        if getattr(user, 'is_staff', False):
            return True

        book_id = self._resolve_book_id(request, view)
        base = active_entitlements_qs(user)

        # subscription sempre libera
        if user_has_subscription(user):
            return True

        # se conseguimos resolver livro, exige entitlement daquele livro
        if book_id is not None:
            return base.filter(product='book', book_id=book_id).exists()

        # fallback (ex.: endpoints de list) - a VIEW tem que filtrar o queryset
        return base.filter(product='book').exists()
