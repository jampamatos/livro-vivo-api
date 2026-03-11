from django.contrib import admin
from django.db.models import Count

from .models import (
    DataPrivacyRequest,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'full_name', 'role', 'profession')
    search_fields = ('user__email', 'full_name', 'profession')
    list_filter = ('role',)
    fieldsets = (
        (
            'Identidade',
            {
                'fields': (
                    'user',
                    'full_name',
                    'profession',
                )
            },
        ),
        (
            'Acesso',
            {
                'fields': (
                    'role',
                )
            },
        ),
    )

    @admin.display(description='Usuário')
    def user_email(self, obj):
        return obj.user.email or obj.user.username


@admin.register(DataPrivacyRequest)
class DataPrivacyRequestAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'request_type',
        'status',
        'retention_policy_summary',
        'created_at',
        'processed_at',
    )
    list_filter = ('request_type', 'status', 'created_at', 'processed_at')
    search_fields = ('user__email', 'user__username', 'retention_policy')
    readonly_fields = (
        'user',
        'request_type',
        'status',
        'retention_policy',
        'payload',
        'created_at',
        'processed_at',
    )
    fieldsets = (
        (
            'Solicitação do titular',
            {
                'fields': (
                    'user',
                    'request_type',
                    'status',
                )
            },
        ),
        (
            'Política e payload de retenção',
            {
                'fields': (
                    'retention_policy',
                    'payload',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'processed_at',
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @staticmethod
    def retention_policy_summary(obj):
        text = (obj.retention_policy or '').strip()
        if len(text) <= 120:
            return text
        return f'{text[:117]}...'
    retention_policy_summary.short_description = 'Retention policy'


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'notifications_enabled',
        'book_version_updates_enabled',
        'new_content_updates_enabled',
        'community_interaction_updates_enabled',
        'push_enabled',
        'updated_at',
    )
    list_filter = (
        'notifications_enabled',
        'book_version_updates_enabled',
        'new_content_updates_enabled',
        'community_interaction_updates_enabled',
        'push_enabled',
    )
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (
            'Usuário',
            {
                'fields': (
                    'user',
                )
            },
        ),
        (
            'Preferências de notificação',
            {
                'fields': (
                    'notifications_enabled',
                    'book_version_updates_enabled',
                    'new_content_updates_enabled',
                    'community_interaction_updates_enabled',
                    'push_enabled',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )


@admin.register(NotificationEvent)
class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'title', 'dedup_key', 'dispatches_count', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('title', 'body', 'dedup_key')
    readonly_fields = ('event_type', 'title', 'body', 'payload', 'dedup_key', 'created_at')
    fieldsets = (
        (
            'Evento',
            {
                'fields': (
                    'event_type',
                    'title',
                    'body',
                    'payload',
                )
            },
        ),
        (
            'Rastreabilidade',
            {
                'fields': (
                    'dedup_key',
                    'created_at',
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_dispatches_count=Count('dispatches', distinct=True))

    @admin.display(description='Disparos')
    def dispatches_count(self, obj):
        return getattr(obj, '_dispatches_count', 0)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(admin.ModelAdmin):
    list_display = ('event', 'user', 'channel', 'status', 'reason', 'created_at', 'dispatched_at', 'acknowledged_at')
    list_filter = ('channel', 'status', 'created_at', 'event__event_type')
    search_fields = ('user__email', 'user__username', 'event__dedup_key', 'reason')
    readonly_fields = (
        'event',
        'user',
        'channel',
        'status',
        'reason',
        'created_at',
        'updated_at',
        'dispatched_at',
        'acknowledged_at',
    )
    fieldsets = (
        (
            'Envio',
            {
                'fields': (
                    'event',
                    'user',
                    'channel',
                    'status',
                    'reason',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'created_at',
                    'dispatched_at',
                    'acknowledged_at',
                    'updated_at',
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'is_active', 'disabled_reason', 'last_seen_at', 'updated_at')
    list_filter = ('platform', 'is_active', 'updated_at')
    search_fields = ('user__email', 'user__username', 'expo_push_token')
    readonly_fields = ('created_at', 'updated_at', 'last_seen_at')
    fieldsets = (
        (
            'Dispositivo',
            {
                'fields': (
                    'user',
                    'platform',
                    'expo_push_token',
                    'is_active',
                    'disabled_reason',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'last_seen_at',
                    'created_at',
                    'updated_at',
                )
            },
        ),
    )
