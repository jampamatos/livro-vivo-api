from datetime import timedelta
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connections
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from community.models import ModerationConfig, UserModerationStatus

from .models import NotificationPreference, Profile
from .signals import cleanup_legacy_user_token_rows
from entitlements.models import Entitlement, Subscription
from library.models import Book

User = get_user_model()


class AccountsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_creates_user_profile_and_jwt(self):
        payload = {
            'email': 'Test@Example.com',
            'password': 'StrongPass123',
            'name': 'Test User',
            'profession': 'Writer',
        }

        response = self.client.post(reverse('auth-register'), payload, format='json')

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='test@example.com')
        profile = user.profile

        self.assertEqual(user.username, 'test@example.com')
        self.assertEqual(profile.full_name, 'Test User')
        self.assertEqual(profile.profession, 'Writer')
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertNotIn('token', response.data)
        refresh = RefreshToken(response.data['refresh'])
        self.assertEqual(int(refresh['user_id']), user.id)

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='StrongPass123',
        )
        payload = {
            'email': 'TEST@example.com',
            'password': 'StrongPass123',
        }

        response = self.client.post(reverse('auth-register'), payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)

    def test_owner_or_moderator_profile_promotes_user_to_staff(self):
        user = User.objects.create_user(
            username='owner@example.com',
            email='owner@example.com',
            password='StrongPass123',
            is_staff=False,
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = Profile.Role.OWNER
        profile.save()

        user.refresh_from_db()
        self.assertTrue(user.is_staff)

    def test_cleanup_legacy_user_token_rows_deletes_authtoken_entries(self):
        connection = connections['default']
        quoted_table = connection.ops.quote_name('authtoken_token')

        with mock.patch.object(connection.introspection, 'table_names', return_value=['authtoken_token']):
            with mock.patch.object(connection, 'cursor') as cursor_mock:
                cleanup_legacy_user_token_rows(user_id=42, using='default')

        cursor = cursor_mock.return_value.__enter__.return_value
        cursor.execute.assert_any_call(f'DELETE FROM {quoted_table} WHERE user_id = %s', [42])

    def test_login_success_returns_token(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'USER@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertNotIn('token', response.data)
        refresh = RefreshToken(response.data['refresh'])
        self.assertEqual(int(refresh['user_id']), user.id)

    def test_login_invalid_credentials_returns_401(self):
        User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'user@example.com', 'password': 'wrong'},
            format='json',
        )

        self.assertEqual(response.status_code, 401)

    def test_login_returns_pending_moderation_notice_and_clears_it(self):
        user = User.objects.create_user(
            username='warned@example.com',
            email='warned@example.com',
            password='StrongPass123',
        )
        UserModerationStatus.objects.create(
            user=user,
            pending_login_message='Aviso de moderação de teste',
            pending_login_message_level=UserModerationStatus.PendingLevel.WARNING,
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'warned@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('moderation_notice', response.data)
        self.assertEqual(response.data['moderation_notice']['message'], 'Aviso de moderação de teste')

        status_obj = UserModerationStatus.objects.get(user=user)
        self.assertEqual(status_obj.pending_login_message, '')
        self.assertIsNone(status_obj.pending_login_message_created_at)

    def test_login_returns_403_for_banned_user(self):
        user = User.objects.create_user(
            username='banned@example.com',
            email='banned@example.com',
            password='StrongPass123',
            is_active=False,
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.APP_WIDE,
            ban_reason='Reincidência em abuso',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'banned@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'account_banned')
        self.assertIn('Reincidência em abuso', response.data['detail'])

    def test_login_allows_community_only_ban_and_returns_notice(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.COMMUNITY_ONLY},
        )
        user = User.objects.create_user(
            username='communitybanned@example.com',
            email='communitybanned@example.com',
            password='StrongPass123',
            is_active=False,
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
            pending_login_message='Seu acesso à comunidade foi suspenso.',
            pending_login_message_level=UserModerationStatus.PendingLevel.DANGER,
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'communitybanned@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertEqual(
            response.data['moderation_notice']['message'],
            'Seu acesso à comunidade foi suspenso.',
        )
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_login_uses_current_global_ban_scope_for_already_banned_user(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.APP_WIDE},
        )
        user = User.objects.create_user(
            username='scopeoverride@example.com',
            email='scopeoverride@example.com',
            password='StrongPass123',
            is_active=True,
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
            ban_reason='Escopo deve seguir config global',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'scopeoverride@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'account_banned')

    def test_login_requires_email_and_password(self):
        response = self.client.post(
            reverse('auth-login'),
            {'email': '', 'password': ''},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'email e password são obrigatórios.')

    def test_login_fallback_authenticates_when_username_differs_from_email(self):
        user = User.objects.create_user(
            username='custom-username',
            email='user@example.com',
            password='StrongPass123',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'user@example.com', 'password': 'StrongPass123'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        refresh = RefreshToken(response.data['refresh'])
        self.assertEqual(int(refresh['user_id']), user.id)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 401)

    def test_me_returns_profile_and_creates_if_missing(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(response.data['email'], 'user@example.com')
        self.assertEqual(response.data['name'], '')
        self.assertEqual(response.data['profession'], '')

    def test_me_accepts_jwt_bearer_token(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'user@example.com')

    def test_me_notification_preferences_get_creates_defaults(self):
        user = User.objects.create_user(
            username='pref@example.com',
            email='pref@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.get(reverse('me-notification-preferences'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['notifications_enabled'])
        self.assertTrue(response.data['book_version_updates_enabled'])
        self.assertTrue(response.data['new_content_updates_enabled'])
        self.assertTrue(response.data['push_enabled'])
        self.assertTrue(NotificationPreference.objects.filter(user=user).exists())

    def test_me_notification_preferences_patch_updates_values(self):
        user = User.objects.create_user(
            username='prefpatch@example.com',
            email='prefpatch@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me-notification-preferences'),
            {
                'notifications_enabled': True,
                'book_version_updates_enabled': False,
                'new_content_updates_enabled': True,
                'push_enabled': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['book_version_updates_enabled'])
        self.assertFalse(response.data['push_enabled'])

        preference = NotificationPreference.objects.get(user=user)
        self.assertTrue(preference.notifications_enabled)
        self.assertFalse(preference.book_version_updates_enabled)
        self.assertTrue(preference.new_content_updates_enabled)
        self.assertFalse(preference.push_enabled)

    def test_auth_refresh_rotates_and_blacklists_old_refresh(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        old_refresh = str(RefreshToken.for_user(user))

        response = self.client.post(
            reverse('auth-refresh'),
            {'refresh': old_refresh},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

        replay = self.client.post(
            reverse('auth-refresh'),
            {'refresh': old_refresh},
            format='json',
        )
        self.assertEqual(replay.status_code, 401)

    def test_logout_requires_refresh_field(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(reverse('auth-logout'), {}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'Token de refresh é obrigatório.')

    def test_logout_blacklists_refresh_and_is_idempotent_for_invalid_token(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        refresh_obj = RefreshToken.for_user(user)
        refresh = str(refresh_obj)
        access = str(refresh_obj.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        first = self.client.post(reverse('auth-logout'), {'refresh': refresh}, format='json')
        self.assertEqual(first.status_code, 204)

        replay = self.client.post(
            reverse('auth-refresh'),
            {'refresh': refresh},
            format='json',
        )
        self.assertEqual(replay.status_code, 401)

        invalid = self.client.post(
            reverse('auth-logout'),
            {'refresh': 'invalid-refresh-token'},
            format='json',
        )
        self.assertEqual(invalid.status_code, 204)

    def test_me_entitlements_returns_sorted_list(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='StrongPass123',
        )
        book = Book.objects.create(title='Livro de teste')
        other_book = Book.objects.create(title='Livro de outro usuário')

        older = Entitlement.objects.create(
            user=user,
            product=Entitlement.Product.BOOK,
            book=book,
            status=Entitlement.Status.ACTIVE,
            expires_at=timezone.now() + timedelta(days=7),
            source='test',
        )
        newer = Entitlement.objects.create(
            user=user,
            product=Entitlement.Product.SUBSCRIPTION,
            status=Entitlement.Status.REVOKED,
            source='test',
        )
        Entitlement.objects.create(
            user=other_user,
            product=Entitlement.Product.BOOK,
            book=other_book,
            status=Entitlement.Status.ACTIVE,
        )

        Entitlement.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
        Entitlement.objects.filter(pk=newer.pk).update(created_at=timezone.now() - timedelta(days=1))

        response = self.client.get(reverse('me-entitlements'))

        self.assertEqual(response.status_code, 200)
        items = response.data['entitlements']
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], newer.id)
        self.assertEqual(items[1]['id'], older.id)
        self.assertFalse(items[0]['is_active'])
        self.assertIn('subscription_id', items[0])
        self.assertIn('tier', items[0])
        self.assertIn('is_founder', items[0])
        self.assertIsNone(response.data['effective_tier'])
        self.assertIsNone(response.data['subscription'])

    def test_me_entitlements_includes_effective_subscription_snapshot(self):
        user = User.objects.create_user(
            username='tiered@example.com',
            email='tiered@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        subscription = Subscription.objects.create(
            user=user,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            is_founder=True,
            source='founder-beta',
        )
        Entitlement.objects.create(
            user=user,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='admin',
        )

        response = self.client.get(reverse('me-entitlements'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['moderation']['is_banned'], False)

    def test_me_entitlements_includes_moderation_summary(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.COMMUNITY_ONLY},
        )
        user = User.objects.create_user(
            username='modsummary@example.com',
            email='modsummary@example.com',
            password='StrongPass123',
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
            warnings_issued=2,
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.get(reverse('me-entitlements'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['moderation']['is_banned'], True)
        self.assertEqual(response.data['moderation']['ban_scope'], 'community_only')
        self.assertEqual(response.data['moderation']['community_access'], False)
        self.assertEqual(response.data['moderation']['app_access'], True)
        self.assertEqual(response.data['moderation']['warnings_issued'], 2)

    def test_me_entitlements_uses_current_global_ban_scope_for_summary(self):
        config, _ = ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.APP_WIDE},
        )
        user = User.objects.create_user(
            username='modscope@example.com',
            email='modscope@example.com',
            password='StrongPass123',
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
            warnings_issued=1,
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        first_response = self.client.get(reverse('me-entitlements'))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.data['moderation']['ban_scope'], 'app_wide')
        self.assertEqual(first_response.data['moderation']['community_access'], False)
        self.assertEqual(first_response.data['moderation']['app_access'], False)

        config.ban_scope = ModerationConfig.BanScope.COMMUNITY_ONLY
        config.save()

        second_response = self.client.get(reverse('me-entitlements'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.data['moderation']['ban_scope'], 'community_only')
        self.assertEqual(second_response.data['moderation']['community_access'], False)
        self.assertEqual(second_response.data['moderation']['app_access'], True)

    def test_login_is_throttled(self):
        cache.clear()
        User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'auth_login': '1/min'}):
            first = self.client.post(
                reverse('auth-login'),
                {'email': 'user@example.com', 'password': 'StrongPass123'},
                format='json',
            )
            second = self.client.post(
                reverse('auth-login'),
                {'email': 'user@example.com', 'password': 'StrongPass123'},
                format='json',
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_register_is_throttled(self):
        cache.clear()
        payload = {
            'email': 'user@example.com',
            'password': 'StrongPass123',
        }

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'auth_register': '1/min'}):
            first = self.client.post(reverse('auth-register'), payload, format='json')
            second = self.client.post(
                reverse('auth-register'),
                {'email': 'another@example.com', 'password': 'StrongPass123'},
                format='json',
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class HealthAndReadinessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_healthz_returns_ok(self):
        response = self.client.get('/healthz/')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['app'], 'livro-vivo-api')
        self.assertIn('version', payload)

    def test_readyz_returns_ok_when_dependencies_respond(self):
        response = self.client.get('/readyz/')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['checks']['database'], 'ok')
        self.assertEqual(payload['checks']['cache'], 'ok')

    def test_readyz_returns_degraded_when_database_fails(self):
        with mock.patch('config.urls.connection.cursor', side_effect=RuntimeError('db-down')):
            response = self.client.get('/readyz/')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload['status'], 'degraded')
        self.assertIn('error', payload['checks']['database'])

    def test_readyz_returns_degraded_when_cache_fails(self):
        with mock.patch('config.urls.cache.get', return_value=None):
            response = self.client.get('/readyz/')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload['status'], 'degraded')
        self.assertEqual(payload['checks']['cache'], 'error')
