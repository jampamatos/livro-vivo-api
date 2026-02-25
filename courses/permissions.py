from rest_framework.permissions import BasePermission

from entitlements.models import Subscription
from entitlements.services import get_effective_tier


class IsProfessionalSubscriberOrStaff(BasePermission):
    message = 'Acesso restrito ao plano profissional.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        return get_effective_tier(user) == Subscription.Tier.PROFESSIONAL
