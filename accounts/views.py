import logging
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework.views import APIView

from entitlements.models import Entitlement
from entitlements.services import get_effective_tier, get_subscription_snapshot

from .models import ExternalIdentity, NotificationDispatch, NotificationPreference, Profile, PushDevice
from .legal import (
    accept_required_legal_documents,
    build_legal_status,
    get_auth_methods,
    get_request_ip,
    list_required_legal_documents_for_user,
    list_user_legal_acceptances,
)
from .permissions import HasAcceptedRequiredLegalDocuments
from .serializers import (
    LegalAcceptanceSubmitSerializer,
    MePasswordChangeSerializer,
    MePasswordSetSerializer,
    MeUpdateSerializer,
    NotificationDispatchSerializer,
    NotificationPreferenceSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PushDeviceRegisterSerializer,
    PushDeviceSerializer,
    PushDeviceUnregisterSerializer,
    RegisterSerializer,
    SocialAuthCompleteSerializer,
    SocialAuthStartSerializer,
)
from .services import create_user_data_export_package, request_user_data_erasure
from .social import (
    SocialAuthConfigurationError,
    SocialCallbackResolution,
    SocialIntent,
    SocialProviderAuthError,
    SocialResultCode,
    append_result_token_to_redirect_uri,
    build_provider_authorization_url,
    build_social_result_token,
    build_social_state_token,
    exchange_provider_code_for_identity,
    get_social_provider_config,
    list_linked_accounts,
    list_social_providers,
    resolve_social_auth_callback,
    serialize_social_complete_link_payload,
    unlink_external_identity,
    load_social_state_token,
)
from .view_helpers import (
    authenticate_user_by_email,
    delete_stored_file,
    issue_tokens_for_user,
    serialize_user_payload,
)
from community.services import (
    get_banned_login_message,
    pull_pending_login_notice,
    get_user_moderation_summary,
    sync_user_activity_with_moderation,
)

User = get_user_model()
logger = logging.getLogger("livro_vivo.api")


class SocialAuthResultRedirect(HttpResponseRedirect):
    @property
    def allowed_schemes(self):
        schemes = set(HttpResponseRedirect.allowed_schemes)
        for redirect_uri in getattr(settings, 'SOCIAL_AUTH_ALLOWED_REDIRECT_URIS', []):
            scheme = urlsplit(str(redirect_uri).strip()).scheme
            if scheme:
                schemes.add(scheme)
        return list(schemes)


PASSWORD_RESET_REQUEST_MESSAGE = (
    'Se o e-mail informado estiver cadastrado, enviaremos instrucoes para redefinir a senha.'
)


def _serialize_auth_context(user, *, request=None) -> dict:
    return {
        'auth_methods': get_auth_methods(user),
        'legal_status': build_legal_status(user, request=request),
    }


def _serialize_me_payload(user, profile, *, request=None) -> dict:
    return {
        **serialize_user_payload(user, profile, request=request),
        'has_usable_password': user.has_usable_password(),
        **_serialize_auth_context(user, request=request),
    }


