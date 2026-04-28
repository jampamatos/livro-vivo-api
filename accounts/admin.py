from django import forms
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
    ExternalIdentity,
    LegalDocumentVersion,
    NotificationDispatch,
    NotificationEvent,
    NotificationPreference,
    Profile,
    PushDevice,
    UserLegalAcceptance,
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


def _external_identities_root_url():
    return reverse('admin:accounts_externalidentity_changelist')


def _legal_documents_root_url():
    return reverse('admin:accounts_legaldocumentversion_changelist')


def _legal_document_change_url(document: LegalDocumentVersion) -> str:
    return reverse('admin:accounts_legaldocumentversion_change', args=[document.id])


def _legal_acceptances_root_url():
    return reverse('admin:accounts_userlegalacceptance_changelist')


def _user_legal_acceptances_changelist_url(*, user_id=None, document_id=None) -> str:
    return admin_url(
        'admin:accounts_userlegalacceptance_changelist',
        params={
            'user__id__exact': user_id,
            'document__id__exact': document_id,
        },
    )


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


class LegalDocumentVersionAdminForm(forms.ModelForm):
    class Meta:
        model = LegalDocumentVersion
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_active'].help_text = (
            'Ao ativar esta versão, qualquer outra versão ativa do mesmo tipo será desativada automaticamente.'
        )


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
        external_identities_total = obj.user.external_identities.count()
        legal_acceptances_total = obj.user.legal_acceptances.count()
        privacy_requests_total = obj.user.data_privacy_requests.count()

        return format_html(
            '<div class="lv-inline-actions">'
            '<a class="button" href="{}">{}</a> '
            '<a class="button" href="{}">Dispositivos push ({})</a> '
            '<a class="button" href="{}">Identidades externas ({})</a> '
            '<a class="button" href="{}">Adicionar dispositivo</a> '
            '<a class="button" href="{}">Assinaturas ({})</a> '
            '<a class="button" href="{}">Adicionar assinatura</a> '
            '<a class="button" href="{}">Direitos de acesso ({})</a> '
            '<a class="button" href="{}">Adicionar direito de acesso</a> '
            '<a class="button" href="{}">Aceites legais ({})</a> '
            '<a class="button" href="{}">Solicitações de privacidade ({})</a>'
            '</div>',
            preference_url,
            preference_label,
            admin_url('admin:accounts_pushdevice_changelist', params={'user__id__exact': obj.user_id}),
            push_devices_total,
            admin_url('admin:accounts_externalidentity_changelist', params={'user__id__exact': obj.user_id}),
            external_identities_total,
            admin_url('admin:accounts_pushdevice_add', params={'user': obj.user_id}),
            admin_url('admin:entitlements_subscription_changelist', params={'user__id__exact': obj.user_id}),
            subscriptions_total,
            admin_url('admin:entitlements_subscription_add', params={'user': obj.user_id}),
            admin_url('admin:entitlements_entitlement_changelist', params={'user__id__exact': obj.user_id}),
            entitlements_total,
            admin_url('admin:entitlements_entitlement_add', params={'user': obj.user_id}),
            _user_legal_acceptances_changelist_url(user_id=obj.user_id),
            legal_acceptances_total,
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


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    list_display = (
        'user',
        'provider',
        'display_name',
        'provider_email',
        'email_verified',
        'linked_at',
        'last_login_at',
    )
    list_filter = ('provider', 'email_verified', 'linked_at', 'last_login_at')
    search_fields = ('user__email', 'user__username', 'email', 'display_name', 'provider_subject')
    readonly_fields = (
        'user',
        'provider',
        'provider_subject',
        'email',
        'email_verified',
        'display_name',
        'avatar_url',
        'linked_at',
        'last_login_at',
        'last_synced_at',
        'provider_claims',
    )
    fieldsets = (
        (
            'Vinculação',
            {
                'fields': (
                    'user',
                    'provider',
                    'provider_subject',
                    'linked_at',
                )
            },
        ),
        (
            'Identidade do provedor',
            {
                'fields': (
                    'display_name',
                    'email',
                    'email_verified',
                    'avatar_url',
                    'provider_claims',
                )
            },
        ),
        (
            'Auditoria',
            {
                'fields': (
                    'last_login_at',
                    'last_synced_at',
                )
            },
        ),
    )

    @admin.display(description='E-mail do provedor')
    def provider_email(self, obj):
        return obj.email or '-'

    def get_lv_navigation_path(self, request):
        root_url = _external_identities_root_url()
        path = [
            nav_item('Usuários e assinaturas', _profiles_root_url()),
        ]

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        identity = self.get_object(request, object_id) if object_id else None
        profile = _profile_from_user_id(identity.user_id) if identity else _profile_from_request(request)

        if profile:
            path.append(nav_item('Perfis de usuários', _profiles_root_url()))
            path.append(nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)))
            if action == 'changelist':
                path.append(nav_item('Identidades externas', admin_url('admin:accounts_externalidentity_changelist', params={'user__id__exact': profile.user_id})))
            elif identity:
                path.append(nav_item(f'{identity.get_provider_display()}'))
            else:
                path.append(nav_item('Identidades externas'))
            return path

        path.append(nav_item('Identidades externas', root_url))
        if identity:
            path.append(nav_item(f'{identity.get_provider_display()}'))
        return path

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LegalDocumentVersion)
class LegalDocumentVersionAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    form = LegalDocumentVersionAdminForm
    change_form_template = 'admin/accounts/legal_document_version/change_form.html'
    list_display = (
        'document_type',
        'version',
        'title',
        'is_active',
        'published_at',
        'enforcement_starts_at',
        'acceptances_count',
    )
    list_filter = ('document_type', 'is_active', 'published_at', 'enforcement_starts_at')
    search_fields = ('title', 'version', 'content_html')
    readonly_fields = (
        'content_sha256',
        'created_at',
        'updated_at',
        'document_operations_panel',
    )
    fieldsets = (
        (
            'Documento',
            {
                'fields': (
                    'document_type',
                    'version',
                    'title',
                    'content_html',
                )
            },
        ),
        (
            'Publicação',
            {
                'fields': (
                    'is_active',
                    'published_at',
                    'enforcement_starts_at',
                    'content_sha256',
                )
            },
        ),
        (
            'Operação do documento',
            {
                'fields': (
                    'document_operations_panel',
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

    class Media:
        js = ('accounts/admin/legal_document_version_form.js',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_acceptances_count=Count('acceptances', distinct=True))

    def _active_document_versions_by_type(self):
        active_documents = (
            LegalDocumentVersion.objects.filter(is_active=True)
            .order_by('document_type', '-published_at', '-created_at', '-id')
        )
        snapshot = {}
        for document in active_documents:
            snapshot.setdefault(
                document.document_type,
                {
                    'id': document.id,
                    'document_type': document.document_type,
                    'document_type_label': document.get_document_type_display(),
                    'version': document.version,
                    'title': document.title,
                    'label': f'{document.get_document_type_display()} v{document.version} - {document.title}',
                },
            )
        return snapshot

    @admin.display(description='Aceites')
    def acceptances_count(self, obj):
        return getattr(obj, '_acceptances_count', 0)

    @admin.display(description='Fluxo do documento')
    def document_operations_panel(self, obj):
        if not obj or not obj.pk:
            return 'Salve o documento para inspecionar os aceites vinculados.'

        return format_html(
            '<div class="lv-inline-actions">'
            '<a class="button" href="{}">Aceites deste documento ({})</a>'
            '</div>',
            _user_legal_acceptances_changelist_url(document_id=obj.id),
            obj.acceptances.count(),
        )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj=obj))
        if obj and obj.published_at:
            readonly_fields.extend(['document_type', 'version', 'title', 'content_html', 'published_at'])
        return readonly_fields

    def get_lv_navigation_path(self, request):
        root_url = _legal_documents_root_url()
        path = [
            nav_item('Privacidade e compliance', root_url),
            nav_item('Documentos legais', root_url),
        ]

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        document = self.get_object(request, object_id) if object_id else None
        if action == 'add':
            path.append(nav_item('Novo documento legal'))
            return path
        if document:
            path.append(nav_item(f'{document.get_document_type_display()} v{document.version}'))
        return path

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context = {
            **context,
            'legal_document_version_admin_state': {
                'activeByType': self._active_document_versions_by_type(),
                'currentDocumentId': obj.id if obj and obj.pk else None,
            },
        }
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )


@admin.register(UserLegalAcceptance)
class UserLegalAcceptanceAdmin(HierarchicalAdminMixin, admin.ModelAdmin):
    list_display = (
        'user',
        'document_reference',
        'source',
        'app_platform',
        'app_version',
        'ip_address',
        'accepted_at',
    )
    list_filter = ('source', 'app_platform', 'accepted_at', 'document__document_type')
    search_fields = ('user__email', 'user__username', 'document__title', 'document__version', 'user_agent')
    readonly_fields = (
        'user',
        'document',
        'accepted_at',
        'source',
        'app_platform',
        'app_version',
        'ip_address',
        'user_agent',
    )
    fieldsets = (
        (
            'Aceite',
            {
                'fields': (
                    'user',
                    'document',
                    'accepted_at',
                )
            },
        ),
        (
            'Origem',
            {
                'fields': (
                    'source',
                    'app_platform',
                    'app_version',
                )
            },
        ),
        (
            'Rastreabilidade',
            {
                'fields': (
                    'ip_address',
                    'user_agent',
                )
            },
        ),
    )

    @admin.display(description='Documento')
    def document_reference(self, obj):
        return f'{obj.document.get_document_type_display()} v{obj.document.version}'

    def get_lv_navigation_path(self, request):
        root_url = _legal_acceptances_root_url()
        path = []

        action = get_admin_action(request)
        object_id = request.resolver_match.kwargs.get('object_id')
        acceptance = self.get_object(request, object_id) if object_id else None
        profile = _profile_from_user_id(acceptance.user_id) if acceptance else _profile_from_request(request)
        document = (
            acceptance.document
            if acceptance
            else object_from_request(request, LegalDocumentVersion.objects.all(), 'document', 'document__id__exact')
        )

        if profile:
            path.extend(
                [
                    nav_item('Usuários e assinaturas', _profiles_root_url()),
                    nav_item('Perfis de usuários', _profiles_root_url()),
                    nav_item(profile.user.email or profile.user.username, _profile_change_url(profile)),
                ]
            )
            if action == 'changelist':
                path.append(nav_item('Aceites legais', _user_legal_acceptances_changelist_url(user_id=profile.user_id)))
            elif acceptance:
                path.append(nav_item(f'Aceite #{acceptance.id}'))
            else:
                path.append(nav_item('Aceites legais'))
            return path

        path.extend(
            [
                nav_item('Privacidade e compliance', _legal_documents_root_url()),
                nav_item('Aceites legais', root_url),
            ]
        )
        if document:
            path[1] = nav_item('Documentos legais', _legal_documents_root_url())
            path.append(nav_item(f'{document.get_document_type_display()} v{document.version}', _legal_document_change_url(document)))
            if action == 'changelist':
                path.append(nav_item('Aceites legais', _user_legal_acceptances_changelist_url(document_id=document.id)))
                return path
        if acceptance:
            path.append(nav_item(f'Aceite #{acceptance.id}'))
        return path

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
    search_fields = ('user__email', 'user__username', 'installation_id', 'expo_push_token')
    readonly_fields = ('created_at', 'updated_at', 'last_seen_at')
    fieldsets = (
        (
            'Dispositivo',
            {
                'fields': (
                    'user',
                    'platform',
                    'installation_id',
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
