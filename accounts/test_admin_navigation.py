from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from config import admin_navigation  # noqa: F401
from library.models import Book


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
            app_names[:5],
            [
                'Painel operacional',
                'Livros e publicacoes',
                'Conteudo juridico',
                'Comunidade',
                'Moderacao da comunidade',
            ],
        )
        self.assertIn('Usuarios, assinaturas e notificacoes', app_names)
        self.assertIn('Privacidade e compliance', app_names)
        self.assertNotIn('Versoes do livro', model_names)
        self.assertNotIn('Posts da comunidade', model_names)
        self.assertNotIn('Comentarios da comunidade', model_names)

    def test_operational_panel_shortcuts_use_prefiltered_links(self):
        app_list = self._get_app_list_for_user(self.superuser)
        self.assertEqual(app_list[0]['name'], 'Painel operacional')

        shortcuts = {item['name']: item['admin_url'] for item in app_list[0]['models']}
        self.assertIn('status__exact=open', shortcuts['Fila de reports abertos'])
        self.assertIn('status__exact=draft', shortcuts['Pecas juridicas em rascunho'])
        self.assertIn('status__exact=requested', shortcuts['Solicitacoes de privacidade pendentes'])

    def test_admin_index_renders_new_groups(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Painel operacional')
        self.assertContains(response, 'Livros e publicacoes')
        self.assertContains(response, 'Conteudo juridico')
        self.assertContains(response, 'Comunidade')
        self.assertContains(response, 'Moderacao da comunidade')
        self.assertContains(response, 'Usuarios, assinaturas e notificacoes')
        self.assertContains(response, 'Privacidade e compliance')
        self.assertNotContains(response, 'Comunidade e moderacao')
        self.assertNotContains(response, '>Versoes do livro<', html=False)
        self.assertNotContains(response, '>Versoes do livro em rascunho<', html=False)

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
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Livros e publicacoes')
        self.assertContains(response, 'Catalogo de livros')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_operational_shortcut_uses_operational_path(self):
        self.client.force_login(self.superuser)
        response = self.client.get(f"{reverse('admin:community_report_changelist')}?status__exact=open")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Painel operacional')
        self.assertContains(response, 'Fila de reports abertos')
        path = response.context['lv_navigation_path']
        self.assertIn('status__exact=open', path[0]['url'])
        self.assertIn('status__exact=open', path[1]['url'])

    def test_report_changelist_without_filter_uses_moderation_path(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:community_report_changelist'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Moderacao da comunidade')
        self.assertContains(response, 'Fila de reports')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:community_report_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:community_report_changelist'))

    def test_book_change_form_appends_object_to_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Curso de Processo Civil')

        response = self.client.get(reverse('admin:library_book_change', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Livros e publicacoes')
        self.assertContains(response, 'Catalogo de livros')
        self.assertContains(response, 'Curso de Processo Civil')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_book_history_page_keeps_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Manual de Direito Penal')

        response = self.client.get(reverse('admin:library_book_history', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Livros e publicacoes')
        self.assertContains(response, 'Catalogo de livros')
        self.assertContains(response, 'Manual de Direito Penal')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))

    def test_book_delete_page_keeps_navigation_path(self):
        self.client.force_login(self.superuser)
        book = Book.objects.create(title='Direito Tributario Essencial')

        response = self.client.get(reverse('admin:library_book_delete', args=[book.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Voce esta em:')
        self.assertContains(response, 'Livros e publicacoes')
        self.assertContains(response, 'Catalogo de livros')
        self.assertContains(response, 'Direito Tributario Essencial')
        path = response.context['lv_navigation_path']
        self.assertEqual(path[0]['url'], reverse('admin:library_book_changelist'))
        self.assertEqual(path[1]['url'], reverse('admin:library_book_changelist'))