def _issue_authenticated_session_response(
    user,
    *,
    request,
    success_event: str,
    blocked_event: str,
    source: str,
    extra_payload: dict | None = None,
):
    sync_user_activity_with_moderation(user)
    user.refresh_from_db(fields=['is_active'])
    message = get_banned_login_message(user)
    if message:
        logger.warning(
            blocked_event,
            extra={"reason": "account_banned", "user_id": user.id, "source": source},
        )
        return Response(
            {"detail": message, "code": "account_banned"},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not user.is_active:
        logger.warning(
            blocked_event,
            extra={"reason": "inactive_account", "user_id": user.id, "source": source},
        )
        return Response(
            {"detail": "Esta conta está inativa."},
            status=status.HTTP_403_FORBIDDEN,
        )

    tokens = issue_tokens_for_user(user)
    profile, _ = Profile.objects.get_or_create(user=user)
    moderation_notice = pull_pending_login_notice(user)
    payload = {
        **tokens,
        'user': serialize_user_payload(user, profile, request=request),
        **_serialize_auth_context(user, request=request),
    }
    if extra_payload:
        payload.update(extra_payload)
    if moderation_notice:
        payload['moderation_notice'] = moderation_notice
    logger.info(
        success_event,
        extra={"user_id": user.id, "source": source, "has_moderation_notice": bool(moderation_notice)},
    )
    return Response(payload, status=status.HTTP_200_OK)


class RegisterView(APIView):
    """Cadastro de usuário com criação de sessão JWT e perfil."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = serializer.save()
        except IntegrityError:
            logger.warning("auth_register_failed", extra={"reason": "registration_conflict"})
            raise ValidationError({"detail": "Nao foi possivel concluir o cadastro com os dados informados."})
        profile, _ = Profile.objects.get_or_create(user=user)
        tokens = issue_tokens_for_user(user)
        logger.info("auth_register_success", extra={"user_id": user.id})

        return Response(
            {
                **tokens,
                'user': serialize_user_payload(user, profile, request=request),
                **_serialize_auth_context(user, request=request),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """Login por email e senha com retorno de sessão JWT."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        if not email or not password:
            logger.warning("auth_login_failed", extra={"reason": "missing_credentials"})
            return Response({"detail": "Email e senha são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate_user_by_email(request, email, password)

        if not user:
            logger.warning("auth_login_failed", extra={"reason": "invalid_credentials"})
            return Response({"detail": "Credenciais inválidas."}, status=status.HTTP_401_UNAUTHORIZED)
        return _issue_authenticated_session_response(
            user,
            request=request,
            success_event='auth_login_success',
            blocked_event='auth_login_blocked',
            source='password',
        )


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        user = User.objects.filter(email__iexact=email, is_active=True).order_by('id').first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            query = urlencode({'uid': uid, 'token': token})
            separator = '&' if '?' in settings.PASSWORD_RESET_CONFIRM_URL else '?'
            reset_url = f'{settings.PASSWORD_RESET_CONFIRM_URL}{separator}{query}'
            subject = 'Redefinicao de senha - Livro Vivo'
            message = (
                'Recebemos uma solicitacao para redefinir sua senha no Livro Vivo.\n\n'
                f'Acesse o link abaixo para criar uma nova senha:\n{reset_url}\n\n'
                'Se voce nao solicitou esta alteracao, ignore este e-mail.'
            )
            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
                logger.info('auth_password_reset_requested', extra={'user_id': user.id})
            except Exception:
                logger.exception('auth_password_reset_email_failed', extra={'user_id': user.id})
        else:
            logger.info('auth_password_reset_requested_unknown_email')

        return Response({'detail': PASSWORD_RESET_REQUEST_MESSAGE}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset_confirm'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        logger.info('auth_password_reset_confirmed', extra={'user_id': user.id})
        return Response({'detail': 'Senha redefinida com sucesso.'}, status=status.HTTP_200_OK)


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_refresh'


class AuthProvidersView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'providers': list_social_providers()}, status=status.HTTP_200_OK)


class SocialAuthStartView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'

    def post(self, request, provider: str):
        serializer = SocialAuthStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        intent = serializer.validated_data['intent']
        if intent == SocialIntent.LINK and not request.user.is_authenticated:
            return Response(
                {'detail': 'Autentique-se antes de vincular um provider social.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            config = get_social_provider_config(provider)
            state_token = build_social_state_token(
                provider=config.provider,
                intent=intent,
                redirect_uri=serializer.validated_data['redirect_uri'],
                user_id=request.user.id if intent == SocialIntent.LINK else None,
            )
            callback_url = request.build_absolute_uri(
                reverse('auth-social-callback', kwargs={'provider': config.provider})
            )
            authorization_url = build_provider_authorization_url(
                config=config,
                state_token=state_token,
                callback_url=callback_url,
            )
        except SocialAuthConfigurationError as exc:
            raise ValidationError({'detail': str(exc)}) from exc

        return Response(
            {
                'provider': config.provider,
                'intent': intent,
                'authorization_url': authorization_url,
            },
            status=status.HTTP_200_OK,
        )


class SocialAuthCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, provider: str):
        state_token = (request.query_params.get('state') or '').strip()
        if not state_token:
            return Response({'detail': 'state é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            state_payload = load_social_state_token(state_token)
        except Exception:
            return Response({'detail': 'state inválido ou expirado.'}, status=status.HTTP_400_BAD_REQUEST)

        state_provider = (state_payload.get('provider') or '').strip().lower()
        if state_provider != (provider or '').strip().lower():
            return Response(
                {'detail': 'Provider do callback não confere com o state.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        redirect_uri = state_payload['redirect_uri']
        error_code = (request.query_params.get('error') or '').strip()
        error_description = (request.query_params.get('error_description') or '').strip()

        if error_code:
            result_token = build_social_result_token(
                SocialCallbackResolution(
                    result_code=SocialResultCode.PROVIDER_AUTH_FAILED,
                    provider=state_provider,
                    message=error_description or f'Provider retornou erro: {error_code}.',
                )
            )
            return SocialAuthResultRedirect(
                append_result_token_to_redirect_uri(redirect_uri, result_token=result_token)
            )

        code = (request.query_params.get('code') or '').strip()
        if not code:
            result_token = build_social_result_token(
                SocialCallbackResolution(
                    result_code=SocialResultCode.PROVIDER_AUTH_FAILED,
                    provider=state_provider,
                    message='Provider não retornou authorization code.',
                )
            )
            return SocialAuthResultRedirect(
                append_result_token_to_redirect_uri(redirect_uri, result_token=result_token)
            )

        callback_url = request.build_absolute_uri(
            reverse('auth-social-callback', kwargs={'provider': state_provider})
        )
        try:
            identity = exchange_provider_code_for_identity(
                provider=state_provider,
                code=code,
                callback_url=callback_url,
            )
            resolution = resolve_social_auth_callback(
                provider=state_provider,
                intent=state_payload['intent'],
                identity=identity,
                user_id=state_payload.get('user_id'),
            )
        except SocialProviderAuthError as exc:
            resolution = SocialCallbackResolution(
                result_code=SocialResultCode.PROVIDER_AUTH_FAILED,
                provider=state_provider,
                message=str(exc),
            )
        except SocialAuthConfigurationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        result_token = build_social_result_token(resolution)
        return SocialAuthResultRedirect(
            append_result_token_to_redirect_uri(redirect_uri, result_token=result_token)
        )


class SocialAuthCompleteView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SocialAuthCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result_payload = serializer.validated_data['result_payload']
        result_code = result_payload['result_code']
        provider = result_payload['provider']
        user_id = result_payload.get('user_id')
        email = result_payload.get('email', '')
        message = result_payload.get('message', '')

        if result_code in {SocialResultCode.LOGIN_SUCCESS, SocialResultCode.REGISTER_SUCCESS}:
            user = User.objects.filter(id=user_id).first()
            if user is None:
                return Response(
                    {'detail': 'Usuário do fluxo social não encontrado.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return _issue_authenticated_session_response(
                user,
                request=request,
                success_event='auth_social_complete_success',
                blocked_event='auth_social_complete_blocked',
                source=provider,
                extra_payload={
                    'result_code': result_code,
                    'provider': provider,
                },
            )

        if result_code == SocialResultCode.LINK_SUCCESS:
            if not request.user.is_authenticated:
                return Response(
                    {'detail': 'Autentique-se antes de concluir o vínculo do provider social.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if request.user.id != user_id:
                return Response(
                    {'detail': 'O vínculo retornado não pertence à sessão autenticada atual.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {
                    'result_code': result_code,
                    'provider': provider,
                    **serialize_social_complete_link_payload(user=request.user, request=request),
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                'result_code': result_code,
                'provider': provider,
                'email': email,
                'message': message,
            },
            status=status.HTTP_200_OK,
        )

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            logger.warning("auth_logout_failed", extra={"reason": "missing_refresh"})
            return Response({"detail": "Token de refresh é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh)
            token.blacklist()
            logger.info("auth_logout_success", extra={"user_id": request.user.id, "token_status": "blacklisted"})
        except TokenError:
            # não vaza detalhe: se já expirou ou é inválido, tratamos como logout idempotente
            logger.info("auth_logout_success", extra={"user_id": request.user.id, "token_status": "idempotent"})

        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Retorna dados básicos do usuário autenticado."""

    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.request.method.upper() == 'PATCH':
            return [IsAuthenticated(), HasAcceptedRequiredLegalDocuments()]
        return [IsAuthenticated()]

    def get(self, request):
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(_serialize_me_payload(user, profile, request=request))

    def patch(self, request):
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)
        serializer = MeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        update_fields = []
        previous_avatar_storage = profile.avatar.storage if profile.avatar and profile.avatar.name else None
        previous_avatar_name = profile.avatar.name if profile.avatar and profile.avatar.name else ''

        if 'name' in serializer.validated_data:
            profile.full_name = serializer.validated_data['name']
            update_fields.append('full_name')

        if 'profession' in serializer.validated_data:
            profile.profession = serializer.validated_data['profession']
            update_fields.append('profession')

        if 'avatar_url' in serializer.validated_data:
            profile.avatar_url = serializer.validated_data['avatar_url']
            if serializer.validated_data['avatar_url'] and profile.avatar:
                profile.avatar = None
                update_fields.extend(['avatar', 'avatar_url'])
            else:
                update_fields.append('avatar_url')

        if serializer.validated_data.get('avatar_clear'):
            profile.avatar = None
            profile.avatar_url = ''
            update_fields.extend(['avatar', 'avatar_url'])

        if 'avatar' in serializer.validated_data and serializer.validated_data['avatar'] is not None:
            profile.avatar = serializer.validated_data['avatar']
            profile.avatar_url = ''
            update_fields.extend(['avatar', 'avatar_url'])

        if update_fields:
            profile.save(update_fields=list(dict.fromkeys(update_fields)))
            current_avatar_name = profile.avatar.name if profile.avatar and profile.avatar.name else ''
            if previous_avatar_name and previous_avatar_name != current_avatar_name:
                delete_stored_file(previous_avatar_storage, previous_avatar_name)
            avatar_action = (
                'upload'
                if ('avatar' in serializer.validated_data and serializer.validated_data['avatar'] is not None)
                else 'clear'
                if serializer.validated_data.get('avatar_clear')
                else 'url'
                if 'avatar_url' in serializer.validated_data and serializer.validated_data['avatar_url']
                else 'none'
            )
            logger.info(
                'me_profile_updated',
                extra={
                    'user_id': user.id,
                    'updated_fields': list(dict.fromkeys(update_fields)),
                    'avatar_action': avatar_action,
                },
            )

        return Response(_serialize_me_payload(user, profile, request=request), status=status.HTTP_200_OK)


class MeLegalDocumentsRequiredView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'documents': list_required_legal_documents_for_user(request.user)})


class MeLegalAcceptancesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'acceptances': list_user_legal_acceptances(request.user)})


class MeLegalAcceptancesAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LegalAcceptanceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        acceptances = accept_required_legal_documents(
            user=request.user,
            document_ids=serializer.validated_data['document_ids'],
            source=serializer.validated_data['source'],
            app_platform=serializer.validated_data['app_platform'],
            app_version=serializer.validated_data.get('app_version', ''),
            ip_address=get_request_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '').strip(),
        )
        setattr(request, '_lv_legal_status_cache', None)

        return Response(
            {
                'accepted_document_ids': [acceptance.document_id for acceptance in acceptances],
                'legal_status': build_legal_status(request.user, request=request),
            },
            status=status.HTTP_200_OK,
        )


class MePasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MePasswordChangeSerializer(data=request.data, context={'user': request.user})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        logger.info('me_password_changed', extra={'user_id': user.id})

        return Response({'detail': 'Senha atualizada com sucesso.'}, status=status.HTTP_200_OK)


class MePasswordSetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.has_usable_password():
            return Response(
                {
                    'detail': 'Esta conta já possui senha definida.',
                    'code': 'password_already_set',
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = MePasswordSetSerializer(data=request.data, context={'user': user})
        serializer.is_valid(raise_exception=True)

        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        logger.info('me_password_set', extra={'user_id': user.id})

        return Response(
            {
                'detail': 'Senha definida com sucesso.',
                **serialize_social_complete_link_payload(user=user, request=request),
            },
            status=status.HTTP_200_OK,
        )


class MeLinkedAccountsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(list_linked_accounts(request.user), status=status.HTTP_200_OK)


class MeLinkedAccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, provider: str):
        try:
            payload = unlink_external_identity(user=request.user, provider=provider)
        except ExternalIdentity.DoesNotExist as exc:
            raise NotFound('Vínculo externo não encontrado.') from exc
        except ValueError as exc:
            return Response(
                {
                    'detail': str(exc),
                    'code': 'last_auth_method_removal_not_allowed',
                },
                status=status.HTTP_409_CONFLICT,
            )

        logger.info(
            'me_linked_account_removed',
            extra={'user_id': request.user.id, 'provider': (provider or '').strip().lower()},
        )
        return Response(payload, status=status.HTTP_200_OK)


class MeDataExportView(APIView):
    """Exporta os dados do usuário autenticado em um pacote JSON."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        export_payload = create_user_data_export_package(user=request.user)
        logger.info('me_data_export_generated', extra={'user_id': request.user.id})
        return Response(export_payload, status=status.HTTP_200_OK)


class MeDataErasureRequestView(APIView):
    """Inicia solicitação de exclusão com soft-delete e anonimização da conta."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        confirmation = (request.data.get('confirmation') or '').strip().upper()
        if confirmation != 'DELETE':
            return Response(
                {
                    'detail': 'Confirmação inválida. Envie confirmation="DELETE".',
                    'required_confirmation': 'DELETE',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get('reason') or '').strip()
        result = request_user_data_erasure(user=request.user, reason=reason)
        logger.info('me_data_erasure_requested', extra={'user_id': request.user.id})
        return Response(result, status=status.HTTP_202_ACCEPTED)


class MeEntitlementsView(APIView):
    """Lista entitlements do usuário."""

    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments]

    def get(self, request):
        effective_tier = get_effective_tier(request.user)
        subscription_snapshot = get_subscription_snapshot(request.user)
        qs = (
            Entitlement.objects
            .filter(user=request.user)
            .select_related('subscription')
            .order_by('-created_at')
        )

        data = [
            {
                'id': e.id,
                'product': e.product,
                'book_id': e.book_id,
                'subscription_id': e.subscription_id,
                'tier': (
                    e.subscription.tier
                    if e.product == Entitlement.Product.SUBSCRIPTION and e.subscription_id
                    else (effective_tier if e.product == Entitlement.Product.SUBSCRIPTION and e.is_active() else None)
                ),
                'is_founder': (
                    bool(e.subscription.is_founder)
                    if e.product == Entitlement.Product.SUBSCRIPTION and e.subscription_id
                    else bool(
                        e.product == Entitlement.Product.SUBSCRIPTION
                        and e.is_active()
                        and subscription_snapshot
                        and subscription_snapshot.get('is_founder')
                    )
                ),
                'status': e.status,
                'expires_at': e.expires_at,
                'is_active': e.is_active(),
                'source': e.source,
            }
            for e in qs
        ]

        return Response(
            {
                "entitlements": data,
                "effective_tier": effective_tier,
                "subscription": subscription_snapshot,
                "moderation": get_user_moderation_summary(request.user),
            }
        )


class MeNotificationPreferencesView(APIView):
    """Leitura/atualização das preferências de notificação do usuário."""

    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'notifications_sensitive'

    @staticmethod
    def _get_preferences(user):
        preferences, _ = NotificationPreference.objects.get_or_create(user=user)
        return preferences

    def get(self, request):
        preferences = self._get_preferences(request.user)
        serializer = NotificationPreferenceSerializer(preferences)
        return Response(serializer.data)

    def patch(self, request):
        preferences = self._get_preferences(request.user)
        serializer = NotificationPreferenceSerializer(preferences, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MeNotificationsView(APIView):
    """Lista notificações do usuário para banner/inbox no app."""

    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'notifications_sensitive'

    def get(self, request):
        channel_filter = (request.query_params.get('channel') or '').strip().lower()
        if channel_filter and channel_filter not in NotificationDispatch.Channel.values:
            return Response(
                {'detail': 'channel inválido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        status_filter = (request.query_params.get('status') or NotificationDispatch.Status.PENDING).strip().lower()
        if status_filter not in NotificationDispatch.Status.values:
            return Response(
                {'detail': 'status inválido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        include_acknowledged = (request.query_params.get('include_acknowledged') or '').strip().lower() in {
            '1',
            'true',
            'yes',
        }
        try:
            limit = int(request.query_params.get('limit') or 20)
        except ValueError:
            limit = 20
        limit = max(1, min(limit, 50))

        queryset = (
            NotificationDispatch.objects
            .filter(user=request.user, status=status_filter)
            .select_related('event')
            .order_by('-created_at')
        )
        if channel_filter:
            queryset = queryset.filter(channel=channel_filter)
        if not include_acknowledged:
            queryset = queryset.filter(acknowledged_at__isnull=True)

        serializer = NotificationDispatchSerializer(queryset[:limit], many=True)
        return Response(serializer.data)


class MeNotificationAcknowledgeView(APIView):
    """Marca uma notificação como consumida pelo usuário."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'notifications_sensitive'

    def post(self, request, dispatch_id: int):
        try:
            dispatch = NotificationDispatch.objects.select_related('event').get(
                id=dispatch_id,
                user=request.user,
            )
        except NotificationDispatch.DoesNotExist as exc:
            raise NotFound('Notificação não encontrada.') from exc

        if dispatch.acknowledged_at is None:
            acked_at = timezone.now()
            NotificationDispatch.objects.filter(
                user=request.user,
                event_id=dispatch.event_id,
                acknowledged_at__isnull=True,
            ).update(acknowledged_at=acked_at, updated_at=acked_at)
            dispatch.refresh_from_db()

        serializer = NotificationDispatchSerializer(dispatch)
        return Response(serializer.data)


class MeInAppNotificationConsumeLatestView(APIView):
    """Entrega só o último banner pendente e colapsa o backlog mais antigo."""

    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'notifications_sensitive'

    def post(self, request):
        dispatch = (
            NotificationDispatch.objects
            .filter(
                user=request.user,
                channel=NotificationDispatch.Channel.IN_APP,
                status=NotificationDispatch.Status.PENDING,
                acknowledged_at__isnull=True,
            )
            .select_related('event')
            .order_by('-created_at')
            .first()
        )
        if dispatch is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        acked_at = timezone.now()
        NotificationDispatch.objects.filter(
            user=request.user,
            channel=NotificationDispatch.Channel.IN_APP,
            status=NotificationDispatch.Status.PENDING,
            acknowledged_at__isnull=True,
            created_at__lte=dispatch.created_at,
        ).update(acknowledged_at=acked_at, updated_at=acked_at)

        dispatch.refresh_from_db()
        serializer = NotificationDispatchSerializer(dispatch)
        return Response(serializer.data)


class MePushDevicesView(APIView):
    """Registro e desativação de dispositivos para push via Expo."""

    permission_classes = [IsAuthenticated, HasAcceptedRequiredLegalDocuments]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'notifications_sensitive'

    def get(self, request):
        devices = PushDevice.objects.filter(user=request.user).order_by('-last_seen_at')
        serializer = PushDeviceSerializer(devices, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = PushDeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data['expo_push_token']
        installation_id = serializer.validated_data['installation_id']

        with transaction.atomic():
            installation_device = (
                PushDevice.objects.select_for_update()
                .filter(installation_id=installation_id)
                .first()
            )
            token_device = (
                PushDevice.objects.select_for_update()
                .filter(expo_push_token=token)
                .first()
            )

            if token_device and token_device.user_id != request.user.id:
                token_installation_id = (token_device.installation_id or '').strip()
                if token_installation_id and token_installation_id != installation_id:
                    raise ValidationError(
                        {'expo_push_token': 'Este dispositivo já está vinculado a outra conta.'}
                    )

            device = installation_device or token_device
            if device is None:
                device = PushDevice(installation_id=installation_id)
            else:
                device.installation_id = installation_id

            if token_device and device.pk and token_device.pk != device.pk:
                token_device.delete()

            device.user = request.user
            device.platform = serializer.validated_data['platform']
            device.expo_push_token = token
            device.is_active = True
            device.disabled_reason = ''
            device.save()

            NotificationDispatch.objects.filter(
                user=request.user,
                channel=NotificationDispatch.Channel.PUSH,
                status=NotificationDispatch.Status.PENDING,
                acknowledged_at__isnull=True,
                created_at__lt=device.last_seen_at,
            ).update(
                status=NotificationDispatch.Status.SKIPPED,
                reason='push_stale_before_current_device',
            )

        response_serializer = PushDeviceSerializer(device)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request):
        serializer = PushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        filters = Q()
        expo_push_token = serializer.validated_data.get('expo_push_token') or ''
        installation_id = serializer.validated_data.get('installation_id') or ''
        if expo_push_token:
            filters |= Q(expo_push_token=expo_push_token)
        if installation_id:
            filters |= Q(installation_id=installation_id)

        updated = PushDevice.objects.filter(user=request.user).filter(filters).update(
            is_active=False,
            disabled_reason='unregistered_by_user',
        )

        if not updated:
            raise NotFound('Dispositivo não encontrado.')

        return Response(status=status.HTTP_204_NO_CONTENT)
