from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from entitlements.models import Subscription

from .models import NotificationDispatch, NotificationEvent, NotificationPreference, PushDevice


logger = logging.getLogger('livro_vivo.notifications')


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
    pending_dispatches = list(
        NotificationDispatch.objects.filter(
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.PENDING,
            acknowledged_at__isnull=True,
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
