from __future__ import annotations

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import APIException

from .models import ExternalIdentity, LegalDocumentVersion, UserLegalAcceptance

REQUIRED_LEGAL_DOCUMENT_TYPES = (
    LegalDocumentVersion.DocumentType.TERMS_OF_USE,
    LegalDocumentVersion.DocumentType.PRIVACY_POLICY,
)

_DOCUMENT_TYPE_ORDER = Case(
    *[
        When(document_type=document_type, then=Value(index))
        for index, document_type in enumerate(REQUIRED_LEGAL_DOCUMENT_TYPES)
    ],
    default=Value(len(REQUIRED_LEGAL_DOCUMENT_TYPES)),
    output_field=IntegerField(),
)

_REQUEST_LEGAL_STATUS_CACHE_ATTR = '_lv_legal_status_cache'


class LegalAcceptanceRequired(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'legal_acceptance_required'
    default_detail = 'Aceite os documentos legais vigentes para continuar usando o beta.'

    def __init__(self, *, required_documents: list[dict], message: str | None = None):
        super().__init__(
            {
                'code': self.default_code,
                'message': message or str(self.default_detail),
                'required_documents': required_documents,
            }
        )


class LegalDocumentsChanged(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'legal_documents_changed'
    default_detail = 'Os documentos legais vigentes mudaram. Recarregue e aceite a versão atual.'

    def __init__(self, *, required_documents: list[dict], message: str | None = None):
        super().__init__(
            {
                'code': self.default_code,
                'message': message or str(self.default_detail),
                'required_documents': required_documents,
            }
        )


def get_request_ip(request) -> str | None:
    forwarded_for = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if forwarded_for:
        return forwarded_for.split(',')[0].strip() or None
    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    return remote_addr or None


def get_auth_methods(user) -> list[str]:
    methods: list[str] = []
    if user.has_usable_password():
        methods.append('password')
    methods.extend(
        user.external_identities.order_by('provider').values_list('provider', flat=True)
    )
    return methods


def get_required_legal_documents_queryset(*, at=None):
    effective_at = at or timezone.now()
    return (
        LegalDocumentVersion.objects.filter(
            document_type__in=REQUIRED_LEGAL_DOCUMENT_TYPES,
            is_active=True,
        )
        .filter(
            Q(enforcement_starts_at__isnull=True)
            | Q(enforcement_starts_at__lte=effective_at)
        )
        .order_by(_DOCUMENT_TYPE_ORDER, '-published_at', '-id')
    )


def _get_acceptance_map(user, *, documents: list[LegalDocumentVersion]) -> dict[int, UserLegalAcceptance]:
    if not documents:
        return {}
    acceptances = (
        UserLegalAcceptance.objects.filter(
            user=user,
            document__in=documents,
        )
        .select_related('document')
        .order_by('-accepted_at')
    )
    return {acceptance.document_id: acceptance for acceptance in acceptances}


def serialize_legal_document_summary(
    document: LegalDocumentVersion,
    *,
    acceptance: UserLegalAcceptance | None = None,
    include_content: bool = False,
) -> dict:
    payload = {
        'id': document.id,
        'document_type': document.document_type,
        'title': document.title,
        'version': document.version,
        'content_sha256': document.content_sha256,
        'published_at': document.published_at,
        'enforcement_starts_at': document.enforcement_starts_at,
        'accepted': acceptance is not None,
        'accepted_at': acceptance.accepted_at if acceptance else None,
    }
    if include_content:
        payload['content_html'] = document.content_html
    return payload


def build_legal_status(user, *, request=None) -> dict:
    if request is not None:
        cached = getattr(request, _REQUEST_LEGAL_STATUS_CACHE_ATTR, None)
        if cached is not None:
            return cached

    documents = list(get_required_legal_documents_queryset())
    acceptance_map = _get_acceptance_map(user, documents=documents)
    current_documents = [
        serialize_legal_document_summary(document, acceptance=acceptance_map.get(document.id))
        for document in documents
    ]
    pending_document_types = [
        document['document_type']
        for document in current_documents
        if not document['accepted']
    ]

    payload = {
        'requires_acceptance': bool(pending_document_types),
        'accepted_current_documents': not pending_document_types,
        'pending_document_types': pending_document_types,
        'current_documents': current_documents,
    }

    if request is not None:
        setattr(request, _REQUEST_LEGAL_STATUS_CACHE_ATTR, payload)
    return payload


def build_legal_acceptance_required_payload(user, *, request=None) -> list[dict]:
    legal_status = build_legal_status(user, request=request)
    return [
        document
        for document in legal_status['current_documents']
        if not document['accepted']
    ]


def list_required_legal_documents_for_user(user) -> list[dict]:
    documents = list(get_required_legal_documents_queryset())
    acceptance_map = _get_acceptance_map(user, documents=documents)
    return [
        serialize_legal_document_summary(
            document,
            acceptance=acceptance_map.get(document.id),
            include_content=True,
        )
        for document in documents
    ]


def list_user_legal_acceptances(user) -> list[dict]:
    acceptances = (
        UserLegalAcceptance.objects.filter(user=user)
        .select_related('document')
        .order_by('-accepted_at')
    )
    return [
        {
            'id': acceptance.id,
            'document_id': acceptance.document_id,
            'document_type': acceptance.document.document_type,
            'document_title': acceptance.document.title,
            'document_version': acceptance.document.version,
            'document_content_sha256': acceptance.document.content_sha256,
            'accepted_at': acceptance.accepted_at,
            'source': acceptance.source,
            'app_platform': acceptance.app_platform,
            'app_version': acceptance.app_version,
            'ip_address': acceptance.ip_address,
            'user_agent': acceptance.user_agent,
        }
        for acceptance in acceptances
    ]


def accept_required_legal_documents(
    *,
    user,
    document_ids: list[int],
    source: str,
    app_platform: str,
    app_version: str,
    ip_address: str | None,
    user_agent: str,
) -> list[UserLegalAcceptance]:
    documents = list(get_required_legal_documents_queryset())
    current_ids = {document.id for document in documents}
    submitted_ids = set(document_ids)

    if current_ids != submitted_ids:
        raise LegalDocumentsChanged(
            required_documents=[
                serialize_legal_document_summary(document)
                for document in documents
            ]
        )

    accepted_documents: list[UserLegalAcceptance] = []
    with transaction.atomic():
        for document in documents:
            acceptance, _ = UserLegalAcceptance.objects.get_or_create(
                user=user,
                document=document,
                defaults={
                    'source': source,
                    'app_platform': app_platform,
                    'app_version': app_version,
                    'ip_address': ip_address,
                    'user_agent': user_agent,
                },
            )
            accepted_documents.append(acceptance)
    return accepted_documents
