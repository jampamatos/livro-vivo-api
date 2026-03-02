from django.contrib.auth import get_user_model
from django.db import connections
from django.db.models.signals import pre_delete
from django.dispatch import receiver


LEGACY_USER_TOKEN_TABLES = ('authtoken_token',)


def cleanup_legacy_user_token_rows(*, user_id: int, using: str):
    connection = connections[using]
    existing_tables = set(connection.introspection.table_names())
    tables_to_clean = [table for table in LEGACY_USER_TOKEN_TABLES if table in existing_tables]
    if not tables_to_clean:
        return

    with connection.cursor() as cursor:
        for table in tables_to_clean:
            quoted_table = connection.ops.quote_name(table)
            cursor.execute(f'DELETE FROM {quoted_table} WHERE user_id = %s', [user_id])


@receiver(pre_delete, sender=get_user_model())
def cleanup_legacy_tokens_before_user_delete(sender, instance, using, **kwargs):
    cleanup_legacy_user_token_rows(user_id=instance.pk, using=using)
