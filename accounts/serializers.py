from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import NotificationDispatch, NotificationPreference, Profile, PushDevice

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    """Valida dados de cadastro e cria usuário+perfil."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(required=False, allow_blank=True)
    profession = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Email já cadastrado.")
        return email

    def validate(self, attrs):
        attrs = super().validate(attrs)
        email = (attrs.get('email') or '').strip().lower()
        password = attrs.get('password') or ''
        candidate_user = User(username=email, email=email)
        try:
            validate_password(password, candidate_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        email = validated_data['email']
        password = validated_data['password']
        name = validated_data.get('name', '').strip()
        profession = validated_data.get('profession', '').strip()

        # Mantém simples: username = email
        user = User.objects.create_user(username=email, email=email, password=password)

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.full_name = name
        profile.profession = profession
        profile.save()

        return user


class LoginSerializer(serializers.Serializer):
    """Valida login por email e senha."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class MeSerializer(serializers.Serializer):
    """Serializer de leitura para o endpoint /me/."""

    id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField(allow_blank=True)
    profession = serializers.CharField(allow_blank=True)
    role = serializers.CharField(allow_blank=True, allow_null=True, required=False)


class EntitlementSerializer(serializers.Serializer):
    """Serializer de entitlements do usuário."""

    id = serializers.IntegerField()
    product = serializers.CharField()
    book_id = serializers.IntegerField(allow_null=True)
    subscription_id = serializers.IntegerField(allow_null=True)
    tier = serializers.CharField(allow_null=True)
    is_founder = serializers.BooleanField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()
    source = serializers.CharField()


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = (
            'notifications_enabled',
            'book_version_updates_enabled',
            'new_content_updates_enabled',
            'community_interaction_updates_enabled',
            'push_enabled',
            'updated_at',
        )
        read_only_fields = ('updated_at',)


class NotificationDispatchSerializer(serializers.ModelSerializer):
    dispatch_id = serializers.IntegerField(source='id', read_only=True)
    event_type = serializers.CharField(source='event.event_type', read_only=True)
    title = serializers.CharField(source='event.title', read_only=True)
    body = serializers.CharField(source='event.body', read_only=True)
    payload = serializers.JSONField(source='event.payload', read_only=True)
    event_created_at = serializers.DateTimeField(source='event.created_at', read_only=True)

    class Meta:
        model = NotificationDispatch
        fields = (
            'dispatch_id',
            'event_type',
            'title',
            'body',
            'payload',
            'channel',
            'status',
            'reason',
            'created_at',
            'event_created_at',
            'dispatched_at',
            'acknowledged_at',
        )


class PushDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushDevice
        fields = (
            'id',
            'platform',
            'expo_push_token',
            'is_active',
            'disabled_reason',
            'last_seen_at',
            'updated_at',
        )
        read_only_fields = ('id', 'is_active', 'disabled_reason', 'last_seen_at', 'updated_at')


class PushDeviceRegisterSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=PushDevice.Platform.choices)
    expo_push_token = serializers.CharField(max_length=255)

    def validate_expo_push_token(self, value: str) -> str:
        token = value.strip()
        if not token:
            raise serializers.ValidationError("expo_push_token é obrigatório.")
        if not (token.startswith('ExponentPushToken[') or token.startswith('ExpoPushToken[')):
            raise serializers.ValidationError("expo_push_token inválido.")
        return token


class PushDeviceUnregisterSerializer(serializers.Serializer):
    expo_push_token = serializers.CharField(max_length=255)

    def validate_expo_push_token(self, value: str) -> str:
        token = value.strip()
        if not token:
            raise serializers.ValidationError("expo_push_token é obrigatório.")
        return token
