from django.contrib.auth import get_user_model
from rest_framework import serializers

from entitlements.models import Entitlement

from .models import Profile

User = get_user_model()

class RegisterSerializer(serializers.Serializer):
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
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField(allow_blank=True)
    profession = serializers.CharField(allow_blank=True)

class EntitlementSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product = serializers.CharField()
    status = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()
    source = serializers.CharField()