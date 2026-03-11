from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from entitlements.models import Entitlement, Subscription
from library.models import Book, BookChapter, BookVersion

from .models import Annotation


class AnnotationModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='StrongPass123',
        )

        self.book = Book.objects.create(title='Livro Teste')
        self.book_version = BookVersion.objects.create(book=self.book, version='1')
        self.chapter = BookChapter.objects.create(
            book_version=self.book_version,
            title='Capítulo 1',
            slug='capitulo-1',
            order=1,
            content_rich='<p>abcdef ghijkl</p>',
        )

    def test_create_annotation_chapter_selector_offsets(self):
        ann = Annotation.objects.create(
            user=self.user,
            book_version=self.book_version,
            chapter=self.chapter,
            selector={'kind': 'text-quote'},
            start_offset=2,
            end_offset=8,
            excerpt='cdef g',
            note='Teste de nota',
            color='yellow',
        )

        self.assertEqual(ann.chapter_id, self.chapter.id)
        self.assertEqual(ann.start_offset, 2)
        self.assertEqual(ann.end_offset, 8)
        self.assertEqual(ann.selector['kind'], 'text-quote')


class AnnotationApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user1 = User.objects.create_user(
            username='u1@example.com',
            email='u1@example.com',
            password='StrongPass123',
        )
        self.user2 = User.objects.create_user(
            username='u2@example.com',
            email='u2@example.com',
            password='StrongPass123',
        )

        self.access1 = str(RefreshToken.for_user(self.user1).access_token)
        self.access2 = str(RefreshToken.for_user(self.user2).access_token)

        self.book = Book.objects.create(title='Livro 1')
        self.book_version = BookVersion.objects.create(book=self.book, version='1')
        self.chapter_1 = BookChapter.objects.create(
            book_version=self.book_version,
            title='Capítulo 1',
            slug='cap-1',
            order=1,
            content_rich='<p>Primeiro capítulo com conteúdo para excerpt.</p>',
        )
        self.chapter_2 = BookChapter.objects.create(
            book_version=self.book_version,
            title='Capítulo 2',
            slug='cap-2',
            order=2,
            content_rich='<p>Segundo capítulo.</p>',
        )

        self.other_book = Book.objects.create(title='Livro 2')
        self.other_book_version = BookVersion.objects.create(book=self.other_book, version='1')
        self.other_chapter = BookChapter.objects.create(
            book_version=self.other_book_version,
            title='Outro capítulo',
            slug='outro-cap',
            order=1,
            content_rich='<p>Outro conteúdo.</p>',
        )

        Entitlement.objects.create(
            user=self.user1,
            product=Entitlement.Product.BOOK,
            book=self.book,
            status=Entitlement.Status.ACTIVE,
        )
        Entitlement.objects.create(
            user=self.user2,
            product=Entitlement.Product.BOOK,
            book=self.book,
            status=Entitlement.Status.ACTIVE,
        )

        self.client = APIClient()

    def auth1(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access1}')

    def auth2(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access2}')

    def test_list_only_returns_own_annotations(self):
        Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=5,
            note='u1',
            color='yellow',
        )
        Annotation.objects.create(
            user=self.user2,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=6,
            note='u2',
            color='green',
        )

        self.auth1()
        resp = self.client.get('/annotations/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['note'], 'u1')

    def test_filters_work_for_book_version_chapter_and_slug(self):
        a1 = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=5,
            note='cap1',
            color='',
        )
        Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            chapter=self.chapter_2,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=5,
            note='cap2',
            color='',
        )

        self.auth1()
        resp = self.client.get(
            f'/annotations/?book_version_id={self.book_version.id}&chapter_id={self.chapter_1.id}'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['id'], a1.id)

        resp = self.client.get(f'/annotations/?book_version={self.book_version.id}&chapter_slug=cap-1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['id'], a1.id)

    def test_cannot_access_other_users_annotation(self):
        ann_user2 = Annotation.objects.create(
            user=self.user2,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=8,
            note='secret',
            color='',
        )

        self.auth1()
        resp = self.client.get(f'/annotations/{ann_user2.id}/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client.patch(f'/annotations/{ann_user2.id}/', {'note': 'hacked'}, format='json')
        self.assertEqual(resp.status_code, 404)

        resp = self.client.delete(f'/annotations/{ann_user2.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_create_sets_user_and_generates_excerpt(self):
        self.auth1()
        payload = {
            'book_version': self.book_version.id,
            'chapter': self.chapter_1.id,
            'selector': {'kind': 'text-quote', 'source': 'selection'},
            'start_offset': 0,
            'end_offset': 8,
            'note': 'nova nota',
            'color': 'yellow',
        }
        resp = self.client.post('/annotations/', payload, format='json')
        self.assertEqual(resp.status_code, 201)

        ann = Annotation.objects.get(id=resp.data['id'])
        self.assertEqual(ann.user_id, self.user1.id)
        self.assertEqual(ann.chapter_id, self.chapter_1.id)
        self.assertEqual(ann.excerpt, self.chapter_1.content_plain[:8].strip())

    def test_create_validates_selector_and_offsets(self):
        self.auth1()
        payload_invalid_selector = {
            'book_version': self.book_version.id,
            'chapter': self.chapter_1.id,
            'selector': ['invalid'],
            'start_offset': 0,
            'end_offset': 8,
        }
        resp = self.client.post('/annotations/', payload_invalid_selector, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('selector', resp.data)

        payload_invalid_offsets = {
            'book_version': self.book_version.id,
            'chapter': self.chapter_1.id,
            'selector': {'kind': 'text-quote'},
            'start_offset': 10,
            'end_offset': 2,
        }
        resp = self.client.post('/annotations/', payload_invalid_offsets, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('end_offset', resp.data)

    def test_create_validates_chapter_belongs_to_book_version(self):
        self.auth1()
        payload = {
            'book_version': self.book_version.id,
            'chapter': self.other_chapter.id,
            'selector': {'kind': 'text-quote'},
            'start_offset': 0,
            'end_offset': 8,
        }
        resp = self.client.post('/annotations/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('chapter', resp.data)

    def test_update_and_delete_own_annotation(self):
        ann = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=8,
            note='old',
            color='yellow',
        )

        self.auth1()
        resp = self.client.patch(
            f'/annotations/{ann.id}/',
            {'note': 'new note', 'color': 'green'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        ann.refresh_from_db()
        self.assertEqual(ann.note, 'new note')
        self.assertEqual(ann.color, 'green')

        resp = self.client.delete(f'/annotations/{ann.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Annotation.objects.filter(id=ann.id).exists())

    def test_list_hides_annotations_from_books_without_entitlement(self):
        allowed = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=5,
            note='allowed',
            color='',
        )
        Annotation.objects.create(
            user=self.user1,
            book_version=self.other_book_version,
            chapter=self.other_chapter,
            selector={'kind': 'text-quote'},
            start_offset=1,
            end_offset=5,
            note='blocked',
            color='',
        )

        self.auth1()
        resp = self.client.get('/annotations/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['id'], allowed.id)

    def test_create_denies_annotation_for_book_without_entitlement(self):
        self.auth1()
        payload = {
            'book_version': self.other_book_version.id,
            'chapter': self.other_chapter.id,
            'selector': {'kind': 'text-quote'},
            'start_offset': 1,
            'end_offset': 5,
            'note': 'sem acesso',
            'color': 'red',
        }
        resp = self.client.post('/annotations/', payload, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_subscription_allows_cross_book_annotation(self):
        Subscription.objects.create(
            user=self.user1,
            tier=Subscription.Tier.ESSENTIAL,
            status=Subscription.Status.ACTIVE,
            source='tests',
        )
        self.auth1()
        payload = {
            'book_version': self.other_book_version.id,
            'chapter': self.other_chapter.id,
            'selector': {'kind': 'text-quote'},
            'start_offset': 1,
            'end_offset': 5,
            'note': 'com assinatura',
            'color': 'blue',
        }
        resp = self.client.post('/annotations/', payload, format='json')
        self.assertEqual(resp.status_code, 201)


class AnnotationAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username='admin-annotations@example.com',
            email='admin-annotations@example.com',
            password='StrongPass123',
        )
        self.client.force_login(self.admin_user)

        self.user_1 = User.objects.create_user(
            username='annotator-1@example.com',
            email='annotator-1@example.com',
            password='StrongPass123',
        )
        self.user_2 = User.objects.create_user(
            username='annotator-2@example.com',
            email='annotator-2@example.com',
            password='StrongPass123',
        )

        self.book = Book.objects.create(title='Livro anotacoes')
        self.book_version = BookVersion.objects.create(book=self.book, version='1')
        self.chapter_1 = BookChapter.objects.create(
            book_version=self.book_version,
            title='Capítulo A',
            slug='capitulo-a',
            order=1,
            content_rich='<p>Texto A</p>',
        )
        self.chapter_2 = BookChapter.objects.create(
            book_version=self.book_version,
            title='Capítulo B',
            slug='capitulo-b',
            order=2,
            content_rich='<p>Texto B</p>',
        )

        self.annotation_1 = Annotation.objects.create(
            user=self.user_1,
            book_version=self.book_version,
            chapter=self.chapter_1,
            selector={'kind': 'text-quote'},
            start_offset=0,
            end_offset=4,
            note='Nota A',
            color='yellow',
        )
        self.annotation_2 = Annotation.objects.create(
            user=self.user_2,
            book_version=self.book_version,
            chapter=self.chapter_2,
            selector={'kind': 'text-quote'},
            start_offset=0,
            end_offset=4,
            note='Nota B',
            color='green',
        )

    def test_admin_annotations_changelist_groups_by_user(self):
        response = self.client.get(reverse('admin:annotations_annotation_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Quantidade de anotacoes')
        self.assertContains(response, self.user_1.email)
        self.assertContains(response, self.user_2.email)
        self.assertContains(response, f'user__id__exact={self.user_1.id}')
        self.assertContains(response, f'user__id__exact={self.user_2.id}')
        self.assertTrue(response.context['annotation_group_by_user'])

    def test_admin_annotations_user_filter_opens_annotations_from_selected_user(self):
        response = self.client.get(
            f'{reverse("admin:annotations_annotation_changelist")}?user__id__exact={self.user_1.id}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('annotation_group_by_user', response.context)
        self.assertEqual(response.context['cl'].result_count, 1)
        result_ids = [annotation.id for annotation in response.context['cl'].result_list]
        self.assertEqual(result_ids, [self.annotation_1.id])

    def test_admin_annotation_change_view_works_with_changelist_filters(self):
        change_url = reverse('admin:annotations_annotation_change', args=[self.annotation_1.id])
        response = self.client.get(
            change_url,
            {'_changelist_filters': f'user__id__exact={self.user_1.id}'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nota A')


class AnnotationMigrationCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='migrate-annotations@example.com',
            email='migrate-annotations@example.com',
            password='StrongPass123',
        )

        self.book = Book.objects.create(title='Livro migracao')
        self.from_version = BookVersion.objects.create(book=self.book, version='2024.01')
        self.to_version = BookVersion.objects.create(book=self.book, version='2024.02')

        self.from_chapter_main = BookChapter.objects.create(
            book_version=self.from_version,
            title='Capitulo principal',
            slug='cap-principal',
            order=1,
            content_rich='<p>Texto legado com trecho importante.</p>',
        )
        self.from_chapter_missing = BookChapter.objects.create(
            book_version=self.from_version,
            title='Capitulo sem destino',
            slug='cap-sem-destino',
            order=2,
            content_rich='<p>Conteudo sem capitulo correspondente.</p>',
        )
        self.to_chapter_main = BookChapter.objects.create(
            book_version=self.to_version,
            title='Capitulo principal v2',
            slug='cap-principal',
            order=1,
            content_rich='<p>Novo texto com trecho importante e ajustes.</p>',
        )

        excerpt = 'trecho importante'
        source_text = self.from_chapter_main.content_plain
        start = source_text.find(excerpt)
        end = start + len(excerpt)

        self.annotation_main = Annotation.objects.create(
            user=self.user,
            book_version=self.from_version,
            chapter=self.from_chapter_main,
            selector={'kind': 'text-quote'},
            start_offset=start,
            end_offset=end,
            excerpt=excerpt,
            note='nota principal',
            color='yellow',
        )
        self.annotation_missing = Annotation.objects.create(
            user=self.user,
            book_version=self.from_version,
            chapter=self.from_chapter_missing,
            selector={'kind': 'text-quote'},
            start_offset=0,
            end_offset=8,
            excerpt='Conteudo',
            note='nota sem destino',
            color='green',
        )

    def test_command_dry_run_then_copy_creates_target_annotations(self):
        dry_stdout = StringIO()
        call_command(
            'migrate_annotations_between_versions',
            from_version_id=self.from_version.id,
            to_version_id=self.to_version.id,
            dry_run=True,
            stdout=dry_stdout,
        )
        self.assertIn('DRY-RUN', dry_stdout.getvalue())
        self.assertEqual(Annotation.objects.filter(book_version=self.to_version).count(), 0)

        run_stdout = StringIO()
        call_command(
            'migrate_annotations_between_versions',
            from_version_id=self.from_version.id,
            to_version_id=self.to_version.id,
            stdout=run_stdout,
        )
        output = run_stdout.getvalue()
        self.assertIn('created=1', output)
        self.assertIn('skipped_missing_chapter=1', output)

        migrated = Annotation.objects.get(book_version=self.to_version, note='nota principal')
        self.assertEqual(migrated.user_id, self.user.id)
        self.assertEqual(migrated.chapter_id, self.to_chapter_main.id)
        self.assertEqual(migrated.excerpt, 'trecho importante')
        self.assertEqual(migrated.color, 'yellow')
        self.assertTrue(Annotation.objects.filter(id=self.annotation_main.id).exists())

    def test_command_move_removes_source_after_copy(self):
        run_stdout = StringIO()
        call_command(
            'migrate_annotations_between_versions',
            from_version_id=self.from_version.id,
            to_version_id=self.to_version.id,
            move=True,
            stdout=run_stdout,
        )
        output = run_stdout.getvalue()
        self.assertIn('created=1', output)
        self.assertIn('moved=1', output)

        self.assertFalse(Annotation.objects.filter(id=self.annotation_main.id).exists())
        self.assertTrue(Annotation.objects.filter(id=self.annotation_missing.id).exists())
        self.assertEqual(Annotation.objects.filter(book_version=self.to_version).count(), 1)

    def test_command_is_idempotent_for_duplicates(self):
        call_command(
            'migrate_annotations_between_versions',
            from_version_id=self.from_version.id,
            to_version_id=self.to_version.id,
            stdout=StringIO(),
        )

        second_stdout = StringIO()
        call_command(
            'migrate_annotations_between_versions',
            from_version_id=self.from_version.id,
            to_version_id=self.to_version.id,
            stdout=second_stdout,
        )
        output = second_stdout.getvalue()

        self.assertIn('created=0', output)
        self.assertIn('duplicates=1', output)
        self.assertEqual(Annotation.objects.filter(book_version=self.to_version).count(), 1)
