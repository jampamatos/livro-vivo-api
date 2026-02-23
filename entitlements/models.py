from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

PRODUCT_BOOK = 'book'
PRODUCT_SUBSCRIPTION = 'subscription'
TIER_ESSENTIAL = 'essential'
TIER_PROFESSIONAL = 'professional'


class Subscription(models.Model):
    """Assinatura do usuário (tier + status), usada para entitlement global."""

    class Tier(models.TextChoices):
        ESSENTIAL = TIER_ESSENTIAL, 'Essencial'
        PROFESSIONAL = TIER_PROFESSIONAL, 'Profissional'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativa'
        INACTIVE = 'inactive', 'Inativa'
        CANCELED = 'canceled', 'Cancelada'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    tier = models.CharField(
        max_length=16,
        choices=Tier.choices,
        default=Tier.ESSENTIAL,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.INACTIVE,
    )
    is_founder = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32, blank=True, default='')  # ex: 'admin', 'payment', 'founder-beta'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(status='active'),
                name='unique_active_subscription_per_user',
            ),
        ]
        ordering = ['-updated_at', '-created_at']

    def is_active(self) -> bool:
        """Retorna True se a assinatura estiver ativa e dentro da janela de validade."""
        if self.status != self.Status.ACTIVE:
            return False
        now = timezone.now()
        if self.started_at is not None and self.started_at > now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True

    def __str__(self) -> str:
        return (
            f"Subscription(user_id={self.user_id}, tier={self.tier}, "
            f"status={self.status}, founder={self.is_founder})"
        )


class Entitlement(models.Model):
    """Direitos de acesso do usuário a produtos."""

    class Product(models.TextChoices):
        BOOK = PRODUCT_BOOK, 'Livro'
        SUBSCRIPTION = PRODUCT_SUBSCRIPTION, 'Assinatura'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        REVOKED = 'revoked', 'Revogado'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='entitlements',
    )

    book = models.ForeignKey(
        'library.Book',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='entitlements'
    )
    subscription = models.ForeignKey(
        'entitlements.Subscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='entitlements',
    )

    product = models.CharField(max_length=32, choices=Product.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(max_length=32, blank=True, default='')  # ex: 'admin', 'import', 'payment'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Subscription é global (book NULL) e pode ou não estar vinculada a Subscription.
            # Book entitlement precisa de book e não pode apontar para Subscription.
            models.CheckConstraint(
                name='entitlement_scope_matches_product',
                condition=Q(product=PRODUCT_SUBSCRIPTION, book__isnull=True)
                | Q(product=PRODUCT_BOOK, book__isnull=False, subscription__isnull=True),
            ),
        ]

    def is_active(self) -> bool:
        """Retorna True se o entitlement estiver ativo e não expirado."""
        if self.status != self.Status.ACTIVE:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()

    def __str__(self) -> str:
        return (f"Entitlement(user_id={self.user_id}, product={self.product}, "
                f"book_id={self.book_id}, status={self.status})")
