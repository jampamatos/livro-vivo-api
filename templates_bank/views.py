from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.permissions import HasAcceptedRequiredLegalDocuments
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
    configured = getattr(settings, 'TEMPLATES_BANK_DOWNLOAD_TOKEN_MAX_AGE_SECONDS', 60)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        return 60
    return max(value, 1)


def _validate_download_token(*, piece, request, token: str, require_authenticated_user: bool = True) -> None:
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

    token_user_id = payload.get('uid')

    if require_authenticated_user:
        if not request.user.is_authenticated:
            raise PermissionDenied('Autenticação obrigatória para este token.')
        if token_user_id != request.user.id:
            raise PermissionDenied('Token não pertence ao usuário autenticado.')
        return

    if request.user.is_authenticated and token_user_id != request.user.id:
        raise PermissionDenied('Token não pertence ao usuário autenticado.')


def _protected_filesystem_download_url(*, piece, request, token: str) -> str:
    download_path = reverse('template-piece-download-file', kwargs={'pk': piece.id})
    query = urlencode({'token': token})
    return request.build_absolute_uri(f'{download_path}?{query}')


class TemplatePieceViewSet(viewsets.ModelViewSet):
    serializer_class = TemplatePieceSerializer
    queryset = TemplatePiece.objects.all()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'templates_bank_api'
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['updated_at', 'created_at', 'published_at', 'template_code', 'version']
    ordering = ['template_code', '-created_at', '-updated_at']

    def get_permissions(self):
        if self.action == 'download_file':
            return [AllowAny()]
        if self.action in ('list', 'retrieve', 'download_token', 'download'):
            return [
                IsAuthenticated(),
                HasAcceptedRequiredLegalDocuments(),
                IsProfessionalSubscriberOrStaff(),
            ]
        return [IsAuthenticated(), HasAcceptedRequiredLegalDocuments(), IsAdminUser()]

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
        _validate_download_token(piece=piece, request=request, token=token)

        file_reference = piece.resolve_file_reference(request=request)
        if piece.file_upload and getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'filesystem') == 'filesystem':
            file_reference = {
                'url': _protected_filesystem_download_url(piece=piece, request=request, token=token),
                'source': 'upload',
            }
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

    @action(detail=True, methods=['get'], url_path='download-file')
    def download_file(self, request, pk=None):
        piece = self.get_object()
        token = (request.query_params.get('token') or '').strip()
        _validate_download_token(
            piece=piece,
            request=request,
            token=token,
            require_authenticated_user=False,
        )

        if not piece.file_upload or getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'filesystem') != 'filesystem':
            raise Http404('Arquivo local protegido indisponível para esta peça.')

        file_handle = piece.file_upload.open('rb')
        response = FileResponse(
            file_handle,
            as_attachment=True,
            filename=piece.file_name or None,
            content_type=piece.file_mime_type or 'application/octet-stream',
        )
        response['Cache-Control'] = getattr(
            settings,
            'MEDIA_PRIVATE_CACHE_CONTROL',
            'private, max-age=300, no-store',
        )
        if piece.file_size_bytes:
            response['Content-Length'] = str(piece.file_size_bytes)
        return response
