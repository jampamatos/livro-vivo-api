from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, storages


DEFAULT_MEDIA_PUBLIC_CACHE_CONTROL = 'public, max-age=86400, stale-while-revalidate=604800'
DEFAULT_MEDIA_PRIVATE_CACHE_CONTROL = 'private, max-age=300, no-store'


class PublicMediaFileSystemStorage(FileSystemStorage):
    @property
    def location(self) -> str:
        return str(Path(settings.MEDIA_ROOT))

    @property
    def base_url(self) -> str:
        return normalize_media_url(getattr(settings, 'MEDIA_URL', '/media/'))


class PrivateMediaFileSystemStorage(FileSystemStorage):
    @property
    def location(self) -> str:
        return str(Path(settings.MEDIA_ROOT))

    @property
    def base_url(self) -> str:
        return normalize_media_url(getattr(settings, 'MEDIA_URL', '/media/'))


def normalize_media_url(value: str | None) -> str:
    raw = (value or '/media/').strip()
    if not raw:
        return '/media/'

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return raw.rstrip('/') + '/'

    return '/' + raw.strip('/') + '/'


def resolve_media_root(*, base_dir: Path, raw_value: str | None) -> Path:
    if not raw_value:
        return base_dir / 'media'

    path = Path(raw_value)
    if path.is_absolute():
        return path
    return base_dir / path


def build_storage_settings(
    *,
    provider: str,
    staticfiles_backend: str,
    media_public_cache_control: str,
    media_private_cache_control: str,
    s3_bucket_name: str = '',
    s3_endpoint_url: str = '',
    s3_region_name: str = '',
    s3_access_key_id: str = '',
    s3_secret_access_key: str = '',
    s3_custom_domain: str = '',
    s3_querystring_expire: int = 300,
) -> dict[str, dict[str, object]]:
    normalized_provider = (provider or 'filesystem').strip().lower()
    storage_settings: dict[str, dict[str, object]] = {
        'staticfiles': {'BACKEND': staticfiles_backend},
    }

    if normalized_provider == 'filesystem':
        storage_settings['default'] = {'BACKEND': 'config.storage.PublicMediaFileSystemStorage'}
        storage_settings['avatars'] = {'BACKEND': 'config.storage.PublicMediaFileSystemStorage'}
        storage_settings['template_uploads'] = {'BACKEND': 'config.storage.PrivateMediaFileSystemStorage'}
        return storage_settings

    if normalized_provider != 's3':
        raise ImproperlyConfigured(
            "DJANGO_STORAGE_PROVIDER must be either 'filesystem' or 's3'."
        )

    if not s3_bucket_name:
        raise ImproperlyConfigured(
            'DJANGO_STORAGE_S3_BUCKET_NAME is required when DJANGO_STORAGE_PROVIDER=s3.'
        )

    common_options: dict[str, object] = {
        'bucket_name': s3_bucket_name,
        'default_acl': None,
        'file_overwrite': False,
        'querystring_expire': max(int(s3_querystring_expire), 1),
    }

    if s3_endpoint_url:
        common_options['endpoint_url'] = s3_endpoint_url
    if s3_region_name:
        common_options['region_name'] = s3_region_name
    if s3_access_key_id:
        common_options['access_key'] = s3_access_key_id
    if s3_secret_access_key:
        common_options['secret_key'] = s3_secret_access_key

    public_options = {
        **common_options,
        'querystring_auth': False,
        'object_parameters': {'CacheControl': media_public_cache_control},
    }
    if s3_custom_domain:
        public_options['custom_domain'] = s3_custom_domain

    private_options = {
        **common_options,
        'querystring_auth': True,
        'object_parameters': {'CacheControl': media_private_cache_control},
    }

    storage_settings['default'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': public_options,
    }
    storage_settings['avatars'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': public_options,
    }
    storage_settings['template_uploads'] = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': private_options,
    }
    return storage_settings


def build_storage_policies(
    *,
    provider: str,
    media_public_cache_control: str,
    media_private_cache_control: str,
) -> dict[str, dict[str, str]]:
    normalized_provider = (provider or 'filesystem').strip().lower()
    return {
        'avatars': {
            'backend': normalized_provider,
            'cache_control': media_public_cache_control,
            'delivery': 'public',
        },
        'template_uploads': {
            'backend': normalized_provider,
            'cache_control': media_private_cache_control,
            'delivery': 'signed' if normalized_provider == 's3' else 'filesystem',
        },
    }


def get_avatar_storage():
    return storages['avatars']


def get_template_uploads_storage():
    return storages['template_uploads']


def _is_absolute_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _absolute_url(value: str, *, request=None) -> str:
    if not value:
        return ''
    if _is_absolute_url(value) or request is None:
        return value
    return request.build_absolute_uri(value)


def build_media_reference(
    *,
    upload_field=None,
    remote_url: str | None = '',
    request=None,
    storage_alias: str | None = None,
    include_internal_metadata: bool = False,
) -> dict[str, str | None]:
    policies = getattr(settings, 'MEDIA_STORAGE_POLICIES', {}) or {}
    alias_policy = policies.get(storage_alias or '', {})

    if upload_field is not None and getattr(upload_field, 'name', ''):
        resolved_url = ''
        try:
            resolved_url = upload_field.url
        except Exception:
            resolved_url = ''

        reference = {
            'url': _absolute_url(resolved_url, request=request) or None,
            'source': 'upload',
        }
        if include_internal_metadata:
            reference.update(
                {
                    'storage_key': str(upload_field.name),
                    'storage_alias': storage_alias,
                    'storage_backend': alias_policy.get('backend')
                    or getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'filesystem'),
                    'cache_control': alias_policy.get('cache_control', ''),
                }
            )
        return reference

    normalized_remote_url = (remote_url or '').strip()
    if normalized_remote_url:
        reference = {
            'url': _absolute_url(normalized_remote_url, request=request),
            'source': 'remote_url',
        }
        if include_internal_metadata:
            reference.update(
                {
                    'storage_key': None,
                    'storage_alias': None,
                    'storage_backend': 'external_url',
                    'cache_control': '',
                }
            )
        return reference

    reference = {
        'url': None,
        'source': 'none',
    }
    if include_internal_metadata:
        reference.update(
            {
                'storage_key': None,
                'storage_alias': storage_alias,
                'storage_backend': alias_policy.get('backend')
                or getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'filesystem'),
                'cache_control': alias_policy.get('cache_control', ''),
            }
        )
    return reference
