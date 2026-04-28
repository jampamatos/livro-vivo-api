import io
from pathlib import Path
from urllib.parse import urlparse
import warnings

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.text import slugify
from rest_framework import serializers
from PIL import Image, UnidentifiedImageError

from .models import (
    NotificationDispatch,
    NotificationPreference,
    Profile,
    PushDevice,
    UserLegalAcceptance,
)

User = get_user_model()

ALLOWED_AVATAR_FORMATS = {
    'JPEG': ('image/jpeg', 'jpg'),
    'PNG': ('image/png', 'png'),
    'WEBP': ('image/webp', 'webp'),
}
INSECURE_AVATAR_HOST_ALLOWLIST = {'localhost', '127.0.0.1', '::1', 'testserver'}


def _avatar_max_upload_bytes() -> int:
    return int(getattr(settings, 'AVATAR_MAX_UPLOAD_BYTES', 5 * 1024 * 1024))


def _avatar_max_dimension() -> int:
    return int(getattr(settings, 'AVATAR_MAX_DIMENSION', 1024))


def _avatar_allowed_mime_types() -> set[str]:
    configured = getattr(settings, 'AVATAR_ALLOWED_MIME_TYPES', tuple(item[0] for item in ALLOWED_AVATAR_FORMATS.values()))
    return {str(item).strip().lower() for item in configured if str(item).strip()}


def _avatar_max_source_pixels() -> int:
    max_dimension = max(_avatar_max_dimension(), 1)
    return max(max_dimension * max_dimension * 16, 16_000_000)


def _format_avatar_max_size(bytes_value: int) -> str:
    megabytes = bytes_value / (1024 * 1024)
    return f"{megabytes:.0f} MB" if megabytes.is_integer() else f"{megabytes:.1f} MB"


def _normalize_avatar_upload(uploaded_file, crop: dict[str, int] | None = None):
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as image:
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise serializers.ValidationError("Avatar deve ser uma imagem válida em JPG, PNG ou WEBP.")
                if width * height > _avatar_max_source_pixels():
                    raise serializers.ValidationError("Avatar possui dimensões maiores que o permitido.")

                image.load()
                source_format = (image.format or '').upper()
                if source_format not in ALLOWED_AVATAR_FORMATS:
                    raise serializers.ValidationError("Avatar deve ser uma imagem JPG, PNG ou WEBP.")

                normalized = image.copy()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError("Avatar deve ser uma imagem válida em JPG, PNG ou WEBP.")

    if crop:
        crop_x = int(crop['x'])
        crop_y = int(crop['y'])
        crop_size = int(crop['size'])
        width, height = normalized.size
        if crop_x < 0 or crop_y < 0 or crop_size <= 0 or crop_x + crop_size > width or crop_y + crop_size > height:
            raise serializers.ValidationError("Recorte do avatar inválido.")
        normalized = normalized.crop((crop_x, crop_y, crop_x + crop_size, crop_y + crop_size))

    max_dimension = _avatar_max_dimension()
    if max(normalized.size) > max_dimension:
        normalized.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    if source_format == 'JPEG':
        if normalized.mode not in {'RGB', 'L'}:
            normalized = normalized.convert('RGB')
    elif source_format == 'PNG':
        if normalized.mode not in {'RGB', 'RGBA', 'L', 'LA'}:
            normalized = normalized.convert('RGBA' if 'A' in normalized.getbands() else 'RGB')
    elif source_format == 'WEBP':
        if normalized.mode not in {'RGB', 'RGBA'}:
            normalized = normalized.convert('RGBA' if 'A' in normalized.getbands() else 'RGB')

    output = io.BytesIO()
    save_kwargs = {'optimize': True}
    if source_format == 'JPEG':
        save_kwargs.update({'quality': 85, 'progressive': True})
    elif source_format == 'WEBP':
        save_kwargs.update({'quality': 85, 'method': 6})

    normalized.save(output, format=source_format, **save_kwargs)
    content = output.getvalue()
    content_type, extension = ALLOWED_AVATAR_FORMATS[source_format]
    base_name = slugify(Path(getattr(uploaded_file, 'name', '') or '').stem)[:48] or 'avatar'
    return SimpleUploadedFile(
        f"{base_name}.{extension}",
        content,
        content_type=content_type,
    )


