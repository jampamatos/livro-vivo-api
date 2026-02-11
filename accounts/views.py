from django.contrib.auth import authenticate, get_user_model

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.views import APIView

from entitlements.models import Entitlement

from .models import Profile
from .serializers import LoginSerializer, RegisterSerializer

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
                'user': _serialize_user_payload(user, profile),
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """Login por email e senha com retorno de token."""

    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        password = request.data.get('password') or ''

        if not email or not password:
            return Response({"detail": "email e password são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Djano autentica por username; aqui a gente trata email como username (padrão simples)
        user = authenticate(request, username=email, password=password)

        if not user:
            # fallback: tenta achar email e autentica com username real, se existir
            User = get_user_model()
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
    
    class RegisterView(APIView):
        permission_classes = [AllowAny]

        def post(self, request):
            email = (request.data.get('email') or '').strip().lower()
            password = request.data.get('password') or ''

            if not email or not password:
                return Response({"detail": "email e password são obrigatórios."}, status=status.HTTP_400_BAD_REQUEST)
            
            User = get_user_model()

            # padrão ismples: username = email
            if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
                return Response({"detail": "Usuário com este email já existe."}, status=status.HTTP_400_BAD_REQUEST)
            
            user = User.objects.create_user(username=email, email=email, password=password)

            tokens = issue_tokens_for_user(user)
            return Response(tokens, status=status.HTTP_201_CREATED)
    
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request):
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
