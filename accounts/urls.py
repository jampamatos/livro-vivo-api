from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    LogoutView,
    MeNotificationAcknowledgeView,
    MeNotificationsView,
    MeEntitlementsView,
    MeNotificationPreferencesView,
    MePushDevicesView,
    MeView,
    RegisterView,
)


urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('auth/refresh', TokenRefreshView.as_view()),
    path('auth/logout/', LogoutView.as_view(), name='auth-logout'),

    path('me/', MeView.as_view(), name='me'),
    path('me/entitlements/', MeEntitlementsView.as_view(), name='me-entitlements'),
    path('me/notifications/', MeNotificationsView.as_view(), name='me-notifications'),
    path('me/notifications/<int:dispatch_id>/ack/', MeNotificationAcknowledgeView.as_view(), name='me-notification-ack'),
    path('me/notification-preferences/', MeNotificationPreferencesView.as_view(), name='me-notification-preferences'),
    path('me/push-devices/', MePushDevicesView.as_view(), name='me-push-devices'),
]
