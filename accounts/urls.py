from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginView,
    LogoutView,
    MeEntitlementsView,
    MeNotificationPreferencesView,
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
    path('me/notification-preferences/', MeNotificationPreferencesView.as_view(), name='me-notification-preferences'),
]
