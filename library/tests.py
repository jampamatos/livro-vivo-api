from datetime import timedelta
import shutil
import tempfile
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from entitlements.models import Entitlement

from .models import Book, BookChapter, BookVersion, PageText
from .permissions import HasActiveBookEntitlement
from .views import (
    DOWNLOAD_URL_SIGNING_SALT,
    DOWNLOAD_URL_TOKEN_PARAM,
    _make_snippet,
)

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
        access = str(RefreshToken.for_user(user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        return self.client

    def _grant_entitlement(
        self,
        user,
        product=Entitlement.Product.BOOK,
        status=Entitlement.Status.ACTIVE,
        expires_at=None,
        book=None,
    ):
        if product == Entitlement.Product.BOOK and book is None:
            book = Book.objects.create(title='Entitled', status=Book.Status.DRAFT)
        if product == Entitlement.Product.SUBSCRIPTION:
            book = None

        return Entitlement.objects.create(
            user=user,
            product=product,
            book=book,
            status=status,
            expires_at=expires_at,
        )

    def _temp_media(self):
        media_dir = tempfile.mkdtemp(prefix='media-')
        self.addCleanup(lambda: shutil.rmtree(media_dir, ignore_errors=True))
        return self.settings(MEDIA_ROOT=media_dir)

    def _path_with_query(self, absolute_url: str) -> str:
        parsed = urlsplit(absolute_url)
        if parsed.query:
            return f'{parsed.path}?{parsed.query}'
        return parsed.path


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

    def test_book_chapter_unique_constraints_per_version(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Intro',
            slug='introducao',
            content_rich='<h1>Introdução</h1><p>Conteúdo</p>',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookChapter.objects.create(
                    book_version=version,
                    order=2,
                    title='Outra intro',
                    slug='introducao',
                    content_rich='<p>Duplicado por slug</p>',
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookChapter.objects.create(
                    book_version=version,
                    order=1,
                    title='Capítulo 1',
                    slug='capitulo-1',
                    content_rich='<p>Duplicado por ordem</p>',
                )

    def test_book_chapter_allows_same_slug_in_different_versions(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        v1 = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        v2 = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)

        BookChapter.objects.create(
            book_version=v1,
            order=1,
            title='Intro',
            slug='introducao',
            content_rich='<p>v1</p>',
        )
        BookChapter.objects.create(
            book_version=v2,
            order=1,
            title='Intro',
            slug='introducao',
            content_rich='<p>v2</p>',
        )

        self.assertEqual(BookChapter.objects.filter(slug='introducao').count(), 2)

    def test_book_chapter_content_plain_is_generated_and_updated(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Intro',
            slug='intro',
            content_rich='<h1>Olá&nbsp;Mundo</h1><p>Linha <strong>um</strong></p>',
        )

        self.assertEqual(chapter.content_plain, 'Olá Mundo Linha um')

        chapter.content_rich = '<p>Texto <em>atualizado</em> &amp; limpo.</p>'
        chapter.save()
        chapter.refresh_from_db()

        self.assertEqual(chapter.content_plain, 'Texto atualizado & limpo.')

    def test_book_chapter_default_ordering(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(book_version=version, order=2, title='B', slug='b', content_rich='<p>B</p>')
        BookChapter.objects.create(book_version=version, order=1, title='A', slug='a', content_rich='<p>A</p>')

        orders = list(BookChapter.objects.filter(book_version=version).values_list('order', flat=True))
        self.assertEqual(orders, [1, 2])

    def test_book_chapter_sanitizes_disallowed_tags_and_attrs(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Segurança',
            slug='seguranca',
            content_rich=(
                '<h2 onclick="alert(1)">Título</h2>'
                '<p>Texto com <a href="javascript:alert(1)" target="_blank">link ruim</a></p>'
                '<p>Texto com <a href="https://example.com" target="_blank">link bom</a></p>'
                '<script>alert("xss")</script>'
            ),
        )

        self.assertNotIn('onclick', chapter.content_rich)
        self.assertNotIn('<script', chapter.content_rich)
        self.assertNotIn('javascript:', chapter.content_rich)
        self.assertIn('<h2>Título</h2>', chapter.content_rich)
        self.assertIn('href="https://example.com"', chapter.content_rich)
        self.assertIn('rel="noopener noreferrer"', chapter.content_rich)
        self.assertNotIn('alert("xss")', chapter.content_plain)

    def test_book_chapter_sanitizer_drops_wrapper_tags_and_keeps_text(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Limpeza',
            slug='limpeza',
            content_rich='<div><span>Texto <em>válido</em></span></div>',
        )

        self.assertEqual(chapter.content_rich, '<p>Texto <em>válido</em></p>')
        self.assertEqual(chapter.content_plain, 'Texto válido')

    def test_book_chapter_sanitizer_normalizes_div_lines_into_paragraphs(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Linhas',
            slug='linhas',
            content_rich='<div>Test B</div><div>Test I</div><div>Test U</div>',
        )

        self.assertEqual(chapter.content_rich, '<p>Test B</p><p>Test I</p><p>Test U</p>')
        self.assertEqual(chapter.content_plain, 'Test B Test I Test U')

    def test_book_chapter_sanitizer_flattens_div_wrappers_inside_list_items(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Listas',
            slug='listas',
            content_rich='<ul><li><div>Item 1</div></li><li><div>Item 2</div></li></ul>',
        )

        self.assertEqual(chapter.content_rich, '<ul><li>Item 1</li><li>Item 2</li></ul>')
        self.assertEqual(chapter.content_plain, 'Item 1 Item 2')


class LibraryAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.client.force_login(self.admin_user)

        self.book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        self.version = BookVersion.objects.create(
            book=self.book,
            version='2024.01',
            status=BookVersion.Status.PUBLISHED,
        )
        self.chapter = BookChapter.objects.create(
            book_version=self.version,
            order=1,
            title='Introdução',
            slug='introducao',
            content_rich='<p>Conteúdo inicial</p>',
        )

    def test_book_chapter_admin_changelist_renders_preview_and_order(self):
        response = self.client.get(reverse('admin:library_bookchapter_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'introducao')
        self.assertContains(response, 'Conteúdo inicial')
        self.assertContains(response, 'id="id_form-0-order"')

    def test_book_chapter_admin_change_form_updates_and_sanitizes_content(self):
        response = self.client.post(
            reverse('admin:library_bookchapter_change', args=[self.chapter.id]),
            data={
                'book_version': self.version.id,
                'order': 2,
                'title': 'Introdução revisada',
                'slug': 'introducao-revisada',
                'content_rich': '<p onclick="alert(1)">Novo texto</p><script>alert("x")</script>',
                '_save': 'Save',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.order, 2)
        self.assertEqual(self.chapter.title, 'Introdução revisada')
        self.assertEqual(self.chapter.slug, 'introducao-revisada')
        self.assertEqual(self.chapter.content_rich, '<p>Novo texto</p>')
        self.assertEqual(self.chapter.content_plain, 'Novo texto')

    def test_book_chapter_admin_change_form_loads_rich_editor_assets(self):
        response = self.client.get(reverse('admin:library_bookchapter_change', args=[self.chapter.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'library/admin/chapter_rich_editor.js')
        self.assertContains(response, 'library/admin/chapter_rich_editor.css')
        self.assertContains(response, 'Tags permitidas:')
        self.assertContains(response, 'Tags permitidas: a, blockquote, br')


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

    def test_permission_allows_active_subscription_entitlement(self):
        user = self._create_user()
        self._grant_entitlement(
            user,
            product=Entitlement.Product.SUBSCRIPTION,
            expires_at=timezone.now() + timedelta(days=1),
        )
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

    def test_permission_denies_revoked_entitlement(self):
        user = self._create_user()
        self._grant_entitlement(
            user,
            status=Entitlement.Status.REVOKED,
            expires_at=timezone.now() + timedelta(days=1),
        )
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
        Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        published = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=published)
        self._auth_client(user)

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

    def test_book_list_with_subscription_includes_all_published_books(self):
        user = self._create_user()
        self._grant_entitlement(user, product=Entitlement.Product.SUBSCRIPTION)
        self._auth_client(user)

        Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        published1 = Book.objects.create(title='Published 1', status=Book.Status.PUBLISHED)
        published2 = Book.objects.create(title='Published 2', status=Book.Status.PUBLISHED)

        response = self.client.get(reverse('book-list'))

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data['books']}
        self.assertEqual(ids, {published1.id, published2.id})

    def test_book_version_list_hides_unpublished_book_for_non_staff(self):
        user = self._create_user()
        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 404)

    def test_book_version_list_filters_versions_for_non_staff(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
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

    def test_book_version_list_allows_subscription_without_book_entitlement(self):
        user = self._create_user()
        self._grant_entitlement(user, product=Entitlement.Product.SUBSCRIPTION)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        published = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        versions = response.data['versions']
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['id'], published.id)

    def test_download_url_requires_published_for_non_staff(self):
        user = self._create_user()
        book = Book.objects.create(title='Draft', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        draft = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)

        response = self.client.get(
            reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': draft.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_download_url_returns_url_when_pdf_present(self):
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user, book=book)
            self._auth_client(user)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/books/{book.id}/versions/{version.id}/download/', response.data['url'])
        parsed = urlsplit(response.data['url'])
        query = parse_qs(parsed.query)
        signed_token = query.get(DOWNLOAD_URL_TOKEN_PARAM, [None])[0]
        self.assertIsNotNone(signed_token)
        payload = signing.loads(
            signed_token,
            salt=DOWNLOAD_URL_SIGNING_SALT,
            max_age=settings.LIBRARY_DOWNLOAD_URL_TTL_SECONDS,
        )
        self.assertEqual(payload['u'], user.id)
        self.assertEqual(payload['b'], book.id)
        self.assertEqual(payload['v'], version.id)

    def test_download_url_returns_404_when_no_pdf(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(
            reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_download_file_response(self):
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user, book=book)
            self._auth_client(user)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))
            signed_url_response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )
            self.assertEqual(signed_url_response.status_code, 200)
            download_path = self._path_with_query(signed_url_response.data['url'])

            self.client.credentials()
            response = self.client.get(download_path)

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="test.pdf"', response.headers.get('Content-Disposition', ''))

    def test_download_file_returns_404_when_signed_token_missing(self):
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user, book=book)
            self._auth_client(user)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))

            response = self.client.get(
                reverse('book-version-download', kwargs={'book_id': book.id, 'version_id': version.id})
            )

        self.assertEqual(response.status_code, 404)

    def test_download_file_returns_404_when_signed_token_is_tampered(self):
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user, book=book)
            self._auth_client(user)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))
            signed_url_response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )
            signed_path = self._path_with_query(signed_url_response.data['url'])
            parsed = urlsplit(signed_path)
            query = parse_qs(parsed.query)
            signed_token = query[DOWNLOAD_URL_TOKEN_PARAM][0]
            tampered = signed_token[:-1] + ('A' if signed_token[-1] != 'A' else 'B')
            tampered_path = f"{parsed.path}?{DOWNLOAD_URL_TOKEN_PARAM}={tampered}"

            response = self.client.get(tampered_path)

        self.assertEqual(response.status_code, 404)

    def test_download_file_returns_404_when_signed_token_is_for_another_user(self):
        user_one = self._create_user(email='u1@example.com')
        user_two = self._create_user(email='u2@example.com')

        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user_one, book=book)
            self._grant_entitlement(user_two, book=book)

            self._auth_client(user_one)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))
            signed_url_response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )
            signed_path = self._path_with_query(signed_url_response.data['url'])

            self._auth_client(user_two)
            response = self.client.get(signed_path)

        self.assertEqual(response.status_code, 404)

    @override_settings(LIBRARY_DOWNLOAD_URL_TTL_SECONDS=1)
    def test_download_file_returns_404_when_signed_token_is_expired(self):
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            self._grant_entitlement(user, book=book)
            self._auth_client(user)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('test.pdf', SimpleUploadedFile('test.pdf', b'%PDF-1.4 test'))
            signed_url_response = self.client.get(
                reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
            )
            signed_path = self._path_with_query(signed_url_response.data['url'])

            with mock.patch('library.views._download_url_max_age_seconds', return_value=-1):
                response = self.client.get(signed_path)

        self.assertEqual(response.status_code, 404)

    def test_download_file_returns_404_when_no_pdf(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(
            reverse('book-version-download', kwargs={'book_id': book.id, 'version_id': version.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_search_validation_errors(self):
        user = self._create_user()
        self._grant_entitlement(user, product=Entitlement.Product.SUBSCRIPTION)
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
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
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
        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
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
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        PageText.objects.create(book_version=version, page_number=1, text='Hello page')

        response = self.client.get(
            reverse('book-version-page-text', kwargs={'book_id': book.id, 'version_id': version.id, 'page_number': 1})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['text'], 'Hello page')
    
    def test_search_by_book_id_path(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        PageText.objects.create(book_version=version, page_number=1, text='Hello world from page 1')

        response = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'hello'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['book_id'], book.id)
        self.assertEqual(response.data['results'][0]['page_number'], 1)

    def test_search_requires_q(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)

        response = self.client.get(reverse('book-search', kwargs={'book_id': book.id}))
        self.assertEqual(response.status_code, 400)

    def test_book_version_list_denies_when_entitlement_is_for_other_book(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)
        target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=entitled_book)
        self._auth_client(user)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': target_book.id}))
        self.assertEqual(response.status_code, 403)

    def test_book_search_denies_when_entitlement_is_for_other_book(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)
        target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
        target_version = BookVersion.objects.create(
            book=target_book,
            version='2024.01',
            status=BookVersion.Status.PUBLISHED,
        )
        PageText.objects.create(book_version=target_version, page_number=1, text='Hello scoped world')

        self._grant_entitlement(user, book=entitled_book)
        self._auth_client(user)

        response = self.client.get(reverse('book-search', kwargs={'book_id': target_book.id}), {'q': 'hello'})
        self.assertEqual(response.status_code, 403)

    def test_download_url_denies_when_entitlement_is_for_other_book(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)
        target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
        target_version = BookVersion.objects.create(
            book=target_book,
            version='2024.01',
            status=BookVersion.Status.PUBLISHED,
        )

        self._grant_entitlement(user, book=entitled_book)
        self._auth_client(user)

        response = self.client.get(
            reverse('book-version-download-url', kwargs={'book_id': target_book.id, 'version_id': target_version.id})
        )
        self.assertEqual(response.status_code, 403)

    def test_download_file_denies_when_entitlement_is_for_other_book(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)

        with self._temp_media():
            target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
            target_version = BookVersion.objects.create(
                book=target_book,
                version='2024.01',
                status=BookVersion.Status.PUBLISHED,
            )
            target_version.pdf.save('target.pdf', SimpleUploadedFile('target.pdf', b'%PDF-1.4 test'))

            self._grant_entitlement(user, book=entitled_book)
            self._auth_client(user)

            response = self.client.get(
                reverse('book-version-download', kwargs={'book_id': target_book.id, 'version_id': target_version.id})
            )

        self.assertEqual(response.status_code, 404)

    def test_search_is_throttled(self):
        cache.clear()
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        PageText.objects.create(book_version=version, page_number=1, text='Hello world')
        self._grant_entitlement(user, book=book)
        self._auth_client(user)

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'library_search': '1/min'}):
            first = self.client.get(reverse('book-search', kwargs={'book_id': book.id}), {'q': 'hello'})
            second = self.client.get(reverse('book-search', kwargs={'book_id': book.id}), {'q': 'hello'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_download_url_is_throttled(self):
        cache.clear()
        user = self._create_user()
        with self._temp_media():
            book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
            version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
            version.pdf.save('throttle.pdf', SimpleUploadedFile('throttle.pdf', b'%PDF-1.4 test'))
            self._grant_entitlement(user, book=book)
            self._auth_client(user)

            with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'library_download_url': '1/min'}):
                first = self.client.get(
                    reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
                )
                second = self.client.get(
                    reverse('book-version-download-url', kwargs={'book_id': book.id, 'version_id': version.id})
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

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
