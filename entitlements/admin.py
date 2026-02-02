from django.contrib import admin

from .models import Entitlement


@admin.register(Entitlement)
class EntitlementAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'status', 'expires_at', 'source', 'created_at')
    list_filter = ('product', 'status')
    search_fields = ('user__email',)
