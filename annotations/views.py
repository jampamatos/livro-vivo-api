from rest_framework import viewsets

from entitlements.services import entitled_book_ids, user_has_subscription
from .models import Annotation
from .permissions import HasActiveBookEntitlementForAnnotation
from .serializers import AnnotationSerializer


class AnnotationViewSet(viewsets.ModelViewSet):
    """
    CRUD de anotações do usuário logado.
    Filtros (query params):
      - book_version_id (ou book_version)
      - chapter_id (ou chapter)
      - chapter_slug
    """
    serializer_class = AnnotationSerializer
    permission_classes = [HasActiveBookEntitlementForAnnotation]

    def get_queryset(self):
        """
        Limita ao usuário logado e filtra por entitlement do livro.

        - subscription: pode ver todas as anotações dele.
        - sem subscription: só anotações cujas versões pertencem a livros com entitlement.
        """
        user = self.request.user
        qs = (
            Annotation.objects
            .filter(user=user)
            .select_related('book_version', 'book_version__book', 'chapter')
        )

        if not getattr(user, 'is_staff', False) and not user_has_subscription(user):
            allowed_book_ids = entitled_book_ids(user)
            qs = qs.filter(book_version__book_id__in=allowed_book_ids)

        bv = self.request.query_params.get('book_version_id') or self.request.query_params.get('book_version')
        if bv:
            qs = qs.filter(book_version_id=bv)

        chapter_id = self.request.query_params.get('chapter_id') or self.request.query_params.get('chapter')
        if chapter_id:
            try:
                qs = qs.filter(chapter_id=int(chapter_id))
            except ValueError:
                pass

        chapter_slug = self.request.query_params.get('chapter_slug')
        if chapter_slug:
            qs = qs.filter(chapter__slug=chapter_slug)

        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
