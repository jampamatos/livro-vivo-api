from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import parse_qsl

from django.contrib import admin
from django.urls import reverse

from .admin_labels import install_admin_labels


_ORIGINAL_GET_APP_LIST = admin.AdminSite.get_app_list

_NAV_GROUPS = (
    {
        'app_label': 'operacao',
        'name': 'Painel operacional',
        'entries': (
            {
                'source': ('community', 'Report'),
                'name': 'Fila de denúncias abertas',
                'query': 'status__exact=open',
                'duplicate': True,
                'hide_add': True,
            },
            {
                'source': ('templates_bank', 'TemplatePiece'),
                'name': 'Peças jurídicas em rascunho',
                'query': 'status__exact=draft',
                'duplicate': True,
                'hide_add': True,
            },
            {
                'source': ('accounts', 'DataPrivacyRequest'),
                'name': 'Solicitações de privacidade pendentes',
                'query': 'status__exact=requested',
                'duplicate': True,
                'hide_add': True,
            },
        ),
    },
    {
        'app_label': 'biblioteca',
        'name': 'Biblioteca',
        'entries': (
            {'source': ('library', 'Book'), 'name': 'Livros'},
            {'source': ('annotations', 'Annotation'), 'name': 'Anotações de leitura'},
        ),
    },
    {
        'app_label': 'curso',
        'name': 'Curso',
        'entries': (
            {'source': ('courses', 'CoursePost'), 'name': 'Posts do curso'},
        ),
    },
    {
        'app_label': 'jurisprudencia',
        'name': 'Jurisprudência',
        'entries': (
            {'source': ('caselaw', 'CaseLaw'), 'name': 'Jurisprudência'},
        ),
    },
    {
        'app_label': 'comunidade',
        'name': 'Comunidade',
        'entries': (
            {'source': ('community', 'Category'), 'name': 'Categorias da comunidade'},
        ),
    },
    {
        'app_label': 'moderacao_comunidade',
        'name': 'Moderação da comunidade',
        'entries': (
            {'source': ('community', 'Report'), 'name': 'Fila de denúncias'},
            {'source': ('community', 'ReportModerationAction'), 'name': 'Ações de moderação'},
            {'source': ('community', 'UserModerationStatus'), 'name': 'Status de moderação de usuários'},
            {'source': ('community', 'UserModerationEvent'), 'name': 'Eventos de moderação de usuários'},
            {'source': ('community', 'ModerationConfig'), 'name': 'Configurações de moderação'},
        ),
    },
    {
        'app_label': 'banco_de_pecas',
        'name': 'Banco de peças',
        'entries': (
            {'source': ('templates_bank', 'TemplatePiece'), 'name': 'Peças jurídicas'},
        ),
    },
    {
        'app_label': 'usuarios_assinaturas',
        'name': 'Usuários e assinaturas',
        'entries': (
            {'source': ('accounts', 'Profile'), 'name': 'Perfis de usuários'},
        ),
    },
    {
        'app_label': 'notificacoes',
        'name': 'Notificações',
        'entries': (
            {'source': ('accounts', 'NotificationEvent'), 'name': 'Eventos de notificação'},
        ),
    },
    {
        'app_label': 'privacidade_compliance',
        'name': 'Privacidade e compliance',
        'entries': (
            {'source': ('accounts', 'DataPrivacyRequest'), 'name': 'Solicitações de privacidade'},
        ),
    },
    {
        'app_label': 'acesso_sistema',
        'name': 'Acesso do sistema',
        'entries': (
            {'source': ('auth', 'User'), 'name': 'Usuários de acesso'},
            {'source': ('auth', 'Group'), 'name': 'Grupos de acesso'},
            {'source': ('token_blacklist', 'OutstandingToken'), 'name': 'Tokens ativos'},
            {'source': ('token_blacklist', 'BlacklistedToken'), 'name': 'Tokens bloqueados'},
        ),
    },
)

_FALLBACK_APP_NAME_OVERRIDES = {
    'accounts': 'Contas',
    'annotations': 'Anotações',
    'auth': 'Acesso',
    'caselaw': 'Jurisprudência',
    'community': 'Comunidade',
    'courses': 'Cursos',
    'entitlements': 'Assinaturas',
    'library': 'Biblioteca',
    'templates_bank': 'Banco de peças',
    'token_blacklist': 'Segurança',
}

