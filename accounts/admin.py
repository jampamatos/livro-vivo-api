from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from config.admin_hierarchy import (
    HierarchicalAdminMixin,
    admin_url,
    get_admin_action,
    nav_item,
    object_from_request,
)
from .models import (
    DataPrivacyRequest,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
)


def _profiles_root_url():
    return reverse('admin:accounts_profile_changelist')


def _profile_change_url(profile: Profile) -> str:
    return reverse('admin:accounts_profile_change', args=[profile.id])


def _notifications_root_url():
    return reverse('admin:accounts_notificationevent_changelist')


def _notification_event_change_url(event: NotificationEvent) -> str:
    return reverse('admin:accounts_notificationevent_change', args=[event.id])


def _notification_dispatch_changelist_url(event: NotificationEvent) -> str:
    return admin_url('admin:accounts_notificationdispatch_changelist', params={'event__id__exact': event.id})


def _profile_from_user_id(user_id):
    if not user_id:
        return None
    try:
        return Profile.objects.select_related('user').get(user_id=user_id)
    except (Profile.DoesNotExist, ValueError, TypeError):
        return None


def _profile_from_request(request):
    user_id = None
    for source in (request.GET, request.POST):
        user_id = (source.get('user') or source.get('user__id__exact') or '').strip()
        if user_id:
            break
    return _profile_from_user_id(user_id)


