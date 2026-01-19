from django.db import models

class Book(models.Model):
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
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PUBLISHED = 'published', 'Published'
        ARCHIVED = 'archived', 'Archived'
    
    def book_version_pdf_path(instance, filename):
        # caminho organizado por livro e versão
        return f"books/{instance.book_id}/versions/{instance.version}/{filename}"

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='versions')
    version = models.CharField(max_length=50) # ex: '2026.01.19'
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