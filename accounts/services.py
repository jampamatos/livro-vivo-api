from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from annotations.models import Annotation
from community.models import Comment as CommunityComment
from community.models import Post as CommunityPost
from community.models import Report
from entitlements.models import Entitlement, Subscription

from .models import (
    DataPrivacyRequest,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
)


logger = logging.getLogger('livro_vivo.notifications')

COMMUNITY_RETENTION_POLICY = (
    'Posts, comentários e denúncias da comunidade são preservados por requisito de moderação e '
    'integridade operacional. A identificação pessoal fica reduzida à conta anonimizada.'
)


def _serialize_profile_for_export(*, user, profile: Profile) -> dict:
    return {
        'id': user.id,
        'email': user.email,
        'username': user.username,
        'is_active': user.is_active,
        'full_name': profile.full_name,
        'profession': profile.profession,
        'avatar_url': (
            profile.avatar.url
            if getattr(profile, 'avatar', None)
            else getattr(profile, 'avatar_url', '') or ''
        ),
        'role': profile.role,
    }


def _serialize_subscription_for_export(subscription: Subscription | None) -> dict | None:
    if subscription is None:
        return None
    return {
        'id': subscription.id,
        'tier': subscription.tier,
        'status': subscription.status,
        'is_founder': subscription.is_founder,
        'started_at': subscription.started_at,
        'expires_at': subscription.expires_at,
        'source': subscription.source,
        'created_at': subscription.created_at,
        'updated_at': subscription.updated_at,
    }


def _delete_profile_avatar_file(*, user_id: int, avatar_storage, avatar_name: str) -> None:
    if not avatar_storage or not avatar_name:
        return

    try:
        avatar_storage.delete(avatar_name)
    except Exception:
        logger.exception(
            'profile_avatar_delete_failed_after_erasure',
            extra={'user_id': user_id},
        )


def _scrub_push_devices_for_erasure(*, user, anonymized_suffix: str) -> int:
    scrubbed_devices = 0
    for device in PushDevice.objects.filter(user=user).order_by('id'):
        device.is_active = False
        device.disabled_reason = 'lgpd_erasure_request'
        device.expo_push_token = f'erased-device-{user.pk}-{device.pk}-{anonymized_suffix}'
        device.save(
            update_fields=[
                'is_active',
                'disabled_reason',
                'expo_push_token',
                'last_seen_at',
                'updated_at',
            ]
        )
        scrubbed_devices += 1
    return scrubbed_devices


