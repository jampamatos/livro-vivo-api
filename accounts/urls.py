from django.urls import path
from .views import RegisterView, LoginView, MeView, MeEntitlementsView

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('me/', MeView.as_view(), name='me'),
    path('me/entitlements/', MeEntitlementsView.as_view(), name='me-entitlements'),
]