from __future__ import annotations

import math
import re

from django.utils import timezone
from rest_framework import serializers


CLIENT_TELEMETRY_EVENT_NAMES = (
    'app_open',
    'app_foreground',
    'app_background',
    'screen_view',
    'api_error',
    'api_slow_request',
    'unhandled_error',
    'login_attempt',
    'login_success',
    'login_failed',
    'social_login_start',
    'social_login_callback_received',
    'social_login_success',
    'social_login_failed',
    'legal_gate_shown',
    'legal_acceptance_success',
    'book_open',
    'chapter_open',
    'search_global',
    'template_download_start',
    'template_download_success',
    'template_download_failed',
)
CLIENT_TELEMETRY_PLATFORMS = ('android',)
CLIENT_TELEMETRY_SEVERITIES = ('info', 'warning', 'error', 'critical')
CLIENT_TELEMETRY_ALLOWED_PROPERTIES = frozenset(
    {
        'api_endpoint',
        'api_method',
        'build_type',
        'chapter_id_hash',
        'duration_ms',
        'error_code',
        'error_type',
        'file_source',
        'flow',
        'http_status',
        'network_type',
        'previous_route',
        'provider',
        'reason',
        'retry_count',
        'screen',
        'source',
        'template_code',
    }
)
MAX_PROPERTIES = 20
MAX_PROPERTY_STRING_LENGTH = 160

EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
USER_ID_HASH_PATTERN = re.compile(r'^[a-f0-9]{64}$')


class ClientTelemetryEventSerializer(serializers.Serializer):
    event_name = serializers.ChoiceField(choices=CLIENT_TELEMETRY_EVENT_NAMES)
    platform = serializers.ChoiceField(choices=CLIENT_TELEMETRY_PLATFORMS)
    app_version = serializers.CharField(required=False, allow_blank=True, max_length=64, default='')
    build_number = serializers.CharField(required=False, allow_blank=True, max_length=32, default='')
    session_id = serializers.UUIDField()
    user_id_hash = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64, default='')
    route = serializers.CharField(max_length=128)
    severity = serializers.ChoiceField(choices=CLIENT_TELEMETRY_SEVERITIES, default='info')
    properties = serializers.DictField(required=False, default=dict)
    occurred_at = serializers.DateTimeField(required=False)

    def validate_user_id_hash(self, value: str | None) -> str:
        if value in (None, ''):
            return ''
        normalized = str(value).strip().lower()
        if not USER_ID_HASH_PATTERN.fullmatch(normalized):
            raise serializers.ValidationError('user_id_hash deve ser um SHA-256 hexadecimal ou vazio.')
        return normalized

    def validate_route(self, value: str) -> str:
        route = value.strip()
        if not route:
            raise serializers.ValidationError('route nao pode ficar vazio.')
        if EMAIL_PATTERN.search(route):
            raise serializers.ValidationError('route nao deve conter dados pessoais.')
        return route

    def validate_properties(self, value: dict) -> dict:
        if len(value) > MAX_PROPERTIES:
            raise serializers.ValidationError(f'properties aceita no maximo {MAX_PROPERTIES} chaves.')

        sanitized = {}
        for key, raw_value in value.items():
            normalized_key = str(key).strip()
            if normalized_key not in CLIENT_TELEMETRY_ALLOWED_PROPERTIES:
                raise serializers.ValidationError(f"Propriedade '{normalized_key}' nao permitida.")
            sanitized[normalized_key] = self._validate_property_value(normalized_key, raw_value)
        return sanitized

    def validate(self, attrs: dict) -> dict:
        attrs.setdefault('occurred_at', timezone.now())
        return attrs

    def _validate_property_value(self, key: str, value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise serializers.ValidationError(f"Propriedade '{key}' deve ser um numero finito.")
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if len(normalized) > MAX_PROPERTY_STRING_LENGTH:
                raise serializers.ValidationError(
                    f"Propriedade '{key}' excede {MAX_PROPERTY_STRING_LENGTH} caracteres."
                )
            if EMAIL_PATTERN.search(normalized):
                raise serializers.ValidationError(f"Propriedade '{key}' nao deve conter dados pessoais.")
            return normalized
        raise serializers.ValidationError(f"Propriedade '{key}' deve ser texto, numero, booleano ou null.")