def create_user_data_export_package(*, user) -> dict:
    profile, _ = Profile.objects.get_or_create(user=user)
    notification_preference, _ = NotificationPreference.objects.get_or_create(user=user)

    subscriptions = list(
        Subscription.objects.filter(user=user)
        .order_by('-updated_at', '-created_at')
    )
    entitlements = list(
        Entitlement.objects.filter(user=user)
        .select_related('book', 'subscription')
        .order_by('-created_at')
    )
    annotations = list(
        Annotation.objects.filter(user=user)
        .select_related('book_version__book', 'chapter')
        .order_by('-updated_at', '-created_at')
    )
    community_posts = list(
        CommunityPost.objects.filter(author=user)
        .select_related('category')
        .order_by('-created_at')
    )
    community_comments = list(
        CommunityComment.objects.filter(author=user)
        .order_by('-created_at')
    )
    community_reports = list(
        Report.objects.filter(reporter=user)
        .order_by('-created_at')
    )

    export_payload = {
        'generated_at': timezone.now(),
        'profile': _serialize_profile_for_export(user=user, profile=profile),
        'subscription': _serialize_subscription_for_export(subscriptions[0] if subscriptions else None),
        'subscriptions': [_serialize_subscription_for_export(item) for item in subscriptions],
        'entitlements': [
            {
                'id': entitlement.id,
                'product': entitlement.product,
                'status': entitlement.status,
                'book_id': entitlement.book_id,
                'book_title': entitlement.book.title if entitlement.book_id else '',
                'subscription_id': entitlement.subscription_id,
                'expires_at': entitlement.expires_at,
                'source': entitlement.source,
                'created_at': entitlement.created_at,
                'updated_at': entitlement.updated_at,
            }
            for entitlement in entitlements
        ],
        'annotations': [
            {
                'id': annotation.id,
                'book_id': annotation.book_version.book_id,
                'book_title': annotation.book_version.book.title,
                'book_version_id': annotation.book_version_id,
                'book_version': annotation.book_version.version,
                'chapter_id': annotation.chapter_id,
                'chapter_title': annotation.chapter.title,
                'selector': annotation.selector,
                'start_offset': annotation.start_offset,
                'end_offset': annotation.end_offset,
                'excerpt': annotation.excerpt,
                'note': annotation.note,
                'color': annotation.color,
                'created_at': annotation.created_at,
                'updated_at': annotation.updated_at,
            }
            for annotation in annotations
        ],
        'activity': {
            'community_posts': [
                {
                    'id': post.id,
                    'title': post.title,
                    'category': post.category.slug if post.category_id else '',
                    'moderation_state': post.moderation_state,
                    'created_at': post.created_at,
                    'updated_at': post.updated_at,
                }
                for post in community_posts
            ],
            'community_comments': [
                {
                    'id': comment.id,
                    'post_id': comment.post_id,
                    'moderation_state': comment.moderation_state,
                    'created_at': comment.created_at,
                    'updated_at': comment.updated_at,
                }
                for comment in community_comments
            ],
            'community_reports': [
                {
                    'id': report.id,
                    'post_id': report.post_id,
                    'comment_id': report.comment_id,
                    'reason': report.reason,
                    'status': report.status,
                    'priority': report.priority,
                    'decision': report.decision,
                    'created_at': report.created_at,
                    'updated_at': report.updated_at,
                }
                for report in community_reports
            ],
        },
        'notification_preferences': {
            'notifications_enabled': notification_preference.notifications_enabled,
            'book_version_updates_enabled': notification_preference.book_version_updates_enabled,
            'new_content_updates_enabled': notification_preference.new_content_updates_enabled,
            'community_interaction_updates_enabled': notification_preference.community_interaction_updates_enabled,
            'push_enabled': notification_preference.push_enabled,
            'updated_at': notification_preference.updated_at,
        },
        'retention_policy': {
            'community': COMMUNITY_RETENTION_POLICY,
        },
    }

    DataPrivacyRequest.objects.create(
        user=user,
        request_type=DataPrivacyRequest.RequestType.EXPORT,
        status=DataPrivacyRequest.Status.COMPLETED,
        retention_policy=COMMUNITY_RETENTION_POLICY,
        payload={
            'summary': {
                'subscriptions': len(subscriptions),
                'entitlements': len(entitlements),
                'annotations': len(annotations),
                'community_posts': len(community_posts),
                'community_comments': len(community_comments),
                'community_reports': len(community_reports),
            }
        },
        processed_at=timezone.now(),
    )

    return export_payload


