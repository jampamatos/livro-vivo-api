from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

PRODUCT_BOOK = 'book'
PRODUCT_SUBSCRIPTION = 'subscription'


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

    product = models.CharField(max_length=32, choices=Product.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(max_length=32, blank=True, default='')  # ex: 'admin', 'import', 'payment'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Subscription pode ser global (book NULL).
            # Book entitlements precisa ter book preenchido.
            models.CheckConstraint(
                name='entitlement_scope_matches_product',
                condition=Q(product=PRODUCT_SUBSCRIPTION, book__isnull=True)
                | Q(product=PRODUCT_BOOK, book__isnull=False),
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
