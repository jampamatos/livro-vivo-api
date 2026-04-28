from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from .legal import build_legal_status
from .models import ExternalIdentity, Profile
from .view_helpers import serialize_user_payload

User = get_user_model()

SOCIAL_AUTH_STATE_SALT = 'accounts-social-auth-state-v1'
SOCIAL_AUTH_RESULT_SALT = 'accounts-social-auth-result-v1'


class SocialIntent:
    LOGIN = 'login'
    LINK = 'link'

    CHOICES = {LOGIN, LINK}


class SocialResultCode:
    LOGIN_SUCCESS = 'login_success'
    REGISTER_SUCCESS = 'register_success'
    LINK_SUCCESS = 'link_success'
    ACCOUNT_EXISTS_REQUIRES_LINKING = 'account_exists_requires_linking'
    PROVIDER_IDENTITY_ALREADY_LINKED = 'provider_identity_already_linked'
    PROVIDER_EMAIL_MISSING = 'provider_email_missing'
    PROVIDER_AUTH_FAILED = 'provider_auth_failed'


@dataclass(frozen=True)
class SocialProviderConfig:
    provider: str
    label: str
    enabled: bool
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class SocialIdentityPayload:
    provider: str
    provider_subject: str
    email: str
    email_verified: bool
    display_name: str
    avatar_url: str
    provider_claims: dict


@dataclass(frozen=True)
class SocialCallbackResolution:
    result_code: str
    provider: str
    user_id: int | None = None
    email: str = ''
    message: str = ''


class SocialAuthConfigurationError(Exception):
    pass


class SocialProviderAuthError(Exception):
    pass


def _social_http_timeout_seconds() -> int:
    try:
        return max(int(getattr(settings, 'SOCIAL_AUTH_HTTP_TIMEOUT_SECONDS', 8)), 1)
    except (TypeError, ValueError):
        return 8


def _social_state_max_age_seconds() -> int:
    try:
        return max(int(getattr(settings, 'SOCIAL_AUTH_STATE_MAX_AGE_SECONDS', 600)), 1)
    except (TypeError, ValueError):
        return 600


def _social_result_max_age_seconds() -> int:
    try:
        return max(int(getattr(settings, 'SOCIAL_AUTH_RESULT_TOKEN_MAX_AGE_SECONDS', 300)), 1)
    except (TypeError, ValueError):
        return 300


def get_supported_social_providers() -> tuple[str, ...]:
    return tuple(choice[0] for choice in ExternalIdentity.Provider.choices)


