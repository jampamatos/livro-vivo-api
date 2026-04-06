from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from config import admin_navigation  # noqa: F401
from courses.models import CourseAsset, CoursePost, PublicationStatus
from library.models import Book, BookChapter, BookVersion


class AdminNavigationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username='admin-nav@example.com',
            email='admin-nav@example.com',
            password='StrongPass123',
        )

    def _get_app_list_for_user(self, user):
        request = self.factory.get('/admin/')
        request.user = user
        return admin.site.get_app_list(request)

    def test_admin_navigation_is_grouped_by_operational_domain(self):
        app_list = self._get_app_list_for_user(self.superuser)
        app_names = [app['name'] for app in app_list]
        model_names = [model['name'] for app in app_list for model in app['models']]

        self.assertGreaterEqual(len(app_names), 5)
        self.assertEqual(
            app_names[:6],
            [
                'Painel operacional',
                'Biblioteca',
                'Curso',
                'Jurisprudência',
                'Comunidade',
                'Moderação da comunidade',
            ],
        )
        self.assertIn('Banco de peças', app_names)
        self.assertIn('Usuários e assinaturas', app_names)
        self.assertIn('Notificações', app_names)
        self.assertIn('Privacidade e compliance', app_names)
        self.assertNotIn('Versões do livro', model_names)
        self.assertNotIn('Posts da comunidade', model_names)
        self.assertNotIn('Comentários da comunidade', model_names)
        self.assertNotIn('Materiais de curso', model_names)
        self.assertNotIn('Lives e eventos', model_names)
        self.assertNotIn('Preferências de notificação', model_names)
        self.assertNotIn('Envios de notificação', model_names)
        self.assertNotIn('Dispositivos push', model_names)
        self.assertNotIn('Assinaturas', model_names)
        self.assertNotIn('Direitos de acesso', model_names)

    def test_operational_panel_shortcuts_use_prefiltered_links(self):
        app_list = self._get_app_list_for_user(self.superuser)
        self.assertEqual(app_list[0]['name'], 'Painel operacional')

        shortcuts = {item['name']: item['admin_url'] for item in app_list[0]['models']}
        self.assertIn('status__exact=open', shortcuts['Fila de denúncias abertas'])
        self.assertIn('status__exact=draft', shortcuts['Peças jurídicas em rascunho'])
        self.assertIn('status__exact=requested', shortcuts['Solicitações de privacidade pendentes'])

    def test_admin_index_renders_new_groups(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Painel operacional')
        self.assertContains(response, 'Biblioteca')
        self.assertContains(response, 'Curso')
        self.assertContains(response, 'Jurisprudência')
        self.assertContains(response, 'Comunidade')
        self.assertContains(response, 'Moderação da comunidade')
        self.assertContains(response, 'Banco de peças')
        self.assertContains(response, 'Usuários e assinaturas')
        self.assertContains(response, 'Notificações')
        self.assertContains(response, 'Privacidade e compliance')
        self.assertNotContains(response, 'Livros e publicacoes')
        self.assertNotContains(response, 'Cursos e eventos')
        self.assertNotContains(response, '>Versões do livro<', html=False)
        self.assertNotContains(response, '>Versões do livro em rascunho<', html=False)

    def test_non_staff_user_keeps_empty_admin_navigation(self):
        User = get_user_model()
        non_staff_user = User.objects.create_user(
            username='user-nav@example.com',
            email='user-nav@example.com',
            password='StrongPass123',
        )

        app_list = self._get_app_list_for_user(non_staff_user)
        self.assertEqual(app_list, [])

    def test_book_changelist_shows_global_navigation_path(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:library_book_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Biblioteca')
        self.assertContains(response, 'Livros')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_operational_shortcut_uses_operational_path(self):
        self.client.force_login(self.superuser)
        response = self.client.get(f"{reverse('admin:community_report_changelist')}?status__exact=open")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Painel operacional')
        self.assertContains(response, 'Fila de denúncias abertas')
        path = response.context['lv_navigation_path']
        self.assertIn('status__exact=open', path[0]['url'])
        self.assertIn('status__exact=open', path[1]['url'])

    def test_report_changelist_without_filter_uses_moderation_path(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:community_report_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Moderação da comunidade')
        self.assertContains(response, 'Fila de denúncias')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:community_report_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:community_report_changelist'))

    def test_book_change_form_appends_object_to_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Curso de Processo Civil')

        response = self.client.get(reverse('admin:library_book_change', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Biblioteca')
        self.assertContains(response, 'Livros')
        self.assertContains(response, 'Curso de Processo Civil')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_book_history_page_keeps_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Manual de Direito Penal')

        response = self.client.get(reverse('admin:library_book_history', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Biblioteca')
        self.assertContains(response, 'Livros')
        self.assertContains(response, 'Manual de Direito Penal')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_book_delete_page_keeps_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Direito Tributario Essencial')

        response = self.client.get(reverse('admin:library_book_delete', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Você está em:')
        self.assertContains(response, 'Biblioteca')
        self.assertContains(response, 'Livros')
        self.assertContains(response, 'Direito Tributario Essencial')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_book_version_add_redirects_back_to_book_change(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Curso de Responsabilidade Civil')

        response = self.client.post(
            f"{reverse('admin:library_bookversion_add')}?book={book.id}",
            {
                'book': str(book.id),
                'version': '2026.04.06',
                'changelog': 'Versao inicial',
                'status': 'draft',
                'chapters-TOTAL_FORMS': '0',
                'chapters-INITIAL_FORMS': '0',
                'chapters-MIN_NUM_FORMS': '0',
                'chapters-MAX_NUM_FORMS': '1000',
                '_save': 'Salvar',
            },
        )

        self.assertRedirects(response, reverse('admin:library_book_change', args=[book.id]))
        self.assertTrue(BookVersion.objects.filter(book=book, version='2026.04.06').exists())

    def test_book_chapter_add_redirects_back_to_version_change(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Tratado de Contratos')
        version = BookVersion.objects.create(book=book, version='2026.04.06', changelog='Nova base editorial')

        response = self.client.post(
            f"{reverse('admin:library_bookchapter_add')}?book_version={version.id}",
            {
                'book_version': str(version.id),
                'order': '1',
                'title': 'Introducao',
                'slug': 'introducao',
                'content_rich': '<p>Capitulo inicial</p>',
                '_save': 'Salvar',
            },
        )

        self.assertRedirects(response, reverse('admin:library_bookversion_change', args=[version.id]))

    def test_book_chapter_add_prefills_version_and_next_order(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Manual de Recursos')
        version = BookVersion.objects.create(book=book, version='2026.04.06', changelog='Nova base editorial')
        BookChapter.objects.create(
            book_version=version,
            order=6,
            title='Capítulo anterior',
            slug='capitulo-anterior',
            content_rich='<p>Texto anterior</p>',
        )

        response = self.client.get(f"{reverse('admin:library_bookchapter_add')}?book_version={version.id}")

        self.assertEqual(response.status_code, 200)
        form = response.context['adminform'].form
        self.assertEqual(int(form['book_version'].value()), version.id)
        self.assertEqual(int(form['order'].value()), 7)

    def test_book_chapter_add_prefills_from_preserved_changelist_filters(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Curso de Execução')
        version = BookVersion.objects.create(book=book, version='2026.04.06', changelog='Nova base editorial')
        BookChapter.objects.create(
            book_version=version,
            order=3,
            title='Capítulo anterior',
            slug='capitulo-anterior',
            content_rich='<p>Texto anterior</p>',
        )

        response = self.client.get(
            reverse('admin:library_bookchapter_add'),
            {'_changelist_filters': f'book_version__id__exact={version.id}'},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['adminform'].form
        self.assertEqual(int(form['book_version'].value()), version.id)
        self.assertEqual(int(form['order'].value()), 4)

    def test_course_asset_add_redirects_back_to_course_post_change(self):
        self.client.force_login(self.superuser)
        post = CoursePost.objects.create(
            title='Post do curso',
            slug='post-do-curso',
            author_name='Equipe',
            excerpt='Resumo',
            content_rich='<p>Conteudo</p>',
            post_type=CoursePost.PostType.LESSON,
            tags=['curso'],
            status=PublicationStatus.DRAFT,
        )

        response = self.client.post(
            f"{reverse('admin:courses_courseasset_add')}?post={post.id}",
            {
                'post': str(post.id),
                'title': 'Checklist da aula',
                'description': 'Material complementar',
                'asset_type': CourseAsset.AssetType.CHECKLIST,
                'tags': '["curso"]',
                'status': PublicationStatus.DRAFT,
                'file_url': 'https://example.com/checklist.pdf',
                '_save': 'Salvar',
            },
        )

        self.assertRedirects(response, reverse('admin:courses_coursepost_change', args=[post.id]))
        self.assertTrue(CourseAsset.objects.filter(post=post, title='Checklist da aula').exists())
