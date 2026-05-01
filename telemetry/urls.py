from django.urls import path

from .views import ClientTelemetryEventView


urlpatterns = [
    path('telemetry/client-events/', ClientTelemetryEventView.as_view(), name='client-telemetry-events'),
]
