from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle


class ClientTelemetryEventTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            'event_name': 'login_failed',
            'platform': 'android',
            'app_version': '1.0.0',
            'build_number': '42',
            'session_id': '9c4a296f-0ad2-41aa-a25a-f4c8d0e9e8fa',
            'user_id_hash': 'a' * 64,
            'route': 'LoginScreen',
            'severity': 'warning',
            'properties': {
                'provider': 'google',
                'reason': 'provider_auth_failed',
            },
            'occurred_at': '2026-04-30T12:00:00Z',
        }

    def test_client_event_accepts_anonymous_payload(self):
        with mock.patch('telemetry.views.record_domain_event') as record_metric:
            response = self.client.post(reverse('client-telemetry-events'), self.payload, format='json')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data, {'accepted': True})
        record_metric.assert_called_once_with(
            event='client_telemetry_event',
            result='login_failed',
            source='android',
        )

    @override_settings(CLIENT_TELEMETRY_ENABLED=False)
    def test_client_event_returns_404_when_disabled(self):
        response = self.client.post(reverse('client-telemetry-events'), self.payload, format='json')

        self.assertEqual(response.status_code, 404)

    @override_settings(CLIENT_TELEMETRY_SHARED_SECRET='shared-test-secret')
    def test_client_event_requires_shared_secret_when_configured(self):
        response = self.client.post(reverse('client-telemetry-events'), self.payload, format='json')

        self.assertEqual(response.status_code, 403)

    @override_settings(CLIENT_TELEMETRY_SHARED_SECRET='shared-test-secret')
    def test_client_event_accepts_configured_shared_secret(self):
        response = self.client.post(
            reverse('client-telemetry-events'),
            self.payload,
            format='json',
            HTTP_X_CLIENT_TELEMETRY_SECRET='shared-test-secret',
        )

        self.assertEqual(response.status_code, 202)

    def test_client_event_rejects_unknown_event(self):
        payload = {**self.payload, 'event_name': 'email_entered'}

        response = self.client.post(reverse('client-telemetry-events'), payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('event_name', response.data)

    def test_client_event_rejects_raw_user_id(self):
        payload = {**self.payload, 'user_id_hash': '123'}

        response = self.client.post(reverse('client-telemetry-events'), payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('user_id_hash', response.data)

    def test_client_event_rejects_unknown_property(self):
        payload = {**self.payload, 'properties': {'email': 'user@example.com'}}

        response = self.client.post(reverse('client-telemetry-events'), payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('properties', response.data)

    def test_client_event_rejects_pii_like_property_value(self):
        payload = {**self.payload, 'properties': {'reason': 'user@example.com'}}

        response = self.client.post(reverse('client-telemetry-events'), payload, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('properties', response.data)

    @override_settings(CLIENT_TELEMETRY_MAX_BYTES=128)
    def test_client_event_rejects_payload_above_limit(self):
        payload = {**self.payload, 'route': 'LoginScreen' * 20}

        response = self.client.post(reverse('client-telemetry-events'), payload, format='json')

        self.assertEqual(response.status_code, 413)

    def test_client_event_is_throttled(self):
        cache.clear()

        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'client_telemetry': '1/min'}):
            first = self.client.post(reverse('client-telemetry-events'), self.payload, format='json')
            second = self.client.post(reverse('client-telemetry-events'), self.payload, format='json')

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 429)
