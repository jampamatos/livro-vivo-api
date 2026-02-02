import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from library.models import BookVersion, PageText

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

def _cleanup(text: str) -> str:
    """Normaliza o texto extraído do PDF."""
    if not text:
        return ''

    # Normaliza NBSP e remove zero-width.
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")

    # Colapsa espaços por linha, mas mantém \n.
    cleaned_lines = []
    blank_streak = 0
    for ln in text.splitlines():
        ln = re.sub(r'[ \t]+', ' ', ln).strip()
        if ln == '':
            blank_streak += 1
            if blank_streak <= 1:
                cleaned_lines.append('')
        else:
            blank_streak = 0
            cleaned_lines.append(ln)

    return '\n'.join(cleaned_lines).strip()


def _extract_page_text(page) -> str:
    """Reconstrói o texto preservando a ordem por bloco/linha."""
    words = page.get_text('words')  # (x0,y0,x1,y1, word, block, line, word_no)
    if not words:
        return page.get_text('text') or ''

    # Ordena por bloco/linha/palavra.
    words.sort(key=lambda w: (w[5], w[6], w[7]))

    out_lines = []
    current_block = None
    current_line = None
    line_words = []

    for w in words:
        word = w[4]
        block_no = w[5]
        line_no = w[6]

        if current_block is None:
            current_block, current_line = block_no, line_no
        
        if (block_no, line_no) != (current_block, current_line):
            # Flush linha anterior.
            if line_words:
                out_lines.append(' '.join(line_words))
                line_words = []

            # Separa blocos com uma linha em branco.
            if block_no != current_block:
                out_lines.append('')

            current_block, current_line = block_no, line_no

        line_words.append(word)

    if line_words:
        out_lines.append(' '.join(line_words))

    return '\n'.join(out_lines)


class Command(BaseCommand):
    help = 'Extract text from a BookVersion PDF and store per-page text into PageText.'

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
        """Extrai texto de cada página e grava em PageText."""
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
                raw = _extract_page_text(page)
                text = _cleanup(raw)
                rows.append(
                    PageText(
                        book_version=bv,
                        page_number=page_index + 1,  # 1-based
                        text=text,
                    )
                )

            # Se não usou --force e já existirem páginas, pode bater UniqueConstraint.
            # Por padrão, o comando assume uso com --force durante o MVP.
            PageText.objects.bulk_create(rows, batch_size=200)

            self.stdout.write(self.style.SUCCESS(f'Inserted PageText rows: {len(rows)}'))
