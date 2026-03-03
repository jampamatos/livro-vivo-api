from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ModerationConfig, Post
from .services import ensure_post_follow, sync_banned_users_with_config


@receiver(post_save, sender=ModerationConfig)
def sync_banned_users_after_config_change(sender, instance, **kwargs):
    sync_banned_users_with_config(instance)


@receiver(post_save, sender=Post)
def ensure_author_follows_own_post(sender, instance, created, **kwargs):
    if not created:
        return
    ensure_post_follow(post=instance, user=instance.author)
