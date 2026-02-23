from django.db import migrations
from django.db.models import Q
from django.utils import timezone


def _is_founder_source(value):
    normalized = (value or '').strip().lower()
    return 'founder' in normalized or 'beta' in normalized


def forwards(apps, schema_editor):
    Entitlement = apps.get_model('entitlements', 'Entitlement')
    Subscription = apps.get_model('entitlements', 'Subscription')

    now = timezone.now()
    user_ids = (
        Entitlement.objects
        .filter(product='subscription')
        .values_list('user_id', flat=True)
        .distinct()
    )

    for user_id in user_ids:
        ents_qs = Entitlement.objects.filter(user_id=user_id, product='subscription').order_by('-created_at')
        latest = ents_qs.first()
        if latest is None:
            continue

        active_entitlement = (
            ents_qs
            .filter(status='active')
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .first()
        )

        subscription = (
            Subscription.objects
            .filter(user_id=user_id)
            .order_by('-updated_at', '-created_at')
            .first()
        )

        if subscription is None:
            source_entitlement = active_entitlement or latest
            subscription = Subscription.objects.create(
                user_id=user_id,
                tier='essential',
                status='active' if active_entitlement else 'inactive',
                is_founder=_is_founder_source(source_entitlement.source),
                expires_at=source_entitlement.expires_at,
                source=(source_entitlement.source or 'legacy-entitlement'),
            )

        ents_qs.filter(subscription__isnull=True).update(subscription_id=subscription.id)


def backwards(apps, schema_editor):
    Entitlement = apps.get_model('entitlements', 'Entitlement')
    Entitlement.objects.filter(product='subscription').update(subscription_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ('entitlements', '0005_subscription_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
