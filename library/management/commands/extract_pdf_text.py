from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from library.models import BookVersion, PageText

try:
    import fitz     # PyMuPDF
except Exception:   # pragma: no cover
    fitz = None

def _normalize(text: str) -> str:
    # normalização simples para o MVP: remove espaços excessivos
    return ''.join((text or '').split()).strip()

class Command(BaseCommand):
    help = 'Extract text frin a BookVersion PDF and store per-page text into PageText.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--book-version-id',
            type=int,
            required=True,
            help='ID of BookVersion to extract text from.',
        )

        parser.add_argument(
            '--force',
            action='store_true',
            help='Delete existing PageText row for this version before inserting'
        )
    
    def handle(self, *args, **options):
        book_version_id = options['book_version_id']
        force = options['force']

        try:
            bv = BookVersion.objects.select_related('book').get(id=book_version_id)
        except BookVersion.DoesNotExist:
            raise CommandError(f'BookVersion id={book_version_id} not found')
        
        if not bv.pdf:
            raise CommandError(f'BookVersion id={book_version_id} has no PDF uploaded')
        
        pdf_path = bv.pdf.path

        self.stdout.write(self.style.NOTICE(f'BookVersion: {bv}'))
        self.stdout.write(self.style.NOTICE(f'PDF path: {pdf_path}'))

        if fitz is None:
            raise CommandError(
                "PyMuPDF is not installed. Add 'PyMuPDF' to requirements.txt and pip install -r requirements.txt."
            )
        
        doc = fitz.open(pdf_path)
        num_pages = doc.page_count
        self.stdout.write(self.style.NOTICE(f'Pages detected: {num_pages}'))

        with transaction.atomic():
            if force:
                deleted, _ = PageText.objects.filter(book_version=bv).delete()
                self.stdout.write(self.style.WARNING(f'Deleted existing PageText rows: {deleted}'))
            
            rows = []
            for page_index in range(num_pages):
                page = doc.load_page(page_index)
                raw = page.get_text('text') or ''
                text = _normalize(raw)
                rows.append(
                    PageText(
                        book_version=bv,
                        page_number=page_index + 1, # 1-based
                        text=text,
                    )
                )
            
            # Se não usou --force e já existirem páginas, pode bater UniqueConstraint.
            # Por padrão, o comando assume uso com --force durante o MVP.
            PageText.objects.bulk_create(rows, batch_size=200)

            self.stdout.write(self.style.SUCCESS(f'Inserted PageText rows: {len(rows)}'))