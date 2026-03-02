from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ModerationConfig
from .services import sync_banned_users_with_config


@receiver(post_save, sender=ModerationConfig)
def sync_banned_users_after_config_change(sender, instance, **kwargs):
    sync_banned_users_with_config(instance)
