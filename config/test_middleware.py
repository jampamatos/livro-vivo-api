from django.test import SimpleTestCase

from .middleware import _normalize_request_id, _sanitize_request_path


class MiddlewareHelpersTests(SimpleTestCase):
    def test_sanitize_request_path_redacts_sensitive_query_params(self):
        sanitized = _sanitize_request_path(
            '/templates-bank/templates/1/download/?token=secret-token&foo=bar&X-Amz-Signature=abc123'
        )

        self.assertEqual(
            sanitized,
            '/templates-bank/templates/1/download/?token=redacted&foo=bar&X-Amz-Signature=redacted',
        )

    def test_normalize_request_id_preserves_safe_value(self):
        self.assertEqual(_normalize_request_id('test-request-id-123'), 'test-request-id-123')

    def test_normalize_request_id_replaces_invalid_value(self):
        normalized = _normalize_request_id('request id with spaces')

        self.assertRegex(normalized, r'^[a-f0-9]{32}$')
