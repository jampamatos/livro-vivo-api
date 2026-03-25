import logging

from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView

from entitlements.models import Entitlement
from entitlements.services import get_effective_tier, get_subscription_snapshot
from config.storage import build_media_reference

from .models import NotificationDispatch, NotificationPreference, Profile, PushDevice
from .serializers import (
    MePasswordChangeSerializer,
    MeUpdateSerializer,
    NotificationDispatchSerializer,
    NotificationPreferenceSerializer,
    PushDeviceRegisterSerializer,
    PushDeviceSerializer,
    PushDeviceUnregisterSerializer,
    RegisterSerializer,
)
from .services import create_user_data_export_package, request_user_data_erasure
from .roles import get_user_role
from community.services import (
    get_banned_login_message,
    get_user_moderation_summary,
    sync_user_activity_with_moderation,
)

User = get_user_model()
logger = logging.getLogger("livro_vivo.api")


def issue_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def _resolve_profile_avatar_reference(profile: Profile, request=None):
    return build_media_reference(
        upload_field=getattr(profile, 'avatar', None),
        remote_url=getattr(profile, 'avatar_url', ''),
        request=request,
        storage_alias='avatars',
    )


def _delete_stored_file(storage, name: str):
    if not storage or not name:
        return
    try:
        storage.delete(name)
    except Exception:  # pragma: no cover
        return


def _serialize_user_payload(user, profile: Profile, request=None):
    avatar_reference = _resolve_profile_avatar_reference(profile, request=request)
    return {
        'id': user.id,
        'email': user.email,
        'name': profile.full_name,
        'profession': profile.profession,
        'avatar_url': avatar_reference['url'],
        'avatar_source': avatar_reference['source'],
        'avatar_storage_alias': avatar_reference['storage_alias'],
        'avatar_storage_backend': avatar_reference['storage_backend'],
        'avatar_storage_key': avatar_reference['storage_key'],
        'avatar_cache_control': avatar_reference['cache_control'],
        'role': get_user_role(user),
    }


class RegisterView(APIView):
    """Cadastro de usuário com criação de sessão JWT e perfil."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        tokens = issue_tokens_for_user(user)
        logger.info("auth_register_success", extra={"user_id": user.id})

        return Response(
            {
                **tokens,
                'user': _serialize_user_payload(user, profile, request=request),
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
            return Response({"detail": "email e password são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)

        # Django autentica por username; aqui tratamos email como username.
        user = authenticate(request, username=email, password=password)

        if not user:
            # fallback: tenta achar email e autentica com username real, se existir
            try:
                u = User.objects.get(email=email)
            except User.DoesNotExist:
                u = None
            if u:
                user = authenticate(request, username=u.username, password=password)

        if not user:
            candidate_user = User.objects.filter(email__iexact=email).first()
            if candidate_user and candidate_user.check_password(password):
                user = candidate_user

        if not user:
            logger.warning("auth_login_failed", extra={"reason": "invalid_credentials"})
            return Response({"detail": "Credenciais inválidas."}, status=status.HTTP_401_UNAUTHORIZED)

        sync_user_activity_with_moderation(user)
        user.refresh_from_db(fields=['is_active'])
        message = get_banned_login_message(user)
        if message:
            logger.warning("auth_login_blocked", extra={"reason": "account_banned", "user_id": user.id})
            return Response(
                {"detail": message, "code": "account_banned"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user.is_active:
            logger.warning("auth_login_blocked", extra={"reason": "inactive_account", "user_id": user.id})
            return Response(
                {"detail": "Esta conta está inativa."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = issue_tokens_for_user(user)
        from community.services import pull_pending_login_notice

        moderation_notice = pull_pending_login_notice(user)
        payload = {**tokens}
        if moderation_notice:
            payload['moderation_notice'] = moderation_notice
        logger.info(
            "auth_login_success",
            extra={"user_id": user.id, "has_moderation_notice": bool(moderation_notice)},
        )

        return Response(payload, status=status.HTTP_200_OK)

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

    def get(self, request):
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(_serialize_user_payload(user, profile, request=request))

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
                _delete_stored_file(previous_avatar_storage, previous_avatar_name)
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

        return Response(_serialize_user_payload(user, profile, request=request), status=status.HTTP_200_OK)


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

    permission_classes = [IsAuthenticated]
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

    permission_classes = [IsAuthenticated]
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

    permission_classes = [IsAuthenticated]
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

    permission_classes = [IsAuthenticated]
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
        existing_device = PushDevice.objects.filter(expo_push_token=token).first()
        if existing_device and existing_device.user_id != request.user.id:
            raise ValidationError(
                {'expo_push_token': 'Este dispositivo já está vinculado a outra conta.'}
            )

        device, _ = PushDevice.objects.update_or_create(
            expo_push_token=token,
            defaults={
                'user': request.user,
                'platform': serializer.validated_data['platform'],
                'is_active': True,
                'disabled_reason': '',
            },
        )

        response_serializer = PushDeviceSerializer(device)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request):
        serializer = PushDeviceUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = PushDevice.objects.filter(
            user=request.user,
            expo_push_token=serializer.validated_data['expo_push_token'],
        ).update(is_active=False, disabled_reason='unregistered_by_user')

        if not updated:
            raise NotFound('Dispositivo não encontrado.')

        return Response(status=status.HTTP_204_NO_CONTENT)
