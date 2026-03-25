import hashlib
import shutil
import tempfile
import time
from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from entitlements.models import Subscription

from .file_metadata import FileMetadata
from .models import PublicationStatus, TemplatePiece

User = get_user_model()


class TemplatesBankApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.professional_user = User.objects.create_user(
            username='professional@example.com',
            email='professional@example.com',
            password='StrongPass123',
        )
        self.essential_user = User.objects.create_user(
            username='essential@example.com',
            email='essential@example.com',
            password='StrongPass123',
        )
        self.staff_user = User.objects.create_superuser(
            username='staff@example.com',
            email='staff@example.com',
            password='StrongPass123',
        )

        now = timezone.now()
        Subscription.objects.create(
            user=self.professional_user,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            started_at=now - timedelta(days=5),
        )
        Subscription.objects.create(
            user=self.essential_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
            started_at=now - timedelta(days=5),
        )

        self.professional_token = str(RefreshToken.for_user(self.professional_user).access_token)
        self.essential_token = str(RefreshToken.for_user(self.essential_user).access_token)
        self.staff_token = str(RefreshToken.for_user(self.staff_user).access_token)

        self.piece_v1 = TemplatePiece.objects.create(
            title='Ação de cobrança v1',
            slug='acao-cobranca-v1',
            template_code='acao-cobranca',
            version='1.0.0',
            changelog='Versão inicial.',
            description='Peça inicial para cobrança.',
            category=TemplatePiece.Category.PETITION,
            tags=['cobranca'],
            file_url='https://example.com/files/acao-cobranca-v1.docx',
            file_name='acao-cobranca-v1.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=10240,
            file_sha256='a' * 64,
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=4),
        )
        self.piece_v2 = TemplatePiece.objects.create(
            title='Ação de cobrança v2',
            slug='acao-cobranca-v2',
            template_code='acao-cobranca',
            version='1.1.0',
            changelog='Atualização com novos fundamentos.',
            description='Versão revisada da peça.',
            category=TemplatePiece.Category.PETITION,
            tags=['cobranca', 'atualizado'],
            file_url='https://example.com/files/acao-cobranca-v2.docx',
            file_name='acao-cobranca-v2.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=12288,
            file_sha256='b' * 64,
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=2),
        )
        self.piece_draft = TemplatePiece.objects.create(
            title='Contrato de locação draft',
            slug='contrato-locacao-draft',
            template_code='contrato-locacao',
            version='0.1.0',
            changelog='Rascunho interno.',
            description='Peça em revisão.',
            category=TemplatePiece.Category.CONTRACT,
            file_url='https://example.com/files/contrato-locacao-draft.docx',
            file_name='contrato-locacao-draft.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=8096,
            file_sha256='c' * 64,
            status=PublicationStatus.DRAFT,
        )

    def _auth(self, token: str):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_list_requires_authentication(self):
        response = self.client.get('/templates-bank/templates/')
        self.assertIn(response.status_code, (401, 403))

    def test_list_blocks_essential_tier(self):
        self._auth(self.essential_token)
        response = self.client.get('/templates-bank/templates/')
        self.assertEqual(response.status_code, 403)

    def test_list_for_professional_excludes_drafts(self):
        self._auth(self.professional_token)
        response = self.client.get('/templates-bank/templates/')
        self.assertEqual(response.status_code, 200)

        ids = {item['id'] for item in response.data}
        self.assertIn(self.piece_v1.id, ids)
        self.assertIn(self.piece_v2.id, ids)
        self.assertNotIn(self.piece_draft.id, ids)

    def test_list_staff_can_see_drafts(self):
        self._auth(self.staff_token)
        response = self.client.get('/templates-bank/templates/')
        self.assertEqual(response.status_code, 200)

        ids = {item['id'] for item in response.data}
        self.assertIn(self.piece_draft.id, ids)

    def test_filters_status_category_code_and_date(self):
        self._auth(self.professional_token)
        response = self.client.get(
            '/templates-bank/templates/',
            {
                'status': PublicationStatus.PUBLISHED,
                'category': TemplatePiece.Category.PETITION,
                'template_code': 'acao-cobranca',
                'date_from': (timezone.now() + timedelta(days=1)).date().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

        response_all = self.client.get(
            '/templates-bank/templates/',
            {
                'category': TemplatePiece.Category.PETITION,
                'template_code': 'acao-cobranca',
            },
        )
        self.assertEqual(response_all.status_code, 200)
        self.assertEqual(len(response_all.data), 2)

    def test_invalid_date_filter_returns_400(self):
        self._auth(self.professional_token)
        response = self.client.get('/templates-bank/templates/', {'date_from': '31-12-2026'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('date_from', response.data)

    def test_professional_cannot_retrieve_draft_piece(self):
        self._auth(self.professional_token)
        response = self.client.get(f'/templates-bank/templates/{self.piece_draft.id}/')
        self.assertEqual(response.status_code, 404)

    def test_professional_cannot_create_piece(self):
        self._auth(self.professional_token)
        payload = {
            'title': 'Novo modelo',
            'slug': 'novo-modelo',
            'template_code': 'novo-modelo',
            'version': '1.0.0',
            'category': TemplatePiece.Category.OTHER,
            'file_url': 'https://example.com/files/novo-modelo.docx',
            'file_name': 'novo-modelo.docx',
            'status': PublicationStatus.PUBLISHED,
        }
        response = self.client.post('/templates-bank/templates/', payload, format='json')
        self.assertEqual(response.status_code, 403)

    def test_staff_can_create_piece(self):
        self._auth(self.staff_token)
        payload = {
            'title': 'Modelo novo',
            'slug': 'modelo-novo',
            'template_code': 'modelo-novo',
            'version': '1.0.0',
            'changelog': 'Versão inicial.',
            'description': 'Peça nova.',
            'category': TemplatePiece.Category.MOTION,
            'tags': ['novo'],
            'file_url': 'https://example.com/files/modelo-novo.docx',
            'file_name': 'modelo-novo.docx',
            'file_mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'file_size_bytes': 9000,
            'file_sha256': 'd' * 64,
            'status': PublicationStatus.PUBLISHED,
        }
        response = self.client.post('/templates-bank/templates/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['template_code'], 'modelo-novo')

    def test_duplicate_code_and_version_is_rejected(self):
        self._auth(self.staff_token)
        payload = {
            'title': 'Duplicado',
            'slug': 'duplicado',
            'template_code': self.piece_v1.template_code,
            'version': self.piece_v1.version,
            'category': TemplatePiece.Category.PETITION,
            'file_url': 'https://example.com/files/duplicado.docx',
            'file_name': 'duplicado.docx',
            'status': PublicationStatus.DRAFT,
        }
        response = self.client.post('/templates-bank/templates/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('non_field_errors', response.data)

    def test_professional_can_generate_download_token(self):
        self._auth(self.professional_token)
        response = self.client.get(f'/templates-bank/templates/{self.piece_v2.id}/download-token/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('token', response.data)
        self.assertIn('download_url', response.data)
        self.assertIn('/templates-bank/templates/', response.data['download_url'])
        self.assertIn('/download/', response.data['download_url'])

    def test_download_returns_file_metadata_with_valid_token(self):
        self._auth(self.professional_token)
        token_response = self.client.get(f'/templates-bank/templates/{self.piece_v2.id}/download-token/')
        token = token_response.data['token']

        response = self.client.get(f'/templates-bank/templates/{self.piece_v2.id}/download/', {'token': token})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.piece_v2.id)
        self.assertEqual(response.data['file_url'], self.piece_v2.file_url)
        self.assertEqual(response.data['file_name'], self.piece_v2.file_name)
        self.assertEqual(response.data['file_source'], 'remote_url')
        self.assertIsNone(response.data['file_storage_key'])
        self.assertEqual(response.data['file_storage_backend'], 'external_url')

    def test_download_blocks_essential_even_with_token_from_other_user(self):
        self._auth(self.professional_token)
        token_response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download-token/')
        token = token_response.data['token']

        self._auth(self.essential_token)
        response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download/', {'token': token})
        self.assertEqual(response.status_code, 403)

    def test_download_requires_token(self):
        self._auth(self.professional_token)
        response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('token', response.data)

    def test_download_rejects_invalid_token(self):
        self._auth(self.professional_token)
        response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download/', {'token': 'invalid'})
        self.assertEqual(response.status_code, 403)

    def test_download_rejects_token_for_other_piece(self):
        self._auth(self.professional_token)
        token_response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download-token/')
        token = token_response.data['token']

        response = self.client.get(f'/templates-bank/templates/{self.piece_v2.id}/download/', {'token': token})
        self.assertEqual(response.status_code, 403)

    @override_settings(TEMPLATES_BANK_DOWNLOAD_TOKEN_MAX_AGE_SECONDS=1)
    def test_download_rejects_expired_token(self):
        self._auth(self.professional_token)
        token_response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download-token/')
        token = token_response.data['token']

        time.sleep(1.1)

        response = self.client.get(f'/templates-bank/templates/{self.piece_v1.id}/download/', {'token': token})
        self.assertEqual(response.status_code, 403)

    def test_download_returns_media_url_for_uploaded_file(self):
        with tempfile.TemporaryDirectory(prefix='templates-bank-api-media-') as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                upload_piece = TemplatePiece.objects.create(
                    title='Modelo Upload API',
                    slug='modelo-upload-api',
                    template_code='modelo-upload-api',
                    version='1.0.0',
                    category=TemplatePiece.Category.OTHER,
                    file_upload=SimpleUploadedFile(
                        'modelo-upload-api.docx',
                        b'conteudo para download seguro',
                        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    ),
                    status=PublicationStatus.PUBLISHED,
                )

                self._auth(self.professional_token)
                token_response = self.client.get(f'/templates-bank/templates/{upload_piece.id}/download-token/')
                token = token_response.data['token']
                response = self.client.get(f'/templates-bank/templates/{upload_piece.id}/download/', {'token': token})

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data['file_url'].startswith('http://testserver/media/templates_bank/uploads/'))
                self.assertEqual(response.data['file_name'], 'modelo-upload-api.docx')
                self.assertEqual(response.data['file_source'], 'upload')
                self.assertEqual(response.data['file_storage_alias'], 'template_uploads')
                self.assertEqual(response.data['file_storage_backend'], 'filesystem')
                self.assertTrue(response.data['file_storage_key'].startswith('templates_bank/uploads/'))

    def test_templates_bank_endpoints_are_throttled(self):
        cache.clear()
        self._auth(self.professional_token)

        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'templates_bank_api': '1/min'}):
            first = self.client.get('/templates-bank/templates/')
            second = self.client.get('/templates-bank/templates/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class TemplatesBankAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.client.force_login(self.admin_user)
        self.piece = TemplatePiece.objects.create(
            title='Modelo Admin',
            slug='modelo-admin',
            template_code='modelo-admin',
            version='1.0.0',
            category=TemplatePiece.Category.OTHER,
            file_url='https://example.com/files/modelo-admin.docx',
            file_name='modelo-admin.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=1024,
            file_sha256='e' * 64,
            status=PublicationStatus.PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
        )

    def test_model_registered_in_admin(self):
        self.assertIn(TemplatePiece, site._registry)

    def test_change_form_is_accessible(self):
        response = self.client.get(reverse('admin:templates_bank_templatepiece_change', args=[self.piece.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'template_code')
        self.assertContains(response, 'file_name')
        self.assertContains(response, 'file_upload')

    def _create_draft_piece(self, *, slug: str, changelog: str):
        return TemplatePiece.objects.create(
            title=f'Modelo {slug}',
            slug=slug,
            template_code=slug,
            version='0.1.0',
            category=TemplatePiece.Category.OTHER,
            file_url=f'https://example.com/files/{slug}.docx',
            file_name=f'{slug}.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=2048,
            file_sha256='f' * 64,
            changelog=changelog,
            status=PublicationStatus.DRAFT,
        )

    def test_bulk_publish_requires_sensitive_confirmation(self):
        draft_piece = self._create_draft_piece(slug='modelo-sem-confirmacao', changelog='Ajustes iniciais')

        response = self.client.post(
            reverse('admin:templates_bank_templatepiece_changelist'),
            data={
                'action': 'mark_published',
                '_selected_action': [str(draft_piece.id)],
                'select_across': '0',
                'index': '0',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft_piece.refresh_from_db()
        self.assertEqual(draft_piece.status, PublicationStatus.DRAFT)
        self.assertContains(response, 'Confirme a ação sensível para publicar peças em massa.')

    def test_bulk_publish_requires_changelog(self):
        draft_piece = self._create_draft_piece(slug='modelo-sem-changelog', changelog='')

        response = self.client.post(
            reverse('admin:templates_bank_templatepiece_changelist'),
            data={
                'action': 'mark_published',
                '_selected_action': [str(draft_piece.id)],
                'select_across': '0',
                'index': '0',
                'confirm_sensitive_action': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft_piece.refresh_from_db()
        self.assertEqual(draft_piece.status, PublicationStatus.DRAFT)
        self.assertContains(response, 'changelog vazio')

    def test_bulk_publish_updates_status_when_confirmed(self):
        draft_piece = self._create_draft_piece(slug='modelo-com-confirmacao', changelog='Versão para publicar')

        response = self.client.post(
            reverse('admin:templates_bank_templatepiece_changelist'),
            data={
                'action': 'mark_published',
                '_selected_action': [str(draft_piece.id)],
                'select_across': '0',
                'index': '0',
                'confirm_sensitive_action': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft_piece.refresh_from_db()
        self.assertEqual(draft_piece.status, PublicationStatus.PUBLISHED)
        self.assertIsNotNone(draft_piece.published_at)


class TemplatesBankFileMetadataTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp(prefix='templates-bank-tests-')
        self.override_media = override_settings(MEDIA_ROOT=self.media_dir)
        self.override_media.enable()

    def tearDown(self):
        self.override_media.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def test_upload_auto_generates_file_metadata(self):
        payload = b'modelo de peca para upload'
        upload = SimpleUploadedFile(
            'modelo-upload.docx',
            payload,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        piece = TemplatePiece.objects.create(
            title='Modelo Upload',
            slug='modelo-upload',
            template_code='modelo-upload',
            version='1.0.0',
            category=TemplatePiece.Category.OTHER,
            file_upload=upload,
            status=PublicationStatus.DRAFT,
        )

        self.assertEqual(piece.file_url, '')
        self.assertEqual(piece.file_name, 'modelo-upload.docx')
        self.assertEqual(
            piece.file_mime_type,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertEqual(piece.file_size_bytes, len(payload))
        self.assertEqual(piece.file_sha256, hashlib.sha256(payload).hexdigest())

    @patch('templates_bank.models.fetch_remote_file_metadata')
    def test_remote_url_auto_generates_file_metadata(self, fetch_remote_metadata_mock):
        fetch_remote_metadata_mock.return_value = FileMetadata(
            file_name='modelo-remoto.docx',
            file_mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size_bytes=4096,
            file_sha256='f' * 64,
        )

        piece = TemplatePiece.objects.create(
            title='Modelo Remoto',
            slug='modelo-remoto',
            template_code='modelo-remoto',
            version='1.0.0',
            category=TemplatePiece.Category.OTHER,
            file_url='https://files.example.com/modelo-remoto.docx',
            status=PublicationStatus.DRAFT,
        )

        fetch_remote_metadata_mock.assert_called_once_with(
            'https://files.example.com/modelo-remoto.docx',
            timeout_seconds=8,
            max_bytes=30 * 1024 * 1024,
        )
        self.assertEqual(piece.file_name, 'modelo-remoto.docx')
        self.assertEqual(
            piece.file_mime_type,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertEqual(piece.file_size_bytes, 4096)
        self.assertEqual(piece.file_sha256, 'f' * 64)

    def test_rejects_when_no_file_source_is_provided(self):
        with self.assertRaises(ValidationError):
            TemplatePiece.objects.create(
                title='Sem Arquivo',
                slug='sem-arquivo',
                template_code='sem-arquivo',
                version='1.0.0',
                category=TemplatePiece.Category.OTHER,
                status=PublicationStatus.DRAFT,
            )

    def test_rejects_when_upload_and_remote_url_are_provided_together(self):
        upload = SimpleUploadedFile(
            'modelo-conflito.docx',
            b'conteudo',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        with self.assertRaises(ValidationError):
            TemplatePiece.objects.create(
                title='Fonte Duplicada',
                slug='fonte-duplicada',
                template_code='fonte-duplicada',
                version='1.0.0',
                category=TemplatePiece.Category.OTHER,
                file_upload=upload,
                file_url='https://files.example.com/modelo-conflito.docx',
                status=PublicationStatus.DRAFT,
            )

    def test_rejects_remote_url_with_unsupported_scheme(self):
        with self.assertRaises(ValidationError):
            TemplatePiece.objects.create(
                title='URL invalida',
                slug='url-invalida',
                template_code='url-invalida',
                version='1.0.0',
                category=TemplatePiece.Category.OTHER,
                file_url='ftp://files.example.com/modelo.docx',
                status=PublicationStatus.DRAFT,
            )

    def test_rejects_remote_url_pointing_to_local_network(self):
        with self.assertRaises(ValidationError):
            TemplatePiece.objects.create(
                title='URL local',
                slug='url-local',
                template_code='url-local',
                version='1.0.0',
                category=TemplatePiece.Category.OTHER,
                file_url='http://127.0.0.1/modelo.docx',
                status=PublicationStatus.DRAFT,
            )
