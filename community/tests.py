from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Category, Post, Comment


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

        self.user_token = Token.objects.create(user=self.user)
        self.other_token = Token.objects.create(user=self.other)
        self.staff_token = Token.objects.create(user=self.staff)

        self.category = Category.objects.create(name="Geral", slug="geral")

    def auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_categories_list_requires_auth(self):
        res = self.client.get("/community/categories/")
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_token.key)
        res = self.client.get("/community/categories/")
        self.assertEqual(res.status_code, 200)

    def test_category_create_staff_only(self):
        self.auth(self.user_token.key)
        res = self.client.post("/community/categories/", {"name": "X", "slug": "x"})
        self.assertEqual(res.status_code, 403)

        self.auth(self.staff_token.key)
        res = self.client.post("/community/categories/", {"name": "X", "slug": "x"})
        self.assertEqual(res.status_code, 201)

    def test_post_crud_permissions(self):
        self.auth(self.user_token.key)
        res = self.client.post("/community/posts/", {"title": "T1", "body": "B1", "category_id": self.category.id})
        self.assertEqual(res.status_code, 201)
        post_id = res.data["id"]

        # other user cannot edit/delete
        self.auth(self.other_token.key)
        res = self.client.patch(f"/community/posts/{post_id}/", {"title": "HACK"})
        self.assertEqual(res.status_code, 403)

        # author can edit
        self.auth(self.user_token.key)
        res = self.client.patch(f"/community/posts/{post_id}/", {"title": "T2"})
        self.assertEqual(res.status_code, 200)

        # staff can delete
        self.auth(self.staff_token.key)
        res = self.client.delete(f"/community/posts/{post_id}/")
        self.assertEqual(res.status_code, 204)

    def test_posts_require_auth(self):
        res = self.client.get("/community/posts/")
        self.assertEqual(res.status_code, 401)

        res = self.client.post("/community/posts/", {"title": "T1", "body": "B1", "category_id": self.category.id})
        self.assertEqual(res.status_code, 401)

        self.auth(self.user_token.key)
        res = self.client.get("/community/posts/")
        self.assertEqual(res.status_code, 200)

    def test_comment_create_and_filter(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.user_token.key)
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

        self.auth(self.user_token.key)
        res = self.client.get("/community/comments/")
        self.assertEqual(res.status_code, 200)
