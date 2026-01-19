from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from entitlements.models import Entitlement

User = get_user_model()


class AccountsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_creates_user_profile_and_token(self):
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
        token = Token.objects.get(user=user)

        self.assertEqual(user.username, 'test@example.com')
        self.assertEqual(profile.full_name, 'Test User')
        self.assertEqual(profile.profession, 'Writer')
        self.assertEqual(response.data['token'], token.key)

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
        token = Token.objects.get(user=user)
        self.assertEqual(response.data['token'], token.key)

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

    def test_me_requires_authentication(self):
        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 401)

    def test_me_returns_profile_and_creates_if_missing(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(hasattr(user, 'profile'))
        self.assertEqual(response.data['email'], 'user@example.com')
        self.assertEqual(response.data['name'], '')
        self.assertEqual(response.data['profession'], '')

    def test_me_entitlements_returns_sorted_list(self):
        user = User.objects.create_user(
            username='user@example.com',
            email='user@example.com',
            password='StrongPass123',
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='StrongPass123',
        )

        older = Entitlement.objects.create(
            user=user,
            product=Entitlement.Product.BOOK,
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
