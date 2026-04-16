from datetime import timedelta
from unittest import mock

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
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
        self.assertEqual(res.data[0]['file_source'], 'remote_url')
        self.assertNotIn('file_storage_backend', res.data[0])
        self.assertNotIn('file_storage_key', res.data[0])
        self.assertNotIn('file_cache_control', res.data[0])

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

    def test_courses_endpoints_are_throttled(self):
        cache.clear()
        self._auth(self.professional_token)

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'courses_api': '1/min'}):
            first = self.client.get('/courses/posts/')
            second = self.client.get('/courses/posts/')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class CoursesAdminTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin@example.com',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.client.force_login(self.admin_user)
        self.post = CoursePost.objects.create(
            title='Post Admin',
            slug='post-admin',
            author_name='Admin',
            excerpt='Resumo',
            content_rich='<h2>Título</h2><p>Texto <strong>rico</strong>.</p>',
            post_type=CoursePost.PostType.BLOG,
            status=PublicationStatus.PUBLISHED,
            published_at=timezone.now() - timedelta(days=1),
        )
        self.live_event = LiveEvent.objects.create(
            post=self.post,
            title='Live Admin',
            description='<h3>Agenda</h3><p>Conteúdo <strong>ao vivo</strong>.</p>',
            event_type=LiveEvent.EventType.LIVE_CLASS,
            status=LiveEvent.Status.SCHEDULED,
            starts_at=timezone.now() + timedelta(days=2),
            meeting_url='https://example.com/live',
        )

    def test_models_registered_in_admin(self):
        self.assertIn(CoursePost, site._registry)
        self.assertIn(CourseAsset, site._registry)
        self.assertIn(LiveEvent, site._registry)

    def test_course_post_admin_change_form_loads_rich_editor_assets(self):
        response = self.client.get(reverse('admin:courses_coursepost_change', args=[self.post.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'library/admin/chapter_rich_editor.css')
        self.assertContains(response, 'tinymce/tinymce.min.js')
        self.assertContains(response, 'django_tinymce/init_tinymce.js')
        self.assertContains(response, 'undo redo | blocks | bold italic underline superscript subscript')
        self.assertContains(response, 'min_height')
        self.assertContains(response, '&quot;width&quot;: &quot;100%&quot;')
        self.assertContains(response, 'style="width: 100%;"')
        self.assertContains(response, 'lists link wordcount')
        self.assertNotContains(response, 'lists link autoresize wordcount')
        self.assertContains(response, 'Nota de rodap\\u00e9=footnote')
        self.assertContains(response, '&quot;formats&quot;: {&quot;footnote&quot;: {&quot;block&quot;: &quot;aside&quot;}}')
        self.assertContains(response, 'Tags permitidas:')
        self.assertContains(response, 'sub, sup')
        self.assertContains(response, 'lv-rich-editor-preview')

    def test_course_post_admin_save_sanitizes_content_and_keeps_formatting(self):
        response = self.client.post(
            reverse('admin:courses_coursepost_change', args=[self.post.id]),
            data={
                'title': 'Post Admin atualizado',
                'slug': 'post-admin',
                'author_name': 'Admin',
                'excerpt': 'Resumo atualizado',
                'post_type': CoursePost.PostType.BLOG,
                'tags': '["curso"]',
                'status': PublicationStatus.PUBLISHED,
                'published_at': (timezone.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S'),
                'content_rich': (
                    '<h2 onclick="alert(1)">Título</h2>'
                    '<p>Texto <strong>formatado</strong><sup>1</sup> com H<sub>2</sub>O e '
                    '<a href="https://example.com" target="_blank">link</a>.</p>'
                    '<aside>Nota editorial.</aside>'
                    '<script>alert("xss")</script>'
                ),
                '_save': 'Save',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.post.refresh_from_db()
        self.assertIn('<h2>Título</h2>', self.post.content_rich)
        self.assertIn('<strong>formatado</strong>', self.post.content_rich)
        self.assertIn('<sup>1</sup>', self.post.content_rich)
        self.assertIn('<sub>2</sub>', self.post.content_rich)
        self.assertIn('href="https://example.com"', self.post.content_rich)
        self.assertIn('<aside>Nota editorial.</aside>', self.post.content_rich)
        self.assertNotIn('<script', self.post.content_rich)
        self.assertNotIn('onclick', self.post.content_rich)
        self.assertIn('Título Texto formatado 1 com H 2 O e link', self.post.content_plain)
        self.assertIn('Nota editorial.', self.post.content_plain)

    def test_live_event_admin_change_form_loads_rich_editor_assets(self):
        response = self.client.get(reverse('admin:courses_liveevent_change', args=[self.live_event.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'library/admin/chapter_rich_editor.css')
        self.assertContains(response, 'tinymce/tinymce.min.js')
        self.assertContains(response, 'django_tinymce/init_tinymce.js')
        self.assertContains(response, 'undo redo | blocks | bold italic underline superscript subscript')
        self.assertContains(response, 'Nota de rodap\\u00e9=footnote')
        self.assertContains(response, '&quot;formats&quot;: {&quot;footnote&quot;: {&quot;block&quot;: &quot;aside&quot;}}')
        self.assertContains(response, 'Tags permitidas:')
        self.assertContains(response, 'sub, sup')
        self.assertContains(response, 'lv-rich-editor-preview')

    def test_live_event_admin_save_sanitizes_description_and_keeps_formatting(self):
        starts_at = timezone.now() + timedelta(days=3)
        response = self.client.post(
            reverse('admin:courses_liveevent_change', args=[self.live_event.id]),
            data={
                'post': str(self.post.id),
                'title': 'Live Admin atualizada',
                'description': (
                    '<h3 onclick="alert(1)">Agenda</h3>'
                    '<p>Sessão com <strong>material</strong> e '
                    '<a href="https://example.com/live" target="_blank">link</a>.</p>'
                    '<script>alert("xss")</script>'
                ),
                'event_type': LiveEvent.EventType.LIVE_CLASS,
                'status': LiveEvent.Status.SCHEDULED,
                'starts_at_0': starts_at.strftime('%Y-%m-%d'),
                'starts_at_1': starts_at.strftime('%H:%M:%S'),
                'ends_at_0': '',
                'ends_at_1': '',
                'meeting_url': 'https://example.com/live',
                'recording_url': '',
                '_save': 'Save',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.live_event.refresh_from_db()
        self.assertIn('<h3>Agenda</h3>', self.live_event.description)
        self.assertIn('<strong>material</strong>', self.live_event.description)
        self.assertIn('href="https://example.com/live"', self.live_event.description)
        self.assertNotIn('<script', self.live_event.description)
        self.assertNotIn('onclick', self.live_event.description)

    def test_course_post_bulk_publish_requires_sensitive_confirmation(self):
        draft_post = CoursePost.objects.create(
            title='Post rascunho',
            slug='post-rascunho',
            author_name='Equipe',
            excerpt='Rascunho para teste',
            content_rich='<p>Conteudo</p>',
            post_type=CoursePost.PostType.LESSON,
            status=PublicationStatus.DRAFT,
        )

        response = self.client.post(
            reverse('admin:courses_coursepost_changelist'),
            data={
                'action': 'publish_selected_posts',
                '_selected_action': [str(draft_post.id)],
                'select_across': '0',
                'index': '0',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft_post.refresh_from_db()
        self.assertEqual(draft_post.status, PublicationStatus.DRAFT)
        self.assertContains(response, 'Confirme a ação sensível para publicar posts em massa.')

    def test_course_post_bulk_publish_updates_status_when_confirmed(self):
        draft_post = CoursePost.objects.create(
            title='Post rascunho confirmado',
            slug='post-rascunho-confirmado',
            author_name='Equipe',
            excerpt='Rascunho com confirmação',
            content_rich='<p>Conteudo</p>',
            post_type=CoursePost.PostType.ANNOUNCEMENT,
            status=PublicationStatus.DRAFT,
        )

        response = self.client.post(
            reverse('admin:courses_coursepost_changelist'),
            data={
                'action': 'publish_selected_posts',
                '_selected_action': [str(draft_post.id)],
                'select_across': '0',
                'index': '0',
                'confirm_sensitive_action': 'on',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft_post.refresh_from_db()
        self.assertEqual(draft_post.status, PublicationStatus.PUBLISHED)
        self.assertIsNotNone(draft_post.published_at)

    def test_course_asset_bulk_archive_requires_sensitive_confirmation(self):
        asset = CourseAsset.objects.create(
            post=self.post,
            title='Checklist operacional',
            description='Checklist para revisão',
            asset_type=CourseAsset.AssetType.CHECKLIST,
            status=PublicationStatus.PUBLISHED,
            published_at=timezone.now(),
        )

        response = self.client.post(
            reverse('admin:courses_courseasset_changelist'),
            data={
                'action': 'archive_selected_assets',
                '_selected_action': [str(asset.id)],
                'select_across': '0',
                'index': '0',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        asset.refresh_from_db()
        self.assertEqual(asset.status, PublicationStatus.PUBLISHED)
        self.assertContains(response, 'Confirme a ação sensível para arquivar materiais em massa.')
