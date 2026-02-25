from django.contrib.auth import authenticate, get_user_model

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView

from entitlements.models import Entitlement
from entitlements.services import get_effective_tier, get_subscription_snapshot

from .models import NotificationPreference, Profile
from .serializers import NotificationPreferenceSerializer, RegisterSerializer

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
        return Response(tokens, status=status.HTTP_200_OK)

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
            }
        )


class MeNotificationPreferencesView(APIView):
    """Leitura/atualização das preferências de notificação do usuário."""

    permission_classes = [IsAuthenticated]

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
