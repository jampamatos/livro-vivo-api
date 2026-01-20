from datetime import timedelta
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APIRequestFactory

from entitlements.models import Entitlement
from .models import Book, BookVersion, PageText
from .permissions import HasActiveBookEntitlement
from .views import _make_snippet

User = get_user_model()


class LibraryBaseTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()

    def _create_user(self, email='user@example.com', is_staff=False):
        user = User.objects.create_user(
            username=email,
            email=email,
            password='StrongPass123',
        )
        user.is_staff = is_staff
        user.save(update_fields=['is_staff'])
        return user

    def _auth_client(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return self.client

    def _grant_entitlement(self, user, product=Entitlement.Product.BOOK, status=Entitlement.Status.ACTIVE, expires_at=None):
        return Entitlement.objects.create(
            user=user,
            product=product,
            status=status,
            expires_at=expires_at,
        )

    def _temp_media(self):
        media_dir = tempfile.mkdtemp(prefix='media-')
        self.addCleanup(lambda: shutil.rmtree(media_dir, ignore_errors=True))
        return self.settings(MEDIA_ROOT=media_dir)


class LibraryModelTests(LibraryBaseTestCase):
    def test_book_version_unique_constraint(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

    def test_page_text_unique_constraint(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        PageText.objects.create(book_version=version, page_number=1, text='Hello')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PageText.objects.create(book_version=version, page_number=1, text='Dup')


class LibraryPermissionTests(LibraryBaseTestCase):
    def test_permission_denies_anonymous(self):
        request = self.factory.get('/books/')
        request.user = AnonymousUser()
        permission = HasActiveBookEntitlement()

        self.assertFalse(permission.has_permission(request, None))

    def test_permission_allows_staff(self):
        user = self._create_user(is_staff=True)
        request = self.factory.get('/books/')
        request.user = user
        permission = HasActiveBookEntitlement()

        self.assertTrue(permission.has_permission(request, None))

    def test_permission_allows_active_entitlement(self):
        user = self._create_user()
        self._grant_entitlement(user, expires_at=timezone.now() + timedelta(days=1))
        request = self.factory.get('/books/')
        request.user = user
        permission = HasActiveBookEntitlement()

        self.assertTrue(permission.has_permission(request, None))

    def test_permission_denies_expired_entitlement(self):
        user = self._create_user()
        self._grant_entitlement(user, expires_at=timezone.now() - timedelta(days=1))
        request = self.factory.get('/books/')
        request.user = user
        permission = HasActiveBookEntitlement()

        self.assertFalse(permission.has_permission(request, None))


class LibrarySnippetTests(LibraryBaseTestCase):
    def test_make_snippet_with_match(self):
        text = 'Hello world, this is a long text for testing snippets.'
        snippet = _make_snippet(text, 'long', window=5)

        self.assertIn('long', snippet)
        self.assertTrue(snippet.startswith('...'))

    def test_make_snippet_without_match(self):
        text = 'Hello world, this is a long text for testing snippets.'
        snippet = _make_snippet(text, 'missing', window=5)

        self.assertTrue(snippet.endswith('...'))


class LibraryAPITests(LibraryBaseTestCase):
    def test_book_list_filters_for_non_staff(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        published = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)

        response = self.client.get(reverse('book-list'))

        self.assertEqual(response.status_code, 200)
        books = response.data['books']
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]['id'], published.id)

    def test_book_list_includes_all_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)

        draft = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        published = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)

        response = self.client.get(reverse('book-list'))

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data['books']}
        self.assertEqual(ids, {draft.id, published.id})

    def test_book_version_list_hides_unpublished_book_for_non_staff(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 404)

    def test_book_version_list_filters_versions_for_non_staff(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        published = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        versions = response.data['versions']
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['id'], published.id)

    def test_book_version_list_all_versions_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        draft = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)
        published = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data['versions']}
        self.assertEqual(ids, {draft.id, published.id})

    def test_download_url_requires_published_for_non_staff(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Draft', status=Book.Status.PUBLISHED)
        draft = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)

        response = self.client.get(
            reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': draft.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_download_url_returns_url_when_pdf_present(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/books/{book.id}/versions/{version.id}/download/', response.data['url'])

    def test_download_url_returns_404_when_no_pdf(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(
            reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_download_file_response(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            response = self.client.get(
                reverse('book-version-download', kwargs={'book_id': book.id, 'version_id': version.id})
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="test.pdf"', response.headers.get('Content-Disposition', ''))

    def test_search_validation_errors(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        response = self.client.get(reverse('search'))
        self.assertEqual(response.status_code, 400)

        response = self.client.get(reverse('search'), {'q': 'a', 'book_id': 1})
        self.assertEqual(response.status_code, 400)

        response = self.client.get(reverse('search'), {'q': 'abc'})
        self.assertEqual(response.status_code, 400)

        response = self.client.get(reverse('search'), {'q': 'abc', 'book_version_id': 'nope'})
        self.assertEqual(response.status_code, 400)

        response = self.client.get(reverse('search'), {'q': 'abc', 'book_id': 'nope'})
        self.assertEqual(response.status_code, 400)

    def test_search_filters_non_staff_to_published(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        published_version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        draft_version = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)

        PageText.objects.create(book_version=published_version, page_number=1, text='Hello world')
        PageText.objects.create(book_version=draft_version, page_number=1, text='Hello world')

        response = self.client.get(
            reverse('search'),
            {'q': 'hello', 'book_id': book.id, 'limit': 200, 'offset': -1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['limit'], 100)
        self.assertEqual(response.data['offset'], 0)

    def test_search_includes_draft_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)

        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        version = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)
        PageText.objects.create(book_version=version, page_number=1, text='Hello world')

        response = self.client.get(reverse('search'), {'q': 'hello', 'book_version_id': version.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    def test_page_text_view_validation_and_visibility(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)

        response = self.client.get(
            reverse('book-version-page-text', kwargs={'book_id': book.id, 'version_id': version.id, 'page_number': 0})
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            reverse('book-version-page-text', kwargs={'book_id': book.id, 'version_id': version.id, 'page_number': 1})
        )
        self.assertEqual(response.status_code, 404)

    def test_page_text_view_returns_text_for_published(self):
        user = self._create_user()
        self._grant_entitlement(user)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        PageText.objects.create(book_version=version, page_number=1, text='Hello page')

        response = self.client.get(
            reverse('book-version-page-text', kwargs={'book_id': book.id, 'version_id': version.id, 'page_number': 1})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['text'], 'Hello page')


class ExtractPdfTextCommandTests(LibraryBaseTestCase):
    def test_cleanup_removes_noise(self):
        from .management.commands.extract_pdf_text import _cleanup

        text = "Hello\u00a0world\u200b\n\n\nLine 2\t\t"
        cleaned = _cleanup(text)

        self.assertEqual(cleaned, "Hello world\n\nLine 2")

    def test_command_raises_without_pdf(self):
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self.assertRaises(CommandError):
            call_command('extract_pdf_text', book_version_id=version.id, force=True)

    def test_command_raises_when_pymupdf_missing(self):
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self._temp_media():
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            with mock.patch('library.management.commands.extract_pdf_text.fitz', None):
                with self.assertRaises(CommandError):
                    call_command('extract_pdf_text', book_version_id=version.id, force=True)

    def test_command_inserts_page_texts(self):
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self._temp_media():
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            fake_doc = SimpleNamespace(
                page_count=2,
                load_page=lambda index: SimpleNamespace(
                    get_text=lambda mode: [] if mode == 'words' else f"Page {index + 1}"
                ),
            )

            with mock.patch('library.management.commands.extract_pdf_text.fitz', SimpleNamespace(open=lambda _: fake_doc)):
                call_command('extract_pdf_text', book_version_id=version.id, force=True)

        rows = PageText.objects.filter(book_version=version).order_by('page_number')
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.first().text, 'Page 1')

    def test_command_force_replaces_existing_rows(self):
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self._temp_media():
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))
            PageText.objects.create(book_version=version, page_number=1, text='Old')

            fake_doc = SimpleNamespace(
                page_count=1,
                load_page=lambda index: SimpleNamespace(
                    get_text=lambda mode: [] if mode == 'words' else 'New'
                ),
            )

            with mock.patch('library.management.commands.extract_pdf_text.fitz', SimpleNamespace(open=lambda _: fake_doc)):
                call_command('extract_pdf_text', book_version_id=version.id, force=True)

        rows = PageText.objects.filter(book_version=version)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().text, 'New')

class TestCorsHealth(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_has_cors_for_expo_web(self):
        origin = "http://localhost:8081"
        resp = self.client.get("/health/", HTTP_ORIGIN=origin)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), origin)