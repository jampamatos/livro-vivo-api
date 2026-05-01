from __future__ import annotations

import logging

from django.conf import settings
from django.http import Http404
from django.utils.crypto import constant_time_compare
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from config.metrics import record_domain_event

from .serializers import ClientTelemetryEventSerializer


logger = logging.getLogger("livro_vivo.api")


class ClientTelemetryEventView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'client_telemetry'

    def post(self, request):
        if not settings.CLIENT_TELEMETRY_ENABLED:
            raise Http404()

        shared_secret = settings.CLIENT_TELEMETRY_SHARED_SECRET
        if shared_secret:
            provided_secret = (request.headers.get('X-Client-Telemetry-Secret') or '').strip()
            if not constant_time_compare(provided_secret, shared_secret):
                return Response(status=status.HTTP_403_FORBIDDEN)

        max_payload_bytes = settings.CLIENT_TELEMETRY_MAX_BYTES
        if len(request.body or b'') > max_payload_bytes:
            return Response(
                {'detail': f'Payload de telemetria excede {max_payload_bytes} bytes.'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        serializer = ClientTelemetryEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.validated_data

        logger.info(
            'client_telemetry_event',
            extra={
                'event_name': event['event_name'],
                'platform': event['platform'],
                'app_version': event['app_version'],
                'build_number': event['build_number'],
                'session_id': str(event['session_id']),
                'user_id_hash': event['user_id_hash'],
                'route': event['route'],
                'severity': event['severity'],
                'properties': event['properties'],
                'occurred_at': event['occurred_at'].isoformat(),
            },
        )
        record_domain_event(
            event='client_telemetry_event',
            result=event['event_name'],
            source=event['platform'],
        )

        return Response({'accepted': True}, status=status.HTTP_202_ACCEPTED)
