from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Category, Post, Comment, Report


User = get_user_model()


class CommunityApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="u@test.com",
            email="u@test.com",
            password="pass1234",
        )
        self.other = User.objects.create_user(
            username="o@test.com",
            email="o@test.com",
            password="pass1234",
        )
        self.staff = User.objects.create_user(
            username="s@test.com",
            email="s@test.com",
            password="pass1234",
            is_staff=True,
        )

        self.user_access = str(RefreshToken.for_user(self.user).access_token)
        self.other_access = str(RefreshToken.for_user(self.other).access_token)
        self.staff_access = str(RefreshToken.for_user(self.staff).access_token)

        self.category = Category.objects.create(name="Geral", slug="geral")

    def auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def test_categories_list_requires_auth(self):
        res = self.client.get("/community/categories/")
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_access)
        res = self.client.get("/community/categories/")
        self.assertEqual(res.status_code, 200)

    def test_category_create_staff_only(self):
        self.auth(self.user_access)
        res = self.client.post("/community/categories/", {"name": "X", "slug": "x"})
        self.assertEqual(res.status_code, 403)

        self.auth(self.staff_access)
        res = self.client.post("/community/categories/", {"name": "X", "slug": "x"})
        self.assertEqual(res.status_code, 201)

    def test_post_crud_permissions(self):
        self.auth(self.user_access)
        res = self.client.post("/community/posts/", {"title": "T1", "body": "B1", "category_id": self.category.id})
        self.assertEqual(res.status_code, 201)
        post_id = res.data["id"]

        # other user cannot edit/delete
        self.auth(self.other_access)
        res = self.client.patch(f"/community/posts/{post_id}/", {"title": "HACK"})
        self.assertEqual(res.status_code, 403)

        # author can edit
        self.auth(self.user_access)
        res = self.client.patch(f"/community/posts/{post_id}/", {"title": "T2"})
        self.assertEqual(res.status_code, 200)

        # staff can delete
        self.auth(self.staff_access)
        res = self.client.delete(f"/community/posts/{post_id}/")
        self.assertEqual(res.status_code, 204)

    def test_posts_require_auth(self):
        res = self.client.get("/community/posts/")
        self.assertEqual(res.status_code, 401)

        res = self.client.post("/community/posts/", {"title": "T1", "body": "B1", "category_id": self.category.id})
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_access)
        res = self.client.get("/community/posts/")
        self.assertEqual(res.status_code, 200)

    def test_comment_create_and_filter(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.user_access)
        res = self.client.post("/community/comments/", {"post_id": post.id, "body": "C1"})
        self.assertEqual(res.status_code, 201)

        res = self.client.get(f"/community/comments/?post={post.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(len(res.data) >= 1)

    def test_comments_require_auth(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        res = self.client.get("/community/comments/")
        self.assertEqual(res.status_code, 401)

        res = self.client.post("/community/comments/", {"post_id": post.id, "body": "C1"})
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_access)
        res = self.client.get("/community/comments/")
        self.assertEqual(res.status_code, 200)

    def test_posts_filter_by_category(self):
        other_category = Category.objects.create(name="Outros", slug="outros")
        Post.objects.create(author=self.user, category=self.category, title="G1", body="B1")
        Post.objects.create(author=self.user, category=other_category, title="O1", body="B2")

        self.auth(self.user_access)
        res = self.client.get(f"/community/posts/?category={self.category.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(p["category"]["id"] == self.category.id for p in res.data))

    def test_comment_update_delete_permissions(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.user, body="C1")

        # outro usuário não pode editar
        self.auth(self.other_access)
        res = self.client.patch(f"/community/comments/{comment.id}/", {"body": "HACK"})
        self.assertEqual(res.status_code, 403)

        # autor pode editar
        self.auth(self.user_access)
        res = self.client.patch(f"/community/comments/{comment.id}/", {"body": "C2"})
        self.assertEqual(res.status_code, 200)

        # staff pode deletar
        self.auth(self.staff_access)
        res = self.client.delete(f"/community/comments/{comment.id}/")
        self.assertEqual(res.status_code, 204)

    def test_report_create_post(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        res = self.client.post("/community/reports/", {"post_id": post.id, "reason": "spam"})
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_access)
        res = self.client.post("/community/reports/", {"post_id": post.id, "reason": "spam"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], Report.Status.OPEN)

    def test_report_create_comment(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.other, body="C")

        self.auth(self.user_access)
        res = self.client.post("/community/reports/", {"comment_id": comment.id, "reason": "abuso"})
        self.assertEqual(res.status_code, 201)

    def test_report_requires_exactly_one_target(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.other, body="C")

        self.auth(self.user_access)
        res = self.client.post("/community/reports/", {"reason": "x"})
        self.assertEqual(res.status_code, 400)

        res = self.client.post("/community/reports/", {"post_id": post.id, "comment_id": comment.id, "reason": "x"})
        self.assertEqual(res.status_code, 400)

    def test_reports_list_staff_only(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.user_access)
        res = self.client.post("/community/reports/", {"post_id": post.id, "reason": "spam"})
        self.assertEqual(res.status_code, 201)

        # user não pode listar
        res = self.client.get("/community/reports/")
        self.assertEqual(res.status_code, 403)

        # staff pode listar
        self.auth(self.staff_access)
        res = self.client.get("/community/reports/")
        self.assertEqual(res.status_code, 200)

    def test_report_update_staff_only(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.user, post=post, reason="spam")

        # usuário comum não pode atualizar
        self.auth(self.user_access)
        res = self.client.patch(f"/community/reports/{report.id}/", {"status": Report.Status.RESOLVED})
        self.assertEqual(res.status_code, 403)

        # staff pode atualizar
        self.auth(self.staff_access)
        res = self.client.patch(f"/community/reports/{report.id}/", {"status": Report.Status.RESOLVED})
        self.assertEqual(res.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.RESOLVED)

    def test_community_posts_is_throttled(self):
        cache.clear()
        self.auth(self.user_access)

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'community_api': '1/min'}):
            first = self.client.get("/community/posts/")
            second = self.client.get("/community/posts/")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
