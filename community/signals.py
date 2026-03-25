from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Comment, CommentLike, ModerationConfig, Post, PostLike
from .services import (
    ensure_post_follow,
    refresh_comment_public_metrics,
    refresh_post_public_metrics,
    sync_banned_users_with_config,
)


@receiver(post_save, sender=ModerationConfig)
def sync_banned_users_after_config_change(sender, instance, **kwargs):
    sync_banned_users_with_config(instance)


@receiver(post_save, sender=Post)
def ensure_author_follows_own_post(sender, instance, created, **kwargs):
    if not created:
        return
    ensure_post_follow(post=instance, user=instance.author)
    refresh_post_public_metrics(post=instance)


@receiver(post_save, sender=Comment)
def refresh_post_metrics_after_comment_save(sender, instance, **kwargs):
    refresh_post_public_metrics(post=instance.post_id)


@receiver(post_delete, sender=Comment)
def refresh_post_metrics_after_comment_delete(sender, instance, **kwargs):
    refresh_post_public_metrics(post=instance.post_id)


@receiver(post_save, sender=PostLike)
def refresh_post_metrics_after_post_like_save(sender, instance, **kwargs):
    refresh_post_public_metrics(post=instance.post_id)


@receiver(post_delete, sender=PostLike)
def refresh_post_metrics_after_post_like_delete(sender, instance, **kwargs):
    refresh_post_public_metrics(post=instance.post_id)


@receiver(post_save, sender=CommentLike)
def refresh_comment_metrics_after_comment_like_save(sender, instance, **kwargs):
    refresh_comment_public_metrics(comment=instance.comment_id)


@receiver(post_delete, sender=CommentLike)
def refresh_comment_metrics_after_comment_like_delete(sender, instance, **kwargs):
    refresh_comment_public_metrics(comment=instance.comment_id)
