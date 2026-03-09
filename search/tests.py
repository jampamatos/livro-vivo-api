from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from caselaw.models import CaseLaw
from community.models import Category, Post
from entitlements.models import Subscription
from library.models import Book, BookChapter, BookVersion


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
        self.assertNotIn('caselaw', {row['type'] for row in response.data['results']})

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
