from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import BasePermission

from entitlements.models import Entitlement

class HasActiveBookEntitlement(BasePermission):
    """
    MVP: acesso liberado se o usuário tiver entitlement ativo de:
    - book OU subscription
    """
    message = 'Você não tem direito de acesso à esse livro.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # staff/admin bypass (para teste)
        if getattr(user, 'is_staff', False):
            return True
        
        now = timezone.now()

        return (
            Entitlement.objects
            .filter(user=user, status=Entitlement.Status.ACTIVE)
            .filter(Q(product=Entitlement.Product.BOOK) | Q(product=Entitlement.Product.SUBSCRIPTION))
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .exists()
        )