from django.db.models import Q
from django.utils import timezone

from .models import Entitlement, Subscription


def active_entitlements_qs(user):
    """Queryset de entitlements ativos (status e expiração)."""
    now = timezone.now()
    return (
        Entitlement.objects
        .filter(user=user, status=Entitlement.Status.ACTIVE)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )


def _active_legacy_subscription_entitlements_qs(user):
    return active_entitlements_qs(user).filter(product=Entitlement.Product.SUBSCRIPTION)


def active_subscriptions_qs(user):
    """Queryset de assinaturas ativas/validas para cálculo de tier efetivo."""
    now = timezone.now()
    return (
        Subscription.objects
        .filter(user=user, status=Subscription.Status.ACTIVE)
        .filter(Q(started_at__isnull=True) | Q(started_at__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )


def get_effective_subscription(user):
    """
    Retorna a assinatura efetiva do usuário.

    Se houver mais de uma ativa (cenário anômalo), prioriza Profissional e,
    em seguida, o registro mais recente.
    """
    subscriptions = list(active_subscriptions_qs(user))
    if not subscriptions:
        return None

    def _sort_key(subscription: Subscription):
        return (
            1 if subscription.tier == Subscription.Tier.PROFESSIONAL else 0,
            subscription.updated_at,
            subscription.created_at,
        )

    return max(subscriptions, key=_sort_key)


def get_effective_tier(user) -> str | None:
    """
    Tier efetivo para autorização:
    - assinatura ativa -> tier da assinatura
    - fallback legado (entitlement subscription) -> essential
    """
    effective = get_effective_subscription(user)
    if effective:
        return effective.tier

    if _active_legacy_subscription_entitlements_qs(user).exists():
        return Subscription.Tier.ESSENTIAL

    return None


def user_has_subscription(user) -> bool:
    """Retorna True quando o usuário tem tier efetivo ativo."""
    return get_effective_tier(user) is not None


def user_is_founder(user) -> bool:
    """
    Marca founder do usuário.

    Compatibilidade: em legado, infere founder via `source` contendo
    "founder" ou "beta".
    """
    effective = get_effective_subscription(user)
    if effective:
        return bool(effective.is_founder)

    legacy_source_qs = _active_legacy_subscription_entitlements_qs(user).values_list('source', flat=True)
    for source in legacy_source_qs:
        normalized = (source or '').strip().lower()
        if 'founder' in normalized or 'beta' in normalized:
            return True
    return False


def get_subscription_snapshot(user) -> dict | None:
    """
    Retorno consolidado para /me/entitlements.

    Ordem:
    1) assinatura ativa (canônica)
    2) fallback legado de entitlement subscription (tier essential)
    3) última assinatura inativa/cancelada (status informativo)
    """
    effective = get_effective_subscription(user)
    if effective:
        return {
            'id': effective.id,
            'tier': effective.tier,
            'status': effective.status,
            'is_founder': bool(effective.is_founder),
            'expires_at': effective.expires_at,
            'source': effective.source,
            'is_legacy_fallback': False,
        }

    legacy = _active_legacy_subscription_entitlements_qs(user).order_by('-created_at').first()
    if legacy:
        return {
            'id': None,
            'tier': Subscription.Tier.ESSENTIAL,
            'status': Subscription.Status.ACTIVE,
            'is_founder': user_is_founder(user),
            'expires_at': legacy.expires_at,
            'source': legacy.source or 'legacy-entitlement',
            'is_legacy_fallback': True,
        }

    latest = Subscription.objects.filter(user=user).order_by('-updated_at', '-created_at').first()
    if latest:
        return {
            'id': latest.id,
            'tier': latest.tier,
            'status': latest.status,
            'is_founder': bool(latest.is_founder),
            'expires_at': latest.expires_at,
            'source': latest.source,
            'is_legacy_fallback': False,
        }

    return None


def entitled_book_ids(user) -> list[int]:
    """Retorna uma lista de book_id com entitlement ativo (product=BOOK)."""
    return list(
        active_entitlements_qs(user)
        .filter(product=Entitlement.Product.BOOK)
        .exclude(book_id__isnull=True)
        .values_list('book_id', flat=True)
        .distinct()
    )


def user_has_book_entitlement(user, book_id: int) -> bool:
    """Retorna True se o usuário tem entitlement ativo para um book_id específico."""
    return active_entitlements_qs(user).filter(product=Entitlement.Product.BOOK, book_id=book_id).exists()
