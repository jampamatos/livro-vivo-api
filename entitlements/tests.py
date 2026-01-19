from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Entitlement

User = get_user_model()


class EntitlementModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )

    def test_is_active_with_no_expiry(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.BOOK,
            status=Entitlement.Status.ACTIVE,
        )

        self.assertTrue(entitlement.is_active())

    def test_is_active_with_future_expiry(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.SUBSCRIPTION,
            status=Entitlement.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(days=1),
        )

        self.assertTrue(entitlement.is_active())

    def test_is_active_with_past_expiry(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.BOOK,
            status=Entitlement.Status.ACTIVE,
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(entitlement.is_active())

    def test_is_active_with_revoked_status(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.BOOK,
            status=Entitlement.Status.REVOKED,
        )

        self.assertFalse(entitlement.is_active())
