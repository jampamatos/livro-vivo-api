from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Informações extras do usuário."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    full_name = models.CharField(max_length=150, blank=True)
    profession = models.CharField(max_length=120, blank=True)

    def __str__(self) -> str:
        return f"Profile(user_id={self.user_id})"