def get_social_provider_config(provider: str) -> SocialProviderConfig:
    normalized = (provider or '').strip().lower()
    if normalized == ExternalIdentity.Provider.GOOGLE:
        return SocialProviderConfig(
            provider=normalized,
            label='Google',
            enabled=bool(getattr(settings, 'SOCIAL_AUTH_GOOGLE_ENABLED', False)),
            client_id=(getattr(settings, 'SOCIAL_AUTH_GOOGLE_CLIENT_ID', '') or '').strip(),
            client_secret=(getattr(settings, 'SOCIAL_AUTH_GOOGLE_CLIENT_SECRET', '') or '').strip(),
            authorization_url=(getattr(settings, 'SOCIAL_AUTH_GOOGLE_AUTHORIZATION_URL', '') or '').strip(),
            token_url=(getattr(settings, 'SOCIAL_AUTH_GOOGLE_TOKEN_URL', '') or '').strip(),
            userinfo_url=(getattr(settings, 'SOCIAL_AUTH_GOOGLE_USERINFO_URL', '') or '').strip(),
            scopes=tuple(getattr(settings, 'SOCIAL_AUTH_GOOGLE_SCOPES', ('openid', 'email', 'profile'))),
        )
    if normalized == ExternalIdentity.Provider.LINKEDIN:
        return SocialProviderConfig(
            provider=normalized,
            label='LinkedIn',
            enabled=bool(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_ENABLED', False)),
            client_id=(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_CLIENT_ID', '') or '').strip(),
            client_secret=(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_CLIENT_SECRET', '') or '').strip(),
            authorization_url=(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_AUTHORIZATION_URL', '') or '').strip(),
            token_url=(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_TOKEN_URL', '') or '').strip(),
            userinfo_url=(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_USERINFO_URL', '') or '').strip(),
            scopes=tuple(getattr(settings, 'SOCIAL_AUTH_LINKEDIN_SCOPES', ('openid', 'profile', 'email'))),
        )
    raise SocialAuthConfigurationError('Provider social não suportado.')


def list_social_providers() -> list[dict]:
    providers = []
    for provider in get_supported_social_providers():
        config = get_social_provider_config(provider)
        providers.append(
            {
                'provider': config.provider,
                'label': config.label,
                'enabled': config.enabled,
            }
        )
    return providers


def list_linked_accounts(user) -> dict:
    by_provider = {
        identity.provider: identity
        for identity in user.external_identities.order_by('provider')
    }
    accounts = []
    for provider in get_supported_social_providers():
        config = get_social_provider_config(provider)
        identity = by_provider.get(provider)
        accounts.append(
            {
                'provider': provider,
                'label': config.label,
                'enabled': config.enabled,
                'connected': identity is not None,
                'email': identity.email if identity else '',
                'email_verified': bool(identity.email_verified) if identity else False,
                'display_name': identity.display_name if identity else '',
                'avatar_url': identity.avatar_url if identity else '',
                'linked_at': identity.linked_at if identity else None,
                'last_login_at': identity.last_login_at if identity else None,
            }
        )
    return {
        'has_usable_password': user.has_usable_password(),
        'auth_methods': _get_auth_methods(user),
        'linked_accounts': accounts,
    }


def _get_auth_methods(user) -> list[str]:
    methods: list[str] = []
    if user.has_usable_password():
        methods.append('password')
    methods.extend(
        user.external_identities.order_by('provider').values_list('provider', flat=True)
    )
    return methods


def build_social_state_token(*, provider: str, intent: str, redirect_uri: str, user_id: int | None = None) -> str:
    payload = {
        'provider': provider,
        'intent': intent,
        'redirect_uri': redirect_uri,
        'user_id': user_id,
        'nonce': secrets.token_urlsafe(12),
    }
    return signing.dumps(payload, salt=SOCIAL_AUTH_STATE_SALT)


def load_social_state_token(token: str) -> dict:
    return signing.loads(
        token,
        salt=SOCIAL_AUTH_STATE_SALT,
        max_age=_social_state_max_age_seconds(),
    )


def build_social_result_token(resolution: SocialCallbackResolution) -> str:
    payload = {
        'result_code': resolution.result_code,
        'provider': resolution.provider,
        'user_id': resolution.user_id,
        'email': resolution.email,
        'message': resolution.message,
        'nonce': secrets.token_urlsafe(12),
    }
    return signing.dumps(payload, salt=SOCIAL_AUTH_RESULT_SALT)


def load_social_result_token(token: str) -> dict:
    return signing.loads(
        token,
        salt=SOCIAL_AUTH_RESULT_SALT,
        max_age=_social_result_max_age_seconds(),
    )


def validate_social_redirect_uri(redirect_uri: str) -> str:
    normalized = (redirect_uri or '').strip()
    if not normalized:
        raise SocialAuthConfigurationError('redirect_uri é obrigatória.')
    allowed = {
        item.strip()
        for item in getattr(settings, 'SOCIAL_AUTH_ALLOWED_REDIRECT_URIS', [])
        if str(item).strip()
    }
    if normalized not in allowed:
        raise SocialAuthConfigurationError('redirect_uri não autorizada.')
    return normalized


def build_provider_authorization_url(*, config: SocialProviderConfig, state_token: str, callback_url: str) -> str:
    if not config.enabled:
        raise SocialAuthConfigurationError('Provider social desabilitado.')
    if not config.client_id or not config.client_secret:
        raise SocialAuthConfigurationError('Credenciais do provider social não configuradas.')

    params = {
        'client_id': config.client_id,
        'redirect_uri': callback_url,
        'response_type': 'code',
        'scope': ' '.join(config.scopes),
        'state': state_token,
        'access_type': 'offline',
        'include_granted_scopes': 'true',
        'prompt': 'select_account',
    }
    return f'{config.authorization_url}?{urlencode(params)}'


def append_result_token_to_redirect_uri(redirect_uri: str, *, result_token: str) -> str:
    parts = urlsplit(redirect_uri)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query['result_token'] = result_token
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _request_json(url: str, *, method: str = 'GET', data: bytes | None = None, headers: dict | None = None) -> dict:
    request = Request(url, data=data, headers=headers or {}, method=method.upper())
    timeout = _social_http_timeout_seconds()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8')
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        raise SocialProviderAuthError(body or 'Provider respondeu com erro.') from exc
    except URLError as exc:
        raise SocialProviderAuthError('Falha de comunicação com o provider.') from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SocialProviderAuthError('Provider respondeu com payload inválido.') from exc


def exchange_provider_code_for_identity(*, provider: str, code: str, callback_url: str) -> SocialIdentityPayload:
    config = get_social_provider_config(provider)
    if provider != ExternalIdentity.Provider.GOOGLE:
        raise SocialAuthConfigurationError('Provider social não suportado nesta fase.')

    token_payload = urlencode(
        {
            'code': code,
            'client_id': config.client_id,
            'client_secret': config.client_secret,
            'redirect_uri': callback_url,
            'grant_type': 'authorization_code',
        }
    ).encode('utf-8')
    token_response = _request_json(
        config.token_url,
        method='POST',
        data=token_payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    access_token = (token_response.get('access_token') or '').strip()
    if not access_token:
        raise SocialProviderAuthError('Provider não retornou access_token.')

    userinfo = _request_json(
        config.userinfo_url,
        method='GET',
        headers={'Authorization': f'Bearer {access_token}'},
    )
    provider_subject = str(userinfo.get('sub') or '').strip()
    if not provider_subject:
        raise SocialProviderAuthError('Provider não retornou subject válido.')

    email = str(userinfo.get('email') or '').strip().lower()
    email_verified_raw = userinfo.get('email_verified')
    email_verified = bool(email_verified_raw is True or str(email_verified_raw).strip().lower() == 'true')
    display_name = str(userinfo.get('name') or '').strip()
    avatar_url = str(userinfo.get('picture') or '').strip()

    return SocialIdentityPayload(
        provider=provider,
        provider_subject=provider_subject,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
        avatar_url=avatar_url,
        provider_claims=userinfo,
    )


def _find_user_by_email(email: str):
    normalized = (email or '').strip().lower()
    if not normalized:
        return None
    return User.objects.filter(email__iexact=normalized).first()


def _create_social_user(identity: SocialIdentityPayload):
    email = identity.email.strip().lower()
    with transaction.atomic():
        user = User.objects.create_user(username=email, email=email)
        user.set_unusable_password()
        user.save(update_fields=['password'])
        profile, _ = Profile.objects.get_or_create(user=user)
        if identity.display_name:
            profile.full_name = identity.display_name
        if identity.avatar_url:
            profile.avatar_url = identity.avatar_url
        profile.save()
        ExternalIdentity.objects.create(
            user=user,
            provider=identity.provider,
            provider_subject=identity.provider_subject,
            email=email,
            email_verified=identity.email_verified,
            display_name=identity.display_name,
            avatar_url=identity.avatar_url,
            last_login_at=timezone.now(),
            last_synced_at=timezone.now(),
            provider_claims=identity.provider_claims,
        )
    return user


def _sync_identity(identity_record: ExternalIdentity, identity: SocialIdentityPayload, *, mark_login: bool) -> ExternalIdentity:
    identity_record.email = identity.email
    identity_record.email_verified = identity.email_verified
    identity_record.display_name = identity.display_name
    identity_record.avatar_url = identity.avatar_url
    identity_record.provider_claims = identity.provider_claims
    identity_record.last_synced_at = timezone.now()
    if mark_login:
        identity_record.last_login_at = identity_record.last_synced_at
    identity_record.save(
        update_fields=[
            'email',
            'email_verified',
            'display_name',
            'avatar_url',
            'provider_claims',
            'last_synced_at',
            'last_login_at',
        ] if mark_login else [
            'email',
            'email_verified',
            'display_name',
            'avatar_url',
            'provider_claims',
            'last_synced_at',
        ]
    )
    return identity_record


def resolve_social_auth_callback(*, provider: str, intent: str, identity: SocialIdentityPayload, user_id: int | None = None) -> SocialCallbackResolution:
    if not identity.email:
        return SocialCallbackResolution(
            result_code=SocialResultCode.PROVIDER_EMAIL_MISSING,
            provider=provider,
            message='O provider não retornou um e-mail utilizável para esta conta.',
        )

    existing_identity = ExternalIdentity.objects.filter(
        provider=provider,
        provider_subject=identity.provider_subject,
    ).select_related('user').first()

    if intent == SocialIntent.LOGIN:
        if existing_identity is not None:
            _sync_identity(existing_identity, identity, mark_login=True)
            return SocialCallbackResolution(
                result_code=SocialResultCode.LOGIN_SUCCESS,
                provider=provider,
                user_id=existing_identity.user_id,
                email=identity.email,
            )

        existing_user = _find_user_by_email(identity.email)
        if existing_user is not None:
            return SocialCallbackResolution(
                result_code=SocialResultCode.ACCOUNT_EXISTS_REQUIRES_LINKING,
                provider=provider,
                email=identity.email,
                message='Já existe uma conta local com este e-mail. Entre com seu método atual e vincule o provider manualmente.',
            )

        user = _create_social_user(identity)
        return SocialCallbackResolution(
            result_code=SocialResultCode.REGISTER_SUCCESS,
            provider=provider,
            user_id=user.id,
            email=identity.email,
        )

    if intent != SocialIntent.LINK or not user_id:
        raise SocialAuthConfigurationError('Intent social inválido.')

    target_user = User.objects.filter(id=user_id).first()
    if target_user is None:
        return SocialCallbackResolution(
            result_code=SocialResultCode.PROVIDER_AUTH_FAILED,
            provider=provider,
            message='Conta alvo do vínculo não encontrada.',
        )

    if existing_identity is not None:
        if existing_identity.user_id == target_user.id:
            _sync_identity(existing_identity, identity, mark_login=False)
            return SocialCallbackResolution(
                result_code=SocialResultCode.LINK_SUCCESS,
                provider=provider,
                user_id=target_user.id,
                email=identity.email,
            )
        return SocialCallbackResolution(
            result_code=SocialResultCode.PROVIDER_IDENTITY_ALREADY_LINKED,
            provider=provider,
            email=identity.email,
            message='Esta identidade externa já está vinculada a outra conta.',
        )

    current_provider_identity = ExternalIdentity.objects.filter(
        user=target_user,
        provider=provider,
    ).first()
    if current_provider_identity is not None:
        return SocialCallbackResolution(
            result_code=SocialResultCode.PROVIDER_IDENTITY_ALREADY_LINKED,
            provider=provider,
            email=identity.email,
            message='Esta conta já possui um vínculo ativo com este provider.',
        )

    with transaction.atomic():
        ExternalIdentity.objects.create(
            user=target_user,
            provider=provider,
            provider_subject=identity.provider_subject,
            email=identity.email,
            email_verified=identity.email_verified,
            display_name=identity.display_name,
            avatar_url=identity.avatar_url,
            last_synced_at=timezone.now(),
            provider_claims=identity.provider_claims,
        )

    return SocialCallbackResolution(
        result_code=SocialResultCode.LINK_SUCCESS,
        provider=provider,
        user_id=target_user.id,
        email=identity.email,
    )


def serialize_social_complete_link_payload(*, user, request=None) -> dict:
    profile, _ = Profile.objects.get_or_create(user=user)
    return {
        'user': serialize_user_payload(user, profile, request=request),
        'has_usable_password': user.has_usable_password(),
        'auth_methods': _get_auth_methods(user),
        'legal_status': build_legal_status(user, request=request),
        **list_linked_accounts(user),
    }


def unlink_external_identity(*, user, provider: str) -> dict:
    normalized = (provider or '').strip().lower()
    identity = user.external_identities.filter(provider=normalized).first()
    if identity is None:
        raise ExternalIdentity.DoesNotExist

    has_other_identity = user.external_identities.exclude(pk=identity.pk).exists()
    if not user.has_usable_password() and not has_other_identity:
        raise ValueError('Não é permitido remover o último método de acesso da conta.')

    identity.delete()
    return list_linked_accounts(user)
