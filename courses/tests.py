from datetime import timedelta

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from entitlements.models import Subscription

from .models import CourseAsset, CoursePost, LiveEvent, PublicationStatus

User = get_user_model()


class CoursesApiTests(TestCase):
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

        self.post_published_blog = CoursePost.objects.create(
            title='Publicado blog',
            slug='publicado-blog',
            author_name='Autor 1',
            excerpt='Resumo 1',
            content_rich='<p>Conteudo publicado 1</p>',
            post_type=CoursePost.PostType.BLOG,
            tags=['consumidor', 'curso'],
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=3),
        )
        self.post_published_lesson = CoursePost.objects.create(
            title='Publicado aula',
            slug='publicado-aula',
            author_name='Autor 2',
            excerpt='Resumo 2',
            content_rich='<p>Conteudo publicado 2</p>',
            post_type=CoursePost.PostType.LESSON,
            tags=['aula'],
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=1),
        )
        self.post_draft = CoursePost.objects.create(
            title='Rascunho',
            slug='rascunho',
            author_name='Autor 3',
            excerpt='Rascunho',
            content_rich='<p>Conteudo draft</p>',
            post_type=CoursePost.PostType.ANNOUNCEMENT,
            tags=['interno'],
            status=PublicationStatus.DRAFT,
        )

        self.asset_pdf = CourseAsset.objects.create(
            post=self.post_published_blog,
            title='Material PDF',
            description='Descricao do material',
            asset_type=CourseAsset.AssetType.PDF,
            file_url='https://example.com/material.pdf',
            tags=['pdf'],
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=2),
        )
        self.asset_video = CourseAsset.objects.create(
            post=self.post_published_lesson,
            title='Video de apoio',
            description='Descricao do video',
            asset_type=CourseAsset.AssetType.VIDEO,
            file_url='https://example.com/video',
            tags=['video'],
            status=PublicationStatus.PUBLISHED,
            published_at=now - timedelta(days=1),
        )
        self.asset_draft = CourseAsset.objects.create(
            post=self.post_draft,
            title='Rascunho anexo',
            description='Draft',
            asset_type=CourseAsset.AssetType.MODEL,
            file_url='https://example.com/modelo',
            status=PublicationStatus.DRAFT,
        )

        self.live_scheduled = LiveEvent.objects.create(
            post=self.post_published_blog,
            title='Live agendada',
            description='Descricao live',
            event_type=LiveEvent.EventType.LIVE_CLASS,
            status=LiveEvent.Status.SCHEDULED,
            starts_at=now + timedelta(days=2),
            meeting_url='https://zoom.us/j/123',
        )
        self.live_finished = LiveEvent.objects.create(
            post=self.post_published_lesson,
            title='Live gravada',
            description='Descricao gravada',
            event_type=LiveEvent.EventType.WEBINAR,
            status=LiveEvent.Status.FINISHED,
            starts_at=now - timedelta(days=10),
            recording_url='https://example.com/gravacao',
        )
        self.live_draft = LiveEvent.objects.create(
            post=self.post_draft,
            title='Live interna',
            description='Nao publicada',
            event_type=LiveEvent.EventType.MENTORING,
            status=LiveEvent.Status.DRAFT,
            starts_at=now + timedelta(days=5),
        )

    def _auth(self, token: str):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_posts_requires_authentication(self):
        res = self.client.get('/courses/posts/')
        self.assertIn(res.status_code, (401, 403))

    def test_posts_blocks_essential_tier(self):
        self._auth(self.essential_token)
        res = self.client.get('/courses/posts/')
        self.assertEqual(res.status_code, 403)

    def test_posts_list_for_professional_excludes_drafts(self):
        self._auth(self.professional_token)
        res = self.client.get('/courses/posts/')
        self.assertEqual(res.status_code, 200)

        ids = {item['id'] for item in res.data}
        self.assertIn(self.post_published_blog.id, ids)
        self.assertIn(self.post_published_lesson.id, ids)
        self.assertNotIn(self.post_draft.id, ids)

    def test_posts_staff_can_see_drafts(self):
        self._auth(self.staff_token)
        res = self.client.get('/courses/posts/')
        self.assertEqual(res.status_code, 200)

        ids = {item['id'] for item in res.data}
        self.assertIn(self.post_draft.id, ids)

    def test_posts_filters_status_type_and_date_range(self):
        self._auth(self.professional_token)
        res = self.client.get(
            '/courses/posts/',
            {
                'status': PublicationStatus.PUBLISHED,
                'type': CoursePost.PostType.LESSON,
                'date_from': (timezone.now() - timedelta(days=2)).date().isoformat(),
                'date_to': timezone.now().date().isoformat(),
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], self.post_published_lesson.id)
        self.assertIn('content_plain', res.data[0])

    def test_assets_filters_type_and_date_range(self):
        self._auth(self.professional_token)
        res = self.client.get(
            '/courses/assets/',
            {
                'type': CourseAsset.AssetType.VIDEO,
                'date_from': (timezone.now() - timedelta(days=2)).date().isoformat(),
                'date_to': timezone.now().date().isoformat(),
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], self.asset_video.id)
        self.assertEqual(res.data[0]['asset_type'], CourseAsset.AssetType.VIDEO)

    def test_lives_filters_status_type_and_date_range(self):
        self._auth(self.professional_token)
        res = self.client.get(
            '/courses/lives/',
            {
                'status': LiveEvent.Status.SCHEDULED,
                'type': LiveEvent.EventType.LIVE_CLASS,
                'date_from': timezone.now().date().isoformat(),
                'date_to': (timezone.now() + timedelta(days=7)).date().isoformat(),
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], self.live_scheduled.id)

    def test_professional_cannot_create_post_via_api(self):
        self._auth(self.professional_token)
        payload = {
            'title': 'Novo post',
            'slug': 'novo-post',
            'author_name': 'Autor',
            'content_rich': '<p>texto</p>',
            'post_type': CoursePost.PostType.BLOG,
            'status': PublicationStatus.PUBLISHED,
        }
        res = self.client.post('/courses/posts/', payload, format='json')
        self.assertEqual(res.status_code, 403)

    def test_staff_can_create_post_via_api(self):
        self._auth(self.staff_token)
        payload = {
            'title': 'Post staff',
            'slug': 'post-staff',
            'author_name': 'Staff',
            'excerpt': 'Resumo',
            'content_rich': '<p>Conteudo staff</p>',
            'post_type': CoursePost.PostType.BLOG,
            'tags': ['novo'],
            'status': PublicationStatus.PUBLISHED,
        }
        res = self.client.post('/courses/posts/', payload, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['slug'], 'post-staff')
        self.assertTrue(CoursePost.objects.filter(slug='post-staff').exists())

    def test_professional_cannot_retrieve_draft_items(self):
        self._auth(self.professional_token)
        res = self.client.get(f'/courses/posts/{self.post_draft.id}/')
        self.assertEqual(res.status_code, 404)

    def test_invalid_date_filter_returns_400(self):
        self._auth(self.professional_token)
        res = self.client.get('/courses/posts/', {'date_from': '31-12-2026'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('date_from', res.data)


class CoursesAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.client.force_authenticate(user=self.admin_user)

    def test_models_registered_in_admin(self):
        self.assertIn(CoursePost, site._registry)
        self.assertIn(CourseAsset, site._registry)
        self.assertIn(LiveEvent, site._registry)
