from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CaseLaw


class CaseLawModelTests(TestCase):
    def test_create_caselaw_generates_ementa_plain_and_normalizes_anchors(self):
        cl = CaseLaw.objects.create(
            court='STJ',
            case_number='REsp 123456/DF',
            decision_date=date(2025, 1, 1),
            ementa_rich='<h2>Tema</h2><p>Ementa <strong>rica</strong>.</p>',
            url='https://example.com/case',
            anchors=[
                {'label': 'Fundamentos', 'start_offset': 20, 'end_offset': 80},
                'Dispositivo',
            ],
            tags=['consumidor', ' bagagem ', ''],
        )

        self.assertIn('Tema', cl.ementa_plain)
        self.assertIn('Ementa rica', cl.ementa_plain)
        self.assertEqual(len(cl.anchors), 2)
        self.assertEqual(cl.anchors[0]['id'], 'fundamentos')
        self.assertEqual(cl.tags, ['consumidor', 'bagagem'])
        self.assertIn('STJ', str(cl))

    def test_unique_constraint_court_case_number(self):
        CaseLaw.objects.create(
            court='STF',
            case_number='ARE 1',
            decision_date=date(2025, 1, 1),
            ementa_rich='<p>x</p>',
            url='https://example.com/1',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CaseLaw.objects.create(
                    court='STF',
                    case_number='ARE 1',
                    decision_date=date(2025, 1, 1),
                    ementa_rich='<p>y</p>',
                    url='https://example.com/2',
                )


class CaseLawApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='u1@example.com',
            email='u1@example.com',
            password='StrongPass123',
        )
        self.access = str(RefreshToken.for_user(self.user).access_token)
        self.client = APIClient()

        self.stj = CaseLaw.objects.create(
            court='STJ',
            case_number='REsp 123/DF',
            decision_date=date(2025, 1, 2),
            ementa_rich='<p>Bagagem extraviada - dano moral</p>',
            url='https://example.com/stj-123',
            tags=['bagagem', 'dano moral'],
            anchors=[
                {'id': 'fundamentos', 'label': 'Fundamentos', 'start_offset': 0, 'end_offset': 35},
            ],
        )
        self.tjmg = CaseLaw.objects.create(
            court='TJMG',
            case_number='ApCiv 456/MG',
            decision_date=date(2024, 12, 10),
            ementa_rich='<p>Atraso de voo - indenização</p>',
            url='https://example.com/tjmg-456',
            tags=['atraso'],
            anchors=[
                {'label': 'Dispositivo'},
            ],
        )

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')

    def test_requires_auth(self):
        resp = self.client.get('/caselaw/')
        self.assertIn(resp.status_code, (401, 403))

    def test_list_paginated_shape_and_new_contract(self):
        self.auth()
        resp = self.client.get('/caselaw/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('count', resp.data)
        self.assertIn('results', resp.data)
        self.assertIn('q', resp.data)
        self.assertNotIn('summary', resp.data['results'][0])
        self.assertNotIn('relevance', resp.data['results'][0])
        self.assertIn('ementa_rich', resp.data['results'][0])
        self.assertIn('ementa_plain', resp.data['results'][0])
        self.assertIn('anchors', resp.data['results'][0])

    def test_search_q_hits_ementa_plain(self):
        self.auth()
        resp = self.client.get('/caselaw/?q=bagagem')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['court'], 'STJ')

    def test_search_q_hits_tags_and_anchors(self):
        self.auth()
        resp = self.client.get('/caselaw/?q=fundamentos')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['id'], self.stj.id)

    def test_filter_court(self):
        self.auth()
        resp = self.client.get('/caselaw/?court=TJMG')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['court'], 'TJMG')

    def test_limit_offset(self):
        self.auth()
        resp = self.client.get('/caselaw/?limit=1&offset=0')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['limit'], 1)
        self.assertEqual(resp.data['offset'], 0)

    def test_detail_returns_new_fields_only(self):
        self.auth()
        resp = self.client.get(f'/caselaw/{self.stj.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ementa_rich', resp.data)
        self.assertIn('ementa_plain', resp.data)
        self.assertIn('anchors', resp.data)
        self.assertNotIn('summary', resp.data)
        self.assertNotIn('relevance', resp.data)
