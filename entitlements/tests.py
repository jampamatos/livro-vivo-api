from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.test import TransactionTestCase
from django.utils import timezone

from library.models import Book

from .models import Entitlement

User = get_user_model()


class EntitlementModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        self.book = Book.objects.create(title='Livro de teste')

    def test_is_active_with_no_expiry(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.BOOK,
            book=self.book,
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
            book=self.book,
            status=Entitlement.Status.ACTIVE,
            expires_at=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(entitlement.is_active())

    def test_is_active_with_revoked_status(self):
        entitlement = Entitlement.objects.create(
            user=self.user,
            product=Entitlement.Product.BOOK,
            book=self.book,
            status=Entitlement.Status.REVOKED,
        )

        self.assertFalse(entitlement.is_active())

    def test_book_entitlement_requires_book_scope(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Entitlement.objects.create(
                    user=self.user,
                    product=Entitlement.Product.BOOK,
                    status=Entitlement.Status.ACTIVE,
                )

    def test_subscription_entitlement_must_not_target_specific_book(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Entitlement.objects.create(
                    user=self.user,
                    product=Entitlement.Product.SUBSCRIPTION,
                    book=self.book,
                    status=Entitlement.Status.ACTIVE,
                )


class EntitlementMigrationTests(TransactionTestCase):
    def _targets_with_entitlements(self, entitlements_migration: str):
        executor = MigrationExecutor(connection)
        targets = []
        for app_label, migration_name in executor.loader.graph.leaf_nodes():
            if app_label == 'entitlements':
                targets.append((app_label, entitlements_migration))
            else:
                targets.append((app_label, migration_name))
        return targets

    def test_legacy_book_entitlement_without_scope_is_normalized(self):
        old_targets = self._targets_with_entitlements('0002_entitlement_book_and_more')
        latest_targets = self._targets_with_entitlements('0004_entitlement_scope_constraint')

        MigrationExecutor(connection).migrate(old_targets)

        try:
            user = User.objects.create_user(
                username='legacy@example.com',
                email='legacy@example.com',
                password='StrongPass123',
            )
            now = timezone.now()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO entitlements_entitlement
                    (user_id, product, status, expires_at, source, created_at, updated_at, book_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [user.id, 'book', 'active', None, 'legacy-migration', now, now, None],
                )

            MigrationExecutor(connection).migrate(latest_targets)

            entitlement = Entitlement.objects.get(user=user, source='legacy-migration')
            self.assertEqual(entitlement.product, Entitlement.Product.SUBSCRIPTION)
            self.assertIsNone(entitlement.book_id)
        finally:
            MigrationExecutor(connection).migrate(latest_targets)
