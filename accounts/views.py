from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView

from entitlements.models import Entitlement
from entitlements.services import get_effective_tier, get_subscription_snapshot

from .models import NotificationDispatch, NotificationPreference, Profile, PushDevice
from .serializers import (
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


def issue_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def _serialize_user_payload(user, profile: Profile):
    return {
        'id': user.id,
        'email': user.email,
        'name': profile.full_name,
        'profession': profile.profession,
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

        return Response(
            {
                **tokens,
                'user': _serialize_user_payload(user, profile),
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
            return Response({"detail": "email e password são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)

        candidate_user = User.objects.filter(email__iexact=email).first()
        if candidate_user:
            sync_user_activity_with_moderation(candidate_user)
            candidate_user.refresh_from_db(fields=['is_active'])
            message = get_banned_login_message(candidate_user)
            if message:
                return Response(
                    {"detail": message, "code": "account_banned"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        if candidate_user and not candidate_user.is_active:
            return Response(
                {"detail": "Esta conta está inativa."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Djano autentica por username; aqui a gente trata email como username (padrão simples)
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
            return Response({"detail": "Credenciais inválidas."}, status=status.HTTP_401_UNAUTHORIZED)

        tokens = issue_tokens_for_user(user)
        from community.services import pull_pending_login_notice

        moderation_notice = pull_pending_login_notice(user)
        payload = {**tokens}
        if moderation_notice:
            payload['moderation_notice'] = moderation_notice

        return Response(payload, status=status.HTTP_200_OK)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response({"detail": "Token de refresh é obrigatório."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            # não vaza detalhe: se já expirou ou é inválido, tratamos como logout idempotente
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Retorna dados básicos do usuário autenticado."""

    def get(self, request):
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(_serialize_user_payload(user, profile))


class MeDataExportView(APIView):
    """Exporta os dados do usuário autenticado em um pacote JSON."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        export_payload = create_user_data_export_package(user=request.user)
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

        device, _ = PushDevice.objects.update_or_create(
            expo_push_token=serializer.validated_data['expo_push_token'],
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
