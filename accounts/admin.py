from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'full_name', 'profession')
    search_fields = ('user__email', 'full_name', 'profession')
    list_filter = ('role',)