@admin.register(Profile)
class ProfileAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    list_display = ('user_email', 'full_name', 'role', 'profession')
    search_fields = ('user__email', 'full_name', 'profession', 'avatar_url')
    list_filter = ('role',)
    readonly_fields = ('profile_operations_panel',)
    fieldsets = (
        (
            'Identidade',
            {
                'fields': (
                    'user',
                    'full_name',
                    'profession',
                    'avatar',
                    'avatar_url',
                )
            },
        ),
        (
            'Operação do perfil',
            {
                'fields': (
                    'profile_operations_panel',
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

    def get_lv_navigation_path(self, request):
        profiles_url = _profiles_root_url()
        path = [
            nav_item('Usuários e assinaturas', profiles_url),
            nav_item('Perfis de usuários', profiles_url),
        ]

        action = get_admin_action(request)
        if action == 'add':
            path.append(nav_item('Novo perfil'))
            return path

        object_id = request.resolver_match.kwargs.get('object_id')
        profile = self.get_object(request, object_id) if object_id else None
        if profile:
            path.append(nav_item(self.user_email(profile)))
        return path

    @admin.display(description='Usuário')
    def user_email(self, obj):
        return obj.user.email or obj.user.username

    @admin.display(description='Fluxos relacionados')
    def profile_operations_panel(self, obj):
        if not obj or not obj.pk:
            return 'Salve o perfil para gerenciar notificações, dispositivos, assinaturas e acessos.'

        preference = NotificationPreference.objects.filter(user=obj.user).first()
        preference_url = (
            reverse('admin:accounts_notificationpreference_change', args=[preference.id])
            if preference
            else admin_url('admin:accounts_notificationpreference_add', params={'user': obj.user_id})
        )
        preference_label = 'Abrir preferência de notificação' if preference else 'Criar preferência de notificação'
        push_devices_total = PushDevice.objects.filter(user=obj.user).count()
        subscriptions_total = obj.user.subscriptions.count()
        entitlements_total = obj.user.entitlements.count()
        privacy_requests_total = obj.user.data_privacy_requests.count()

        return format_html(
            '<div class="lv-inline-actions">'
            '<a class="button" href="{}">{}</a> '
            '<a class="button" href="{}">Dispositivos push ({})</a> '
            '<a class="button" href="{}">Adicionar dispositivo</a> '
            '<a class="button" href="{}">Assinaturas ({})</a> '
            '<a class="button" href="{}">Adicionar assinatura</a> '
            '<a class="button" href="{}">Direitos de acesso ({})</a> '
            '<a class="button" href="{}">Adicionar direito de acesso</a> '
            '<a class="button" href="{}">Solicitações de privacidade ({})</a>'
            '</div>',
            preference_url,
            preference_label,
            admin_url('admin:accounts_pushdevice_changelist', params={'user__id__exact': obj.user_id}),
            push_devices_total,
            admin_url('admin:accounts_pushdevice_add', params={'user': obj.user_id}),
            admin_url('admin:entitlements_subscription_changelist', params={'user__id__exact': obj.user_id}),
            subscriptions_total,
            admin_url('admin:entitlements_subscription_add', params={'user': obj.user_id}),
            admin_url('admin:entitlements_entitlement_changelist', params={'user__id__exact': obj.user_id}),
            entitlements_total,
            admin_url('admin:entitlements_entitlement_add', params={'user': obj.user_id}),
            admin_url('admin:accounts_dataprivacyrequest_changelist', params={'user__id__exact': obj.user_id}),
            privacy_requests_total,
        )


@admin.register(DataPrivacyRequest)
class DataPrivacyRequestAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
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

    def get_lv_navigation_path(self, request):
        root_url = reverse('admin:accounts_dataprivacyrequest_changelist')
        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        request_obj = self.get_object(request, object_id) if object_id else None
        profile = None
        if request_obj and request_obj.user_id:
            profile = _profile_from_user_id(request_obj.user_id)
        if not profile:
            profile = _profile_from_request(request)

        if profile:
            path = [
                nav_item('Usuários e assinaturas', _profiles_root_url()),
                nav_item('Perfis de usuários', _profiles_root_url()),
                nav_item(self._profile_label(profile), _profile_change_url(profile)),
            ]
            if action == 'changelist':
                path.append(
                    nav_item(
                        'Solicitações de privacidade',
                        admin_url('admin:accounts_dataprivacyrequest_changelist', params={'user__id__exact': profile.user_id}),
                    )
                )
            elif request_obj:
                path.append(nav_item(f'Solicitação #{request_obj.id}'))
            return path

        path = [
            nav_item('Privacidade e compliance', root_url),
            nav_item('Solicitações de privacidade', root_url),
        ]
        if request_obj:
            path.append(nav_item(f'Solicitação #{request_obj.id}'))
        return path

    def _profile_label(self, profile: Profile) -> str:
        return profile.user.email or profile.user.username or f'Usuário {profile.user_id}'

    @staticmethod
    def retention_policy_summary(obj):
        text = (obj.retention_policy or '').strip()
        if len(text) <= 120:
            return text
        return f'{text[:117]}...'
    retention_policy_summary.short_description = 'Política de retenção'


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'user': ('user', 'user__id__exact')}
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
        preference = self.get_object(request, object_id) if object_id else None
        profile = _profile_from_user_id(preference.user_id) if preference else _profile_from_request(request)
        if not profile:
            path.append(nav_item('Preferência de notificação'))
            return path

        path.append(nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)))
        if action == 'add':
            path.append(nav_item('Nova preferência de notificação'))
        else:
            path.append(nav_item('Preferência de notificação'))
        return path

    def get_lv_parent_redirect_url(self, request, obj):
        profile = _profile_from_user_id(obj.user_id)
        return _profile_change_url(profile) if profile else None

    def get_lv_addanother_redirect_url(self, request, obj):
        return None


@admin.register(NotificationEvent)
class NotificationEventAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    list_display = ('event_type', 'title', 'dedup_key', 'dispatches_count', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('title', 'body', 'dedup_key')
    readonly_fields = ('event_type', 'title', 'body', 'payload', 'dedup_key', 'created_at', 'dispatches_panel')
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
            'Envios relacionados',
            {
                'fields': (
                    'dispatches_panel',
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

    def get_lv_navigation_path(self, request):
        events_url = _notifications_root_url()
        path = [
            nav_item('Notificações', events_url),
            nav_item('Eventos de notificação', events_url),
        ]

        object_id = request.resolver_match.kwargs.get('object_id')
        event = self.get_object(request, object_id) if object_id else None
        if event:
            path.append(nav_item(event.title or event.dedup_key))
        return path

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

    @admin.display(description='Fluxo do evento')
    def dispatches_panel(self, obj):
        if not obj or not obj.pk:
            return '-'

        return format_html(
            '<div class="lv-inline-actions">'
            '<a class="button" href="{}">Abrir envios deste evento ({})</a>'
            '</div>',
            _notification_dispatch_changelist_url(obj),
            obj.dispatches.count(),
        )


@admin.register(NotificationDispatch)
class NotificationDispatchAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    list_display = (
        'event_reference',
        'user',
        'channel',
        'status',
        'reason',
        'created_at',
        'dispatched_at',
        'acknowledged_at',
    )
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

    def has_module_permission(self, request):
        return False

    def get_lv_navigation_path(self, request):
        events_url = _notifications_root_url()
        path = [
            nav_item('Notificações', events_url),
            nav_item('Eventos de notificação', events_url),
        ]

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        dispatch = self.get_object(request, object_id) if object_id else None
        event = dispatch.event if dispatch else object_from_request(request, NotificationEvent.objects.all(), 'event', 'event__id__exact')

        if not event:
            path.append(nav_item('Envios', reverse('admin:accounts_notificationdispatch_changelist')))
            return path

        path.append(nav_item(event.title or event.dedup_key, _notification_event_change_url(event)))
        if action == 'changelist':
            path.append(nav_item('Envios', _notification_dispatch_changelist_url(event)))
            return path
        if dispatch:
            path.append(nav_item(f'Envio #{dispatch.id}'))
        return path

    def get_lv_parent_redirect_url(self, request, obj):
        return _notification_event_change_url(obj.event)

    @admin.display(description='Evento')
    def event_reference(self, obj):
        title = obj.event.title or obj.event.get_event_type_display()
        return format_html(
            '{}<div class="help">{}</div>',
            title,
            obj.event.dedup_key,
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PushDevice)
class PushDeviceAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    lv_request_initial_fields = {'user': ('user', 'user__id__exact')}
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
        device = self.get_object(request, object_id) if object_id else None
        profile = _profile_from_user_id(device.user_id) if device else _profile_from_request(request)
        if not profile:
            path.append(nav_item('Dispositivos push'))
            return path

        path.append(nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)))
        if action == 'changelist':
            path.append(nav_item('Dispositivos push', admin_url('admin:accounts_pushdevice_changelist', params={'user__id__exact': profile.user_id})))
            return path
        if action == 'add':
            path.append(nav_item('Novo dispositivo push'))
            return path
        if device:
            path.append(nav_item(f'Dispositivo #{device.id}'))
        return path

    def get_lv_parent_redirect_url(self, request, obj):
        profile = _profile_from_user_id(obj.user_id)
        return _profile_change_url(profile) if profile else None

    def get_lv_addanother_redirect_url(self, request, obj):
        return admin_url('admin:accounts_pushdevice_add', params={'user': obj.user_id})
