from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

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
