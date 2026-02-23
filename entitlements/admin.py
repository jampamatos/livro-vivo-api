from django.contrib import admin

from .models import Entitlement, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
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


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
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

    @admin.display(ordering='subscription__tier', description='Tier')
    def subscription_tier(self, obj: Entitlement):
        if obj.product != Entitlement.Product.SUBSCRIPTION:
            return '-'
        if not obj.subscription_id:
            return 'legacy'
        return obj.subscription.tier

    @admin.display(ordering='subscription__is_founder', boolean=True, description='Founder')
    def is_founder(self, obj: Entitlement):
        if obj.product != Entitlement.Product.SUBSCRIPTION or not obj.subscription_id:
            return False
        return bool(obj.subscription.is_founder)
