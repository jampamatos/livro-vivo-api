from __future__ import annotations

from .admin_navigation import get_admin_navigation_path


def admin_current_path(request):
    return {
        'lv_navigation_path': get_admin_navigation_path(request),
    }
