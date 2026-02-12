import tempfile
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from library.models import Book, BookVersion

from .models import Annotation


def _uniq(prefix: str = 'x') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def create_min_instance(model_cls, **overrides):
    """
    Cria uma instância preenchendo automaticamente campos obrigatórios básicos.
    Ajuda a não depender do formato exato dos models do app `library`.
    """
    data = {}
    for field in model_cls._meta.fields:
        if field.primary_key or field.auto_created:
            continue

        # Se já veio override, pula
        if field.name in overrides:
            continue

        # FK: cria recursivamente se necessário
        if isinstance(field, models.ForeignKey):
            rel_model = field.remote_field.model
            # evita criar User sem querer
            if rel_model == get_user_model():
                continue
            data[field.name] = create_min_instance(rel_model)
            continue

        # Defaults
        if field.has_default():
            data[field.name] = field.get_default()
            continue

        # Campos opcionais
        if getattr(field, "null", False):
            data[field.name] = None
            continue
        if getattr(field, "blank", False):
            # se blank mas não null, manda string vazia
            if isinstance(field, (models.CharField, models.TextField)):
                data[field.name] = ""
                continue

        # Campos obrigatórios sem default
        if isinstance(field, models.CharField):
            data[field.name] = _uniq('s')
        elif isinstance(field, models.TextField):
            data[field.name] = 'test'
        elif isinstance(field, (models.IntegerField, models.PositiveIntegerField, models.BigIntegerField)):
            data[field.name] = 1
        elif isinstance(field, models.BooleanField):
            data[field.name] = False
        elif isinstance(field, models.DateTimeField):
            data[field.name] = timezone.now()
        elif isinstance(field, models.DateField):
            data[field.name] = timezone.now().date()
        elif isinstance(field, models.JSONField):
            data[field.name] = []
        elif isinstance(field, models.DecimalField):
            data[field.name] = 0
        elif isinstance(field, models.FileField):
            data[field.name] = SimpleUploadedFile(
                'livro.pdf',
                b"%PDF-1.4\n%...\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
                content_type='application/pdf',
            )
        else:
            # fallback genérico: tenta string
            data[field.name] = _uniq('v')

    data.update(overrides)
    return model_cls.objects.create(**data)


class AnnotationModelTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def test_create_annotation(self):
        User = get_user_model()
        # Seu projeto não define AUTH_USER_MODEL no settings -> normalmente é User padrão do Django
        user = User.objects.create_user(
            username='test@example.com',
            email='test@example.com',
            password='StrongPass123',
        )

        book = create_min_instance(Book)
        book_version = create_min_instance(BookVersion, book=book)

        ann = Annotation.objects.create(
            user=user,
            book_version=book_version,
            page_number=12,
            rects_normalizados=[{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}],
            note="Teste de nota",
            color="yellow",
        )

        self.assertEqual(ann.user_id, user.id)
        self.assertEqual(ann.book_version_id, book_version.id)
        self.assertEqual(ann.page_number, 12)
        self.assertEqual(ann.note, "Teste de nota")
        self.assertEqual(ann.color, "yellow")
        self.assertIsInstance(ann.rects_normalizados, list)
        self.assertEqual(len(ann.rects_normalizados), 1)

class AnnotationApiTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._override = override_settings(MEDIA_ROOT=self._tmp.name)
        self._override.enable()

        User = get_user_model()
        self.user1 = User.objects.create_user(
            username="u1@example.com",
            email="u1@example.com",
            password="StrongPass123",
        )
        self.user2 = User.objects.create_user(
            username="u2@example.com",
            email="u2@example.com",
            password="StrongPass123",
        )

        self.access1 = str(RefreshToken.for_user(self.user1).access_token)
        self.access2 = str(RefreshToken.for_user(self.user2).access_token)

        book = create_min_instance(Book)
        self.book_version = create_min_instance(BookVersion, book=book)

        self.client = APIClient()

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def auth1(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access1}")

    def auth2(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access2}")

    def test_list_only_returns_own_annotations(self):
        Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            page_number=1,
            rects_normalizados=[{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}],
            note="u1",
            color="yellow",
        )
        Annotation.objects.create(
            user=self.user2,
            book_version=self.book_version,
            page_number=1,
            rects_normalizados=[{"x": 0.2, "y": 0.2, "w": 0.3, "h": 0.05}],
            note="u2",
            color="green",
        )

        self.auth1()
        resp = self.client.get("/annotations/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["note"], "u1")

    def test_filters_work(self):
        a1 = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            page_number=10,
            rects_normalizados=[],
            note="p10",
            color="",
        )
        Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            page_number=11,
            rects_normalizados=[],
            note="p11",
            color="",
        )

        self.auth1()
        resp = self.client.get(f"/annotations/?book_version_id={self.book_version.id}&page_number=10")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["id"], a1.id)

    def test_filter_by_book_version_alias(self):
        a1 = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            page_number=5,
            rects_normalizados=[],
            note="alias",
            color="",
        )

        self.auth1()
        resp = self.client.get(f"/annotations/?book_version={self.book_version.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["id"], a1.id)

    def test_cannot_access_other_users_annotation(self):
        a2 = Annotation.objects.create(
            user=self.user2,
            book_version=self.book_version,
            page_number=1,
            rects_normalizados=[],
            note="secret",
            color="",
        )

        self.auth1()
        resp = self.client.get(f"/annotations/{a2.id}/")
        self.assertEqual(resp.status_code, 404)

        resp = self.client.patch(
            f"/annotations/{a2.id}/",
            {"note": "hacked"},
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

        resp = self.client.delete(f"/annotations/{a2.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_create_sets_user_automatically(self):
        self.auth1()
        payload = {
            "book_version": self.book_version.id,
            "page_number": 12,
            "rects_normalizados": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}],
            "note": "nova nota",
            "color": "yellow",
        }
        resp = self.client.post("/annotations/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        ann_id = resp.data["id"]

        ann = Annotation.objects.get(id=ann_id)
        self.assertEqual(ann.user_id, self.user1.id)
        self.assertEqual(ann.page_number, 12)

    def test_update_and_delete_own_annotation(self):
        ann = Annotation.objects.create(
            user=self.user1,
            book_version=self.book_version,
            page_number=2,
            rects_normalizados=[],
            note="old",
            color="yellow",
        )

        self.auth1()
        resp = self.client.patch(
            f"/annotations/{ann.id}/",
            {"note": "new note", "color": "green"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        ann.refresh_from_db()
        self.assertEqual(ann.note, "new note")
        self.assertEqual(ann.color, "green")

        resp = self.client.delete(f"/annotations/{ann.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Annotation.objects.filter(id=ann.id).exists())
