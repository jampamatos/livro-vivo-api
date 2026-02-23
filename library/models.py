import re
from html import unescape

from django.db import models


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
        text = re.sub(r'<[^>]+>', ' ', value)
        text = unescape(text)
        return re.sub(r'\s+', ' ', text).strip()

    def save(self, *args, **kwargs):
        # Keep plain text deterministic for search/index tasks.
        self.content_plain = self.to_plain_text(self.content_rich or '')
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.book_version} :: {self.order} - {self.slug}'
