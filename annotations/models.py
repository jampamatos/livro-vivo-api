from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Annotation(models.Model):
    """
    Destaques/Notas por capítulo/trecho de um BookVersion.

    - selector: payload flexível (ex.: XPath/range id/text quote)
    - start_offset/end_offset: offsets absolutos em relação ao conteúdo plain do capítulo
    - excerpt: trecho destacado para renderização rápida
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

    chapter = models.ForeignKey(
        'library.BookChapter',
        on_delete=models.CASCADE,
        related_name='annotations',
    )
    selector = models.JSONField(default=dict, blank=True)
    start_offset = models.PositiveIntegerField(default=0)
    end_offset = models.PositiveIntegerField(default=1)
    excerpt = models.TextField(blank=True, default='')

    note = models.TextField(blank=True, default='')
    color = models.CharField(max_length=32, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_offset__gte=F('start_offset')),
                name='annotation_end_offset_gte_start_offset',
            ),
        ]
        indexes = [
            models.Index(
                fields=['user', 'book_version', 'chapter', 'start_offset'],
                name='ann_u_bv_ch_start_idx',
            ),
        ]
        ordering = ['-updated_at', '-created_at']

    def __str__(self) -> str:
        return f'Anotação #{self.pk or "nova"} no capítulo #{self.chapter_id}'
