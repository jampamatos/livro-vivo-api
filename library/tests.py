from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import NotificationDispatch, NotificationEvent, NotificationPreference
from entitlements.models import Entitlement, Subscription

from .models import Book, BookChapter, BookVersion
from .permissions import HasActiveBookEntitlement
from .services import (
    create_preloaded_book_version,
    enqueue_book_chapter_publication_notifications,
    enqueue_book_version_publication_notifications,
)
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

class LibraryModelTests(LibraryBaseTestCase):
    def test_book_version_unique_constraint(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

    def test_book_version_allows_only_one_published_per_book(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.PUBLISHED)

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


class LibraryServicesTests(LibraryBaseTestCase):
    def test_create_preloaded_book_version_clones_chapters_and_changelog(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        source = BookVersion.objects.create(
            book=book,
            version='2024.01',
            changelog='Fonte',
            status=BookVersion.Status.PUBLISHED,
        )
        BookChapter.objects.create(
            book_version=source,
            order=2,
            title='Cap 2',
            slug='cap-2',
            content_rich='<p>Capítulo 2</p>',
        )
        BookChapter.objects.create(
            book_version=source,
            order=1,
            title='Cap 1',
            slug='cap-1',
            content_rich='<h2>Capítulo 1</h2><p>Texto</p>',
        )

        created = create_preloaded_book_version(
            source_version=source,
            new_version='2024.02',
            changelog='Nova publicação',
        )

        self.assertEqual(created.book_id, source.book_id)
        self.assertEqual(created.version, '2024.02')
        self.assertEqual(created.status, BookVersion.Status.DRAFT)
        self.assertEqual(created.changelog, 'Nova publicação')

        source_orders = list(source.chapters.order_by('order').values_list('order', flat=True))
        cloned_orders = list(created.chapters.order_by('order').values_list('order', flat=True))
        self.assertEqual(source_orders, [1, 2])
        self.assertEqual(cloned_orders, [1, 2])

        source_slugs = list(source.chapters.order_by('order').values_list('slug', flat=True))
        cloned_slugs = list(created.chapters.order_by('order').values_list('slug', flat=True))
        self.assertEqual(cloned_slugs, source_slugs)
        self.assertEqual(created.chapters.count(), source.chapters.count())

    def test_create_preloaded_book_version_requires_changelog(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        source = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        with self.assertRaisesMessage(ValueError, 'Changelog is required.'):
            create_preloaded_book_version(
                source_version=source,
                new_version='2024.02',
                changelog='',
            )

    def test_create_preloaded_book_version_does_not_change_source_history(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        source = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        source_chapter = BookChapter.objects.create(
            book_version=source,
            order=1,
            title='Original',
            slug='original',
            content_rich='<p>Texto original</p>',
        )

        created = create_preloaded_book_version(
            source_version=source,
            new_version='2024.02',
            changelog='Nova versão',
        )
        clone_chapter = created.chapters.get(order=1)
        clone_chapter.title = 'Clone alterado'
        clone_chapter.content_rich = '<p>Texto alterado</p>'
        clone_chapter.save()

        source_chapter.refresh_from_db()
        self.assertEqual(source_chapter.title, 'Original')
        self.assertEqual(source_chapter.content_plain, 'Texto original')

    def test_create_preloaded_book_version_published_queues_notification_event(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        source = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=source,
            order=1,
            title='Capítulo',
            slug='capitulo',
            content_rich='<p>Texto</p>',
        )

        allowed_user = self._create_user(email='allowed@example.com')
        blocked_user = self._create_user(email='blocked@example.com')
        ignored_user = self._create_user(email='ignored@example.com')

        Subscription.objects.create(
            user=allowed_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )
        Subscription.objects.create(
            user=blocked_user,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
        )
        Subscription.objects.create(
            user=ignored_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.CANCELED,
        )

        NotificationPreference.objects.create(
            user=blocked_user,
            notifications_enabled=True,
            book_version_updates_enabled=False,
            new_content_updates_enabled=True,
            push_enabled=True,
        )

        created = create_preloaded_book_version(
            source_version=source,
            new_version='2024.02',
            changelog='Publicação com alerta',
            status=BookVersion.Status.PUBLISHED,
            published_at=timezone.localdate(),
        )

        event = NotificationEvent.objects.get(dedup_key=f'book-version-published:{created.id}')
        self.assertEqual(event.event_type, NotificationEvent.EventType.BOOK_VERSION_PUBLISHED)
        self.assertEqual(event.payload['book_version_id'], created.id)
        self.assertEqual(event.payload['book_id'], book.id)
        self.assertFalse(
            NotificationEvent.objects.filter(
                dedup_key__startswith='book-chapter-published:'
            ).exists()
        )

        push_dispatches = NotificationDispatch.objects.filter(
            event=event,
            channel=NotificationDispatch.Channel.PUSH,
        ).order_by('user_id')
        in_app_dispatches = NotificationDispatch.objects.filter(
            event=event,
            channel=NotificationDispatch.Channel.IN_APP,
        ).order_by('user_id')
        self.assertEqual(push_dispatches.count(), 2)
        self.assertEqual(in_app_dispatches.count(), 2)

        pending = push_dispatches.get(user=allowed_user)
        pending_in_app = in_app_dispatches.get(user=allowed_user)
        self.assertEqual(pending.status, NotificationDispatch.Status.PENDING)
        self.assertEqual(pending_in_app.status, NotificationDispatch.Status.PENDING)

        skipped = push_dispatches.get(user=blocked_user)
        skipped_in_app = in_app_dispatches.get(user=blocked_user)
        self.assertEqual(skipped.status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(skipped.reason, 'book_updates_disabled')
        self.assertEqual(skipped_in_app.status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(skipped_in_app.reason, 'book_updates_disabled')

        self.assertFalse(push_dispatches.filter(user=ignored_user).exists())

    def test_enqueue_book_version_publication_notifications_is_idempotent(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(
            book=book,
            version='2024.10',
            status=BookVersion.Status.PUBLISHED,
            changelog='Publicada',
            published_at=timezone.localdate(),
        )
        user = self._create_user(email='idempotent@example.com')

        Subscription.objects.create(
            user=user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        first = enqueue_book_version_publication_notifications(book_version=version)
        second = enqueue_book_version_publication_notifications(book_version=version)

        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(NotificationEvent.objects.filter(dedup_key=f'book-version-published:{version.id}').count(), 1)
        self.assertEqual(NotificationDispatch.objects.filter(event=first, user=user).count(), 2)

    def test_new_chapter_in_published_version_queues_notification_event(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(
            book=book,
            version='2024.11',
            status=BookVersion.Status.PUBLISHED,
            changelog='Atualização incremental',
            published_at=timezone.localdate(),
        )
        allowed_user = self._create_user(email='chapter-allowed@example.com')
        blocked_user = self._create_user(email='chapter-blocked@example.com')

        Subscription.objects.create(
            user=allowed_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )
        Subscription.objects.create(
            user=blocked_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )
        NotificationPreference.objects.create(
            user=blocked_user,
            notifications_enabled=True,
            book_version_updates_enabled=False,
            push_enabled=True,
        )

        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Novo capítulo',
            slug='novo-capitulo',
            content_rich='<p>Conteúdo novo do capítulo.</p>',
        )

        event = NotificationEvent.objects.get(dedup_key=f'book-chapter-published:{chapter.id}')
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

        self.assertEqual(event.event_type, NotificationEvent.EventType.CONTENT_PUBLISHED)
        self.assertEqual(event.payload['resource_type'], 'book_chapter')
        self.assertEqual(event.payload['book_chapter_id'], chapter.id)
        self.assertEqual(push_dispatches[allowed_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(in_app_dispatches[allowed_user.id].status, NotificationDispatch.Status.PENDING)
        self.assertEqual(push_dispatches[blocked_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(in_app_dispatches[blocked_user.id].status, NotificationDispatch.Status.SKIPPED)
        self.assertEqual(push_dispatches[blocked_user.id].reason, 'book_updates_disabled')
        self.assertEqual(in_app_dispatches[blocked_user.id].reason, 'book_updates_disabled')

    def test_new_chapter_in_draft_version_does_not_queue_notification(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(
            book=book,
            version='2024.12',
            status=BookVersion.Status.DRAFT,
        )
        user = self._create_user(email='chapter-draft@example.com')
        Subscription.objects.create(
            user=user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Capítulo rascunho',
            slug='capitulo-rascunho',
            content_rich='<p>Texto</p>',
        )

        self.assertFalse(
            NotificationEvent.objects.filter(dedup_key=f'book-chapter-published:{chapter.id}').exists()
        )

    def test_enqueue_book_chapter_publication_notifications_is_idempotent(self):
        book = Book.objects.create(title='Book', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(
            book=book,
            version='2024.13',
            status=BookVersion.Status.PUBLISHED,
            changelog='Atualização incremental',
            published_at=timezone.localdate(),
        )
        user = self._create_user(email='chapter-idempotent@example.com')

        Subscription.objects.create(
            user=user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        chapter = BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Capítulo único',
            slug='capitulo-unico',
            content_rich='<p>Texto</p>',
        )

        first = enqueue_book_chapter_publication_notifications(book_chapter=chapter)
        second = enqueue_book_chapter_publication_notifications(book_chapter=chapter)

        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(NotificationEvent.objects.filter(dedup_key=f'book-chapter-published:{chapter.id}').count(), 1)
        self.assertEqual(NotificationDispatch.objects.filter(event=first, user=user).count(), 2)


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
            changelog='Versão inicial',
            status=BookVersion.Status.PUBLISHED,
        )
        self.chapter = BookChapter.objects.create(
            book_version=self.version,
            order=1,
            title='Introdução',
            slug='introducao',
            content_rich='<p>Conteúdo inicial</p>',
        )

    def test_book_admin_changelist_uses_title_as_link_without_id_column(self):
        response = self.client.get(reverse('admin:library_book_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<a href="{reverse("admin:library_book_change", args=[self.book.id])}">{self.book.title}</a>',
            html=True,
        )
        self.assertNotContains(response, 'field-id')

    def test_book_admin_change_form_shows_current_chapters_and_old_versions(self):
        old_version = BookVersion.objects.create(
            book=self.book,
            version='2023.12',
            changelog='Versao antiga',
            status=BookVersion.Status.ARCHIVED,
        )
        BookChapter.objects.create(
            book_version=old_version,
            order=1,
            title='Capítulo antigo',
            slug='capitulo-antigo',
            content_rich='<p>Capitulo antigo</p>',
        )
        draft_version = BookVersion.objects.create(
            book=self.book,
            version='2024.02',
            changelog='Nova versao em rascunho',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.get(reverse('admin:library_book_change', args=[self.book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pipeline de versoes')
        self.assertContains(response, 'Adicionar nova versao')
        self.assertContains(response, f'data-create-url="{reverse("admin:library_book_create_version", args=[self.book.id])}"')
        self.assertContains(response, f'data-version-label="{draft_version.version}"')
        self.assertContains(response, reverse('admin:library_book_publish_version', args=[self.book.id, draft_version.id]))
        self.assertContains(response, f'?book_version__id__exact={self.version.id}')
        self.assertContains(response, f'?book_version={self.version.id}')
        self.assertContains(response, reverse('admin:library_bookversion_change', args=[self.version.id]))
        self.assertContains(response, f'?book_version__id__exact={old_version.id}')
        self.assertContains(response, old_version.version)

    def test_book_admin_create_version_endpoint_creates_draft_and_clones_chapters(self):
        response = self.client.post(
            reverse('admin:library_book_create_version', args=[self.book.id]),
            data={
                'version': '2024.02',
                'changelog': 'Nova iteracao',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        created = BookVersion.objects.get(book=self.book, version='2024.02')
        self.assertEqual(created.status, BookVersion.Status.DRAFT)
        self.assertIsNone(created.published_at)
        self.assertEqual(created.changelog, 'Nova iteracao')
        self.assertEqual(created.chapters.count(), self.version.chapters.count())
        self.assertContains(response, 'Versao &quot;2024.02&quot; criada em rascunho.')

    def test_book_admin_publish_version_endpoint_publishes_target_and_archives_others(self):
        target_user = User.objects.create_user(
            username='notify-pipeline@example.com',
            email='notify-pipeline@example.com',
            password='StrongPass123',
        )
        Subscription.objects.create(
            user=target_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        self.version.status = BookVersion.Status.ARCHIVED
        self.version.save(update_fields=['status'])

        other_published = BookVersion.objects.create(
            book=self.book,
            version='2024.00',
            changelog='Publicada antiga',
            status=BookVersion.Status.PUBLISHED,
            published_at=timezone.localdate() - timedelta(days=1),
        )
        target = BookVersion.objects.create(
            book=self.book,
            version='2024.02',
            changelog='Pronta para publicar',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_book_publish_version', args=[self.book.id, target.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.version.refresh_from_db()
        other_published.refresh_from_db()
        self.book.refresh_from_db()

        self.assertEqual(target.status, BookVersion.Status.PUBLISHED)
        self.assertIsNotNone(target.published_at)
        self.assertEqual(self.version.status, BookVersion.Status.ARCHIVED)
        self.assertEqual(other_published.status, BookVersion.Status.ARCHIVED)
        self.assertEqual(self.book.status, Book.Status.PUBLISHED)
        self.assertTrue(
            NotificationEvent.objects.filter(dedup_key=f'book-version-published:{target.id}').exists()
        )
        self.assertContains(response, f'Versao &quot;{target.version}&quot; publicada com sucesso.')

    def test_book_admin_publish_version_endpoint_requires_changelog(self):
        target = BookVersion.objects.create(
            book=self.book,
            version='2024.03',
            changelog='',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_book_publish_version', args=[self.book.id, target.id]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.status, BookVersion.Status.DRAFT)
        self.assertContains(response, 'Nao e possivel publicar sem changelog.')

    def test_book_chapter_admin_changelist_renders_preview_and_order(self):
        response = self.client.get(reverse('admin:library_bookchapter_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'introducao')
        self.assertContains(response, 'Conteúdo inicial')
        self.assertContains(response, 'id="id_form-0-order"')
        self.assertNotContains(response, 'field-id')

    def test_book_chapter_model_is_hidden_from_admin_index_menu(self):
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Capitulos do livro')

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
        self.assertContains(response, 'library/admin/chapter_rich_editor.css')
        self.assertContains(response, 'tinymce/tinymce.min.js')
        self.assertContains(response, 'django_tinymce/init_tinymce.js')
        self.assertContains(response, 'undo redo | blocks | bold italic underline')
        self.assertContains(response, 'Tags permitidas:')
        self.assertContains(response, 'Tags permitidas: a, blockquote, br')
        self.assertContains(response, 'lv-rich-editor-preview')

    def test_book_version_changelist_uses_bulk_action_buttons_instead_of_dropdown(self):
        response = self.client.get(reverse('admin:library_bookversion_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-lv-action-buttons')
        self.assertContains(response, 'Selecione itens para habilitar ações em massa.')
        self.assertContains(response, 'Criar nova versão a partir da selecionada')
        self.assertContains(response, 'Apagar selecionados')
        self.assertContains(response, 'data-lv-confirm-message="Tem certeza que deseja publicar os itens selecionados?"')
        self.assertContains(response, 'Confirmar ação sensível')
        self.assertContains(response, 'lv-sensitive-action-modal__card')
        self.assertNotContains(response, 'Confirmo ação sensível')

    def test_book_version_admin_action_creates_preloaded_version_with_chapters(self):
        BookChapter.objects.create(
            book_version=self.version,
            order=2,
            title='Capítulo 2',
            slug='capitulo-2',
            content_rich='<p>Segundo</p>',
        )

        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'create_preloaded_version',
                '_selected_action': [str(self.version.id)],
                'select_across': '0',
                'index': '0',
                'new_version': '2024.02',
                'new_changelog': 'Clonada com ajustes',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        cloned = BookVersion.objects.get(book=self.book, version='2024.02')
        self.assertEqual(cloned.status, BookVersion.Status.DRAFT)
        self.assertEqual(cloned.changelog, 'Clonada com ajustes')
        self.assertEqual(list(cloned.chapters.order_by('order').values_list('order', flat=True)), [1, 2])
        self.assertContains(response, 'Versão pré-carregada &quot;2024.02&quot; criada')

    def test_book_version_admin_action_requires_single_selection(self):
        second = BookVersion.objects.create(
            book=self.book,
            version='2024.02',
            changelog='Segunda',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'create_preloaded_version',
                '_selected_action': [str(self.version.id), str(second.id)],
                'select_across': '0',
                'index': '0',
                'new_version': '2024.03',
                'new_changelog': 'Tentativa',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(BookVersion.objects.filter(book=self.book, version='2024.03').exists())
        self.assertContains(response, 'Selecione exatamente 1 versão de origem para clonar.')

    def test_book_version_admin_action_requires_changelog(self):
        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'create_preloaded_version',
                '_selected_action': [str(self.version.id)],
                'select_across': '0',
                'index': '0',
                'new_version': '2024.03',
                'new_changelog': '',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(BookVersion.objects.filter(book=self.book, version='2024.03').exists())
        self.assertContains(response, 'Changelog is required.')

    def test_book_version_admin_form_requires_changelog_when_publishing(self):
        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.90',
            changelog='',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_change', args=[draft.id]),
            data={
                'book': self.book.id,
                'version': '2024.90',
                'published_at': timezone.localdate().isoformat(),
                'changelog': '',
                'status': BookVersion.Status.PUBLISHED,
                'chapters-TOTAL_FORMS': '0',
                'chapters-INITIAL_FORMS': '0',
                'chapters-MIN_NUM_FORMS': '0',
                'chapters-MAX_NUM_FORMS': '1000',
                '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Changelog é obrigatório ao publicar uma versão.')
        draft.refresh_from_db()
        self.assertEqual(draft.status, BookVersion.Status.DRAFT)

    def test_book_version_admin_publish_queues_notification_event(self):
        target_user = User.objects.create_user(
            username='notify-target@example.com',
            email='notify-target@example.com',
            password='StrongPass123',
        )
        Subscription.objects.create(
            user=target_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        self.version.status = BookVersion.Status.ARCHIVED
        self.version.save(update_fields=['status'])

        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.91',
            changelog='',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_change', args=[draft.id]),
            data={
                'book': self.book.id,
                'version': '2024.91',
                'published_at': timezone.localdate().isoformat(),
                'changelog': 'Publicação pronta',
                'status': BookVersion.Status.PUBLISHED,
                'chapters-TOTAL_FORMS': '0',
                'chapters-INITIAL_FORMS': '0',
                'chapters-MIN_NUM_FORMS': '0',
                'chapters-MAX_NUM_FORMS': '1000',
                '_save': 'Save',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.status, BookVersion.Status.PUBLISHED)
        self.assertTrue(
            NotificationEvent.objects.filter(dedup_key=f'book-version-published:{draft.id}').exists()
        )

    def test_book_version_admin_publish_with_inline_chapter_suppresses_chapter_notifications(self):
        target_user = User.objects.create_user(
            username='notify-inline@example.com',
            email='notify-inline@example.com',
            password='StrongPass123',
        )
        Subscription.objects.create(
            user=target_user,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
        )

        self.version.status = BookVersion.Status.ARCHIVED
        self.version.save(update_fields=['status'])

        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.92',
            changelog='',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_change', args=[draft.id]),
            data={
                'book': self.book.id,
                'version': '2024.92',
                'published_at': timezone.localdate().isoformat(),
                'changelog': 'Versão com capítulo novo',
                'status': BookVersion.Status.PUBLISHED,
                'chapters-TOTAL_FORMS': '1',
                'chapters-INITIAL_FORMS': '0',
                'chapters-MIN_NUM_FORMS': '0',
                'chapters-MAX_NUM_FORMS': '1000',
                'chapters-0-id': '',
                'chapters-0-book_version': str(draft.id),
                'chapters-0-order': '1',
                'chapters-0-title': 'Capítulo inédito',
                'chapters-0-slug': 'capitulo-inedito',
                'chapters-0-content_rich': '<p>Conteúdo inédito</p>',
                '_save': 'Save',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        chapter = draft.chapters.get(slug='capitulo-inedito')

        self.assertTrue(
            NotificationEvent.objects.filter(dedup_key=f'book-version-published:{draft.id}').exists()
        )
        self.assertFalse(
            NotificationEvent.objects.filter(dedup_key=f'book-chapter-published:{chapter.id}').exists()
        )

    def test_book_version_admin_bulk_publish_requires_sensitive_confirmation(self):
        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.93',
            changelog='Publicação em lote',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'publish_selected_versions',
                '_selected_action': [str(draft.id)],
                'select_across': '0',
                'index': '0',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.status, BookVersion.Status.DRAFT)
        self.assertContains(response, 'Confirme a ação sensível para publicar versões em massa.')

    def test_book_version_admin_bulk_publish_archives_old_published_version(self):
        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.94',
            changelog='Publicação em lote com confirmação',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'publish_selected_versions',
                '_selected_action': [str(draft.id)],
                'select_across': '0',
                'index': '0',
                'confirm_sensitive_action': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.version.refresh_from_db()
        self.assertEqual(draft.status, BookVersion.Status.PUBLISHED)
        self.assertEqual(self.version.status, BookVersion.Status.ARCHIVED)
        self.assertContains(response, f'Versão &quot;{draft.version}&quot; publicada com sucesso.')

    def test_book_version_admin_bulk_archive_skips_published_versions(self):
        draft = BookVersion.objects.create(
            book=self.book,
            version='2024.95',
            changelog='Rascunho para arquivar',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.post(
            reverse('admin:library_bookversion_changelist'),
            data={
                'action': 'archive_selected_versions',
                '_selected_action': [str(self.version.id), str(draft.id)],
                'select_across': '0',
                'index': '0',
                'confirm_sensitive_action': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.version.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(self.version.status, BookVersion.Status.PUBLISHED)
        self.assertEqual(draft.status, BookVersion.Status.ARCHIVED)
        self.assertContains(response, 'não foram arquivadas')


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

    def test_book_version_list_filters_versions_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)

        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)
        published = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(reverse('book-versions', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        versions = response.data['versions']
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['id'], published.id)

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

    def test_current_version_returns_latest_published_for_non_staff(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)

        archived_old = BookVersion.objects.create(
            book=book,
            version='2024.01',
            status=BookVersion.Status.ARCHIVED,
        )
        published_current = BookVersion.objects.create(
            book=book,
            version='2024.02',
            status=BookVersion.Status.PUBLISHED,
        )
        BookVersion.objects.create(
            book=book,
            version='2024.03',
            status=BookVersion.Status.DRAFT,
        )

        response = self.client.get(reverse('book-current-version', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['book']['id'], book.id)
        self.assertEqual(response.data['version']['id'], published_current.id)
        self.assertNotEqual(response.data['version']['id'], archived_old.id)

    def test_current_version_returns_only_published_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)
        book = Book.objects.create(title='Published Book', status=Book.Status.PUBLISHED)
        published = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)

        response = self.client.get(reverse('book-current-version', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['version']['id'], published.id)
        self.assertEqual(response.data['version']['status'], BookVersion.Status.PUBLISHED)

    def test_current_version_returns_404_when_non_staff_has_no_published_version(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.DRAFT)

        response = self.client.get(reverse('book-current-version', kwargs={'book_id': book.id}))

        self.assertEqual(response.status_code, 404)

    def test_current_version_chapter_summary_returns_ordered_chapters(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        current = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(book_version=current, order=2, title='Cap 2', slug='cap-2', content_rich='<p>2</p>')
        BookChapter.objects.create(book_version=current, order=1, title='Cap 1', slug='cap-1', content_rich='<p>1</p>')

        response = self.client.get(
            reverse('book-current-version-chapters', kwargs={'book_id': book.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['book_id'], book.id)
        self.assertEqual(response.data['book_version_id'], current.id)
        self.assertEqual([c['order'] for c in response.data['chapters']], [1, 2])
        self.assertEqual([c['slug'] for c in response.data['chapters']], ['cap-1', 'cap-2'])

    def test_current_version_chapter_by_slug_returns_chapter_and_navigation(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        current = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(book_version=current, order=1, title='Cap 1', slug='cap-1', content_rich='<p>1</p>')
        middle = BookChapter.objects.create(
            book_version=current,
            order=2,
            title='Cap 2',
            slug='cap-2',
            content_rich='<h2>Dois</h2><p>Texto</p>',
        )
        BookChapter.objects.create(book_version=current, order=3, title='Cap 3', slug='cap-3', content_rich='<p>3</p>')

        response = self.client.get(
            reverse('book-current-version-chapter-by-slug', kwargs={'book_id': book.id, 'chapter_slug': middle.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['book_version_id'], current.id)
        self.assertEqual(response.data['chapter']['slug'], 'cap-2')
        self.assertEqual(response.data['previous_slug'], 'cap-1')
        self.assertEqual(response.data['next_slug'], 'cap-3')
        self.assertEqual(response.data['chapter']['content_plain'], 'Dois Texto')

    def test_current_version_chapter_by_slug_returns_404_when_missing(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)

        response = self.client.get(
            reverse('book-current-version-chapter-by-slug', kwargs={'book_id': book.id, 'chapter_slug': 'missing'})
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

        BookChapter.objects.create(
            book_version=published_version,
            order=1,
            title='Cap publicado',
            slug='cap-publicado',
            content_rich='<p>Hello world publicado</p>',
        )
        BookChapter.objects.create(
            book_version=draft_version,
            order=1,
            title='Cap draft',
            slug='cap-draft',
            content_rich='<p>Hello world draft</p>',
        )

        response = self.client.get(
            reverse('search'),
            {'q': 'hello', 'book_id': book.id, 'limit': 200, 'offset': -1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['limit'], 100)
        self.assertEqual(response.data['offset'], 0)
        self.assertEqual(response.data['results'][0]['chapter_slug'], 'cap-publicado')

    def test_search_includes_draft_for_staff(self):
        user = self._create_user(is_staff=True)
        self._auth_client(user)

        book = Book.objects.create(title='Draft', status=Book.Status.DRAFT)
        version = BookVersion.objects.create(book=book, version='2024.02', status=BookVersion.Status.DRAFT)
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Cap draft',
            slug='cap-draft',
            content_rich='<p>Hello world</p>',
        )

        response = self.client.get(reverse('search'), {'q': 'hello', 'book_version_id': version.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['chapter_slug'], 'cap-draft')

    def test_search_by_book_id_path(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=version,
            order=3,
            title='Capítulo 3',
            slug='capitulo-3',
            content_rich='<p>Hello world from chapter 3</p>',
        )

        response = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'hello'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['book_id'], book.id)
        self.assertEqual(response.data['results'][0]['chapter_slug'], 'capitulo-3')
        self.assertEqual(response.data['results'][0]['chapter_order'], 3)
        self.assertEqual(response.data['results'][0]['occurrence'], 1)
        self.assertGreaterEqual(response.data['results'][0]['match_end'], response.data['results'][0]['match_start'])
        self.assertIn('Hello', response.data['results'][0]['snippet'])

    def test_search_returns_multiple_occurrences_for_same_chapter(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Capítulo 1',
            slug='cap-1',
            content_rich=(
                '<p>Magic first occurrence with enough spacing between terms to avoid clustering.</p>'
                '<p>' + ('x' * 120) + '</p>'
                '<p>magic second far occurrence after a long separator.</p>'
                '<p>' + ('y' * 120) + '</p>'
                '<p>MAGIC third far occurrence after another separator.</p>'
            ),
        )

        response = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'magic'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual([row['occurrence'] for row in response.data['results']], [1, 2, 3])
        self.assertTrue(all(row['chapter_slug'] == 'cap-1' for row in response.data['results']))

    def test_search_clusters_nearby_occurrences_in_single_result(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Capítulo 1',
            slug='cap-1',
            content_rich='<p>test test test test</p>',
        )

        response = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'test'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['occurrence'], 1)
        self.assertEqual(response.data['results'][0]['chapter_slug'], 'cap-1')

    def test_search_pagination_is_stable_for_chapter_results(self):
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        self._grant_entitlement(user, book=book)
        self._auth_client(user)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        for order in [1, 2, 3]:
            BookChapter.objects.create(
                book_version=version,
                order=order,
                title=f'Capítulo {order}',
                slug=f'cap-{order}',
                content_rich='<p>hello termo comum</p>',
            )

        first_page = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'hello', 'limit': 2, 'offset': 0},
        )
        second_page = self.client.get(
            reverse('book-search', kwargs={'book_id': book.id}),
            {'q': 'hello', 'limit': 2, 'offset': 2},
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(first_page.data['count'], 3)
        self.assertEqual([row['chapter_order'] for row in first_page.data['results']], [1, 2])
        self.assertEqual([row['chapter_order'] for row in second_page.data['results']], [3])

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

    def test_current_version_and_chapter_endpoints_deny_other_book_entitlement(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)
        target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
        target_version = BookVersion.objects.create(
            book=target_book,
            version='2024.01',
            status=BookVersion.Status.PUBLISHED,
        )
        BookChapter.objects.create(
            book_version=target_version,
            order=1,
            title='Cap',
            slug='cap',
            content_rich='<p>cap</p>',
        )
        self._grant_entitlement(user, book=entitled_book)
        self._auth_client(user)

        current_response = self.client.get(
            reverse('book-current-version', kwargs={'book_id': target_book.id})
        )
        summary_response = self.client.get(
            reverse('book-current-version-chapters', kwargs={'book_id': target_book.id})
        )
        chapter_response = self.client.get(
            reverse('book-current-version-chapter-by-slug', kwargs={'book_id': target_book.id, 'chapter_slug': 'cap'})
        )

        self.assertEqual(current_response.status_code, 403)
        self.assertEqual(summary_response.status_code, 403)
        self.assertEqual(chapter_response.status_code, 403)

    def test_book_search_denies_when_entitlement_is_for_other_book(self):
        user = self._create_user()
        entitled_book = Book.objects.create(title='Entitled', status=Book.Status.PUBLISHED)
        target_book = Book.objects.create(title='Target', status=Book.Status.PUBLISHED)
        target_version = BookVersion.objects.create(
            book=target_book,
            version='2024.01',
            status=BookVersion.Status.PUBLISHED,
        )
        BookChapter.objects.create(
            book_version=target_version,
            order=1,
            title='Capítulo alvo',
            slug='cap-alvo',
            content_rich='<p>Hello scoped world</p>',
        )

        self._grant_entitlement(user, book=entitled_book)
        self._auth_client(user)

        response = self.client.get(reverse('book-search', kwargs={'book_id': target_book.id}), {'q': 'hello'})
        self.assertEqual(response.status_code, 403)

    def test_search_is_throttled(self):
        cache.clear()
        user = self._create_user()
        book = Book.objects.create(title='Published', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(book=book, version='2024.01', status=BookVersion.Status.PUBLISHED)
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Capítulo 1',
            slug='cap-1',
            content_rich='<p>Hello world</p>',
        )
        self._grant_entitlement(user, book=book)
        self._auth_client(user)

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'library_search': '1/min'}):
            first = self.client.get(reverse('book-search', kwargs={'book_id': book.id}), {'q': 'hello'})
            second = self.client.get(reverse('book-search', kwargs={'book_id': book.id}), {'q': 'hello'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

class TestCorsHealth(TestCase):
    def setUp(self):
        self.client = Client()

    def test_health_has_cors_for_expo_web(self):
        origin = "http://localhost:8081"
        resp = self.client.get("/health/", HTTP_ORIGIN=origin)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), origin)