def request_user_data_erasure(*, user, reason: str = '') -> dict:
    now = timezone.now()
    anonymized_suffix = now.strftime('%Y%m%d%H%M%S')

    with transaction.atomic():
        privacy_request = DataPrivacyRequest.objects.create(
            user=user,
            request_type=DataPrivacyRequest.RequestType.ERASURE,
            status=DataPrivacyRequest.Status.REQUESTED,
            retention_policy=COMMUNITY_RETENTION_POLICY,
            payload={'reason': (reason or '').strip()},
        )

        profile, _ = Profile.objects.get_or_create(user=user)
        notification_preferences, _ = NotificationPreference.objects.get_or_create(user=user)

        deleted_annotations, _ = Annotation.objects.filter(user=user).delete()
        scrubbed_push_devices = _scrub_push_devices_for_erasure(
            user=user,
            anonymized_suffix=anonymized_suffix,
        )
        revoked_entitlements = Entitlement.objects.filter(
            user=user,
            status=Entitlement.Status.ACTIVE,
        ).update(
            status=Entitlement.Status.REVOKED,
            expires_at=now,
            updated_at=now,
        )
        deactivated_subscriptions = Subscription.objects.filter(
            user=user,
            status=Subscription.Status.ACTIVE,
        ).update(
            status=Subscription.Status.INACTIVE,
            expires_at=now,
            updated_at=now,
        )

        notification_preferences.notifications_enabled = False
        notification_preferences.book_version_updates_enabled = False
        notification_preferences.new_content_updates_enabled = False
        notification_preferences.community_interaction_updates_enabled = False
        notification_preferences.push_enabled = False
        notification_preferences.save(
            update_fields=[
                'notifications_enabled',
                'book_version_updates_enabled',
                'new_content_updates_enabled',
                'community_interaction_updates_enabled',
                'push_enabled',
                'updated_at',
            ]
        )

        user.username = f'deleted-user-{user.pk}-{anonymized_suffix}'
        user.email = f'deleted+{user.pk}-{anonymized_suffix}@anon.livrovivo.local'
        user.first_name = ''
        user.last_name = ''
        user.is_active = False
        user.is_staff = False
        user.is_superuser = False
        user.set_unusable_password()
        user.save(
            update_fields=[
                'username',
                'email',
                'first_name',
                'last_name',
                'is_active',
                'is_staff',
                'is_superuser',
                'password',
            ]
        )

        avatar_storage = profile.avatar.storage if profile.avatar and profile.avatar.name else None
        avatar_name = profile.avatar.name if profile.avatar and profile.avatar.name else ''
        profile.full_name = 'Conta anonimizada'
        profile.profession = ''
        profile.role = Profile.Role.MEMBER
        profile.avatar = None
        profile.avatar_url = ''
        profile.save(update_fields=['full_name', 'profession', 'role', 'avatar', 'avatar_url'])
        _delete_profile_avatar_file(
            user_id=user.id,
            avatar_storage=avatar_storage,
            avatar_name=avatar_name,
        )

        privacy_request.status = DataPrivacyRequest.Status.COMPLETED
        privacy_request.processed_at = now
        privacy_request.payload = {
            'reason': (reason or '').strip(),
            'actions': {
                'annotations_deleted_total': deleted_annotations,
                'push_devices_deactivated_total': scrubbed_push_devices,
                'push_devices_scrubbed_total': scrubbed_push_devices,
                'entitlements_revoked_total': revoked_entitlements,
                'subscriptions_deactivated_total': deactivated_subscriptions,
                'community_posts_retained_total': CommunityPost.objects.filter(author=user).count(),
                'community_comments_retained_total': CommunityComment.objects.filter(author=user).count(),
                'community_reports_retained_total': Report.objects.filter(reporter=user).count(),
            },
        }
        privacy_request.save(update_fields=['status', 'processed_at', 'payload'])

    return {
        'request_id': privacy_request.id,
        'status': privacy_request.status,
        'processed_at': privacy_request.processed_at,
        'retention_policy': COMMUNITY_RETENTION_POLICY,
    }


