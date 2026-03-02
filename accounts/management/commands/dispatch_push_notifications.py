from django.core.management.base import BaseCommand

from accounts.services import dispatch_pending_push_notifications


class Command(BaseCommand):
    help = 'Despacha notificações push pendentes para a API da Expo.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Quantidade máxima de dispatches pendentes a processar.',
        )

    def handle(self, *args, **options):
        summary = dispatch_pending_push_notifications(limit=options['limit'])
        self.stdout.write(
            self.style.SUCCESS(
                (
                    'Push dispatch concluído: '
                    f"queued={summary['queued']} "
                    f"sent={summary['sent']} "
                    f"failed={summary['failed']} "
                    f"devices={summary['devices']}"
                )
            )
        )
