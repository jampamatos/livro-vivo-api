from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .storage import build_storage_policies, build_storage_settings, normalize_media_url, resolve_media_root


class StorageConfigTests(SimpleTestCase):
    def test_normalize_media_url_handles_relative_and_absolute_values(self):
        self.assertEqual(normalize_media_url('media'), '/media/')
        self.assertEqual(normalize_media_url('/media'), '/media/')
        self.assertEqual(normalize_media_url('https://cdn.example.com/media'), 'https://cdn.example.com/media/')

    def test_resolve_media_root_supports_relative_and_absolute_paths(self):
        base_dir = Path('/tmp/livro-vivo-api')
        self.assertEqual(resolve_media_root(base_dir=base_dir, raw_value='uploads'), base_dir / 'uploads')
        self.assertEqual(resolve_media_root(base_dir=base_dir, raw_value='/srv/media'), Path('/srv/media'))

    def test_filesystem_storage_settings_define_storage_aliases(self):
        settings_payload = build_storage_settings(
            provider='filesystem',
            staticfiles_backend='django.contrib.staticfiles.storage.StaticFilesStorage',
            media_public_cache_control='public, max-age=86400',
            media_private_cache_control='private, max-age=300, no-store',
        )
        self.assertEqual(settings_payload['avatars']['BACKEND'], 'config.storage.PublicMediaFileSystemStorage')
        self.assertEqual(settings_payload['template_uploads']['BACKEND'], 'config.storage.PrivateMediaFileSystemStorage')

    def test_s3_storage_requires_bucket_name(self):
        with self.assertRaises(ImproperlyConfigured):
            build_storage_settings(
                provider='s3',
                staticfiles_backend='django.contrib.staticfiles.storage.StaticFilesStorage',
                media_public_cache_control='public, max-age=86400',
                media_private_cache_control='private, max-age=300, no-store',
                s3_bucket_name='',
            )

    def test_storage_policies_reflect_provider(self):
        policies = build_storage_policies(
            provider='s3',
            media_public_cache_control='public, max-age=86400',
            media_private_cache_control='private, max-age=300, no-store',
        )
        self.assertEqual(policies['avatars']['backend'], 's3')
        self.assertEqual(policies['template_uploads']['delivery'], 'signed')
