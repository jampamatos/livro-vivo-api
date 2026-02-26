from django.test import SimpleTestCase

from config.logging import build_logging_config


class LoggingConfigTests(SimpleTestCase):
    def test_dev_profile_uses_console_formatter_and_expected_levels(self):
        config = build_logging_config(
            debug=True,
            profile='dev',
            include_request_logs=True,
            structured=None,
        )

        self.assertEqual(config['handlers']['console']['formatter'], 'console')
        self.assertEqual(config['root']['level'], 'DEBUG')
        self.assertEqual(config['loggers']['django']['level'], 'INFO')
        self.assertEqual(config['loggers']['django.server']['level'], 'INFO')

    def test_prod_profile_defaults_to_structured_json_and_restrictive_levels(self):
        config = build_logging_config(
            debug=False,
            profile='prod',
            include_request_logs=False,
            structured=None,
        )

        self.assertEqual(config['handlers']['console']['formatter'], 'json')
        self.assertEqual(config['root']['level'], 'INFO')
        self.assertEqual(config['loggers']['django']['level'], 'WARNING')
        self.assertEqual(config['loggers']['django.server']['level'], 'WARNING')

    def test_include_request_logs_false_raises_django_server_level_in_dev(self):
        config = build_logging_config(
            debug=True,
            profile='dev',
            include_request_logs=False,
            structured=False,
        )
        self.assertEqual(config['loggers']['django.server']['level'], 'WARNING')

    def test_level_overrides_are_applied_when_valid(self):
        config = build_logging_config(
            debug=True,
            profile='dev',
            root_level='error',
            django_level='debug',
            include_request_logs=True,
            structured=False,
        )

        self.assertEqual(config['root']['level'], 'ERROR')
        self.assertEqual(config['loggers']['django']['level'], 'DEBUG')
        self.assertEqual(config['loggers']['livro_vivo']['level'], 'ERROR')

    def test_invalid_level_overrides_fallback_to_safe_defaults(self):
        config = build_logging_config(
            debug=True,
            profile='dev',
            root_level='invalid-level',
            django_level='also-invalid',
            include_request_logs=True,
            structured=False,
        )

        self.assertEqual(config['root']['level'], 'DEBUG')
        self.assertEqual(config['loggers']['django']['level'], 'INFO')

    def test_profile_fallback_uses_debug_flag_when_profile_is_unknown(self):
        dev_config = build_logging_config(
            debug=True,
            profile='unknown',
            include_request_logs=True,
            structured=None,
        )
        prod_config = build_logging_config(
            debug=False,
            profile='unknown',
            include_request_logs=False,
            structured=None,
        )

        self.assertEqual(dev_config['handlers']['console']['formatter'], 'console')
        self.assertEqual(prod_config['handlers']['console']['formatter'], 'json')

    def test_structured_override_can_force_json_in_dev(self):
        config = build_logging_config(
            debug=True,
            profile='dev',
            include_request_logs=True,
            structured=True,
        )
        self.assertEqual(config['handlers']['console']['formatter'], 'json')
