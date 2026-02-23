import re
from html import escape, unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

from django.contrib.postgres.search import SearchVector
from django.db import models


ALLOWED_CHAPTER_TAGS = {
    'p',
    'br',
    'strong',
    'em',
    'u',
    'ul',
    'ol',
    'li',
    'blockquote',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'a',
}
ALLOWED_CHAPTER_ATTRS = {
    'a': {'href', 'title', 'target', 'rel'},
}
VOID_CHAPTER_TAGS = {'br'}
DROP_CONTENT_TAGS = {'script', 'style'}
ALLOWED_LINK_SCHEMES = {'', 'http', 'https', 'mailto'}
NORMALIZE_CHAPTER_TAGS = {
    'div': 'p',
}
CHAPTER_SEARCH_CONFIG = 'portuguese'


def _is_safe_href(value: str) -> bool:
    href = (value or '').strip()
    if not href:
        return False
    parsed = urlparse(href)
    return (parsed.scheme or '').lower() in ALLOWED_LINK_SCHEMES


class _ChapterHTMLSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._open_tags: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag, attrs):
        raw_tag = (tag or '').lower()
        lower_tag = NORMALIZE_CHAPTER_TAGS.get(raw_tag, raw_tag)

        if self._drop_depth:
            if raw_tag in DROP_CONTENT_TAGS:
                self._drop_depth += 1
            return
        if raw_tag in DROP_CONTENT_TAGS:
            self._drop_depth = 1
            return
        if raw_tag == 'div' and self._open_tags and self._open_tags[-1] == 'li':
            # Browsers costumam embrulhar conteúdo de listas em <div>.
            # Ignoramos esse wrapper para manter UL/OL estáveis.
            return
        if lower_tag not in ALLOWED_CHAPTER_TAGS:
            return

        allowed_attrs = ALLOWED_CHAPTER_ATTRS.get(lower_tag, set())
        clean_attrs: list[tuple[str, str]] = []

        for attr_name, attr_value in attrs:
            name = (attr_name or '').lower()
            if name not in allowed_attrs:
                continue

            value = (attr_value or '').strip()
            if not value:
                continue

            if lower_tag == 'a' and name == 'href' and not _is_safe_href(value):
                continue

            if lower_tag == 'a' and name == 'target' and value not in {'_blank', '_self'}:
                continue

            clean_attrs.append((name, value))

        if lower_tag == 'a':
            has_target_blank = any(name == 'target' and value == '_blank' for name, value in clean_attrs)
            has_rel = any(name == 'rel' for name, _ in clean_attrs)
            if has_target_blank and not has_rel:
                clean_attrs.append(('rel', 'noopener noreferrer'))

        attrs_fragment = ''.join(
            f' {name}="{escape(value, quote=True)}"'
            for name, value in clean_attrs
        )
        if lower_tag in VOID_CHAPTER_TAGS:
            self._parts.append(f'<{lower_tag}{attrs_fragment}>')
            return

        self._parts.append(f'<{lower_tag}{attrs_fragment}>')
        self._open_tags.append(lower_tag)

    def handle_endtag(self, tag):
        raw_tag = (tag or '').lower()
        lower_tag = NORMALIZE_CHAPTER_TAGS.get(raw_tag, raw_tag)

        if self._drop_depth:
            if raw_tag in DROP_CONTENT_TAGS:
                self._drop_depth = max(0, self._drop_depth - 1)
            return
        if raw_tag == 'div' and self._open_tags and self._open_tags[-1] == 'li':
            return
        if lower_tag not in ALLOWED_CHAPTER_TAGS or lower_tag in VOID_CHAPTER_TAGS:
            return
        if lower_tag not in self._open_tags:
            return

        while self._open_tags:
            opened = self._open_tags.pop()
            self._parts.append(f'</{opened}>')
            if opened == lower_tag:
                break

    def handle_data(self, data):
        if self._drop_depth:
            return
        self._parts.append(escape(data or ''))

    def handle_entityref(self, name):
        if self._drop_depth:
            return
        self._parts.append(f'&{name};')

    def handle_charref(self, name):
        if self._drop_depth:
            return
        self._parts.append(f'&#{name};')

    def get_html(self) -> str:
        # Fecha tags pendentes para manter HTML válido.
        while self._open_tags:
            self._parts.append(f'</{self._open_tags.pop()}>')
        return ''.join(self._parts)


def sanitize_chapter_html(value: str) -> str:
    parser = _ChapterHTMLSanitizer()
    parser.feed(value or '')
    parser.close()
    return parser.get_html().strip()


def chapter_search_vector():
    return (
        SearchVector(
            'title',
            config=CHAPTER_SEARCH_CONFIG,
            weight='A',
        )
        + SearchVector(
            'content_plain',
            config=CHAPTER_SEARCH_CONFIG,
            weight='B',
        )
    )


class Book(models.Model):
    """Catálogo de livros."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title


class BookVersion(models.Model):
    """Versões publicáveis de um livro."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'

    def book_version_pdf_path(instance, filename):
        # caminho organizado por livro e versão
        return f"books/{instance.book_id}/versions/{instance.version}/{filename}"

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='versions')
    version = models.CharField(max_length=50)  # ex: '2026.01.19'
    published_at = models.DateField(null=True, blank=True)
    changelog = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    pdf = models.FileField(
        upload_to=book_version_pdf_path,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['book', 'version'],
                name='uniq_book_version_per_book'
            )
        ]

    def __str__(self) -> str:
        return f"{self.book.title} - {self.version}"


class PageText(models.Model):
    """Texto extraído de uma página específica de uma versão."""

    book_version = models.ForeignKey(
        BookVersion,
        on_delete=models.CASCADE,
        related_name='page_texts',
    )
    page_number = models.PositiveIntegerField()  # 1-based
    text = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['page_number']
        constraints = [
            models.UniqueConstraint(
                fields=['book_version', 'page_number'],
                name='uniq_pagetext_per_version_page'
            )
        ]
        indexes = [
            models.Index(fields=['book_version', 'page_number']),
        ]

    def __str__(self) -> str:
        return f'{self.book_version} - p.{self.page_number}'


class BookChapter(models.Model):
    """Capítulo textual de uma versão de livro (fonte nativa de leitura)."""

    book_version = models.ForeignKey(
        BookVersion,
        on_delete=models.CASCADE,
        related_name='chapters',
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    order = models.PositiveIntegerField()
    content_rich = models.TextField(blank=True, default='')  # HTML/Rich text
    content_plain = models.TextField(blank=True, default='', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['book_version', 'slug'],
                name='uniq_bookchapter_slug_per_version',
            ),
            models.UniqueConstraint(
                fields=['book_version', 'order'],
                name='uniq_bookchapter_order_per_version',
            ),
        ]
        indexes = [
            models.Index(fields=['book_version', 'order']),
            models.Index(fields=['book_version', 'slug']),
        ]

    @staticmethod
    def to_plain_text(value: str) -> str:
        if not value:
            return ''
        text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
        text = re.sub(r'</(p|h1|h2|h3|h4|h5|h6|li|blockquote)>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = unescape(text)
        text = text.replace('\xa0', ' ')
        text = re.sub(r'\s*\n\s*', '\n', text)
        return re.sub(r'\s+', ' ', text).strip()

    def save(self, *args, **kwargs):
        self.content_rich = sanitize_chapter_html(self.content_rich or '')
        self.content_plain = self.to_plain_text(self.content_rich)
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.book_version} :: {self.order} - {self.slug}'
