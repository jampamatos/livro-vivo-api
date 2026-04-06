from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.admin.options import IS_POPUP_VAR
from django.http import QueryDict
from django.urls import reverse

from .admin_labels import install_admin_labels


install_admin_labels()


def admin_url(viewname: str, *, args: list | tuple | None = None, params: dict | None = None) -> str:
    url = reverse(viewname, args=args or ())
    if not params:
        return url

    clean_params = {key: value for key, value in params.items() if value not in (None, '')}
    if not clean_params:
        return url
    return f'{url}?{urlencode(clean_params, doseq=True)}'


def nav_item(label: str, url: str | None = None) -> dict:
    return {'label': label, 'url': url}


def get_admin_action(request) -> str:
    resolver_match = getattr(request, 'resolver_match', None)
    url_name = getattr(resolver_match, 'url_name', '') or ''
    for action in ('changelist', 'add', 'change', 'delete', 'history'):
        suffix = f'_{action}'
        if url_name.endswith(suffix):
            return action
    return ''


def _request_sources(request):
    for source in (request.GET, request.POST):
        yield source
        preserved_filters = (source.get('_changelist_filters') or '').strip()
        if preserved_filters:
            yield QueryDict(preserved_filters, mutable=False)


def first_request_value(request, *keys: str) -> str | None:
    for source in _request_sources(request):
        for key in keys:
            value = (source.get(key) or '').strip()
            if value:
                return value
    return None


def object_from_request(request, queryset, *keys: str):
    object_id = first_request_value(request, *keys)
    if not object_id:
        return None
    try:
        return queryset.get(pk=object_id)
    except (queryset.model.DoesNotExist, ValueError, TypeError):
        return None


class HierarchicalAdminMixin:
    lv_request_initial_fields: dict[str, tuple[str, ...] | str] = {}

    def get_lv_navigation_path(self, request):  # pragma: no cover - subclasses opt-in
        return None

    def get_lv_parent_redirect_url(self, request, obj):  # pragma: no cover - subclasses opt-in
        return None

    def get_lv_addanother_redirect_url(self, request, obj):  # pragma: no cover - subclasses opt-in
        return None

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        for field_name, request_keys in getattr(self, 'lv_request_initial_fields', {}).items():
            if initial.get(field_name) not in (None, ''):
                continue
            keys = (request_keys,) if isinstance(request_keys, str) else tuple(request_keys)
            value = first_request_value(request, *keys)
            if value:
                initial[field_name] = value
        return initial

    def _lv_should_preserve_default_flow(self, request) -> bool:
        return IS_POPUP_VAR in request.POST or '_continue' in request.POST or '_saveasnew' in request.POST

    def response_add(self, request, obj, post_url_continue=None):
        if self._lv_should_preserve_default_flow(request):
            return super().response_add(request, obj, post_url_continue=post_url_continue)

        if '_addanother' in request.POST:
            addanother_redirect = self.get_lv_addanother_redirect_url(request, obj)
            if addanother_redirect:
                response = super().response_add(request, obj, post_url_continue=post_url_continue)
                response['Location'] = addanother_redirect
                return response
            return super().response_add(request, obj, post_url_continue=post_url_continue)

        redirect_url = self.get_lv_parent_redirect_url(request, obj)
        if redirect_url:
            response = super().response_add(request, obj, post_url_continue=post_url_continue)
            response['Location'] = redirect_url
            return response
        return super().response_add(request, obj, post_url_continue=post_url_continue)

    def response_change(self, request, obj):
        if self._lv_should_preserve_default_flow(request):
            return super().response_change(request, obj)

        if '_addanother' in request.POST:
            addanother_redirect = self.get_lv_addanother_redirect_url(request, obj)
            if addanother_redirect:
                response = super().response_change(request, obj)
                response['Location'] = addanother_redirect
                return response
            return super().response_change(request, obj)

        redirect_url = self.get_lv_parent_redirect_url(request, obj)
        if redirect_url:
            response = super().response_change(request, obj)
            response['Location'] = redirect_url
            return response
        return super().response_change(request, obj)

    def delete_model(self, request, obj):
        request._lv_parent_redirect_url_after_delete = self.get_lv_parent_redirect_url(request, obj)
        return super().delete_model(request, obj)

    def response_delete(self, request, obj_display, obj_id):
        redirect_url = getattr(request, '_lv_parent_redirect_url_after_delete', None)
        if redirect_url:
            response = super().response_delete(request, obj_display, obj_id)
            response['Location'] = redirect_url
            return response
        return super().response_delete(request, obj_display, obj_id)
