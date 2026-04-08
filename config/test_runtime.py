from django.test import SimpleTestCase

from config.runtime import is_check_only_migration_command


class RuntimeCommandDetectionTests(SimpleTestCase):
    def test_detects_check_only_makemigrations_command(self):
        self.assertTrue(
            is_check_only_migration_command(
                ["manage.py", "makemigrations", "--check", "--dry-run"]
            )
        )

    def test_ignores_plain_makemigrations(self):
        self.assertFalse(
            is_check_only_migration_command(["manage.py", "makemigrations"])
        )

    def test_ignores_other_commands(self):
        self.assertFalse(
            is_check_only_migration_command(
                ["manage.py", "migrate", "--check", "--dry-run"]
            )
        )
