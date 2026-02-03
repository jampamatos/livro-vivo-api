from django.db import models

class CaseLaw(models.Model):
    """
    Jurisprudência (v0).
    Campos mínimos do PRD: tribunal, número, data, ementa/resumo, link, tags/tema, relevância.
    """

    court = models.CharField(max_length=64)         # ex: 'STJ', 'TJMG'
    case_number = models.CharField(max_length=128)  # ex: 'REsp 123456/DF'
    decision_date = models.DateField()

    summary = models.TextField()                    # ementa ou resumo do acórdão
    url = models.URLField()                         # link para o acórdão completo

    tags = models.JSONField(default=list, blank=True)

    # relevância simples, sem regras de negócio ainda (0..n)
    relevance = models.PositiveSmallIntegerField(default=0)

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