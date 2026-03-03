from __future__ import annotations

from django.utils.text import Truncator

from accounts.models import NotificationEvent
from accounts.services import enqueue_notification_event, get_active_subscription_user_ids
from entitlements.models import Subscription

from .models import CaseLaw


def enqueue_caselaw_publication_notifications(*, caselaw: CaseLaw) -> NotificationEvent | None:
    if not caselaw or not caselaw.pk:
        return None

    return enqueue_notification_event(
        event_type=NotificationEvent.EventType.CASELAW_PUBLISHED,
        dedup_key=f'caselaw-published:{caselaw.pk}',
        title=f'Nova jurisprudência: {caselaw.court} {caselaw.case_number}',
        body=Truncator((caselaw.ementa_plain or '').strip()).chars(180),
        payload={
            'caselaw_id': caselaw.pk,
            'court': caselaw.court,
            'case_number': caselaw.case_number,
            'decision_date': caselaw.decision_date.isoformat() if caselaw.decision_date else None,
            'url': caselaw.url,
        },
        recipient_user_ids=get_active_subscription_user_ids(tiers=[Subscription.Tier.PROFESSIONAL]),
        preference_field='new_content_updates_enabled',
        preference_disabled_reason='new_content_disabled',
    )
