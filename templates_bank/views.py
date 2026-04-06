from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import PublicationStatus, TemplatePiece
from .permissions import IsProfessionalSubscriberOrStaff
from .serializers import TemplatePieceSerializer

DOWNLOAD_TOKEN_SALT = 'templates-bank-download-v1'


def _parse_date_or_error(raw_value: str | None, *, field_name: str):
    if not raw_value:
        return None
    parsed = parse_date(raw_value)
    if parsed is None:
        raise ValidationError({field_name: f"Data invalida para '{field_name}'. Use YYYY-MM-DD."})
    return parsed


def _download_token_ttl_seconds() -> int:
    configured = getattr(settings, 'TEMPLATES_BANK_DOWNLOAD_TOKEN_MAX_AGE_SECONDS', 300)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        return 300
    return max(value, 1)


class TemplatePieceViewSet(viewsets.ModelViewSet):
    serializer_class = TemplatePieceSerializer
    queryset = TemplatePiece.objects.all()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'templates_bank_api'
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['updated_at', 'created_at', 'published_at', 'template_code', 'version']
    ordering = ['template_code', '-created_at', '-updated_at']

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'download_token', 'download'):
            return [IsAuthenticated(), IsProfessionalSubscriberOrStaff()]
        return [IsAuthenticated(), IsAdminUser()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_staff:
            qs = qs.filter(status=PublicationStatus.PUBLISHED)

        status_value = (self.request.query_params.get('status') or '').strip()
        if status_value:
            qs = qs.filter(status=status_value)

        category_value = (self.request.query_params.get('category') or '').strip()
        if category_value:
            qs = qs.filter(category=category_value)

        template_code = (self.request.query_params.get('template_code') or '').strip()
        if template_code:
            qs = qs.filter(template_code=template_code)

        date_from = _parse_date_or_error(self.request.query_params.get('date_from'), field_name='date_from')
        if date_from:
            qs = qs.filter(updated_at__date__gte=date_from)

        date_to = _parse_date_or_error(self.request.query_params.get('date_to'), field_name='date_to')
        if date_to:
            qs = qs.filter(updated_at__date__lte=date_to)

        return qs

    @action(detail=True, methods=['get'], url_path='download-token')
    def download_token(self, request, pk=None):
        piece = self.get_object()
        ttl_seconds = _download_token_ttl_seconds()

        token = signing.dumps(
            {
                'piece_id': piece.id,
                'uid': request.user.id,
                'version': piece.version,
            },
            salt=DOWNLOAD_TOKEN_SALT,
        )

        download_path = reverse('template-piece-download', kwargs={'pk': piece.id})
        query = urlencode({'token': token})

        return Response(
            {
                'token': token,
                'expires_in': ttl_seconds,
                'expires_at': (timezone.now() + timedelta(seconds=ttl_seconds)).isoformat(),
                'download_url': request.build_absolute_uri(f'{download_path}?{query}'),
            }
        )

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        piece = self.get_object()
        token = (request.query_params.get('token') or '').strip()
        if not token:
            raise ValidationError({'token': 'token é obrigatório.'})

        ttl_seconds = _download_token_ttl_seconds()

        try:
            payload = signing.loads(token, salt=DOWNLOAD_TOKEN_SALT, max_age=ttl_seconds)
        except signing.SignatureExpired as exc:
            raise PermissionDenied('Token de download expirado.') from exc
        except signing.BadSignature as exc:
            raise PermissionDenied('Token de download inválido.') from exc

        if payload.get('piece_id') != piece.id:
            raise PermissionDenied('Token não corresponde à peça solicitada.')

        if payload.get('uid') != request.user.id:
            raise PermissionDenied('Token não pertence ao usuário autenticado.')

        file_reference = piece.resolve_file_reference(request=request)
        return Response(
            {
                'id': piece.id,
                'title': piece.title,
                'template_code': piece.template_code,
                'version': piece.version,
                'file_name': piece.file_name,
                'file_mime_type': piece.file_mime_type,
                'file_size_bytes': piece.file_size_bytes,
                'file_sha256': piece.file_sha256,
                'file_url': file_reference['url'],
                'file_source': file_reference['source'],
            }
        )
