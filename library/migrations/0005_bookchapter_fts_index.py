from django.db import migrations


def create_bookchapter_fts_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute(
        """
        CREATE INDEX IF NOT EXISTS library_bookchapter_fts_idx
        ON library_bookchapter
        USING GIN (
            to_tsvector(
                'portuguese',
                coalesce(title, '') || ' ' || coalesce(content_plain, '')
            )
        );
        """
    )


def drop_bookchapter_fts_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute("DROP INDEX IF EXISTS library_bookchapter_fts_idx;")


class Migration(migrations.Migration):
    dependencies = [
        ('library', '0004_bookchapter'),
    ]

    operations = [
        migrations.RunPython(
            create_bookchapter_fts_index,
            reverse_code=drop_bookchapter_fts_index,
        ),
    ]
