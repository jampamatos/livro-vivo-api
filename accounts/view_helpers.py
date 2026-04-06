from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model

from config.storage import build_media_reference

from .models import Profile
from .roles import get_user_role

User = get_user_model()


def issue_tokens_for_user(user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def authenticate_user_by_email(request, email: str, password: str):
    """Resolve credenciais por email sem perder a semântica de moderação.

    O backend padrão do Django rejeita usuários inativos durante `authenticate`.
    Aqui só abrimos o fallback manual para contas inativas já localizadas por email,
    preservando o fluxo de bans/notices sem reintroduzir um bypass genérico.
    """

    user = authenticate(request, username=email, password=password)
    if user:
        return user

    candidate_user = User.objects.filter(email__iexact=email).first()
    if not candidate_user:
        return None

    user = authenticate(request, username=candidate_user.username, password=password)
    if user:
        return user

    if candidate_user.is_active:
        return None

    if candidate_user.check_password(password):
        return candidate_user

    return None


def resolve_profile_avatar_reference(profile: Profile, request=None):
    return build_media_reference(
        upload_field=getattr(profile, 'avatar', None),
        remote_url=getattr(profile, 'avatar_url', ''),
        request=request,
        storage_alias='avatars',
    )


def delete_stored_file(storage, name: str):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:  # pragma: no cover
        return


def serialize_user_payload(user, profile: Profile, request=None):
    avatar_reference = resolve_profile_avatar_reference(profile, request=request)
    return {
        'id': user.id,
        'email': user.email,
        'name': profile.full_name,
        'profession': profile.profession,
        'avatar_url': avatar_reference['url'],
        'avatar_source': avatar_reference['source'],
        'role': get_user_role(user),
    }
