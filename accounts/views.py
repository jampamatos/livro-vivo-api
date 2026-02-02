from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from entitlements.models import Entitlement

from .models import Profile
from .serializers import LoginSerializer, RegisterSerializer

User = get_user_model()


class RegisterView(APIView):
    """Cadastro de usuário com criação de token e perfil."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)

        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(
            {
                'token': token.key,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'name': profile.full_name,
                    'profession': profile.profession,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """Login por email e senha com retorno de token."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email'].strip().lower()
        password = serializer.validated_data['password']

        # Autenticação manual para manter o fluxo simples do MVP.
        user = User.objects.filter(email__iexact=email).first()
        if not user or not user.check_password(password):
            raise AuthenticationFailed("Credenciais inválidas.")

        token, _ = Token.objects.get_or_create(user=user)
        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(
            {
                'token': token.key,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'name': profile.full_name,
                    'profession': profile.profession,
                },
            }
        )


class MeView(APIView):
    """Retorna dados básicos do usuário autenticado."""

    def get(self, request):
        user = request.user
        profile, _ = Profile.objects.get_or_create(user=user)

        return Response(
            {
                'id': user.id,
                'email': user.email,
                'name': profile.full_name,
                'profession': profile.profession,
            }
        )


class MeEntitlementsView(APIView):
    """Lista entitlements do usuário."""

    def get(self, request):
        qs = Entitlement.objects.filter(user=request.user).order_by('-created_at')

        data = [
            {
                'id': e.id,
                'product': e.product,
                'status': e.status,
                'expires_at': e.expires_at,
                'is_active': e.is_active(),
                'source': e.source,
            }
            for e in qs
        ]

        return Response({"entitlements": data})
