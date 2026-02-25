from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import NotificationPreference, Profile

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
            'push_enabled',
            'updated_at',
        )
        read_only_fields = ('updated_at',)