_HIDDEN_FROM_MENU_MODELS = {
    # Fluxo de versoes fica centralizado dentro de "Catalogo de livros".
    ('library', 'BookVersion'),
    ('library', 'BookChapter'),
    # Fluxo de curso fica centralizado via "Posts do curso".
    ('courses', 'CourseAsset'),
    ('courses', 'LiveEvent'),
    # Fluxo de comunidade fica centralizado via "Categorias da comunidade".
    ('community', 'Post'),
    ('community', 'Comment'),
    # Fluxo de usuario/notificacao fica centralizado via "Perfis de usuarios" e "Eventos de notificacao".
    ('accounts', 'NotificationPreference'),
    ('accounts', 'NotificationDispatch'),
    ('accounts', 'PushDevice'),
    ('entitlements', 'Subscription'),
    ('entitlements', 'Entitlement'),
}

_ADMIN_MODEL_URL_NAME_RE = re.compile(
    r'^(?P<app_label>[a-z0-9_]+)_(?P<model_name>[a-z0-9_]+)_(?P<action>changelist|add|change|delete|history)$'
)


def _with_query(url: str | None, query: str | None) -> str | None:
    if not url or not query:
        return url
    return f'{url}?{query}'


def _build_model_changelist_url(app_label: str, object_name: str, query: str | None = None) -> str | None:
    try:
        base_url = reverse(f'admin:{app_label}_{object_name.lower()}_changelist')
    except Exception:
        return None
    return _with_query(base_url, query)


def _canonical_pairs(query_string: str | None) -> frozenset[tuple[str, str]]:
    return frozenset(parse_qsl(query_string or '', keep_blank_values=True))


def _build_nav_entries_by_model() -> dict[tuple[str, str], list[dict]]:
    grouped_entries: dict[tuple[str, str], list[dict]] = {}
    for group in _NAV_GROUPS:
        entries = tuple(group.get('entries', ()))
        if not entries:
            continue
        first_source_app, first_source_model = entries[0]['source']
        for entry in entries:
            source_app, source_model = entry['source']
            key = (source_app, source_model.lower())
            grouped_entries.setdefault(key, []).append(
                {
                    'group_name': group['name'],
                    'group_source': (first_source_app, first_source_model),
                    'group_query': entries[0].get('query'),
                    'entry_name': entry.get('name', source_model),
                    'entry_source': (source_app, source_model),
                    'entry_query': entry.get('query'),
                    'query_pairs': _canonical_pairs(entry.get('query')),
                }
            )
    return grouped_entries


_NAV_ENTRIES_BY_MODEL = _build_nav_entries_by_model()


def _pick_nav_entry(app_label: str, model_name: str, query_string: str | None) -> dict | None:
    entries = _NAV_ENTRIES_BY_MODEL.get((app_label, model_name))
    if not entries:
        return None

    request_pairs = _canonical_pairs(query_string)
    matched_entries = [entry for entry in entries if entry['query_pairs'] and entry['query_pairs'].issubset(request_pairs)]
    if matched_entries:
        matched_entries.sort(key=lambda item: len(item['query_pairs']), reverse=True)
        return matched_entries[0]

    for entry in entries:
        if not entry['query_pairs']:
            return entry
    return entries[0]


def _get_registered_model(app_label: str, model_name: str):
    for model in admin.site._registry:
        if model._meta.app_label == app_label and model._meta.model_name == model_name:
            return model
    return None


def _coerce_navigation_path(path: list[dict] | None) -> list[dict] | None:
    if not path:
        return None

    normalized = []
    for item in path:
        label = (item or {}).get('label')
        if not label:
            continue
        normalized.append({'label': label, 'url': (item or {}).get('url')})
    return normalized or None


def _get_object_label(model, object_id: str | None) -> str | None:
    if not model or not object_id:
        return None
    try:
        obj = model._default_manager.get(pk=object_id)
    except Exception:
        return None
    return str(obj)


def _fallback_group_label(app_label: str) -> str:
    return _FALLBACK_APP_NAME_OVERRIDES.get(app_label, app_label.replace('_', ' ').title())


def _navigation_query_string(request, action: str) -> str:
    preserved = (request.GET.get('_changelist_filters') or '').strip()
    if preserved and action in {'add', 'change', 'delete', 'history'}:
        return preserved
    return request.META.get('QUERY_STRING', '')


