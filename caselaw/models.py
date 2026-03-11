import re
from html import unescape

from django.db import models
from django.utils.text import slugify

from library.models import sanitize_chapter_html


def _to_plain_text(value: str) -> str:
    if not value:
        return ''
    text = re.sub(r'<br\s*/?>', '\n', value, flags=re.IGNORECASE)
    text = re.sub(r'</(p|h1|h2|h3|h4|h5|h6|li|blockquote)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s*\n\s*', '\n', text)
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_anchors(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    normalized: list[dict] = []
    for idx, item in enumerate(value):
        if isinstance(item, str):
            label = item.strip()
            if not label:
                continue
            anchor_id = slugify(label) or f'anchor-{idx + 1}'
            normalized.append({'id': anchor_id, 'label': label})
            continue

        if not isinstance(item, dict):
            continue

        raw_label = str(item.get('label') or item.get('title') or '').strip()
        if not raw_label:
            continue

        raw_id = str(item.get('id') or item.get('slug') or '').strip()
        anchor_id = slugify(raw_id or raw_label) or f'anchor-{idx + 1}'

        anchor = {
            'id': anchor_id,
            'label': raw_label,
        }

        start_offset = item.get('start_offset')
        end_offset = item.get('end_offset')
        try:
            if start_offset is not None:
                anchor['start_offset'] = max(0, int(start_offset))
            if end_offset is not None:
                anchor['end_offset'] = max(0, int(end_offset))
        except (TypeError, ValueError):
            pass

        normalized.append(anchor)

    def _sort_key(anchor: dict):
        start = anchor.get('start_offset')
        return (start if isinstance(start, int) else 10**9, anchor.get('id', ''))

    return sorted(normalized, key=_sort_key)

class CaseLaw(models.Model):
    """
    Jurisprudência com ementa rica + anchors.
    """

    court = models.CharField(max_length=64)         # ex: 'STJ', 'TJMG'
    case_number = models.CharField(max_length=128)  # ex: 'REsp 123456/DF'
    decision_date = models.DateField()

    ementa_rich = models.TextField(blank=True, default='')
    ementa_plain = models.TextField(blank=True, default='', editable=False)
    url = models.URLField()                         # link para o acórdão completo

    anchors = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-decision_date', '-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['court', 'case_number'],
                name='uniq_caselaw_court_case_number'
            ),
        ]
        indexes = [
            models.Index(fields=['court', 'decision_date']),
            models.Index(fields=['case_number']),
        ]

    def __str__(self):
        return f"{self.court} {self.case_number} ({self.decision_date})"

    def save(self, *args, **kwargs):
        is_create = self._state.adding
        self.ementa_rich = sanitize_chapter_html(self.ementa_rich or '')
        self.ementa_plain = _to_plain_text(self.ementa_rich)
        self.anchors = _normalize_anchors(self.anchors)
        if not isinstance(self.tags, list):
            self.tags = []
        self.tags = [str(tag).strip() for tag in self.tags if str(tag).strip()]
        result = super().save(*args, **kwargs)

        if is_create:
            from .services import enqueue_caselaw_publication_notifications

            enqueue_caselaw_publication_notifications(caselaw=self)

        return result