class RegisterSerializer(serializers.Serializer):
    """Valida dados de cadastro e cria usuário+perfil."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    name = serializers.CharField(required=False, allow_blank=True)
    profession = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

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


class MeUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    profession = serializers.CharField(required=False, allow_blank=True, max_length=120)
    avatar_url = serializers.URLField(required=False, allow_blank=True, allow_null=True, max_length=500)
    avatar = serializers.ImageField(required=False, allow_null=True)
    avatar_clear = serializers.BooleanField(required=False, default=False)
    avatar_crop_x = serializers.IntegerField(required=False, min_value=0)
    avatar_crop_y = serializers.IntegerField(required=False, min_value=0)
    avatar_crop_size = serializers.IntegerField(required=False, min_value=1)

    def validate_name(self, value: str) -> str:
        return value.strip()

    def validate_profession(self, value: str) -> str:
        return value.strip()

    def validate_avatar_url(self, value: str | None) -> str:
        if value is None:
            return ''
        normalized = value.strip()
        if not normalized:
            return ''

        parsed = urlparse(normalized)
        scheme = (parsed.scheme or '').lower()
        host = (parsed.hostname or '').strip().lower()
        if scheme not in {'http', 'https'}:
            raise serializers.ValidationError("avatar_url deve usar HTTPS ou um host HTTP local permitido.")
        if scheme == 'http' and host not in INSECURE_AVATAR_HOST_ALLOWLIST:
            raise serializers.ValidationError("avatar_url deve usar HTTPS fora de ambiente local.")
        return normalized

    def validate_avatar(self, value):
        max_bytes = _avatar_max_upload_bytes()
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"Avatar deve ter no máximo {_format_avatar_max_size(max_bytes)}."
            )

        content_type = (getattr(value, 'content_type', '') or '').strip().lower()
        allowed_mime_types = _avatar_allowed_mime_types()
        if content_type and content_type not in allowed_mime_types:
            raise serializers.ValidationError("Avatar deve ser uma imagem JPG, PNG ou WEBP.")

        crop = self.initial_data
        has_crop = any(crop.get(key) not in (None, "") for key in ('avatar_crop_x', 'avatar_crop_y', 'avatar_crop_size'))
        crop_payload = None
        if has_crop:
            crop_x = self.initial_data.get('avatar_crop_x')
            crop_y = self.initial_data.get('avatar_crop_y')
            crop_size = self.initial_data.get('avatar_crop_size')
            if crop_x in (None, "") or crop_y in (None, "") or crop_size in (None, ""):
                raise serializers.ValidationError("Recorte do avatar incompleto.")
            try:
                crop_payload = {
                    'x': int(crop_x),
                    'y': int(crop_y),
                    'size': int(crop_size),
                }
            except (TypeError, ValueError):
                raise serializers.ValidationError("Recorte do avatar inválido.")

        normalized = _normalize_avatar_upload(value, crop=crop_payload)
        if normalized.size > max_bytes:
            raise serializers.ValidationError(
                f"Avatar deve ter no máximo {_format_avatar_max_size(max_bytes)}."
            )
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        has_avatar_upload = attrs.get('avatar') is not None
        has_avatar_url = bool(attrs.get('avatar_url'))
        has_avatar_clear = bool(attrs.get('avatar_clear'))
        has_any_crop_field = any(
            attrs.get(field) is not None for field in ('avatar_crop_x', 'avatar_crop_y', 'avatar_crop_size')
        )

        if sum([has_avatar_upload, has_avatar_url, has_avatar_clear]) > 1:
            raise serializers.ValidationError(
                "Envie apenas uma operação de avatar por vez: upload, avatar_url ou avatar_clear."
            )

        if has_any_crop_field and not has_avatar_upload:
            raise serializers.ValidationError("Recorte de avatar só pode ser enviado junto com um upload.")

        return attrs


class MePasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, min_length=8, trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        user = self.context['user']
        if not user.check_password(value):
            raise serializers.ValidationError('Senha atual incorreta.')
        return value

    def validate_new_password(self, value: str) -> str:
        user = self.context['user']
        try:
            validate_password(value, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs['current_password'] == attrs['new_password']:
            raise serializers.ValidationError({'new_password': ['A nova senha deve ser diferente da senha atual.']})
        return attrs


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
            'installation_id',
            'expo_push_token',
            'is_active',
            'disabled_reason',
            'last_seen_at',
            'updated_at',
        )
        read_only_fields = ('id', 'is_active', 'disabled_reason', 'last_seen_at', 'updated_at')


class PushDeviceRegisterSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=PushDevice.Platform.choices)
    installation_id = serializers.CharField(max_length=64)
    expo_push_token = serializers.CharField(max_length=255)

    def validate_installation_id(self, value: str) -> str:
        installation_id = value.strip()
        if not installation_id:
            raise serializers.ValidationError("installation_id é obrigatório.")
        return installation_id

    def validate_expo_push_token(self, value: str) -> str:
        token = value.strip()
        if not token:
            raise serializers.ValidationError("expo_push_token é obrigatório.")
        if not (token.startswith('ExponentPushToken[') or token.startswith('ExpoPushToken[')):
            raise serializers.ValidationError("expo_push_token inválido.")
        return token


class PushDeviceUnregisterSerializer(serializers.Serializer):
    installation_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    expo_push_token = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_installation_id(self, value: str) -> str:
        return value.strip()

    def validate_expo_push_token(self, value: str) -> str:
        return value.strip()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get('expo_push_token') or attrs.get('installation_id'):
            return attrs
        raise serializers.ValidationError("expo_push_token ou installation_id é obrigatório.")


class LegalAcceptanceSubmitSerializer(serializers.Serializer):
    document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    source = serializers.ChoiceField(
        choices=UserLegalAcceptance.Source.choices,
        default=UserLegalAcceptance.Source.LOGIN_GATE,
    )
    app_platform = serializers.ChoiceField(
        choices=UserLegalAcceptance.AppPlatform.choices,
        default=UserLegalAcceptance.AppPlatform.WEB,
    )
    app_version = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_document_ids(self, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError('document_ids contém valores duplicados.')
        return value
