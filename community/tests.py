from types import SimpleNamespace
from unittest import mock

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Profile
from entitlements.models import Entitlement, Subscription

from .models import Category, Comment, CommentLike, Post, PostFollow, PostLike, Report, ReportModerationAction
from .models import ModerationConfig, UserModerationStatus


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
        self.moderator = User.objects.create_user(
            username="moderador@test.com",
            email="moderador@test.com",
            password="pass1234",
            is_staff=False,
        )
        Profile.objects.update_or_create(
            user=self.moderator,
            defaults={'role': Profile.Role.MODERATOR},
        )

        self.user_access = str(RefreshToken.for_user(self.user).access_token)
        self.other_access = str(RefreshToken.for_user(self.other).access_token)
        self.staff_access = str(RefreshToken.for_user(self.staff).access_token)
        self.moderator_access = str(RefreshToken.for_user(self.moderator).access_token)

        self.category = Category.objects.create(name="Geral", slug="geral")

    def auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def paginated_results(self, response):
        self.assertIn("results", response.data)
        self.assertIn("count", response.data)
        self.assertIn("limit", response.data)
        self.assertIn("offset", response.data)
        return response.data["results"]

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

    def test_post_author_follows_own_post_by_default(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        follow = PostFollow.objects.get(post=post, user=self.user)

        self.assertTrue(follow.is_active)

    def test_post_serializer_exposes_follow_state_and_user_can_follow_unfollow(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.other_access)
        list_response = self.client.get("/community/posts/")
        self.assertEqual(list_response.status_code, 200)
        listed_post = next(item for item in self.paginated_results(list_response) if item["id"] == post.id)
        self.assertFalse(listed_post["is_following"])

        follow_response = self.client.post(f"/community/posts/{post.id}/follow/")
        self.assertEqual(follow_response.status_code, 200)
        self.assertTrue(follow_response.data["is_following"])

        follow = PostFollow.objects.get(post=post, user=self.other)
        self.assertTrue(follow.is_active)

        unfollow_response = self.client.post(f"/community/posts/{post.id}/unfollow/")
        self.assertEqual(unfollow_response.status_code, 200)
        self.assertFalse(unfollow_response.data["is_following"])

        follow.refresh_from_db()
        self.assertFalse(follow.is_active)

    def test_post_serializer_exposes_like_state_and_user_can_like_unlike(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.other_access)
        list_response = self.client.get("/community/posts/")
        self.assertEqual(list_response.status_code, 200)
        listed_post = next(item for item in self.paginated_results(list_response) if item["id"] == post.id)
        self.assertEqual(listed_post["likes_count"], 0)
        self.assertFalse(listed_post["liked_by_me"])
        self.assertEqual(listed_post["comments_count"], 0)
        self.assertIsNone(listed_post["last_comment_at"])

        like_response = self.client.post(f"/community/posts/{post.id}/like/")
        self.assertEqual(like_response.status_code, 200)
        self.assertEqual(like_response.data["likes_count"], 1)
        self.assertTrue(like_response.data["liked_by_me"])

        like = PostLike.objects.get(post=post, user=self.other)
        self.assertTrue(like.is_active)

        unlike_response = self.client.post(f"/community/posts/{post.id}/unlike/")
        self.assertEqual(unlike_response.status_code, 200)
        self.assertEqual(unlike_response.data["likes_count"], 0)
        self.assertFalse(unlike_response.data["liked_by_me"])

        like.refresh_from_db()
        self.assertFalse(like.is_active)

    def test_post_serializer_exposes_comment_counters(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        Comment.objects.create(post=post, author=self.other, body="C1")
        Comment.objects.create(post=post, author=self.user, body="C2")

        self.auth(self.user_access)
        list_response = self.client.get("/community/posts/")
        self.assertEqual(list_response.status_code, 200)
        listed_post = next(item for item in self.paginated_results(list_response) if item["id"] == post.id)
        self.assertEqual(listed_post["comments_count"], 2)
        self.assertIsNotNone(listed_post["last_comment_at"])

        detail_response = self.client.get(f"/community/posts/{post.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["comments_count"], 2)
        self.assertIsNotNone(detail_response.data["last_comment_at"])

    def test_post_and_comment_author_display_uses_profile_full_name(self):
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.full_name = "Jampa Matos"
        profile.save(update_fields=["full_name"])

        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.user, body="C1")

        self.auth(self.other_access)
        detail_response = self.client.get(f"/community/posts/{post.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data["author_display"], "Jampa Matos")
        self.assertIn("author_avatar_url", detail_response.data)
        self.assertIsNone(detail_response.data["author_avatar_url"])

        comments_response = self.client.get(f"/community/comments/?post={post.id}")
        self.assertEqual(comments_response.status_code, 200)
        listed_comment = next(item for item in self.paginated_results(comments_response) if item["id"] == comment.id)
        self.assertEqual(listed_comment["author_display"], "Jampa Matos")
        self.assertIn("author_avatar_url", listed_comment)

    def test_post_author_display_never_exposes_email(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.other_access)
        detail_response = self.client.get(f"/community/posts/{post.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotIn("@", detail_response.data["author_display"])

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
        self.assertTrue(len(self.paginated_results(res)) >= 1)

    def test_post_mentions_candidates_list_participants(self):
        profile_user, _ = Profile.objects.get_or_create(user=self.user)
        profile_user.full_name = "Joao Paulo"
        profile_user.save(update_fields=["full_name"])

        profile_other, _ = Profile.objects.get_or_create(user=self.other)
        profile_other.full_name = "Maria Clara"
        profile_other.save(update_fields=["full_name"])

        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        Comment.objects.create(post=post, author=self.other, body="C1")

        self.auth(self.user_access)
        res = self.client.get(f"/community/posts/{post.id}/mention-candidates/")
        self.assertEqual(res.status_code, 200)

        names = {item["display_name"] for item in res.data}
        self.assertIn("Joao Paulo", names)
        self.assertIn("Maria Clara", names)
        self.assertTrue(all("@" not in item["display_name"] for item in res.data))

        res_filtered = self.client.get(f"/community/posts/{post.id}/mention-candidates/?q=maria")
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(len(res_filtered.data), 1)
        self.assertEqual(res_filtered.data[0]["display_name"], "Maria Clara")

    def test_comment_create_accepts_mention_user_ids(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.other_access)
        with mock.patch("community.views.enqueue_new_comment_notifications") as new_comment_mock:
            with mock.patch("community.views.enqueue_comment_mention_notifications") as mention_mock:
                res = self.client.post(
                    "/community/comments/",
                    {"post_id": post.id, "body": "Oi @Joao", "mention_user_ids": [self.user.id]},
                    format="json",
                )

        self.assertEqual(res.status_code, 201)
        new_comment_mock.assert_called_once()
        mention_mock.assert_called_once()
        mention_kwargs = mention_mock.call_args.kwargs
        self.assertEqual(mention_kwargs["mentioned_user_ids"], [self.user.id])
        self.assertEqual(mention_kwargs["comment"].post_id, post.id)

    def test_comment_create_rejects_invalid_mention_user_ids_payload(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        self.auth(self.other_access)

        res = self.client.post(
            "/community/comments/",
            {"post_id": post.id, "body": "Oi", "mention_user_ids": "invalido"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("mention_user_ids", res.data)

    def test_enqueue_comment_mentions_notifies_only_valid_participants(self):
        from .services import enqueue_comment_mention_notifications

        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        Comment.objects.create(post=post, author=self.staff, body="C0")
        comment = Comment.objects.create(post=post, author=self.other, body="Oi @Joao")

        with mock.patch("community.services.get_active_subscription_user_ids", return_value=[self.user.id, self.staff.id]):
            with mock.patch("community.services.enqueue_notification_event") as enqueue_mock:
                enqueue_comment_mention_notifications(
                    comment=comment,
                    mentioned_user_ids=[self.user.id, self.other.id, self.moderator.id],
                )

        enqueue_mock.assert_called_once()
        kwargs = enqueue_mock.call_args.kwargs
        self.assertEqual(kwargs["recipient_user_ids"], [self.user.id])
        self.assertEqual(kwargs["payload"]["comment_id"], comment.id)

    def test_comment_serializer_exposes_like_state_and_user_can_like_unlike(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.user, body="C1")

        self.auth(self.other_access)
        list_response = self.client.get(f"/community/comments/?post={post.id}")
        self.assertEqual(list_response.status_code, 200)
        listed_comment = next(item for item in self.paginated_results(list_response) if item["id"] == comment.id)
        self.assertEqual(listed_comment["likes_count"], 0)
        self.assertFalse(listed_comment["liked_by_me"])

        like_response = self.client.post(f"/community/comments/{comment.id}/like/")
        self.assertEqual(like_response.status_code, 200)
        self.assertEqual(like_response.data["likes_count"], 1)
        self.assertTrue(like_response.data["liked_by_me"])

        like = CommentLike.objects.get(comment=comment, user=self.other)
        self.assertTrue(like.is_active)

        unlike_response = self.client.post(f"/community/comments/{comment.id}/unlike/")
        self.assertEqual(unlike_response.status_code, 200)
        self.assertEqual(unlike_response.data["likes_count"], 0)
        self.assertFalse(unlike_response.data["liked_by_me"])

        like.refresh_from_db()
        self.assertFalse(like.is_active)

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
        self.assertTrue(all(p["category"]["id"] == self.category.id for p in self.paginated_results(res)))

    def test_posts_limit_offset_and_activity_ordering(self):
        older_live = Post.objects.create(author=self.user, category=self.category, title="Mais antigo", body="B")
        newer_silent = Post.objects.create(author=self.user, category=self.category, title="Sem comentario", body="B")
        Comment.objects.create(post=older_live, author=self.other, body="Comentário recente")

        self.auth(self.user_access)
        res = self.client.get("/community/posts/?limit=1&offset=0")
        self.assertEqual(res.status_code, 200)
        results = self.paginated_results(res)
        self.assertEqual(res.data["limit"], 1)
        self.assertEqual(res.data["offset"], 0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], older_live.id)

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

    def test_report_create_ignores_sensitive_fields_from_user(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")

        self.auth(self.user_access)
        res = self.client.post(
            "/community/reports/",
            {
                "post_id": post.id,
                "reason": "spam",
                "status": Report.Status.RESOLVED,
                "priority": Report.Priority.CRITICAL,
                "decision": Report.Decision.REMOVE,
            },
        )
        self.assertEqual(res.status_code, 201)

        report = Report.objects.get(pk=res.data["id"])
        self.assertEqual(report.status, Report.Status.OPEN)
        self.assertEqual(report.priority, Report.Priority.MEDIUM)
        self.assertEqual(report.decision, "")

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

    def test_reports_list_allows_moderator_role_without_is_staff(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        Report.objects.create(reporter=self.other, post=post, reason="spam")

        self.auth(self.moderator_access)
        res = self.client.get("/community/reports/")
        self.assertEqual(res.status_code, 200)

    def test_moderator_role_can_apply_remove_decision(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.other, post=post, reason="spam")

        self.auth(self.moderator_access)
        res = self.client.post(f"/community/reports/{report.id}/remove/", {"note": "moderacao"})
        self.assertEqual(res.status_code, 200)

        report.refresh_from_db()
        post.refresh_from_db()
        self.assertEqual(report.decision, Report.Decision.REMOVE)
        self.assertEqual(post.moderation_state, Post.ModerationState.REMOVED)

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

    def test_report_update_creates_moderation_audit(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.user, post=post, reason="spam")

        self.auth(self.staff_access)
        res = self.client.patch(
            f"/community/reports/{report.id}/",
            {
                "status": Report.Status.IN_REVIEW,
                "priority": Report.Priority.HIGH,
                "moderation_note": "Triagem inicial",
            },
        )
        self.assertEqual(res.status_code, 200)

        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.IN_REVIEW)
        self.assertEqual(report.priority, Report.Priority.HIGH)
        self.assertEqual(report.moderated_by_id, self.staff.id)
        self.assertEqual(report.moderation_actions.count(), 1)

        action = report.moderation_actions.first()
        self.assertEqual(action.action_type, ReportModerationAction.ActionType.STATUS_CHANGED)
        self.assertEqual(action.from_status, Report.Status.OPEN)
        self.assertEqual(action.to_status, Report.Status.IN_REVIEW)
        self.assertEqual(action.from_priority, Report.Priority.MEDIUM)
        self.assertEqual(action.to_priority, Report.Priority.HIGH)
        self.assertEqual(action.actor_id, self.staff.id)

    def test_staff_decision_actions_approve_remove_escalate_are_audited(self):
        post_approve = Post.objects.create(author=self.user, category=self.category, title="T1", body="B1")
        post_remove = Post.objects.create(author=self.user, category=self.category, title="T2", body="B2")
        post_escalate = Post.objects.create(author=self.user, category=self.category, title="T3", body="B3")

        report_approve = Report.objects.create(reporter=self.user, post=post_approve, reason="spam")
        report_remove = Report.objects.create(reporter=self.user, post=post_remove, reason="abuso")
        report_escalate = Report.objects.create(reporter=self.user, post=post_escalate, reason="grave")

        self.auth(self.user_access)
        forbidden = self.client.post(f"/community/reports/{report_approve.id}/approve/", {"note": "x"})
        self.assertEqual(forbidden.status_code, 403)

        self.auth(self.staff_access)
        approve_res = self.client.post(
            f"/community/reports/{report_approve.id}/approve/",
            {"note": "Conteúdo aceitável."},
        )
        remove_res = self.client.post(
            f"/community/reports/{report_remove.id}/remove/",
            {"note": "Remover conteúdo."},
        )
        escalate_res = self.client.post(
            f"/community/reports/{report_escalate.id}/escalate/",
            {"note": "Encaminhar para avaliação jurídica."},
        )

        self.assertEqual(approve_res.status_code, 200)
        self.assertEqual(remove_res.status_code, 200)
        self.assertEqual(escalate_res.status_code, 200)
        self.assertEqual(len(approve_res.data.get("moderation_actions", [])), 1)
        self.assertEqual(len(remove_res.data.get("moderation_actions", [])), 1)
        self.assertEqual(len(escalate_res.data.get("moderation_actions", [])), 1)

        report_approve.refresh_from_db()
        report_remove.refresh_from_db()
        report_escalate.refresh_from_db()
        post_approve.refresh_from_db()
        post_remove.refresh_from_db()
        post_escalate.refresh_from_db()

        self.assertEqual(report_approve.status, Report.Status.RESOLVED)
        self.assertEqual(report_approve.decision, Report.Decision.APPROVE)
        self.assertEqual(report_remove.status, Report.Status.RESOLVED)
        self.assertEqual(report_remove.decision, Report.Decision.REMOVE)
        self.assertEqual(report_escalate.status, Report.Status.ESCALATED)
        self.assertEqual(report_escalate.decision, Report.Decision.ESCALATE)
        self.assertEqual(post_approve.moderation_state, Post.ModerationState.ACTIVE)
        self.assertEqual(post_remove.moderation_state, Post.ModerationState.REMOVED)
        self.assertEqual(post_escalate.moderation_state, Post.ModerationState.UNDER_REVIEW)

        self.assertEqual(report_approve.moderation_actions.count(), 1)
        self.assertEqual(report_remove.moderation_actions.count(), 1)
        self.assertEqual(report_escalate.moderation_actions.count(), 1)

        approve_action = report_approve.moderation_actions.first()
        self.assertEqual(approve_action.action_type, ReportModerationAction.ActionType.APPROVED)
        self.assertEqual(approve_action.from_status, Report.Status.OPEN)
        self.assertEqual(approve_action.to_status, Report.Status.RESOLVED)

        remove_action = report_remove.moderation_actions.first()
        self.assertEqual(remove_action.action_type, ReportModerationAction.ActionType.REMOVED)

        escalate_action = report_escalate.moderation_actions.first()
        self.assertEqual(escalate_action.action_type, ReportModerationAction.ActionType.ESCALATED)

    def test_decision_action_rejects_invalid_transition(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        report = Report.objects.create(
            reporter=self.user,
            post=post,
            reason="spam",
            status=Report.Status.RESOLVED,
            decision=Report.Decision.APPROVE,
        )

        self.auth(self.staff_access)
        res = self.client.post(f"/community/reports/{report.id}/escalate/", {"note": "tarde demais"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("status", res.data)

    def test_remove_and_escalate_hide_content_from_non_staff_lists(self):
        post_visible = Post.objects.create(author=self.user, category=self.category, title="Visível", body="B")
        post_remove = Post.objects.create(author=self.user, category=self.category, title="Remover", body="B")
        post_escalate = Post.objects.create(author=self.user, category=self.category, title="Escalar", body="B")

        report_remove = Report.objects.create(reporter=self.user, post=post_remove, reason="spam")
        report_escalate = Report.objects.create(reporter=self.user, post=post_escalate, reason="spam")

        self.auth(self.staff_access)
        self.client.post(f"/community/reports/{report_remove.id}/remove/", {"note": "ofensivo"})
        self.client.post(f"/community/reports/{report_escalate.id}/escalate/", {"note": "avaliar"})

        self.auth(self.user_access)
        list_res = self.client.get("/community/posts/")
        self.assertEqual(list_res.status_code, 200)
        listed_ids = {item["id"] for item in self.paginated_results(list_res)}
        self.assertIn(post_visible.id, listed_ids)
        self.assertNotIn(post_remove.id, listed_ids)
        self.assertNotIn(post_escalate.id, listed_ids)

        detail_removed = self.client.get(f"/community/posts/{post_remove.id}/")
        detail_escalated = self.client.get(f"/community/posts/{post_escalate.id}/")
        self.assertEqual(detail_removed.status_code, 404)
        self.assertEqual(detail_escalated.status_code, 404)

    def test_remove_decision_applies_to_comment(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        comment = Comment.objects.create(post=post, author=self.other, body="Comentário alvo")
        report = Report.objects.create(reporter=self.user, comment=comment, reason="abuso")

        self.auth(self.staff_access)
        res = self.client.post(f"/community/reports/{report.id}/remove/", {"note": "Removido por abuso"})
        self.assertEqual(res.status_code, 200)

        comment.refresh_from_db()
        self.assertEqual(comment.moderation_state, Comment.ModerationState.REMOVED)

        self.auth(self.user_access)
        comments_res = self.client.get(f"/community/comments/?post={post.id}")
        self.assertEqual(comments_res.status_code, 200)
        self.assertEqual(len(self.paginated_results(comments_res)), 0)

    def test_remove_decision_issues_warning_to_target_author(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={
                'reports_per_warning': 1,
                'max_warnings_before_ban': 2,
                'auto_ban_on_threshold': False,
            },
        )
        post = Post.objects.create(author=self.other, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.user, post=post, reason="abuso")

        self.auth(self.staff_access)
        res = self.client.post(f"/community/reports/{report.id}/remove/", {"note": "conteúdo removido"})
        self.assertEqual(res.status_code, 200)

        status_obj = UserModerationStatus.objects.get(user=self.other)
        self.assertEqual(status_obj.warnings_issued, 1)
        self.assertTrue(bool(status_obj.pending_login_message))
        self.assertFalse(status_obj.is_banned)

    def test_ban_author_action_keeps_subscription_and_entitlements_for_app_wide_scope(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.APP_WIDE},
        )
        post = Post.objects.create(author=self.other, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.user, post=post, reason="grave")
        subscription = Subscription.objects.create(
            user=self.other,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            source='test',
        )
        entitlement = Entitlement.objects.create(
            user=self.other,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='test',
        )

        self.auth(self.staff_access)
        res = self.client.post(f"/community/reports/{report.id}/ban-author/", {"note": "reincidência"})
        self.assertEqual(res.status_code, 200)

        self.other.refresh_from_db()
        subscription.refresh_from_db()
        entitlement.refresh_from_db()
        status_obj = UserModerationStatus.objects.get(user=self.other)

        self.assertFalse(self.other.is_active)
        self.assertTrue(status_obj.is_banned)
        self.assertEqual(status_obj.ban_scope, UserModerationStatus.BanScope.APP_WIDE)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(entitlement.status, Entitlement.Status.ACTIVE)

    def test_ban_author_action_can_be_community_only(self):
        ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.COMMUNITY_ONLY},
        )
        post = Post.objects.create(author=self.other, category=self.category, title="T", body="B")
        report = Report.objects.create(reporter=self.user, post=post, reason="grave")
        subscription = Subscription.objects.create(
            user=self.other,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            source='test',
        )
        entitlement = Entitlement.objects.create(
            user=self.other,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='test',
        )

        self.auth(self.staff_access)
        res = self.client.post(f"/community/reports/{report.id}/ban-author/", {"note": "ban so comunidade"})
        self.assertEqual(res.status_code, 200)

        self.other.refresh_from_db()
        subscription.refresh_from_db()
        entitlement.refresh_from_db()
        status_obj = UserModerationStatus.objects.get(user=self.other)

        self.assertTrue(self.other.is_active)
        self.assertTrue(status_obj.is_banned)
        self.assertEqual(status_obj.ban_scope, UserModerationStatus.BanScope.COMMUNITY_ONLY)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(entitlement.status, Entitlement.Status.ACTIVE)

    def test_community_only_ban_blocks_community_endpoints(self):
        UserModerationStatus.objects.create(
            user=self.user,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
        )

        self.auth(self.user_access)
        posts_res = self.client.get("/community/posts/")
        create_res = self.client.post(
            "/community/reports/",
            {"post_id": 9999, "reason": "x"},
        )

        self.assertEqual(posts_res.status_code, 403)
        self.assertEqual(create_res.status_code, 403)

    def test_changing_global_ban_scope_to_app_wide_syncs_banned_users(self):
        config, _ = ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.COMMUNITY_ONLY},
        )
        subscription = Subscription.objects.create(
            user=self.other,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            source='test',
        )
        entitlement = Entitlement.objects.create(
            user=self.other,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='test',
        )
        status_obj = UserModerationStatus.objects.create(
            user=self.other,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.COMMUNITY_ONLY,
        )
        self.other.is_active = True
        self.other.save(update_fields=['is_active'])

        config.ban_scope = ModerationConfig.BanScope.APP_WIDE
        config.save()

        status_obj.refresh_from_db()
        self.other.refresh_from_db()
        subscription.refresh_from_db()
        entitlement.refresh_from_db()
        self.assertEqual(status_obj.ban_scope, UserModerationStatus.BanScope.APP_WIDE)
        self.assertFalse(self.other.is_active)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(entitlement.status, Entitlement.Status.ACTIVE)

    def test_changing_global_ban_scope_to_community_only_syncs_banned_users(self):
        config, _ = ModerationConfig.objects.update_or_create(
            singleton_key='default',
            defaults={'ban_scope': ModerationConfig.BanScope.APP_WIDE},
        )
        subscription = Subscription.objects.create(
            user=self.other,
            tier=Subscription.Tier.PROFESSIONAL,
            status=Subscription.Status.ACTIVE,
            source='test',
        )
        entitlement = Entitlement.objects.create(
            user=self.other,
            product=Entitlement.Product.SUBSCRIPTION,
            subscription=subscription,
            status=Entitlement.Status.ACTIVE,
            source='test',
        )
        status_obj = UserModerationStatus.objects.create(
            user=self.other,
            is_banned=True,
            ban_scope=UserModerationStatus.BanScope.APP_WIDE,
        )
        self.other.is_active = False
        self.other.save(update_fields=['is_active'])

        config.ban_scope = ModerationConfig.BanScope.COMMUNITY_ONLY
        config.save()

        status_obj.refresh_from_db()
        self.other.refresh_from_db()
        subscription.refresh_from_db()
        entitlement.refresh_from_db()
        self.assertEqual(status_obj.ban_scope, UserModerationStatus.BanScope.COMMUNITY_ONLY)
        self.assertTrue(self.other.is_active)
        self.assertEqual(subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(entitlement.status, Entitlement.Status.ACTIVE)

    def test_reports_queue_filters_by_status_and_priority(self):
        post = Post.objects.create(author=self.user, category=self.category, title="T", body="B")
        Report.objects.create(reporter=self.user, post=post, reason="r1", status=Report.Status.OPEN, priority=Report.Priority.LOW)
        Report.objects.create(
            reporter=self.user,
            post=post,
            reason="r2",
            status=Report.Status.IN_REVIEW,
            priority=Report.Priority.CRITICAL,
        )
        Report.objects.create(
            reporter=self.user,
            post=post,
            reason="r3",
            status=Report.Status.ESCALATED,
            priority=Report.Priority.HIGH,
            decision=Report.Decision.ESCALATE,
        )

        self.auth(self.staff_access)
        status_filtered = self.client.get("/community/reports/?status=in_review")
        priority_filtered = self.client.get("/community/reports/?priority=critical")
        decision_filtered = self.client.get("/community/reports/?decision=escalate")

        self.assertEqual(status_filtered.status_code, 200)
        self.assertEqual(priority_filtered.status_code, 200)
        self.assertEqual(decision_filtered.status_code, 200)
        self.assertEqual(len(status_filtered.data), 1)
        self.assertEqual(len(priority_filtered.data), 1)
        self.assertEqual(len(decision_filtered.data), 1)

    def test_community_posts_is_throttled(self):
        cache.clear()
        self.auth(self.user_access)

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'community_api': '1/min'}):
            first = self.client.get("/community/posts/")
            second = self.client.get("/community/posts/")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)


class CommunityAdminModerationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client()
        self.staff = User.objects.create_user(
            username="admin_mod@test.com",
            email="admin_mod@test.com",
            password="pass1234",
            is_staff=True,
            is_superuser=True,
        )
        self.user = User.objects.create_user(
            username="reporter@test.com",
            email="reporter@test.com",
            password="pass1234",
        )
        self.category = Category.objects.create(name="Geral Admin", slug="geral-admin")
        self.post = Post.objects.create(author=self.user, category=self.category, title="Post alvo", body="B")
        self.report = Report.objects.create(reporter=self.user, post=self.post, reason="spam")
        self.client.force_login(self.staff)

    def test_admin_save_creates_moderation_action_and_applies_remove(self):
        report_admin = site._registry[Report]
        request = self.factory.post("/admin/community/report/")
        request.user = self.staff

        self.report.status = Report.Status.RESOLVED
        self.report.decision = Report.Decision.REMOVE
        self.report.moderation_note = "Remoção via admin form"

        form = SimpleNamespace(changed_data=["status", "decision", "moderation_note"])
        report_admin.save_model(request, self.report, form, change=True)

        self.report.refresh_from_db()
        self.post.refresh_from_db()

        self.assertEqual(self.report.moderated_by_id, self.staff.id)
        self.assertEqual(self.report.moderation_actions.count(), 1)
        action = self.report.moderation_actions.first()
        self.assertEqual(action.action_type, ReportModerationAction.ActionType.REMOVED)
        self.assertEqual(action.from_status, Report.Status.OPEN)
        self.assertEqual(action.to_status, Report.Status.RESOLVED)
        self.assertEqual(self.post.moderation_state, Post.ModerationState.REMOVED)

    def test_bulk_remove_reports_requires_confirmation_and_note(self):
        response = self.client.post(
            reverse("admin:community_report_changelist"),
            data={
                "action": "remove_reports",
                "_selected_action": [str(self.report.id)],
                "select_across": "0",
                "index": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.post.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.OPEN)
        self.assertEqual(self.post.moderation_state, Post.ModerationState.ACTIVE)
        self.assertContains(response, "Confirme a ação sensível para remover conteúdos denunciados em massa.")

    def test_bulk_remove_reports_updates_state_when_confirmed(self):
        response = self.client.post(
            reverse("admin:community_report_changelist"),
            data={
                "action": "remove_reports",
                "_selected_action": [str(self.report.id)],
                "select_across": "0",
                "index": "0",
                "confirm_sensitive_action": "on",
                "moderation_note": "Conteudo removido por violacao clara.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.post.refresh_from_db()
        self.assertEqual(self.report.status, Report.Status.RESOLVED)
        self.assertEqual(self.report.decision, Report.Decision.REMOVE)
        self.assertEqual(self.report.moderation_note, "Conteudo removido por violacao clara.")
        self.assertEqual(self.post.moderation_state, Post.ModerationState.REMOVED)

    def test_bulk_ban_users_requires_confirmation_and_reason(self):
        moderation_status = UserModerationStatus.load_for_user(self.user)

        response = self.client.post(
            reverse("admin:community_usermoderationstatus_changelist"),
            data={
                "action": "ban_selected_users",
                "_selected_action": [str(moderation_status.id)],
                "select_across": "0",
                "index": "0",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        moderation_status.refresh_from_db()
        self.assertFalse(moderation_status.is_banned)
        self.assertContains(response, "Confirme a ação sensível para banir usuários em massa.")

    def test_bulk_ban_users_applies_ban_when_confirmed(self):
        moderation_status = UserModerationStatus.load_for_user(self.user)

        response = self.client.post(
            reverse("admin:community_usermoderationstatus_changelist"),
            data={
                "action": "ban_selected_users",
                "_selected_action": [str(moderation_status.id)],
                "select_across": "0",
                "index": "0",
                "confirm_sensitive_action": "on",
                "ban_reason": "Reincidencia em abuso da comunidade.",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        moderation_status.refresh_from_db()
        self.user.refresh_from_db()
        self.assertTrue(moderation_status.is_banned)
        self.assertEqual(moderation_status.ban_reason, "Reincidencia em abuso da comunidade.")


class CommunityAdminUxTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin_ux@test.com",
            email="admin_ux@test.com",
            password="pass1234",
        )
        self.author = User.objects.create_user(
            username="author_ux@test.com",
            email="author_ux@test.com",
            password="pass1234",
        )
        self.reporter = User.objects.create_user(
            username="reporter_ux@test.com",
            email="reporter_ux@test.com",
            password="pass1234",
        )
        self.category = Category.objects.create(name="Direito Constitucional", slug="constitucional")
        self.post = Post.objects.create(
            author=self.author,
            category=self.category,
            title="Controle de constitucionalidade",
            body="Resumo do tema.",
        )
        self.comment = Comment.objects.create(
            post=self.post,
            author=self.reporter,
            body="Comentario detalhado sobre o entendimento mais recente.",
        )
        Report.objects.create(reporter=self.superuser, comment=self.comment, reason="revisar")
        self.client.force_login(self.superuser)

    def test_category_changelist_links_category_name_to_filtered_posts(self):
        response = self.client.get(reverse("admin:community_category_changelist"))
        self.assertEqual(response.status_code, 200)

        expected_posts_url = f"{reverse('admin:community_post_changelist')}?category__id__exact={self.category.id}"
        self.assertContains(response, "Você está em:")
        self.assertContains(response, "Comunidade")
        self.assertContains(response, expected_posts_url)
        self.assertContains(response, self.category.name)

    def test_post_changelist_shows_context_path_for_filtered_category(self):
        response = self.client.get(
            f"{reverse('admin:community_post_changelist')}?category__id__exact={self.category.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Você está em:")
        self.assertContains(response, "Comunidade")
        self.assertContains(response, self.category.name)

    def test_post_change_page_shows_comments_panel_and_moderation_fields(self):
        response = self.client.get(reverse("admin:community_post_change", args=[self.post.id]))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Você está em:")
        self.assertContains(response, "Comunidade")
        self.assertContains(response, self.category.name)
        self.assertContains(response, self.post.title)
        self.assertContains(response, "Comentários do post")
        self.assertContains(response, reverse("admin:community_comment_change", args=[self.comment.id]))
        self.assertContains(response, "Status de moderação")
        self.assertContains(response, 'name="moderation_state"', html=False)
        self.assertContains(response, 'name="moderated_by"', html=False)
        self.assertContains(response, 'name="moderated_at_0"', html=False)
        self.assertContains(response, 'name="moderated_at_1"', html=False)
        self.assertContains(response, 'name="moderation_note"', html=False)

    def test_comment_change_page_shows_moderation_section(self):
        response = self.client.get(reverse("admin:community_comment_change", args=[self.comment.id]))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Você está em:")
        self.assertContains(response, "Comunidade")
        self.assertContains(response, self.category.name)
        self.assertContains(response, self.post.title)
        self.assertContains(response, f"Comentário #{self.comment.id}")
        self.assertContains(response, "Moderação")
        self.assertContains(response, 'name="moderation_state"', html=False)
        self.assertContains(response, 'name="moderated_by"', html=False)
        self.assertContains(response, 'name="moderated_at_0"', html=False)
        self.assertContains(response, 'name="moderated_at_1"', html=False)
        self.assertContains(response, 'name="moderation_note"', html=False)

    def test_post_changelist_shows_comments_counter_column(self):
        Comment.objects.create(
            post=self.post,
            author=self.author,
            body="Segundo comentário para validar contador.",
        )

        response = self.client.get(reverse("admin:community_post_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comentários")
        self.assertContains(response, 'field-comments_count">2<', html=False)

    def test_comment_changelist_shows_context_path_for_filtered_post(self):
        response = self.client.get(
            f"{reverse('admin:community_comment_changelist')}?post__id__exact={self.post.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Você está em:")
        self.assertContains(response, "Comunidade")
        self.assertContains(response, self.category.name)
        self.assertContains(response, self.post.title)
        self.assertContains(response, "Comentários")
