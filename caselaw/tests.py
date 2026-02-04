from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import CaseLaw


class CaseLawModelTests(TestCase):
    def test_create_caselaw_defaults(self):
        cl = CaseLaw.objects.create(
            court="STJ",
            case_number="REsp 123456/DF",
            decision_date=timezone.now().date(),
            summary="Ementa/resumo de teste",
            url="https://example.com/case",
        )

        self.assertEqual(cl.tags, [])
        self.assertEqual(cl.relevance, 0)
        self.assertIn("STJ", str(cl))

    def test_create_caselaw_with_tags_and_relevance(self):
        cl = CaseLaw.objects.create(
            court="TJMG",
            case_number="0000000-00.0000.0.00.0000",
            decision_date=timezone.now().date(),
            summary="Outra ementa",
            url="https://example.com/tjmg",
            tags=["cancelamento", "bagagem"],
            relevance=5,
        )

        self.assertEqual(cl.tags, ["cancelamento", "bagagem"])
        self.assertEqual(cl.relevance, 5)

    def test_unique_constraint_court_case_number(self):
        d = timezone.now().date()

        CaseLaw.objects.create(
            court="STF",
            case_number="ARE 1",
            decision_date=d,
            summary="x",
            url="https://example.com/1",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CaseLaw.objects.create(
                    court="STF",
                    case_number="ARE 1",
                    decision_date=d,
                    summary="y",
                    url="https://example.com/2",
                )


class CaseLawApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="u1@example.com",
            email="u1@example.com",
            password="StrongPass123",
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()

        CaseLaw.objects.create(
            court="STJ",
            case_number="REsp 123/DF",
            decision_date=date(2025, 1, 2),
            summary="Bagagem extraviada - dano moral",
            url="https://example.com/stj-123",
            tags=["bagagem", "dano moral"],
            relevance=2,
        )
        CaseLaw.objects.create(
            court="TJMG",
            case_number="ApCiv 456/MG",
            decision_date=date(2024, 12, 10),
            summary="Atraso de voo - indenização",
            url="https://example.com/tjmg-456",
            tags=["atraso"],
            relevance=1,
        )

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_requires_auth(self):
        resp = self.client.get("/caselaw/")
        self.assertIn(resp.status_code, (401, 403))

    def test_list_paginated_shape(self):
        self.auth()
        resp = self.client.get("/caselaw/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("count", resp.data)
        self.assertIn("limit", resp.data)
        self.assertIn("offset", resp.data)
        self.assertIn("results", resp.data)
        self.assertIn("q", resp.data)
        self.assertEqual(resp.data["offset"], 0)

    def test_search_q(self):
        self.auth()
        resp = self.client.get("/caselaw/?q=bagagem")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["court"], "STJ")

    def test_filter_court(self):
        self.auth()
        resp = self.client.get("/caselaw/?court=TJMG")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["court"], "TJMG")

    def test_limit_offset(self):
        self.auth()
        resp = self.client.get("/caselaw/?limit=1&offset=0")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["limit"], 1)
        self.assertEqual(resp.data["offset"], 0)