def get_active_subscription_user_ids(*, tiers: Iterable[str] | None = None) -> list[int]:
    now = timezone.now()
    subscriptions = (
        Subscription.objects.filter(status=Subscription.Status.ACTIVE)
        .filter(Q(started_at__isnull=True) | Q(started_at__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )
    if tiers:
        subscriptions = subscriptions.filter(tier__in=list(tiers))

    return list(subscriptions.values_list('user_id', flat=True).distinct())


def get_active_push_devices_for_user_ids(*, user_ids: Iterable[int]) -> list[PushDevice]:
    normalized_user_ids = sorted({int(user_id) for user_id in user_ids if user_id})
    if not normalized_user_ids:
        return []
    return list(
        PushDevice.objects.filter(user_id__in=normalized_user_ids, is_active=True)
        .exclude(expo_push_token='')
        .order_by('user_id', '-last_seen_at')
    )


def enqueue_notification_event(
    *,
    event_type: str,
    dedup_key: str,
    title: str,
    body: str = '',
    payload: dict | None = None,
    recipient_user_ids: Iterable[int] | None = None,
    preference_field: str | None = None,
    preference_disabled_reason: str = '',
) -> NotificationEvent | None:
    if not getattr(settings, 'NOTIFICATIONS_ENABLED', True):
        logger.info('notification_event_skipped', extra={'reason': 'notifications_disabled_global'})
        return None

    normalized_user_ids = sorted(
        {int(user_id) for user_id in (recipient_user_ids or []) if user_id}
    )
    if not normalized_user_ids:
        logger.info(
            'notification_event_skipped',
            extra={'reason': 'no_recipients', 'event_type': event_type, 'dedup_key': dedup_key},
        )
        return None

    event, created = NotificationEvent.objects.get_or_create(
        dedup_key=dedup_key,
        defaults={
            'event_type': event_type,
            'title': (title or '').strip(),
            'body': (body or '').strip(),
            'payload': payload or {},
        },
    )
    if not created:
        logger.info(
            'notification_event_dedup_hit',
            extra={'event_type': event_type, 'dedup_key': dedup_key, 'event_id': event.pk},
        )
        return event

    preference_by_user_id = {
        preference.user_id: preference
        for preference in NotificationPreference.objects.filter(user_id__in=normalized_user_ids)
    }

    pending_count = 0
    skipped_count = 0

    for user_id in normalized_user_ids:
        preference = preference_by_user_id.get(user_id)
        notifications_enabled = preference.notifications_enabled if preference is not None else True
        push_enabled = preference.push_enabled if preference is not None else True
        domain_enabled = (
            getattr(preference, preference_field)
            if preference is not None and preference_field
            else True
        )

        base_status = NotificationDispatch.Status.PENDING
        base_reason = ''
        if not notifications_enabled:
            base_status = NotificationDispatch.Status.SKIPPED
            base_reason = 'notifications_disabled'
        elif preference_field and not domain_enabled:
            base_status = NotificationDispatch.Status.SKIPPED
            base_reason = preference_disabled_reason or f'{preference_field}_disabled'

        in_app_status = base_status
        in_app_reason = base_reason
        push_status = base_status
        push_reason = base_reason
        if push_status == NotificationDispatch.Status.PENDING and not push_enabled:
            push_status = NotificationDispatch.Status.SKIPPED
            push_reason = 'push_disabled'

        for channel, status, reason in (
            (NotificationDispatch.Channel.IN_APP, in_app_status, in_app_reason),
            (NotificationDispatch.Channel.PUSH, push_status, push_reason),
        ):
            if status == NotificationDispatch.Status.PENDING:
                pending_count += 1
            else:
                skipped_count += 1

            NotificationDispatch.objects.get_or_create(
                event=event,
                user_id=user_id,
                channel=channel,
                defaults={
                    'status': status,
                    'reason': reason,
                },
            )

    logger.info(
        'notification_event_enqueued',
        extra={
            'event_type': event.event_type,
            'event_id': event.pk,
            'dedup_key': event.dedup_key,
            'recipient_count': len(normalized_user_ids),
            'pending_count': pending_count,
            'skipped_count': skipped_count,
        },
    )

    if pending_count and getattr(settings, 'PUSH_AUTODISPATCH_ENABLED', True):
        try:
            dispatch_pending_push_notifications(limit=200)
        except Exception:
            logger.exception(
                'notification_push_dispatch_failed_after_enqueue',
                extra={'event_id': event.pk, 'dedup_key': event.dedup_key},
            )

    return event


def _send_expo_push_messages(messages: list[dict]) -> list[dict]:
    if not messages:
        return []

    url = getattr(settings, 'EXPO_PUSH_API_URL', 'https://exp.host/--/api/v2/push/send')
    access_token = getattr(settings, 'EXPO_PUSH_ACCESS_TOKEN', '')
    headers = {
        'Accept': 'application/json',
        'Accept-encoding': 'gzip, deflate',
        'Content-Type': 'application/json',
    }
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'

    payload = json.dumps(messages).encode('utf-8')
    request = urllib_request.Request(url, data=payload, headers=headers, method='POST')

    try:
        with urllib_request.urlopen(request, timeout=15) as response:
            body = response.read().decode('utf-8')
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Expo push API HTTP {exc.code}: {error_body}') from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f'Expo push API indisponível: {exc.reason}') from exc

    parsed = json.loads(body or '{}')
    if parsed.get('errors'):
        raise RuntimeError(f"Expo push API retornou erros: {parsed['errors']}")
    return parsed.get('data', [])


def dispatch_pending_push_notifications(*, limit: int = 100) -> dict[str, int]:
    active_device_user_ids = PushDevice.objects.filter(is_active=True).exclude(
        expo_push_token=''
    ).values_list('user_id', flat=True).distinct()

    pending_dispatches = list(
        NotificationDispatch.objects.filter(
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.PENDING,
            acknowledged_at__isnull=True,
            user_id__in=active_device_user_ids,
        )
        .select_related('event', 'user')
        .order_by('created_at')[:limit]
    )
    if not pending_dispatches:
        return {'queued': 0, 'sent': 0, 'failed': 0, 'devices': 0}

    devices_by_user_id: dict[int, list[PushDevice]] = defaultdict(list)
    for device in get_active_push_devices_for_user_ids(user_ids=[dispatch.user_id for dispatch in pending_dispatches]):
        devices_by_user_id[device.user_id].append(device)

    messages: list[dict] = []
    message_refs: list[tuple[NotificationDispatch, PushDevice]] = []
    for dispatch in pending_dispatches:
        for device in devices_by_user_id.get(dispatch.user_id, []):
            messages.append(
                {
                    'to': device.expo_push_token,
                    'title': dispatch.event.title or 'Livro Vivo',
                    'body': dispatch.event.body or '',
                    'data': {
                        'dispatch_id': dispatch.id,
                        'event_type': dispatch.event.event_type,
                        **(dispatch.event.payload or {}),
                    },
                    'sound': 'default',
                }
            )
            message_refs.append((dispatch, device))

    if not messages:
        return {'queued': len(pending_dispatches), 'sent': 0, 'failed': 0, 'devices': 0}

    responses = _send_expo_push_messages(messages)
    now = timezone.now()
    sent_dispatch_ids: set[int] = set()
    failed_dispatch_ids: set[int] = set()
    failed_reasons_by_dispatch_id: dict[int, str] = {}
    devices_to_deactivate: list[int] = []

    for (dispatch, device), response in zip(message_refs, responses, strict=False):
        if response.get('status') == 'ok':
            sent_dispatch_ids.add(dispatch.id)
            continue

        failed_dispatch_ids.add(dispatch.id)
        details = response.get('details') or {}
        error_reason = details.get('error') or response.get('message') or 'expo_push_failed'
        failed_reasons_by_dispatch_id[dispatch.id] = str(error_reason)
        if error_reason == 'DeviceNotRegistered':
            devices_to_deactivate.append(device.id)

    if devices_to_deactivate:
        PushDevice.objects.filter(id__in=devices_to_deactivate).update(
            is_active=False,
            disabled_reason='device_not_registered',
        )

    if sent_dispatch_ids:
        NotificationDispatch.objects.filter(id__in=sent_dispatch_ids).update(
            status=NotificationDispatch.Status.SENT,
            dispatched_at=now,
            updated_at=now,
        )

    failed_dispatch_ids -= sent_dispatch_ids
    for dispatch_id in failed_dispatch_ids:
        NotificationDispatch.objects.filter(id=dispatch_id).update(
            status=NotificationDispatch.Status.FAILED,
            reason=failed_reasons_by_dispatch_id.get(dispatch_id, 'expo_push_failed'),
            updated_at=now,
        )

    logger.info(
        'notification_push_dispatch_processed',
        extra={
            'queued': len(pending_dispatches),
            'sent': len(sent_dispatch_ids),
            'failed': len(failed_dispatch_ids),
            'devices': len(messages),
        },
    )

    return {
        'queued': len(pending_dispatches),
        'sent': len(sent_dispatch_ids),
        'failed': len(failed_dispatch_ids),
        'devices': len(messages),
    }
