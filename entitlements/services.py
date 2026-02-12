from django.db.models import Q
from django.utils import timezone

from .models import Entitlement

def active_entitlements_qs(user):
    """
    Queryset de entitlements ativos (status e expiração)
    """
    now = timezone.now()
    return(
        Entitlement.objects
          .filter(user=user, status=Entitlement.Status.ACTIVE)
          .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )

def user_has_subscription(user) -> bool:
    """
    Retorna true se o usuário tem entitlement ativo de subscription
    """
    return active_entitlements_qs(user).filter(product=Entitlement.Product.SUBSCRIPTION).exists()

def entitled_book_ids(user) -> list[int]:
    """
    Retorna uma lista de book_id com entitlement ativo (product=BOOK)
    """
    return list(
        active_entitlements_qs(user)
          .filter(product=Entitlement.Product.BOOK)
          .exclude(book_id__isnull=True)
          .values_list('book_id', flat=True)
          .distinct()
    )

def user_has_book_entitlement(user, book_id: int) -> bool:
    """
    Retorna true se o usuário tem entitlement ativo para um book_id específico.
    """
    return active_entitlements_qs(user).filter(product=Entitlement.Product.BOOK, book_id=book_id).exists()