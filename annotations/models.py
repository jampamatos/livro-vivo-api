from django.conf import settings
from django.db import models

class Annotation(models.Model):
    """
    Destaques/Notas do usuário em uma página específica de um BookVersion.
    rects_normalizados: lista de retângulos normalizados (0..1) para overlays no PDF.
    Exemplo:
      [{"x":0.1,"y":0.2,"w":0.3,"h":0.05}, ...]
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='annotations',
    )

    book_version = models.ForeignKey(
        'library.BookVersion',
        on_delete=models.CASCADE,
        related_name='annotations'
    )

    page_number = models.PositiveIntegerField()

    rects_normalizados = models.JSONField(default=list, blank=True)

    note = models.TextField(blank=True, default='')
    color = models.CharField(max_length=32, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'book_version', 'page_number']),
        ]
        ordering = ['-updated_at', '-created_at']
    
    def __str__(self) -> str:
        return f"Annotation(u={self.user_id}, v={self.book_version_id}, p={self.page_number})"