def get_admin_navigation_path(request) -> list[dict]:
    resolver_match = getattr(request, 'resolver_match', None)
    if not resolver_match:
        return []
    if resolver_match.namespace != 'admin':
        return []

    url_name = resolver_match.url_name or ''
    if url_name in {'index', 'login', 'logout', 'password_change', 'password_change_done'}:
        return []

    model_match = _ADMIN_MODEL_URL_NAME_RE.match(url_name)
    if not model_match:
        app_label = resolver_match.kwargs.get('app_label')
        if not app_label:
            return []
        return [{'label': _fallback_group_label(app_label)}]

    app_label = model_match.group('app_label')
    model_name = model_match.group('model_name')
    action = model_match.group('action')
    query_string = _navigation_query_string(request, action)

    model = _get_registered_model(app_label, model_name)
    model_admin = admin.site._registry.get(model) if model else None
    custom_path_builder = getattr(model_admin, 'get_lv_navigation_path', None)
    if callable(custom_path_builder):
        custom_path = _coerce_navigation_path(custom_path_builder(request))
        if custom_path:
            return custom_path

    nav_entry = _pick_nav_entry(app_label, model_name, query_string)
    changelist_url = None
    if nav_entry:
        group_source_app, group_source_model = nav_entry['group_source']
        entry_source_app, entry_source_model = nav_entry['entry_source']
        group_label = nav_entry['group_name']
        group_url = _build_model_changelist_url(
            group_source_app,
            group_source_model,
            nav_entry.get('group_query'),
        )
        model_label = nav_entry['entry_name']
        entry_specific_url = _build_model_changelist_url(
            entry_source_app,
            entry_source_model,
            nav_entry.get('entry_query'),
        )
        changelist_url = entry_specific_url or _build_model_changelist_url(entry_source_app, entry_source_model)
    else:
        group_label = _fallback_group_label(app_label)
        group_url = None
        model_label = (model._meta.verbose_name_plural.title() if model else model_name.replace('_', ' ').title())
        try:
            changelist_url = reverse(f'admin:{app_label}_{model_name}_changelist')
        except Exception:
            changelist_url = None

    path = [{'label': group_label, 'url': group_url}]
    if action == 'changelist':
        path.append({'label': model_label, 'url': changelist_url})
        return path

    path.append({'label': model_label, 'url': changelist_url})
    if action == 'add':
        path.append({'label': 'Novo registro'})
        return path

    object_label = _get_object_label(model, resolver_match.kwargs.get('object_id'))
    if object_label:
        path.append({'label': object_label})
    return path


def _build_grouped_app_list(base_app_list: list[dict]) -> list[dict]:
    model_lookup: dict[tuple[str, str], dict] = {}
    for app_entry in base_app_list:
        for model in app_entry.get('models', ()):
            key = (app_entry.get('app_label'), model.get('object_name'))
            model_lookup[key] = deepcopy(model)

    grouped_apps: list[dict] = []
    consumed_models: set[tuple[str, str]] = set(_HIDDEN_FROM_MENU_MODELS)

    for group in _NAV_GROUPS:
        grouped_models: list[dict] = []
        for entry in group.get('entries', ()):
            source_key = entry['source']
            base_model = model_lookup.get(source_key)
            if not base_model:
                continue

            model_item = deepcopy(base_model)
            model_item['name'] = entry.get('name', model_item.get('name'))
            model_item['admin_url'] = _with_query(model_item.get('admin_url'), entry.get('query'))
            if entry.get('hide_add'):
                model_item['add_url'] = None
            if entry.get('query'):
                model_item['view_only'] = True

            grouped_models.append(model_item)
            if not entry.get('duplicate'):
                consumed_models.add(source_key)

        if not grouped_models:
            continue

        grouped_apps.append(
            {
                'name': group['name'],
                'app_label': group['app_label'],
                'app_url': grouped_models[0].get('admin_url') or reverse('admin:index'),
                'has_module_perms': True,
                'models': grouped_models,
            }
        )

    for app_entry in base_app_list:
        leftover_models: list[dict] = []
        for model in app_entry.get('models', ()):
            key = (app_entry.get('app_label'), model.get('object_name'))
            if key in consumed_models:
                continue
            leftover_models.append(deepcopy(model))

        if not leftover_models:
            continue

        grouped_apps.append(
            {
                'name': _FALLBACK_APP_NAME_OVERRIDES.get(app_entry.get('app_label'), app_entry.get('name')),
                'app_label': app_entry.get('app_label'),
                'app_url': app_entry.get('app_url'),
                'has_module_perms': app_entry.get('has_module_perms', True),
                'models': leftover_models,
            }
        )

    return grouped_apps


def _grouped_get_app_list(self, request, app_label=None):
    base_app_list = _ORIGINAL_GET_APP_LIST(self, request, app_label=app_label)
    if app_label:
        return base_app_list
    return _build_grouped_app_list(base_app_list)


def install_admin_navigation():
    if getattr(admin.AdminSite, '_lv_grouped_navigation_installed', False):
        return
    admin.AdminSite.get_app_list = _grouped_get_app_list
    admin.AdminSite._lv_grouped_navigation_installed = True

    admin.site.site_header = 'Livro Vivo - Operação administrativa'
    admin.site.site_title = 'Admin do Livro Vivo'
    admin.site.index_title = 'Jornadas operacionais'


install_admin_labels()
install_admin_navigation()
