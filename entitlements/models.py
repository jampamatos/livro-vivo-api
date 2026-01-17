from django.conf import settings
from django.db import models
from django.utils import timezone

class Entitlement(models.Model):
    class Product(models.TextChoices):
        BOOK = 'book', 'Livro'
        SUBSCRIPTION = 'subscription', 'Assinatura'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        REVOKED = 'revoked', 'Revogado'
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='entitlements',
    )

    product = models.CharField(max_length=32, choices=Product.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)

    source = models.CharField(max_length=32, blank=True, default='') # ex: 'admin', 'import', 'payment'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_active(self) -> bool:
        if self.status != self.Status.ACTIVE:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()
    
    def __str__(self):
        return f"Entitlement(user_id={self.user_id}, product={self.product}, status={self.status})"

