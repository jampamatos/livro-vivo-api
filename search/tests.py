from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from caselaw.models import CaseLaw
from community.models import Category, Post
from courses.models import CourseAsset, CoursePost, LiveEvent, PublicationStatus as CoursePublicationStatus
from entitlements.models import Subscription
from library.models import Book, BookChapter, BookVersion
from templates_bank.models import PublicationStatus as TemplatePublicationStatus, TemplatePiece


User = get_user_model()


class GlobalSearchApiTests(APITestCase):
    def _create_user(self, email: str):
        username = email.split('@', 1)[0]
        return User.objects.create_user(
            username=username,
            email=email,
            password='StrongPass123',
        )

    def _create_subscription(self, user, tier: str = Subscription.Tier.PROFESSIONAL):
        return Subscription.objects.create(
            user=user,
            tier=tier,
            status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),
            source='test',
        )

    def _result_key(self, row: dict) -> str:
        row_type = row.get('type')
        params = (row.get('target') or {}).get('params') or {}
        if row_type == 'library_chapter':
            return f'library:{params.get("chapter_id")}'
        if row_type == 'course_post':
            return f'course-post:{params.get("post_id")}'
        if row_type == 'course_asset':
            return f'course-asset:{params.get("asset_id")}'
        if row_type == 'course_live':
            return f'course-live:{params.get("live_id")}'
        if row_type == 'template_piece':
            return f'template:{params.get("template_id")}'
        if row_type == 'caselaw':
            return f'caselaw:{params.get("caselaw_id")}'
        if row_type == 'community_post':
            return f'community:{params.get("post_id")}'
        return f'{row_type}:{params}'

    def test_global_search_requires_authentication(self):
        response = self.client.get(reverse('global-search'), {'q': 'bagagem'})
        self.assertEqual(response.status_code, 401)

    def test_global_search_returns_aggregated_typed_results(self):
        user = self._create_user('global-search@example.com')
        self._create_subscription(user, tier=Subscription.Tier.PROFESSIONAL)
        self.client.force_authenticate(user=user)

        book = Book.objects.create(title='Manual de Bagagem', status=Book.Status.PUBLISHED)
        version = BookVersion.objects.create(
            book=book,
            version='2026.03',
            status=BookVersion.Status.PUBLISHED,
            published_at=timezone.now().date(),
        )
        BookChapter.objects.create(
            book_version=version,
            order=1,
            title='Direito de bagagem',
            slug='direito-bagagem',
            content_rich='<p>Dano por extravio de bagagem em voo internacional.</p>',
        )

        course_post = CoursePost.objects.create(
            title='Bagagem no curso',
            slug='bagagem-no-curso',
            author_name='Equipe do curso',
            excerpt='Visão prática sobre bagagem.',
            content_rich='<p>Bagagem e extravio no material do curso.</p>',
            post_type=CoursePost.PostType.BLOG,
            status=CoursePublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )
        CourseAsset.objects.create(
            post=course_post,
            title='Checklist de bagagem',
            description='Material rápido de bagagem para alunos.',
            asset_type=CourseAsset.AssetType.CHECKLIST,
            file_url='https://example.com/assets/checklist-bagagem.pdf',
            status=CoursePublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )
        LiveEvent.objects.create(
            post=course_post,
            title='Live sobre bagagem',
            description='Tira-dúvidas ao vivo sobre bagagem.',
            event_type=LiveEvent.EventType.LIVE_CLASS,
            status=LiveEvent.Status.SCHEDULED,
            starts_at=timezone.now(),
        )

        TemplatePiece.objects.create(
            title='Modelo de petição de bagagem',
            slug='modelo-peticao-bagagem',
            template_code='bagagem-peticao',
            version='1.0.0',
            changelog='Versão inicial sobre bagagem.',
            description='Peça para litígios de bagagem.',
            category=TemplatePiece.Category.PETITION,
            tags=['bagagem'],
            file_upload=SimpleUploadedFile(
                'bagagem.docx',
                b'conteudo do arquivo de bagagem',
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
            status=TemplatePublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )

        CaseLaw.objects.create(
            court='STJ',
            case_number='REsp 1000/DF',
            decision_date=timezone.now().date(),
            ementa_rich='<p>Bagagem extraviada e dano moral.</p>',
            url='https://example.com/caselaw/1',
            anchors=['fundamentos'],
            tags=['bagagem'],
        )

        category = Category.objects.create(name='Viagens', slug='viagens')
        Post.objects.create(
            author=user,
            category=category,
            title='Bagagem: experiência na companhia',
            body='Compartilhando aprendizados sobre extravio de bagagem.',
        )

        response = self.client.get(reverse('global-search'), {'q': 'bagagem', 'limit': 20, 'offset': 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['q'], 'bagagem')
        self.assertGreaterEqual(response.data['count'], 3)

        result_types = {row['type'] for row in response.data['results']}
        self.assertIn('library_chapter', result_types)
        self.assertIn('course_post', result_types)
        self.assertIn('course_asset', result_types)
        self.assertIn('course_live', result_types)
        self.assertIn('template_piece', result_types)
        self.assertIn('caselaw', result_types)
        self.assertIn('community_post', result_types)

        library_rows = [row for row in response.data['results'] if row['type'] == 'library_chapter']
        self.assertGreaterEqual(len(library_rows), 1)
        library_target_params = library_rows[0]['target']['params']
        self.assertEqual(library_target_params['book_id'], book.id)
        self.assertEqual(library_target_params['chapter_slug'], 'direito-bagagem')
        self.assertEqual(library_target_params['q'], 'bagagem')
        self.assertIn('match_start', library_target_params)
        self.assertIn('match_end', library_target_params)

        course_post_rows = [row for row in response.data['results'] if row['type'] == 'course_post']
        self.assertGreaterEqual(len(course_post_rows), 1)
        self.assertEqual(course_post_rows[0]['target']['route'], 'course')
        self.assertEqual(course_post_rows[0]['target']['params']['post_id'], course_post.id)

        template_rows = [row for row in response.data['results'] if row['type'] == 'template_piece']
        self.assertGreaterEqual(len(template_rows), 1)
        self.assertEqual(template_rows[0]['target']['route'], 'templatesBank')
        self.assertEqual(template_rows[0]['target']['params']['q'], 'bagagem')

        for row in response.data['results']:
            self.assertIn('target', row)
            self.assertIn('route', row['target'])
            self.assertIn('params', row['target'])

    def test_global_search_pagination_is_stable(self):
        user = self._create_user('stable-search@example.com')
        self._create_subscription(user, tier=Subscription.Tier.PROFESSIONAL)
        self.client.force_authenticate(user=user)

        category = Category.objects.create(name='Processual', slug='processual')
        for idx in range(5):
            Post.objects.create(
                author=user,
                category=category,
                title=f'Resultado estável {idx}',
                body='Tema estável para paginação.',
            )

        full_response = self.client.get(reverse('global-search'), {'q': 'estável', 'limit': 50, 'offset': 0})
        first_page = self.client.get(reverse('global-search'), {'q': 'estável', 'limit': 2, 'offset': 0})
        second_page = self.client.get(reverse('global-search'), {'q': 'estável', 'limit': 2, 'offset': 2})

        self.assertEqual(full_response.status_code, 200)
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(first_page.data['count'], full_response.data['count'])
        self.assertEqual(second_page.data['count'], full_response.data['count'])

        expected_keys = [self._result_key(row) for row in full_response.data['results']]
        page_keys = [
            *[self._result_key(row) for row in first_page.data['results']],
            *[self._result_key(row) for row in second_page.data['results']],
        ]
        self.assertEqual(page_keys, expected_keys[:4])

    def test_global_search_hides_caselaw_for_non_professional(self):
        user = self._create_user('essential-search@example.com')
        self._create_subscription(user, tier=Subscription.Tier.ESSENTIAL)
        self.client.force_authenticate(user=user)

        CoursePost.objects.create(
            title='Bagagem no curso essencial',
            slug='bagagem-no-curso-essencial',
            author_name='Equipe',
            excerpt='Conteúdo do curso.',
            content_rich='<p>Bagagem no curso.</p>',
            status=CoursePublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )
        TemplatePiece.objects.create(
            title='Modelo de bagagem essencial',
            slug='modelo-bagagem-essencial',
            template_code='bagagem-essencial',
            version='1.0.0',
            description='Peça sobre bagagem.',
            category=TemplatePiece.Category.PETITION,
            file_upload=SimpleUploadedFile(
                'bagagem-essencial.docx',
                b'arquivo essencial',
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
            status=TemplatePublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )
        CaseLaw.objects.create(
            court='STJ',
            case_number='REsp 2222/DF',
            decision_date=timezone.now().date(),
            ementa_rich='<p>Tema de bagagem para plano essencial.</p>',
            url='https://example.com/caselaw/2',
            anchors=['ementa'],
            tags=['bagagem'],
        )

        response = self.client.get(reverse('global-search'), {'q': 'bagagem'})

        self.assertEqual(response.status_code, 200)
        result_types = {row['type'] for row in response.data['results']}
        self.assertNotIn('caselaw', result_types)
        self.assertNotIn('course_post', result_types)
        self.assertNotIn('course_asset', result_types)
        self.assertNotIn('course_live', result_types)
        self.assertNotIn('template_piece', result_types)

    def test_global_search_allows_staff_without_subscription(self):
        staff = User.objects.create_superuser(
            username='searchstaff',
            email='searchstaff@example.com',
            password='StrongPass123',
        )
        self.client.force_authenticate(user=staff)

        CaseLaw.objects.create(
            court='STF',
            case_number='ARE 3333/SP',
            decision_date=timezone.now().date(),
            ementa_rich='<p>Tema de bagagem para staff.</p>',
            url='https://example.com/caselaw/staff',
            anchors=['fundamentos'],
            tags=['bagagem'],
        )

        response = self.client.get(reverse('global-search'), {'q': 'bagagem'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('caselaw', {row['type'] for row in response.data['results']})

    def test_global_search_is_throttled(self):
        cache.clear()
        user = self._create_user('throttle-search@example.com')
        self._create_subscription(user, tier=Subscription.Tier.PROFESSIONAL)
        self.client.force_authenticate(user=user)

        category = Category.objects.create(name='Throttle', slug='throttle')
        Post.objects.create(
            author=user,
            category=category,
            title='Teste de throttle bagagem',
            body='Corpo do post para hit de busca.',
        )

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'global_search': '1/min'}):
            first = self.client.get(reverse('global-search'), {'q': 'bagagem'})
            second = self.client.get(reverse('global-search'), {'q': 'bagagem'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
