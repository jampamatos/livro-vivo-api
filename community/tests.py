from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import Category, Post, Comment


class CommunityModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="alice", password="pass1234")
        self.category = Category.objects.create(name="Geral", slug="geral")

    def test_create_post(self):
        post = Post.objects.create(
            author=self.user,
            category=self.category,
            title="Primeiro post",
            body="Conteúdo do post",
        )
        self.assertEqual(post.author, self.user)
        self.assertEqual(post.category, self.category)
        self.assertEqual(post.title, "Primeiro post")
        self.assertIsNotNone(post.created_at)
        self.assertIsNotNone(post.updated_at)

    def test_create_comment(self):
        post = Post.objects.create(
            author=self.user,
            category=self.category,
            title="Post",
            body="Body",
        )
        comment = Comment.objects.create(post=post, author=self.user, body="Comentário")
        self.assertEqual(comment.post, post)
        self.assertEqual(comment.author, self.user)
        self.assertEqual(comment.body, "Comentário")

    def test_delete_post_cascades_comments(self):
        post = Post.objects.create(
            author=self.user,
            category=self.category,
            title="Post",
            body="Body",
        )
        Comment.objects.create(post=post, author=self.user, body="c1")
        self.assertEqual(Comment.objects.count(), 1)
        post.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_post_ordering_latest_first(self):
        p1 = Post.objects.create(author=self.user, title="p1", body="b1")
        p2 = Post.objects.create(author=self.user, title="p2", body="b2")

        Post.objects.filter(pk=p1.pk).update(created_at=timezone.now() - timezone.timedelta(days=1))
        Post.objects.filter(pk=p2.pk).update(created_at=timezone.now())

        posts = list(Post.objects.all())
        self.assertEqual(posts[0].pk, p2.pk)
        self.assertEqual(posts[1].pk, p1.pk)
