from django.contrib import admin
from django.urls import reverse

from accounts.models import Profile
from config.admin_hierarchy import HierarchicalAdminMixin, admin_url, get_admin_action, nav_item

from .models import Entitlement, Subscription


def _profiles_root_url():
    return reverse('admin:accounts_profile_changelist')


def _profile_from_user_id(user_id):
    if not user_id:
        return None
    try:
        return Profile.objects.select_related('user').get(user_id=user_id)
    except (Profile.DoesNotExist, ValueError, TypeError):
        return None


def _profile_change_url(profile: Profile) -> str:
    return reverse('admin:accounts_profile_change', args=[profile.id])


@admin.register(Subscription)
class SubscriptionAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'user': ('user', 'user__id__exact')}
    list_display = (
        'user',
        'tier',
        'status',
        'is_founder',
        'started_at',
        'expires_at',
        'source',
        'updated_at',
    )
    list_filter = ('tier', 'status', 'is_founder')
    search_fields = ('user__email',)
    autocomplete_fields = ('user',)

    def has_module_permission(self, request):
        return False

    def get_lv_navigation_path(self, request):
        profiles_url = _profiles_root_url()
        path = [
            nav_item('Usuários e assinaturas', profiles_url),
            nav_item('Perfis de usuários', profiles_url),
        ]

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        subscription = self.get_object(request, object_id) if object_id else None

        user_id = subscription.user_id if subscription else request.GET.get('user') or request.GET.get('user__id__exact') or request.POST.get('user')
        profile = _profile_from_user_id(user_id)
        if not profile:
            path.append(nav_item('Assinaturas'))
            return path

        path.append(nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)))
        if action == 'changelist':
            path.append(nav_item('Assinaturas', admin_url('admin:entitlements_subscription_changelist', params={'user__id__exact': profile.user_id})))
            return path
        if action == 'add':
            path.append(nav_item('Nova assinatura'))
            return path
        if subscription:
            path.append(nav_item(f'{subscription.get_tier_display()} · {subscription.get_status_display()}'))
        return path

    def get_lv_parent_redirect_url(self, request, obj):
        profile = _profile_from_user_id(obj.user_id)
        return _profile_change_url(profile) if profile else None

    def get_lv_addanother_redirect_url(self, request, obj):
        return admin_url('admin:entitlements_subscription_add', params={'user': obj.user_id})


@admin.register(Entitlement)
class EntitlementAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'user': ('user', 'user__id__exact')}
    list_display = (
        'user',
        'product',
        'status',
        'book',
        'subscription',
        'subscription_tier',
        'is_founder',
        'expires_at',
        'source',
        'created_at',
    )
    list_filter = ('product', 'status', 'subscription__tier', 'subscription__is_founder')
    search_fields = ('user__email',)
    autocomplete_fields = ('user', 'book', 'subscription')

    def has_module_permission(self, request):
        return False

    def get_lv_navigation_path(self, request):
        profiles_url = _profiles_root_url()
        path = [
            nav_item('Usuários e assinaturas', profiles_url),
            nav_item('Perfis de usuários', profiles_url),
        ]

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        entitlement = self.get_object(request, object_id) if object_id else None

        user_id = entitlement.user_id if entitlement else request.GET.get('user') or request.GET.get('user__id__exact') or request.POST.get('user')
        profile = _profile_from_user_id(user_id)
        if not profile:
            path.append(nav_item('Direitos de acesso'))
            return path

        path.append(nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)))
        if action == 'changelist':
            path.append(nav_item('Direitos de acesso', admin_url('admin:entitlements_entitlement_changelist', params={'user__id__exact': profile.user_id})))
            return path
        if action == 'add':
            path.append(nav_item('Novo direito de acesso'))
            return path
        if entitlement:
            path.append(nav_item(f'Direito de acesso #{entitlement.id}'))
        return path

    def get_lv_parent_redirect_url(self, request, obj):
        profile = _profile_from_user_id(obj.user_id)
        return _profile_change_url(profile) if profile else None

    def get_lv_addanother_redirect_url(self, request, obj):
        return admin_url('admin:entitlements_entitlement_add', params={'user': obj.user_id})

    @admin.display(ordering='subscription__tier', description='Plano')
    def subscription_tier(self, obj: Entitlement):
        if obj.product != Entitlement.Product.SUBSCRIPTION:
            return '-'
        if not obj.subscription_id:
            return 'legado'
        return obj.subscription.tier

    @admin.display(ordering='subscription__is_founder', boolean=True, description='Fundador')
    def is_founder(self, obj: Entitlement):
        if obj.product != Entitlement.Product.SUBSCRIPTION or not obj.subscription_id:
            return False
        return bool(obj.subscription.is_founder)
