from datetime import timedelta
import hashlib
import io
import json
import os
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connections, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from PIL import Image

from annotations.models import Annotation
from caselaw.models import CaseLaw
from community.models import (
    Category,
    Comment as CommunityComment,
    ModerationConfig,
    Post as CommunityPost,
    PostFollow,
    Report,
    UserModerationStatus,
)
from courses.models import CourseAsset, CoursePost, LiveEvent, PublicationStatus
from config.storage import build_media_reference

from .models import (
    DataPrivacyRequest,
    ExternalIdentity,
    LegalDocumentVersion,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
    UserLegalAcceptance,
)
from .services import dispatch_pending_push_notifications, enqueue_notification_event
from .signals import cleanup_legacy_user_token_rows
from .view_helpers import authenticate_user_by_email, serialize_user_payload
from entitlements.models import Entitlement, Subscription
from library.models import Book, BookChapter, BookVersion

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

    def test_register_duplicate_email_returns_generic_error(self):
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
        self.assertNotIn('email', response.data)
        self.assertEqual(
            response.data['detail'],
            'Nao foi possivel concluir o cadastro com os dados informados.',
        )

    def test_register_rejects_weak_password(self):
        response = self.client.post(
            reverse('auth-register'),
            {'email': 'fraco@example.com', 'password': '12345678'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.data)

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

    def test_member_profile_revokes_staff_from_non_superuser(self):
        user = User.objects.create_user(
            username='member@example.com',
            email='member@example.com',
            password='StrongPass123',
            is_staff=True,
            is_superuser=False,
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = Profile.Role.MEMBER
        profile.save()

        user.refresh_from_db()
        self.assertFalse(user.is_staff)

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

    def test_login_for_banned_user_with_wrong_password_stays_generic(self):
        user = User.objects.create_user(
            username='banned-wrong@example.com',
            email='banned-wrong@example.com',
            password='StrongPass123',
            is_active=False,
        )
        UserModerationStatus.objects.create(
            user=user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.APP_WIDE,
            ban_reason='Motivo interno',
        )

        response = self.client.post(
            reverse('auth-login'),
            {'email': 'banned-wrong@example.com', 'password': 'senha-incorreta'},
            format='json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['detail'], 'Credenciais inválidas.')

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
        self.assertEqual(response.data['detail'], 'Email e senha são obrigatórios.')

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
        self.assertIsNone(response.data['avatar_url'])
        self.assertEqual(response.data['avatar_source'], 'none')
        self.assertNotIn('avatar_storage_alias', response.data)
        self.assertNotIn('avatar_storage_backend', response.data)
        self.assertNotIn('avatar_storage_key', response.data)
        self.assertNotIn('avatar_cache_control', response.data)

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

    def test_me_patch_updates_profile_fields_and_avatar_url(self):
        user = User.objects.create_user(
            username='patch@example.com',
            email='patch@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me'),
            {
                'name': 'Jampa Matos',
                'profession': 'Advogado',
                'avatar_url': 'https://example.com/avatar.jpg',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.profile.full_name, 'Jampa Matos')
        self.assertEqual(user.profile.profession, 'Advogado')
        self.assertEqual(user.profile.avatar_url, 'https://example.com/avatar.jpg')
        self.assertEqual(response.data['name'], 'Jampa Matos')
        self.assertEqual(response.data['profession'], 'Advogado')
        self.assertEqual(response.data['avatar_url'], 'https://example.com/avatar.jpg')
        self.assertEqual(response.data['avatar_source'], 'remote_url')
        self.assertNotIn('avatar_storage_key', response.data)
        self.assertNotIn('avatar_storage_backend', response.data)

    def test_me_patch_rejects_avatar_url_with_unsupported_scheme(self):
        user = User.objects.create_user(
            username='patch-avatar-url-invalid@example.com',
            email='patch-avatar-url-invalid@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me'),
            {
                'avatar_url': 'ftp://example.com/avatar.jpg',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar_url', response.data)
        self.assertIn('HTTPS', str(response.data['avatar_url'][0]))

    def test_me_patch_rejects_insecure_remote_http_avatar_url(self):
        user = User.objects.create_user(
            username='patch-avatar-url-http@example.com',
            email='patch-avatar-url-http@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me'),
            {
                'avatar_url': 'http://example.com/avatar.jpg',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar_url', response.data)
        self.assertIn('HTTPS fora de ambiente local', str(response.data['avatar_url'][0]))

    def test_me_patch_accepts_avatar_upload_and_returns_absolute_url(self):
        user = User.objects.create_user(
            username='patch-upload@example.com',
            email='patch-upload@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        Image.new('RGB', (8, 8), color='#1D4ED8').save(image_buffer, format='PNG')
        image_bytes = image_buffer.getvalue()

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-upload-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.patch(
                    reverse('me'),
                    {
                        'name': 'Jampa Matos',
                        'profession': 'Advogado',
                        'avatar': SimpleUploadedFile(
                            'avatar.png',
                            image_bytes,
                            content_type='image/png',
                        ),
                    },
                    format='multipart',
                )

                self.assertEqual(response.status_code, 200)
                user.refresh_from_db()
                self.assertEqual(user.profile.full_name, 'Jampa Matos')
                self.assertEqual(user.profile.profession, 'Advogado')
                self.assertEqual(user.profile.avatar_url, '')
                self.assertTrue(bool(user.profile.avatar))
                self.assertIn('/media/avatars/', response.data['avatar_url'])
                self.assertTrue(response.data['avatar_url'].startswith('http://testserver/media/avatars/'))
                self.assertEqual(response.data['avatar_source'], 'upload')
                self.assertNotIn('avatar_storage_alias', response.data)
                self.assertNotIn('avatar_storage_backend', response.data)
                self.assertNotIn('avatar_storage_key', response.data)

    def test_me_patch_rejects_avatar_with_invalid_type(self):
        user = User.objects.create_user(
            username='patch-invalid-type@example.com',
            email='patch-invalid-type@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        Image.new('RGB', (8, 8), color='#1D4ED8').save(image_buffer, format='GIF')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-invalid-type-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar.gif',
                            image_buffer.getvalue(),
                            content_type='image/gif',
                        ),
                    },
                    format='multipart',
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar', response.data)
        self.assertIn('JPG, PNG ou WEBP', str(response.data['avatar'][0]))

    def test_me_patch_rejects_avatar_too_large(self):
        user = User.objects.create_user(
            username='patch-too-large@example.com',
            email='patch-too-large@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        Image.new('RGB', (8, 8), color='#1D4ED8').save(image_buffer, format='PNG')
        image_bytes = image_buffer.getvalue()

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-too-large-') as media_root:
            with self.settings(MEDIA_ROOT=media_root, AVATAR_MAX_UPLOAD_BYTES=max(1, len(image_bytes) - 1)):
                response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar.png',
                            image_bytes,
                            content_type='image/png',
                        ),
                    },
                    format='multipart',
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar', response.data)
        self.assertIn('no máximo', str(response.data['avatar'][0]))

    def test_me_patch_rejects_avatar_with_excessive_source_dimensions(self):
        user = User.objects.create_user(
            username='patch-dimension-limit@example.com',
            email='patch-dimension-limit@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        Image.new('RGB', (64, 64), color='#1D4ED8').save(image_buffer, format='PNG')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-dimension-limit-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                with mock.patch('accounts.serializers._avatar_max_source_pixels', return_value=1024):
                    response = self.client.patch(
                        reverse('me'),
                        {
                            'avatar': SimpleUploadedFile(
                                'avatar.png',
                                image_buffer.getvalue(),
                                content_type='image/png',
                            ),
                        },
                        format='multipart',
                    )

        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar', response.data)
        self.assertIn('dimensões maiores', str(response.data['avatar'][0]))

    def test_me_patch_accepts_cropped_avatar_upload(self):
        user = User.objects.create_user(
            username='patch-crop@example.com',
            email='patch-crop@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        image = Image.new('RGB', (400, 200), color='#DC2626')
        for x in range(200, 400):
            for y in range(0, 200):
                image.putpixel((x, y), (29, 78, 216))
        image.save(image_buffer, format='PNG')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-crop-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar.png',
                            image_buffer.getvalue(),
                            content_type='image/png',
                        ),
                        'avatar_crop_x': 200,
                        'avatar_crop_y': 0,
                        'avatar_crop_size': 200,
                    },
                    format='multipart',
                )

                self.assertEqual(response.status_code, 200)
                user.refresh_from_db()
                with Image.open(user.profile.avatar.path) as stored:
                    self.assertEqual(stored.size, (200, 200))
                    self.assertEqual(stored.getpixel((100, 100)), (29, 78, 216))

    def test_me_patch_rejects_avatar_crop_without_upload(self):
        user = User.objects.create_user(
            username='patch-crop-invalid@example.com',
            email='patch-crop-invalid@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me'),
            {
                'avatar_crop_x': 10,
                'avatar_crop_y': 10,
                'avatar_crop_size': 120,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('non_field_errors', response.data)

    def test_me_patch_avatar_clear_removes_existing_avatar_reference(self):
        user = User.objects.create_user(
            username='patch-clear@example.com',
            email='patch-clear@example.com',
            password='StrongPass123',
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.avatar_url = 'https://example.com/avatar-antigo.jpg'
        profile.save(update_fields=['avatar_url'])

        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.patch(
            reverse('me'),
            {
                'avatar_clear': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.profile.avatar_url, '')
        self.assertIsNone(response.data['avatar_url'])

    def test_me_patch_replaces_avatar_and_deletes_old_file(self):
        user = User.objects.create_user(
            username='patch-replace@example.com',
            email='patch-replace@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        first_image = io.BytesIO()
        Image.new('RGB', (16, 16), color='#1D4ED8').save(first_image, format='PNG')
        second_image = io.BytesIO()
        Image.new('RGB', (16, 16), color='#DC2626').save(second_image, format='PNG')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-replace-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                first_response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar-1.png',
                            first_image.getvalue(),
                            content_type='image/png',
                        ),
                    },
                    format='multipart',
                )
                self.assertEqual(first_response.status_code, 200)
                user.refresh_from_db()
                first_avatar_path = user.profile.avatar.path
                self.assertTrue(os.path.exists(first_avatar_path))

                second_response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar-2.png',
                            second_image.getvalue(),
                            content_type='image/png',
                        ),
                    },
                    format='multipart',
                )
                self.assertEqual(second_response.status_code, 200)
                user.refresh_from_db()
                self.assertTrue(bool(user.profile.avatar))
                self.assertNotEqual(user.profile.avatar.path, first_avatar_path)
                self.assertFalse(os.path.exists(first_avatar_path))
                self.assertTrue(os.path.exists(user.profile.avatar.path))

    def test_me_patch_avatar_url_replaces_uploaded_avatar_and_deletes_old_file(self):
        user = User.objects.create_user(
            username='patch-avatar-url@example.com',
            email='patch-avatar-url@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        image_buffer = io.BytesIO()
        Image.new('RGB', (16, 16), color='#1D4ED8').save(image_buffer, format='PNG')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-url-replace-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                upload_response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar': SimpleUploadedFile(
                            'avatar.png',
                            image_buffer.getvalue(),
                            content_type='image/png',
                        ),
                    },
                    format='multipart',
                )
                self.assertEqual(upload_response.status_code, 200)
                user.refresh_from_db()
                avatar_path = user.profile.avatar.path
                self.assertTrue(os.path.exists(avatar_path))

                url_response = self.client.patch(
                    reverse('me'),
                    {
                        'avatar_url': 'https://example.com/avatar-final.jpg',
                    },
                    format='json',
                )
                self.assertEqual(url_response.status_code, 200)
                user.refresh_from_db()
                self.assertFalse(bool(user.profile.avatar))
                self.assertEqual(user.profile.avatar_url, 'https://example.com/avatar-final.jpg')
                self.assertFalse(os.path.exists(avatar_path))

    def test_profile_delete_removes_avatar_file(self):
        user = User.objects.create_user(
            username='profile-delete@example.com',
            email='profile-delete@example.com',
            password='StrongPass123',
        )
        profile, _ = Profile.objects.get_or_create(user=user)

        image_buffer = io.BytesIO()
        Image.new('RGB', (16, 16), color='#1D4ED8').save(image_buffer, format='PNG')

        with tempfile.TemporaryDirectory(prefix='accounts-avatar-profile-delete-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                profile.avatar = SimpleUploadedFile(
                    'avatar.png',
                    image_buffer.getvalue(),
                    content_type='image/png',
                )
                profile.save(update_fields=['avatar'])
                avatar_path = profile.avatar.path
                self.assertTrue(os.path.exists(avatar_path))

                profile.delete()

                self.assertFalse(os.path.exists(avatar_path))

    def test_me_change_password_updates_credentials(self):
        user = User.objects.create_user(
            username='password@example.com',
            email='password@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-change-password'),
            {
                'current_password': 'StrongPass123',
                'new_password': 'SenhaNovaForte456',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['detail'], 'Senha atualizada com sucesso.')
        user.refresh_from_db()
        self.assertTrue(user.check_password('SenhaNovaForte456'))

    def test_me_change_password_rejects_invalid_current_password(self):
        user = User.objects.create_user(
            username='wrong-password@example.com',
            email='wrong-password@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-change-password'),
            {
                'current_password': 'senha-incorreta',
                'new_password': 'SenhaNovaForte456',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('current_password', response.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password('StrongPass123'))

    def test_me_data_export_returns_profile_subscription_annotations_and_activity(self):
        user = User.objects.create_user(
            username='export@example.com',
            email='export@example.com',
            password='StrongPass123',
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.full_name = 'Usuário Exportação'
        profile.profession = 'Advogado'
        profile.save()

        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        book = Book.objects.create(title='Livro de Exportação', status=Book.Status.PUBLISHED)
        book_version = BookVersion.objects.create(
            book=book,
            version='2026.01',
            status=BookVersion.Status.PUBLISHED,
        )
        chapter = BookChapter.objects.create(
            book_version=book_version,
            order=1,
            title='Capítulo LGPD',
            slug='cap-lgpd',
            content_rich='<p>Conteúdo</p>',
        )
        Annotation.objects.create(
            user=user,
            book_version=book_version,
            chapter=chapter,
            selector={'type': 'range'},
            start_offset=0,
            end_offset=8,
            excerpt='Conteúdo',
            note='Minha nota',
            color='yellow',
        )

        subscription = Subscription.objects.create(
            user=user,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            source='test',
        )
        Entitlement.objects.create(
            user=user,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='test',
        )

        category = Category.objects.create(name='LGPD', slug='lgpd')
        post = CommunityPost.objects.create(
            author=user,
            category=category,
            title='Post LGPD',
            body='Conteúdo do post',
        )
        comment = CommunityComment.objects.create(
            post=post,
            author=user,
            body='Comentário relevante',
        )
        Report.objects.create(
            reporter=user,
            post=post,
            reason='Denúncia de teste',
        )

        response = self.client.get(reverse('me-data-export'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['profile']['email'], 'export@example.com')
        self.assertEqual(response.data['profile']['full_name'], 'Usuário Exportação')
        self.assertEqual(response.data['subscription']['tier'], Subscription.Tier.PROFESSIONAL)
        self.assertEqual(len(response.data['entitlements']), 1)
        self.assertEqual(len(response.data['annotations']), 1)
        self.assertEqual(response.data['annotations'][0]['note'], 'Minha nota')
        self.assertEqual(len(response.data['activity']['community_posts']), 1)
        self.assertEqual(len(response.data['activity']['community_comments']), 1)
        self.assertEqual(len(response.data['activity']['community_reports']), 1)
        self.assertIn('retention_policy', response.data)
        self.assertIn('community', response.data['retention_policy'])
        self.assertTrue(
            DataPrivacyRequest.objects.filter(
                user=user,
                request_type=DataPrivacyRequest.RequestType.EXPORT,
                status=DataPrivacyRequest.Status.COMPLETED,
            ).exists()
        )

    def test_me_data_erasure_requires_explicit_confirmation(self):
        user = User.objects.create_user(
            username='erase-confirm@example.com',
            email='erase-confirm@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-data-erasure'),
            {'confirmation': 'no'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['required_confirmation'], 'DELETE')
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertFalse(
            DataPrivacyRequest.objects.filter(
                user=user,
                request_type=DataPrivacyRequest.RequestType.ERASURE,
            ).exists()
        )

    def test_me_data_erasure_anonymizes_account_and_keeps_community_retention_trail(self):
        with tempfile.TemporaryDirectory(prefix='accounts-erasure-avatar-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                user = User.objects.create_user(
                    username='erase@example.com',
                    email='erase@example.com',
                    password='StrongPass123',
                )
                profile, _ = Profile.objects.get_or_create(user=user)
                profile.full_name = 'Usuário a remover'
                profile.profession = 'Profissional'
                profile.avatar_url = 'https://example.com/avatar-antigo.jpg'
                avatar_buffer = io.BytesIO()
                Image.new('RGB', (16, 16), color='#1D4ED8').save(avatar_buffer, format='PNG')
                profile.avatar = SimpleUploadedFile(
                    'avatar.png',
                    avatar_buffer.getvalue(),
                    content_type='image/png',
                )
                profile.save()
                avatar_path = profile.avatar.path
                self.assertTrue(os.path.exists(avatar_path))

                NotificationPreference.objects.create(user=user)
                device = PushDevice.objects.create(
                    user=user,
                    platform=PushDevice.Platform.ANDROID,
                    expo_push_token='ExponentPushToken[lgpd-erasure]',
                )

                book = Book.objects.create(title='Livro remoção', status=Book.Status.PUBLISHED)
                book_version = BookVersion.objects.create(
                    book=book,
                    version='2026.02',
                    status=BookVersion.Status.PUBLISHED,
                )
                chapter = BookChapter.objects.create(
                    book_version=book_version,
                    order=1,
                    title='Capítulo remoção',
                    slug='cap-remocao',
                    content_rich='<p>Texto</p>',
                )
                Annotation.objects.create(
                    user=user,
                    book_version=book_version,
                    chapter=chapter,
                    selector={'type': 'range'},
                    start_offset=0,
                    end_offset=5,
                    excerpt='Texto',
                    note='Nota para apagar',
                )

                subscription = Subscription.objects.create(
                    user=user,
                    tier=Subscription.Tier.ESSENTIAL,
                    status=Subscription.Status.ACTIVE,
                    source='test',
                )
                entitlement = Entitlement.objects.create(
                    user=user,
                    product=Entitlement.Product.SUBSCRIPTION,
                    subscription=subscription,
                    status=Entitlement.Status.ACTIVE,
                    source='test',
                )

                category = Category.objects.create(name='Retenção', slug='retencao')
                post = CommunityPost.objects.create(
                    author=user,
                    category=category,
                    title='Post preservado',
                    body='Conteúdo a reter',
                )
                CommunityComment.objects.create(
                    post=post,
                    author=user,
                    body='Comentário preservado',
                )
                Report.objects.create(
                    reporter=user,
                    post=post,
                    reason='Denúncia preservada',
                )

                access = str(RefreshToken.for_user(user).access_token)
                self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

                response = self.client.post(
                    reverse('me-data-erasure'),
                    {'confirmation': 'DELETE', 'reason': 'Solicitação LGPD de teste'},
                    format='json',
                )

                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.data['status'], DataPrivacyRequest.Status.COMPLETED)
                self.assertIn('retention_policy', response.data)

                user.refresh_from_db()
                profile.refresh_from_db()
                subscription.refresh_from_db()
                entitlement.refresh_from_db()

                self.assertFalse(user.is_active)
                self.assertTrue(user.username.startswith(f'deleted-user-{user.id}-'))
                self.assertTrue(user.email.startswith(f'deleted+{user.id}-'))
                self.assertEqual(profile.full_name, 'Conta anonimizada')
                self.assertEqual(profile.profession, '')
                self.assertFalse(bool(profile.avatar))
                self.assertEqual(profile.avatar_url, '')
                self.assertFalse(os.path.exists(avatar_path))
                self.assertEqual(subscription.status, Subscription.Status.INACTIVE)
                self.assertEqual(entitlement.status, Entitlement.Status.REVOKED)
                device.refresh_from_db()
                self.assertFalse(device.is_active)
                self.assertNotEqual(device.expo_push_token, 'ExponentPushToken[lgpd-erasure]')
                self.assertTrue(device.expo_push_token.startswith(f'erased-device-{user.id}-{device.id}-'))
                self.assertEqual(Annotation.objects.filter(user=user).count(), 0)
                self.assertEqual(CommunityPost.objects.filter(author=user).count(), 1)
                self.assertEqual(CommunityComment.objects.filter(author=user).count(), 1)
                self.assertEqual(Report.objects.filter(reporter=user).count(), 1)

                preference = NotificationPreference.objects.get(user=user)
                self.assertFalse(preference.notifications_enabled)
                self.assertFalse(preference.book_version_updates_enabled)
                self.assertFalse(preference.new_content_updates_enabled)
                self.assertFalse(preference.community_interaction_updates_enabled)
                self.assertFalse(preference.push_enabled)

                privacy_request = DataPrivacyRequest.objects.get(pk=response.data['request_id'])
                self.assertEqual(privacy_request.request_type, DataPrivacyRequest.RequestType.ERASURE)
                self.assertEqual(privacy_request.status, DataPrivacyRequest.Status.COMPLETED)
                self.assertIn('moderação', privacy_request.retention_policy)
                self.assertEqual(privacy_request.payload['actions']['community_posts_retained_total'], 1)
                self.assertEqual(privacy_request.payload['actions']['community_comments_retained_total'], 1)
                self.assertEqual(privacy_request.payload['actions']['community_reports_retained_total'], 1)
                self.assertEqual(privacy_request.payload['actions']['push_devices_scrubbed_total'], 1)

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
        self.assertTrue(response.data['community_interaction_updates_enabled'])
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
                'community_interaction_updates_enabled': False,
                'push_enabled': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['book_version_updates_enabled'])
        self.assertFalse(response.data['community_interaction_updates_enabled'])
        self.assertFalse(response.data['push_enabled'])

        preference = NotificationPreference.objects.get(user=user)
        self.assertTrue(preference.notifications_enabled)
        self.assertFalse(preference.book_version_updates_enabled)
        self.assertTrue(preference.new_content_updates_enabled)
        self.assertFalse(preference.community_interaction_updates_enabled)
        self.assertFalse(preference.push_enabled)

    def test_me_notifications_lists_only_pending_unacknowledged_dispatches_by_default(self):
        user = User.objects.create_user(
            username='notify@example.com',
            email='notify@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        pending_event = NotificationEvent.objects.create(
            event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
            dedup_key='course-post-published:api-list',
            title='Novo post do curso',
            payload={'resource_type': 'course_post', 'resource_id': 1},
        )
        pending_dispatch = NotificationDispatch.objects.create(
            event=pending_event,
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )
        acknowledged_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                dedup_key='community-comment-created:api-list',
                title='Novo comentário',
                payload={'resource_type': 'comment', 'resource_id': 2},
            ),
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
            acknowledged_at=timezone.now(),
        )
        NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.CASELAW_PUBLISHED,
                dedup_key='caselaw-published:api-list',
                title='Nova jurisprudência',
            ),
            user=user,
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.SENT,
            dispatched_at=timezone.now(),
        )

        response = self.client.get(reverse('me-notifications'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['dispatch_id'], pending_dispatch.id)
        self.assertNotEqual(response.data[0]['dispatch_id'], acknowledged_dispatch.id)

    def test_me_notifications_filters_by_channel(self):
        user = User.objects.create_user(
            username='notifychannel@example.com',
            email='notifychannel@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        event = NotificationEvent.objects.create(
            event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
            dedup_key='course-post-published:channel-filter',
            title='Novo post do curso',
        )
        in_app_dispatch = NotificationDispatch.objects.create(
            event=event,
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )
        NotificationDispatch.objects.create(
            event=event,
            user=user,
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.SENT,
            dispatched_at=timezone.now(),
        )

        response = self.client.get(
            reverse('me-notifications'),
            {'channel': NotificationDispatch.Channel.IN_APP},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['dispatch_id'], in_app_dispatch.id)
        self.assertEqual(response.data[0]['channel'], NotificationDispatch.Channel.IN_APP)

    def test_me_notification_ack_marks_dispatch_as_acknowledged(self):
        user = User.objects.create_user(
            username='notifyack@example.com',
            email='notifyack@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
                dedup_key='course-post-published:api-ack',
                title='Novo conteúdo',
            ),
            user=user,
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.PENDING,
        )
        sibling_in_app_dispatch = NotificationDispatch.objects.create(
            event=dispatch.event,
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )

        response = self.client.post(reverse('me-notification-ack', args=[dispatch.id]), {}, format='json')

        self.assertEqual(response.status_code, 200)
        dispatch.refresh_from_db()
        sibling_in_app_dispatch.refresh_from_db()
        self.assertIsNotNone(dispatch.acknowledged_at)
        self.assertIsNotNone(sibling_in_app_dispatch.acknowledged_at)
        self.assertEqual(response.data['dispatch_id'], dispatch.id)

    def test_me_notification_consume_latest_returns_latest_in_app_and_collapses_backlog(self):
        user = User.objects.create_user(
            username='notifylatest@example.com',
            email='notifylatest@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        older_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
                dedup_key='book-chapter-published:latest-older',
                title='Capítulo antigo',
            ),
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )
        latest_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.BOOK_VERSION_PUBLISHED,
                dedup_key='book-version-published:latest-newer',
                title='Versão nova',
            ),
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )

        response = self.client.post(reverse('me-notification-consume-latest'), {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['dispatch_id'], latest_dispatch.id)

        older_dispatch.refresh_from_db()
        latest_dispatch.refresh_from_db()
        self.assertIsNotNone(older_dispatch.acknowledged_at)
        self.assertIsNotNone(latest_dispatch.acknowledged_at)

    def test_me_push_devices_register_list_and_unregister(self):
        user = User.objects.create_user(
            username='pushdevice@example.com',
            email='pushdevice@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        register_response = self.client.post(
            reverse('me-push-devices'),
            {
                'platform': PushDevice.Platform.ANDROID,
                'installation_id': 'lv-installation-123',
                'expo_push_token': 'ExponentPushToken[test-device-token]',
            },
            format='json',
        )
        list_response = self.client.get(reverse('me-push-devices'))
        unregister_response = self.client.delete(
            reverse('me-push-devices'),
            {'installation_id': 'lv-installation-123'},
            format='json',
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['platform'], PushDevice.Platform.ANDROID)
        self.assertEqual(list_response.data[0]['installation_id'], 'lv-installation-123')
        self.assertEqual(unregister_response.status_code, 204)

        device = PushDevice.objects.get(expo_push_token='ExponentPushToken[test-device-token]')
        self.assertFalse(device.is_active)
        self.assertEqual(device.disabled_reason, 'unregistered_by_user')

    def test_me_push_devices_updates_existing_row_when_token_rotates_for_same_installation(self):
        owner = User.objects.create_user(
            username='push-owner@example.com',
            email='push-owner@example.com',
            password='StrongPass123',
        )
        existing_device = PushDevice.objects.create(
            user=owner,
            platform=PushDevice.Platform.ANDROID,
            installation_id='lv-installation-rotate',
            expo_push_token='ExponentPushToken[shared-device-old]',
            is_active=True,
        )

        access = str(RefreshToken.for_user(owner).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-push-devices'),
            {
                'platform': PushDevice.Platform.ANDROID,
                'installation_id': 'lv-installation-rotate',
                'expo_push_token': 'ExponentPushToken[shared-device-new]',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        existing_device.refresh_from_db()
        self.assertEqual(existing_device.expo_push_token, 'ExponentPushToken[shared-device-new]')
        self.assertEqual(existing_device.installation_id, 'lv-installation-rotate')
        self.assertEqual(PushDevice.objects.filter(user=owner).count(), 1)

    def test_me_push_devices_registration_skips_older_pending_push_backlog(self):
        user = User.objects.create_user(
            username='push-backlog@example.com',
            email='push-backlog@example.com',
            password='StrongPass123',
        )
        dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                dedup_key='community-comment-created:stale-backlog',
                title='Interação antiga',
            ),
            user=user,
            channel=NotificationDispatch.Channel.PUSH,
            status=NotificationDispatch.Status.PENDING,
        )
        stale_created_at = timezone.now() - timedelta(days=1)
        NotificationDispatch.objects.filter(id=dispatch.id).update(created_at=stale_created_at)

        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-push-devices'),
            {
                'platform': PushDevice.Platform.ANDROID,
                'installation_id': 'lv-installation-backlog',
                'expo_push_token': 'ExponentPushToken[backlog-device]',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(dispatch.reason, 'push_stale_before_current_device')

    def test_me_push_devices_same_installation_can_rebind_device_to_new_account(self):
        owner = User.objects.create_user(
            username='push-owner@example.com',
            email='push-owner@example.com',
            password='StrongPass123',
        )
        other_user = User.objects.create_user(
            username='push-other@example.com',
            email='push-other@example.com',
            password='StrongPass123',
        )
        device = PushDevice.objects.create(
            user=owner,
            platform=PushDevice.Platform.ANDROID,
            installation_id='lv-installation-rebind',
            expo_push_token='ExponentPushToken[shared-device]',
            is_active=True,
        )

        access = str(RefreshToken.for_user(other_user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-push-devices'),
            {
                'platform': PushDevice.Platform.IOS,
                'installation_id': 'lv-installation-rebind',
                'expo_push_token': 'ExponentPushToken[shared-device-new-account]',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)

        device.refresh_from_db()
        self.assertEqual(device.user_id, other_user.id)
        self.assertEqual(device.platform, PushDevice.Platform.IOS)
        self.assertEqual(device.expo_push_token, 'ExponentPushToken[shared-device-new-account]')

    def test_me_push_devices_rejects_token_linked_to_another_identified_installation(self):
        owner = User.objects.create_user(
            username='push-owner@example.com',
            email='push-owner@example.com',
            password='StrongPass123',
        )
        other_user = User.objects.create_user(
            username='push-other@example.com',
            email='push-other@example.com',
            password='StrongPass123',
        )
        PushDevice.objects.create(
            user=owner,
            platform=PushDevice.Platform.ANDROID,
            installation_id='lv-installation-owner',
            expo_push_token='ExponentPushToken[shared-device]',
            is_active=True,
        )

        access = str(RefreshToken.for_user(other_user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        response = self.client.post(
            reverse('me-push-devices'),
            {
                'platform': PushDevice.Platform.IOS,
                'installation_id': 'lv-installation-other',
                'expo_push_token': 'ExponentPushToken[shared-device]',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('expo_push_token', response.data)

        device = PushDevice.objects.get(expo_push_token='ExponentPushToken[shared-device]')
        self.assertEqual(device.user_id, owner.id)

    def test_notifications_sensitive_endpoints_are_throttled(self):
        cache.clear()
        user = User.objects.create_user(
            username='notify-throttle@example.com',
            email='notify-throttle@example.com',
            password='StrongPass123',
        )
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

        dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
                dedup_key='book-chapter-published:notify-throttle',
                title='Throttle notification',
            ),
            user=user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
        )

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'notifications_sensitive': '1/min'}):
            first = self.client.get(reverse('me-notifications'))
            second = self.client.post(reverse('me-notification-ack', args=[dispatch.id]), {}, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

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

    def test_auth_refresh_is_throttled(self):
        cache.clear()
        first_user = User.objects.create_user(
            username='refresh-one@example.com',
            email='refresh-one@example.com',
            password='StrongPass123',
        )
        second_user = User.objects.create_user(
            username='refresh-two@example.com',
            email='refresh-two@example.com',
            password='StrongPass123',
        )
        first_refresh = str(RefreshToken.for_user(first_user))
        second_refresh = str(RefreshToken.for_user(second_user))

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'auth_refresh': '1/min'}):
            first = self.client.post(
                reverse('auth-refresh'),
                {'refresh': first_refresh},
                format='json',
            )
            second = self.client.post(
                reverse('auth-refresh'),
                {'refresh': second_refresh},
                format='json',
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

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


class NotificationTriggerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = timezone.now()

        self.professional_user = self._create_user('pro@example.com')
        self.professional_opt_out_user = self._create_user('pro-optout@example.com')
        self.professional_push_off_user = self._create_user('pro-push-off@example.com')
        self.essential_user = self._create_user('essential@example.com')
        self.community_author = self._create_user('community-author@example.com')
        self.community_opt_out_author = self._create_user('community-optout@example.com')
        self.community_follower = self._create_user('community-follower@example.com')
        self.community_observer = self._create_user('community-observer@example.com')
        self.commenter = self._create_user('commenter@example.com')

        self._create_subscription(self.professional_user, tier=Subscription.Tier.PROFESSIONAL)
        self._create_subscription(self.professional_opt_out_user, tier=Subscription.Tier.PROFESSIONAL)
        self._create_subscription(self.professional_push_off_user, tier=Subscription.Tier.PROFESSIONAL)
        self._create_subscription(self.essential_user, tier=Subscription.Tier.ESSENTIAL)
        self._create_subscription(self.community_author, tier=Subscription.Tier.ESSENTIAL)
        self._create_subscription(self.community_opt_out_author, tier=Subscription.Tier.ESSENTIAL)
        self._create_subscription(self.community_follower, tier=Subscription.Tier.ESSENTIAL)
        self._create_subscription(self.community_observer, tier=Subscription.Tier.ESSENTIAL)
        self._create_subscription(self.commenter, tier=Subscription.Tier.ESSENTIAL)

        NotificationPreference.objects.create(
            user=self.professional_opt_out_user,
            new_content_updates_enabled=False,
        )
        NotificationPreference.objects.create(
            user=self.professional_push_off_user,
            push_enabled=False,
        )
        NotificationPreference.objects.create(
            user=self.community_opt_out_author,
            community_interaction_updates_enabled=False,
        )

        self.category = Category.objects.create(name='Comunidade', slug='comunidade')

    def _create_user(self, email: str):
        return User.objects.create_user(
            username=email,
            email=email,
            password='StrongPass123',
        )

    def _create_subscription(self, user, *, tier: str):
        return Subscription.objects.create(
            user=user,
            tier=tier,
            status=Subscription.Status.ACTIVE,
            started_at=self.now - timedelta(days=1),
            source='test',
        )

    def _auth(self, user):
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    def test_published_course_post_enqueues_notifications_for_professional_users_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            course_post = CoursePost.objects.create(
                title='Novo módulo',
                slug='novo-modulo',
                author_name='Equipe',
                excerpt='Resumo do novo módulo',
                content_rich='<p>Conteúdo do curso</p>',
                post_type=CoursePost.PostType.LESSON,
                status=PublicationStatus.PUBLISHED,
            )

        event = NotificationEvent.objects.get(dedup_key=f'course-post-published:{course_post.pk}')
        push_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.PUSH,
            )
        }
        in_app_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.IN_APP,
            )
        }

        self.assertEqual(event.event_type, NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED)
        self.assertEqual(event.payload['resource_type'], 'course_post')
        self.assertEqual(
            set(push_dispatches),
            {self.professional_user.id, self.professional_opt_out_user.id, self.professional_push_off_user.id},
        )
        self.assertEqual(
            set(in_app_dispatches),
            {self.professional_user.id, self.professional_opt_out_user.id, self.professional_push_off_user.id},
        )
        self.assertEqual(push_dispatches[self.professional_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.professional_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(push_dispatches[self.professional_opt_out_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(in_app_dispatches[self.professional_opt_out_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(push_dispatches[self.professional_opt_out_user.id].reason, 'new_content_disabled')
        self.assertEqual(in_app_dispatches[self.professional_opt_out_user.id].reason, 'new_content_disabled')
        self.assertEqual(push_dispatches[self.professional_push_off_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(push_dispatches[self.professional_push_off_user.id].reason, 'push_disabled')
        self.assertEqual(in_app_dispatches[self.professional_push_off_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertNotIn(self.essential_user.id, push_dispatches)

        with self.captureOnCommitCallbacks(execute=True):
            course_post.excerpt = 'Resumo atualizado sem novo dispatch'
            course_post.save()

        self.assertEqual(
            NotificationEvent.objects.filter(dedup_key=f'course-post-published:{course_post.pk}').count(),
            1,
        )

    def test_published_course_asset_and_live_event_enqueue_notifications(self):
        with self.captureOnCommitCallbacks(execute=True):
            course_post = CoursePost.objects.create(
                title='Post base',
                slug='post-base',
                author_name='Equipe',
                excerpt='Base',
                content_rich='<p>Base</p>',
                post_type=CoursePost.PostType.BLOG,
                status=PublicationStatus.PUBLISHED,
            )
            course_asset = CourseAsset.objects.create(
                post=course_post,
                title='Checklist da aula',
                description='Checklist operacional',
                asset_type=CourseAsset.AssetType.CHECKLIST,
                file_url='https://example.com/checklist.pdf',
                status=PublicationStatus.PUBLISHED,
            )
            live_event = LiveEvent.objects.create(
                post=course_post,
                title='Mentoria ao vivo',
                description='Tire dúvidas na mentoria.',
                event_type=LiveEvent.EventType.MENTORING,
                status=LiveEvent.Status.SCHEDULED,
                starts_at=self.now + timedelta(days=2),
                meeting_url='https://example.com/live',
            )

        asset_event = NotificationEvent.objects.get(dedup_key=f'course-asset-published:{course_asset.pk}')
        live_event_notification = NotificationEvent.objects.get(dedup_key=f'course-live-announced:{live_event.pk}')

        self.assertEqual(asset_event.payload['resource_type'], 'course_asset')
        self.assertEqual(live_event_notification.payload['resource_type'], 'live_event')
        self.assertEqual(
            NotificationDispatch.objects.filter(
                event=asset_event,
                channel=NotificationDispatch.Channel.PUSH,
                status=NotificationDispatch.Status.PENDING,
            ).count(),
            1,
        )
        self.assertEqual(
            NotificationDispatch.objects.filter(
                event=live_event_notification,
                channel=NotificationDispatch.Channel.PUSH,
                status=NotificationDispatch.Status.PENDING,
            ).count(),
            1,
        )
        self.assertEqual(
            NotificationDispatch.objects.filter(
                event=asset_event,
                channel=NotificationDispatch.Channel.IN_APP,
                status=NotificationDispatch.Status.PENDING,
            ).count(),
            2,
        )
        self.assertEqual(
            NotificationDispatch.objects.filter(
                event=live_event_notification,
                channel=NotificationDispatch.Channel.IN_APP,
                status=NotificationDispatch.Status.PENDING,
            ).count(),
            2,
        )

    def test_caselaw_creation_enqueues_notifications_with_dedup(self):
        caselaw = CaseLaw.objects.create(
            court='STJ',
            case_number='REsp 999/DF',
            decision_date=self.now.date(),
            ementa_rich='<p>Nova tese em bagagem extraviada.</p>',
            url='https://example.com/caselaw',
        )

        event = NotificationEvent.objects.get(dedup_key=f'caselaw-published:{caselaw.pk}')
        push_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.PUSH,
            )
        }
        in_app_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.IN_APP,
            )
        }

        self.assertEqual(event.event_type, NotificationEvent.EventType.CASELAW_PUBLISHED)
        self.assertEqual(
            set(push_dispatches),
            {self.professional_user.id, self.professional_opt_out_user.id, self.professional_push_off_user.id},
        )
        self.assertEqual(
            set(in_app_dispatches),
            {self.professional_user.id, self.professional_opt_out_user.id, self.professional_push_off_user.id},
        )
        self.assertEqual(push_dispatches[self.professional_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.professional_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(push_dispatches[self.professional_opt_out_user.id].reason, 'new_content_disabled')
        self.assertEqual(in_app_dispatches[self.professional_opt_out_user.id].reason, 'new_content_disabled')
        self.assertEqual(push_dispatches[self.professional_push_off_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(push_dispatches[self.professional_push_off_user.id].reason, 'push_disabled')
        self.assertEqual(in_app_dispatches[self.professional_push_off_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertNotIn(self.essential_user.id, push_dispatches)

        caselaw.tags = ['atualizado']
        caselaw.save()

        self.assertEqual(
            NotificationEvent.objects.filter(dedup_key=f'caselaw-published:{caselaw.pk}').count(),
            1,
        )

    def test_new_comment_notifies_active_post_followers_only(self):
        post = CommunityPost.objects.create(
            author=self.community_author,
            category=self.category,
            title='Dúvida importante',
            body='Texto do post',
        )
        PostFollow.objects.create(
            post=post,
            user=self.community_follower,
            is_active=True,
        )

        self._auth(self.commenter)
        response = self.client.post(
            '/community/comments/',
            {'post_id': post.pk, 'body': 'Tenho uma sugestão.'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)

        event = NotificationEvent.objects.get(
            dedup_key=f'community-comment-created:{response.data["id"]}'
        )
        push_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.PUSH,
            )
        }
        in_app_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.IN_APP,
            )
        }

        self.assertEqual(event.event_type, NotificationEvent.EventType.COMMUNITY_INTERACTION)
        self.assertEqual(set(push_dispatches), {self.community_author.id, self.community_follower.id})
        self.assertEqual(set(in_app_dispatches), {self.community_author.id, self.community_follower.id})
        self.assertEqual(push_dispatches[self.community_author.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.community_author.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(push_dispatches[self.community_author.id].reason, '')
        self.assertEqual(in_app_dispatches[self.community_author.id].reason, '')
        self.assertEqual(push_dispatches[self.community_follower.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.community_follower.id].status, NotificationDispatch.Status.PENDING)
        self.assertNotIn(self.community_observer.id, push_dispatches)
        self.assertNotIn(self.commenter.id, push_dispatches)

    def test_new_comment_respects_community_preference_unfollow_and_self_comment_is_ignored(self):
        opt_out_post = CommunityPost.objects.create(
            author=self.community_opt_out_author,
            category=self.category,
            title='Post sem notificação',
            body='Texto',
        )
        PostFollow.objects.filter(post=opt_out_post, user=self.community_opt_out_author).update(is_active=False)
        PostFollow.objects.create(
            post=opt_out_post,
            user=self.community_follower,
            is_active=True,
        )

        self._auth(self.commenter)
        opt_out_response = self.client.post(
            '/community/comments/',
            {'post_id': opt_out_post.pk, 'body': 'Comentário para usuário opt-out'},
            format='json',
        )

        self.assertEqual(opt_out_response.status_code, 201)

        event = NotificationEvent.objects.get(
            dedup_key=f'community-comment-created:{opt_out_response.data["id"]}'
        )
        push_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.PUSH,
            )
        }
        in_app_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.IN_APP,
            )
        }
        self.assertEqual(set(push_dispatches), {self.community_follower.id})
        self.assertEqual(set(in_app_dispatches), {self.community_follower.id})
        self.assertEqual(push_dispatches[self.community_follower.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.community_follower.id].status, NotificationDispatch.Status.PENDING)
        self.assertNotIn(self.community_opt_out_author.id, push_dispatches)

        opted_out_follower_post = CommunityPost.objects.create(
            author=self.community_author,
            category=self.category,
            title='Post com follower opt-out',
            body='Texto',
        )
        PostFollow.objects.create(
            post=opted_out_follower_post,
            user=self.community_opt_out_author,
            is_active=True,
        )

        preference_response = self.client.post(
            '/community/comments/',
            {'post_id': opted_out_follower_post.pk, 'body': 'Comentário para follower opt-out'},
            format='json',
        )
        self.assertEqual(preference_response.status_code, 201)

        preference_event = NotificationEvent.objects.get(
            dedup_key=f'community-comment-created:{preference_response.data["id"]}'
        )
        push_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=preference_event,
                channel=NotificationDispatch.Channel.PUSH,
            )
        }
        in_app_dispatches = {
            dispatch.user_id: dispatch
            for dispatch in NotificationDispatch.objects.filter(
                event=preference_event,
                channel=NotificationDispatch.Channel.IN_APP,
            )
        }
        self.assertEqual(push_dispatches[self.community_author.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[self.community_author.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(push_dispatches[self.community_opt_out_author.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(in_app_dispatches[self.community_opt_out_author.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(
            push_dispatches[self.community_opt_out_author.id].reason,
            'community_interactions_disabled',
        )
        self.assertEqual(
            in_app_dispatches[self.community_opt_out_author.id].reason,
            'community_interactions_disabled',
        )

        self.client.credentials()
        self._auth(self.community_author)
        self_comment_response = self.client.post(
            '/community/comments/',
            {'post_id': CommunityPost.objects.create(
                author=self.community_author,
                category=self.category,
                title='Meu próprio post',
                body='Texto',
            ).pk, 'body': 'Comentário próprio'},
            format='json',
        )

        self.assertEqual(self_comment_response.status_code, 201)
        self.assertFalse(
            NotificationEvent.objects.filter(
                dedup_key=f'community-comment-created:{self_comment_response.data["id"]}'
            ).exists()
        )


class NotificationDeliveryTests(TestCase):
    def test_enqueue_notification_event_autodispatches_push_by_default(self):
        user = User.objects.create_user(
            username='pendingpush@example.com',
            email='pendingpush@example.com',
            password='StrongPass123',
        )

        with mock.patch('accounts.services.dispatch_pending_push_notifications') as dispatch_mock:
            event = enqueue_notification_event(
                event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                dedup_key='community-comment-created:no-autodispatch',
                title='Interacao na comunidade',
                recipient_user_ids=[user.id],
            )

        self.assertIsNotNone(event)
        dispatch_mock.assert_called_once_with(limit=200)
        self.assertEqual(
            NotificationDispatch.objects.filter(
                event=event,
                channel=NotificationDispatch.Channel.PUSH,
                status=NotificationDispatch.Status.PENDING,
            ).count(),
            1,
        )

    @override_settings(PUSH_AUTODISPATCH_ENABLED=False)
    def test_enqueue_notification_event_can_opt_out_of_autodispatch(self):
        user = User.objects.create_user(
            username='autodispatch@example.com',
            email='autodispatch@example.com',
            password='StrongPass123',
        )

        with mock.patch('accounts.services.dispatch_pending_push_notifications') as dispatch_mock:
            enqueue_notification_event(
                event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                dedup_key='community-comment-created:autodispatch-enabled',
                title='Interacao na comunidade',
                recipient_user_ids=[user.id],
            )

        dispatch_mock.assert_not_called()

    def test_dispatch_pending_push_notifications_marks_success_and_failure(self):
        user = User.objects.create_user(
            username='push@example.com',
            email='push@example.com',
            password='StrongPass123',
        )
        success_device = PushDevice.objects.create(
            user=user,
            platform=PushDevice.Platform.ANDROID,
            expo_push_token='ExponentPushToken[success-device]',
        )
        failed_device = PushDevice.objects.create(
            user=user,
            platform=PushDevice.Platform.IOS,
            expo_push_token='ExponentPushToken[failed-device]',
        )

        success_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
                dedup_key='course-post-published:delivery-success',
                title='Post publicado',
            ),
            user=user,
            status=NotificationDispatch.Status.PENDING,
        )
        failed_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.CASELAW_PUBLISHED,
                dedup_key='caselaw-published:delivery-failed',
                title='Jurisprudência publicada',
            ),
            user=user,
            status=NotificationDispatch.Status.PENDING,
            acknowledged_at=timezone.now(),
        )

        with mock.patch(
            'accounts.services.get_active_push_devices_for_user_ids',
            return_value=[success_device, failed_device],
        ), mock.patch(
            'accounts.services._send_expo_push_messages',
            return_value=[
                {'status': 'ok', 'id': 'ticket-success'},
                {'status': 'error', 'details': {'error': 'DeviceNotRegistered'}},
            ],
        ):
            summary = dispatch_pending_push_notifications(limit=10)

        success_dispatch.refresh_from_db()
        failed_dispatch.refresh_from_db()
        success_device.refresh_from_db()
        failed_device.refresh_from_db()

        self.assertEqual(summary['queued'], 1)
        self.assertEqual(summary['sent'], 1)
        self.assertEqual(summary['failed'], 0)
        self.assertEqual(summary['devices'], 2)
        self.assertEqual(success_dispatch.status, NotificationDispatch.Status.SENT)
        self.assertIsNotNone(success_dispatch.dispatched_at)
        self.assertEqual(failed_dispatch.status, NotificationDispatch.Status.PENDING)
        self.assertTrue(success_device.is_active)
        self.assertFalse(failed_device.is_active)
        self.assertEqual(failed_device.disabled_reason, 'device_not_registered')

    def test_dispatch_pending_push_notifications_marks_failed_dispatch_when_all_devices_fail(self):
        user = User.objects.create_user(
            username='pushfail@example.com',
            email='pushfail@example.com',
            password='StrongPass123',
        )
        PushDevice.objects.create(
            user=user,
            platform=PushDevice.Platform.ANDROID,
            expo_push_token='ExponentPushToken[all-fail-device]',
        )
        dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                dedup_key='community-comment-created:delivery-failed',
                title='Interação na comunidade',
            ),
            user=user,
            status=NotificationDispatch.Status.PENDING,
        )

        with mock.patch(
            'accounts.services._send_expo_push_messages',
            return_value=[
                {'status': 'error', 'details': {'error': 'MessageRateExceeded'}},
            ],
        ):
            summary = dispatch_pending_push_notifications(limit=10)

        dispatch.refresh_from_db()

        self.assertEqual(summary['queued'], 1)
        self.assertEqual(summary['sent'], 0)
        self.assertEqual(summary['failed'], 1)
        self.assertEqual(dispatch.status, NotificationDispatch.Status.FAILED)
        self.assertEqual(dispatch.reason, 'MessageRateExceeded')

    def test_dispatch_pending_push_notifications_skips_older_pending_rows_without_active_devices(self):
        stale_user = User.objects.create_user(
            username='stalepush@example.com',
            email='stalepush@example.com',
            password='StrongPass123',
        )
        target_user = User.objects.create_user(
            username='freshpush@example.com',
            email='freshpush@example.com',
            password='StrongPass123',
        )
        PushDevice.objects.create(
            user=target_user,
            platform=PushDevice.Platform.ANDROID,
            expo_push_token='ExponentPushToken[fresh-device]',
        )

        for index in range(3):
            NotificationDispatch.objects.create(
                event=NotificationEvent.objects.create(
                    event_type=NotificationEvent.EventType.COMMUNITY_INTERACTION,
                    dedup_key=f'community-comment-created:stale-{index}',
                    title=f'Evento antigo {index}',
                ),
                user=stale_user,
                status=NotificationDispatch.Status.PENDING,
            )

        fresh_dispatch = NotificationDispatch.objects.create(
            event=NotificationEvent.objects.create(
                event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
                dedup_key='content-published:fresh-device',
                title='Evento atual',
            ),
            user=target_user,
            status=NotificationDispatch.Status.PENDING,
        )

        with mock.patch(
            'accounts.services._send_expo_push_messages',
            return_value=[{'status': 'ok', 'id': 'ticket-fresh'}],
        ) as send_mock:
            summary = dispatch_pending_push_notifications(limit=1)

        fresh_dispatch.refresh_from_db()

        self.assertEqual(summary['queued'], 1)
        self.assertEqual(summary['sent'], 1)
        self.assertEqual(summary['failed'], 0)
        self.assertEqual(summary['devices'], 1)
        self.assertEqual(fresh_dispatch.status, NotificationDispatch.Status.SENT)
        send_mock.assert_called_once()


class AccountsLegalAcceptanceFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='legal-flow@example.com',
            email='legal-flow@example.com',
            password='StrongPass123',
        )
        Profile.objects.get_or_create(user=self.user)
        self.terms = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.28',
            title='Termos do beta',
            content_html='<p>Termos atuais</p>',
            is_active=True,
        )
        self.privacy = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
            version='2026.04.28',
            title='Política do beta',
            content_html='<p>Política atual</p>',
            is_active=True,
        )

    def _authenticate(self, user=None):
        target_user = user or self.user
        access = str(RefreshToken.for_user(target_user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return access

    def _accept_all_documents(self):
        self._authenticate()
        return self.client.post(
            reverse('me-legal-acceptances-accept'),
            {
                'document_ids': [self.terms.id, self.privacy.id],
                'source': UserLegalAcceptance.Source.LOGIN_GATE,
                'app_platform': UserLegalAcceptance.AppPlatform.WEB,
                'app_version': 'beta-web',
            },
            format='json',
        )

    def test_login_and_register_include_auth_methods_and_legal_status(self):
        register_response = self.client.post(
            reverse('auth-register'),
            {
                'email': 'novo-legal@example.com',
                'password': 'StrongPass123',
                'name': 'Novo Legal',
            },
            format='json',
        )
        self.assertEqual(register_response.status_code, 201)
        self.assertEqual(register_response.data['auth_methods'], ['password'])
        self.assertTrue(register_response.data['legal_status']['requires_acceptance'])
        self.assertEqual(
            register_response.data['legal_status']['pending_document_types'],
            [
                LegalDocumentVersion.DocumentType.TERMS_OF_USE,
                LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
            ],
        )

        login_response = self.client.post(
            reverse('auth-login'),
            {'email': self.user.email, 'password': 'StrongPass123'},
            format='json',
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.data['auth_methods'], ['password'])
        self.assertTrue(login_response.data['legal_status']['requires_acceptance'])
        self.assertIn('user', login_response.data)

    def test_me_returns_account_state_and_linked_auth_methods(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=['password'])
        ExternalIdentity.objects.create(
            user=self.user,
            provider=ExternalIdentity.Provider.GOOGLE,
            provider_subject='google-legal-flow',
            email=self.user.email,
            email_verified=True,
        )
        self._authenticate()

        response = self.client.get(reverse('me'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_usable_password'])
        self.assertEqual(response.data['auth_methods'], [ExternalIdentity.Provider.GOOGLE])
        self.assertTrue(response.data['legal_status']['requires_acceptance'])
        self.assertEqual(len(response.data['legal_status']['current_documents']), 2)

    def test_required_legal_documents_endpoint_returns_current_documents_with_content(self):
        self._authenticate()

        response = self.client.get(reverse('me-legal-documents-required'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['documents']), 2)
        self.assertEqual(
            response.data['documents'][0]['document_type'],
            LegalDocumentVersion.DocumentType.TERMS_OF_USE,
        )
        self.assertIn('content_html', response.data['documents'][0])
        self.assertFalse(response.data['documents'][0]['accepted'])

    def test_accept_endpoint_creates_acceptances_and_is_idempotent(self):
        first_response = self._accept_all_documents()
        second_response = self._accept_all_documents()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(first_response.data['legal_status']['requires_acceptance'])
        self.assertFalse(second_response.data['legal_status']['requires_acceptance'])
        self.assertEqual(
            UserLegalAcceptance.objects.filter(user=self.user).count(),
            2,
        )

    def test_accept_endpoint_rejects_stale_or_partial_document_set(self):
        self._authenticate()

        response = self.client.post(
            reverse('me-legal-acceptances-accept'),
            {'document_ids': [self.terms.id]},
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'legal_documents_changed')
        self.assertEqual(len(response.data['required_documents']), 2)

    def test_legal_acceptances_endpoint_lists_audit_history(self):
        self._accept_all_documents()

        response = self.client.get(reverse('me-legal-acceptances'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['acceptances']), 2)
        self.assertEqual(
            {item['document_type'] for item in response.data['acceptances']},
            {
                LegalDocumentVersion.DocumentType.TERMS_OF_USE,
                LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
            },
        )

    def test_business_endpoints_require_current_legal_acceptance(self):
        self._authenticate()
        blocked_routes = [
            reverse('me-entitlements'),
            reverse('book-list'),
            reverse('global-search') + '?q=livro',
            reverse('template-piece-list'),
            reverse('course-post-list'),
            reverse('caselaw-list'),
            reverse('community-post-list'),
            reverse('annotation-list'),
        ]

        for route in blocked_routes:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 409, route)
            self.assertEqual(response.data['code'], 'legal_acceptance_required')
            self.assertEqual(len(response.data['required_documents']), 2)

    def test_me_get_is_allowed_but_me_patch_is_blocked_before_acceptance(self):
        self._authenticate()

        get_response = self.client.get(reverse('me'))
        patch_response = self.client.patch(
            reverse('me'),
            {'name': 'Novo Nome'},
            format='json',
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(patch_response.status_code, 409)
        self.assertEqual(patch_response.data['code'], 'legal_acceptance_required')

    def test_business_endpoints_stop_returning_legal_block_after_acceptance(self):
        self._accept_all_documents()

        global_search_response = self.client.get(reverse('global-search') + '?q=livro')
        templates_response = self.client.get(reverse('template-piece-list'))

        self.assertNotEqual(global_search_response.status_code, 409)
        self.assertNotEqual(templates_response.status_code, 409)


class AccountsDomainFoundationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='domain@example.com',
            email='domain@example.com',
            password='StrongPass123',
        )
        Profile.objects.get_or_create(user=self.user)

    def test_external_identity_enforces_user_provider_and_subject_uniqueness(self):
        ExternalIdentity.objects.create(
            user=self.user,
            provider=ExternalIdentity.Provider.GOOGLE,
            provider_subject='google-subject-1',
            email='domain@example.com',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalIdentity.objects.create(
                    user=self.user,
                    provider=ExternalIdentity.Provider.GOOGLE,
                    provider_subject='google-subject-2',
                    email='other@example.com',
                )

        other_user = User.objects.create_user(
            username='other-domain@example.com',
            email='other-domain@example.com',
            password='StrongPass123',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExternalIdentity.objects.create(
                    user=other_user,
                    provider=ExternalIdentity.Provider.GOOGLE,
                    provider_subject='google-subject-1',
                    email='other-domain@example.com',
                )

    def test_legal_document_version_computes_hash_and_deactivates_previous_active_version(self):
        previous = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.01',
            title='Termos do beta',
            content_html='<p>Primeira versão</p>',
            is_active=True,
        )

        current = LegalDocumentVersion(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.28',
            title='Termos do beta atualizados',
            content_html='<p>Segunda versão</p>',
            is_active=True,
        )
        current.full_clean()
        current.save()

        previous.refresh_from_db()
        self.assertFalse(previous.is_active)
        self.assertTrue(current.is_active)
        self.assertEqual(
            current.content_sha256,
            hashlib.sha256('<p>Segunda versão</p>'.encode('utf-8')).hexdigest(),
        )
        self.assertIsNotNone(current.published_at)
        self.assertIsNotNone(current.enforcement_starts_at)

    def test_published_legal_document_rejects_core_content_edits(self):
        document = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
            version='2026.04.28',
            title='Política inicial',
            content_html='<p>Texto original</p>',
            is_active=True,
        )

        document.title = 'Política alterada'
        document.content_html = '<p>Texto alterado</p>'

        with self.assertRaises(ValidationError) as context:
            document.clean()

        self.assertIn('title', context.exception.message_dict)
        self.assertIn('content_html', context.exception.message_dict)

    def test_user_legal_acceptance_is_unique_per_user_and_document(self):
        document = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.28',
            title='Termos',
            content_html='<p>Texto</p>',
            is_active=True,
        )
        UserLegalAcceptance.objects.create(
            user=self.user,
            document=document,
            source=UserLegalAcceptance.Source.LOGIN_GATE,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserLegalAcceptance.objects.create(
                    user=self.user,
                    document=document,
                    source=UserLegalAcceptance.Source.ACCOUNT_SETTINGS,
                )


class AccountsAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.client.force_login(self.admin_user)

    def test_notification_and_privacy_models_are_registered_in_admin(self):
        preference_user = User.objects.create_user(
            username='pref-admin@example.com',
            email='pref-admin@example.com',
            password='StrongPass123',
        )
        NotificationPreference.objects.create(user=preference_user)
        event = NotificationEvent.objects.create(
            event_type=NotificationEvent.EventType.COURSE_CONTENT_PUBLISHED,
            dedup_key='course-post-published:admin-check',
            title='Evento de admin',
            payload={'resource_type': 'course_post'},
        )
        NotificationDispatch.objects.create(
            event=event,
            user=preference_user,
            status=NotificationDispatch.Status.PENDING,
        )
        PushDevice.objects.create(
            user=preference_user,
            platform=PushDevice.Platform.ANDROID,
            expo_push_token='ExponentPushToken[admin-check-device]',
        )
        DataPrivacyRequest.objects.create(
            user=preference_user,
            request_type=DataPrivacyRequest.RequestType.ERASURE,
            status=DataPrivacyRequest.Status.COMPLETED,
            retention_policy='Retenção de comunidade e reports para moderação.',
            payload={'source': 'test'},
            processed_at=timezone.now(),
        )

        preference_response = self.client.get(reverse('admin:accounts_notificationpreference_changelist'))
        event_response = self.client.get(reverse('admin:accounts_notificationevent_changelist'))
        dispatch_response = self.client.get(reverse('admin:accounts_notificationdispatch_changelist'))
        push_device_response = self.client.get(reverse('admin:accounts_pushdevice_changelist'))
        privacy_response = self.client.get(reverse('admin:accounts_dataprivacyrequest_changelist'))

        self.assertEqual(preference_response.status_code, 200)
        self.assertEqual(event_response.status_code, 200)
        self.assertEqual(dispatch_response.status_code, 200)
        self.assertEqual(push_device_response.status_code, 200)
        self.assertEqual(privacy_response.status_code, 200)
        self.assertContains(preference_response, 'community_interaction_updates_enabled')
        self.assertContains(event_response, 'course-post-published:admin-check')
        self.assertContains(dispatch_response, 'course-post-published:admin-check')
        self.assertContains(push_device_response, 'pref-admin@example.com')
        self.assertContains(privacy_response, 'Retenção de comunidade e reports para moderação.')

    def test_notification_event_admin_is_read_only(self):
        event = NotificationEvent.objects.create(
            event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
            dedup_key='admin-read-only-event',
            title='Evento somente leitura',
            payload={'source': 'test'},
        )

        add_response = self.client.get(reverse('admin:accounts_notificationevent_add'))
        change_response = self.client.get(reverse('admin:accounts_notificationevent_change', args=[event.id]))

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'Rastreabilidade')
        self.assertNotContains(change_response, 'name="_save"', html=False)

    def test_notification_dispatch_admin_is_read_only(self):
        target_user = User.objects.create_user(
            username='dispatch-admin@example.com',
            email='dispatch-admin@example.com',
            password='StrongPass123',
        )
        event = NotificationEvent.objects.create(
            event_type=NotificationEvent.EventType.CONTENT_PUBLISHED,
            dedup_key='admin-read-only-dispatch',
            title='Evento dispatch leitura',
            payload={'source': 'test'},
        )
        dispatch = NotificationDispatch.objects.create(
            event=event,
            user=target_user,
            status=NotificationDispatch.Status.PENDING,
        )

        add_response = self.client.get(reverse('admin:accounts_notificationdispatch_add'))
        change_response = self.client.get(reverse('admin:accounts_notificationdispatch_change', args=[dispatch.id]))

        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'Envio')
        self.assertNotContains(change_response, 'name="_save"', html=False)

    def test_auth_domain_foundation_models_are_registered_in_admin(self):
        target_user = User.objects.create_user(
            username='legal-admin@example.com',
            email='legal-admin@example.com',
            password='StrongPass123',
        )
        Profile.objects.create(user=target_user, full_name='Usuário Legal')
        identity = ExternalIdentity.objects.create(
            user=target_user,
            provider=ExternalIdentity.Provider.GOOGLE,
            provider_subject='google-admin-subject',
            email='legal-admin@example.com',
            email_verified=True,
            display_name='Usuário Google',
        )
        document = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.28',
            title='Termos Beta',
            content_html='<p>Termos beta</p>',
            is_active=True,
        )
        acceptance = UserLegalAcceptance.objects.create(
            user=target_user,
            document=document,
            source=UserLegalAcceptance.Source.LOGIN_GATE,
        )

        identity_response = self.client.get(reverse('admin:accounts_externalidentity_changelist'))
        document_response = self.client.get(reverse('admin:accounts_legaldocumentversion_changelist'))
        acceptance_response = self.client.get(reverse('admin:accounts_userlegalacceptance_changelist'))

        self.assertEqual(identity_response.status_code, 200)
        self.assertEqual(document_response.status_code, 200)
        self.assertEqual(acceptance_response.status_code, 200)
        self.assertContains(identity_response, identity.display_name)
        self.assertContains(document_response, 'Termos Beta')
        self.assertContains(acceptance_response, f'{document.get_document_type_display()} v{document.version}')
        self.assertContains(acceptance_response, acceptance.user.email)

    def test_external_identity_and_legal_acceptance_admin_are_read_only(self):
        target_user = User.objects.create_user(
            username='readonly-admin@example.com',
            email='readonly-admin@example.com',
            password='StrongPass123',
        )
        identity = ExternalIdentity.objects.create(
            user=target_user,
            provider=ExternalIdentity.Provider.GOOGLE,
            provider_subject='google-readonly-subject',
        )
        document = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
            version='2026.04.28',
            title='Política Beta',
            content_html='<p>Política beta</p>',
            is_active=True,
        )
        acceptance = UserLegalAcceptance.objects.create(
            user=target_user,
            document=document,
            source=UserLegalAcceptance.Source.LOGIN_GATE,
        )

        identity_add_response = self.client.get(reverse('admin:accounts_externalidentity_add'))
        identity_change_response = self.client.get(reverse('admin:accounts_externalidentity_change', args=[identity.id]))
        acceptance_add_response = self.client.get(reverse('admin:accounts_userlegalacceptance_add'))
        acceptance_change_response = self.client.get(reverse('admin:accounts_userlegalacceptance_change', args=[acceptance.id]))

        self.assertEqual(identity_add_response.status_code, 403)
        self.assertEqual(identity_change_response.status_code, 200)
        self.assertNotContains(identity_change_response, 'name="_save"', html=False)
        self.assertEqual(acceptance_add_response.status_code, 403)
        self.assertEqual(acceptance_change_response.status_code, 200)
        self.assertNotContains(acceptance_change_response, 'name="_save"', html=False)

    def test_legal_document_admin_change_form_explains_active_version_rollover(self):
        active_document = LegalDocumentVersion.objects.create(
            document_type=LegalDocumentVersion.DocumentType.TERMS_OF_USE,
            version='2026.04.28',
            title='Termos Beta',
            content_html='<p>Texto</p>',
            is_active=True,
        )

        response = self.client.get(reverse('admin:accounts_legaldocumentversion_add'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Se voce publicar uma nova versao ativa do mesmo tipo de documento, a versao ativa anterior sera desativada automaticamente.',
        )
        self.assertContains(response, 'lv-legal-document-version-admin-state')
        self.assertContains(response, active_document.title)


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
        self.assertIn('X-Request-ID', response)
        self.assertIn('X-Response-Time-ms', response)

    def test_readyz_returns_ok_when_dependencies_respond(self):
        response = self.client.get('/readyz/')
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['app'], 'livro-vivo-api')
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

    def test_health_preserves_incoming_request_id(self):
        response = self.client.get('/healthz/', HTTP_X_REQUEST_ID='test-request-id-123')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Request-ID'], 'test-request-id-123')

    def test_health_replaces_invalid_incoming_request_id(self):
        response = self.client.get('/healthz/', HTTP_X_REQUEST_ID='request id with spaces')

        self.assertEqual(response.status_code, 200)
        self.assertRegex(response['X-Request-ID'], r'^[a-f0-9]{32}$')


class AccountViewHelperTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().post('/auth/login/')

    def test_authenticate_user_by_email_resolves_username_fallback(self):
        user = User.objects.create_user(
            username='usuario-login',
            email='login@example.com',
            password='StrongPass123',
        )

        authenticated = authenticate_user_by_email(self.request, 'LOGIN@example.com', 'StrongPass123')

        self.assertEqual(authenticated, user)

    def test_authenticate_user_by_email_allows_inactive_user_with_valid_password(self):
        user = User.objects.create_user(
            username='banido-login',
            email='inactive@example.com',
            password='StrongPass123',
            is_active=False,
        )

        authenticated = authenticate_user_by_email(self.request, 'inactive@example.com', 'StrongPass123')

        self.assertEqual(authenticated, user)

    def test_authenticate_user_by_email_returns_none_for_invalid_password(self):
        User.objects.create_user(
            username='usuario-invalido',
            email='invalid@example.com',
            password='StrongPass123',
            is_active=False,
        )

        authenticated = authenticate_user_by_email(self.request, 'invalid@example.com', 'senha-errada')

        self.assertIsNone(authenticated)

    def test_serialize_user_payload_exposes_only_public_avatar_fields(self):
        user = User.objects.create_user(
            username='perfil@example.com',
            email='perfil@example.com',
            password='StrongPass123',
        )
        profile = Profile.objects.create(
            user=user,
            full_name='Perfil Público',
            profession='Advogada',
            avatar_url='https://cdn.example.com/avatar.jpg',
            role=Profile.Role.MODERATOR,
        )

        payload = serialize_user_payload(user, profile, request=None)

        self.assertEqual(payload['name'], 'Perfil Público')
        self.assertEqual(payload['profession'], 'Advogada')
        self.assertEqual(payload['avatar_url'], 'https://cdn.example.com/avatar.jpg')
        self.assertEqual(payload['avatar_source'], 'remote_url')
        self.assertEqual(payload['role'], 'moderator')
        self.assertNotIn('storage_key', payload)
        self.assertNotIn('storage_backend', payload)

    def test_build_media_reference_hides_internal_metadata_by_default(self):
        upload_field = SimpleNamespace(name='avatars/teste.png', url='/media/avatars/teste.png')

        reference = build_media_reference(
            upload_field=upload_field,
            request=None,
            storage_alias='avatars',
        )

        self.assertEqual(reference, {'url': '/media/avatars/teste.png', 'source': 'upload'})

    def test_build_media_reference_exposes_internal_metadata_only_when_requested(self):
        upload_field = SimpleNamespace(name='avatars/teste.png', url='/media/avatars/teste.png')

        reference = build_media_reference(
            upload_field=upload_field,
            request=None,
            storage_alias='avatars',
            include_internal_metadata=True,
        )

        self.assertEqual(reference['url'], '/media/avatars/teste.png')
        self.assertEqual(reference['source'], 'upload')
        self.assertEqual(reference['storage_key'], 'avatars/teste.png')
        self.assertEqual(reference['storage_alias'], 'avatars')
        self.assertIn('storage_backend', reference)
        self.assertIn('cache_control', reference)
