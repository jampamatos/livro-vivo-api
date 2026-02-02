from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Annotation
from .serializers import AnnotationSerializer

class AnnotationViewSet(viewsets.ModelViewSet):
    """
    CRUD de anotações do usuário logado.
    Filtros (query params):
      - book_version_id
      - page_number
    """
    serializer_class = AnnotationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Limita o queryset ao usuário logado e aplica filtros opcionais."""
        qs = Annotation.objects.filter(user=self.request.user)

        # Aceita ambos os nomes por compatibilidade com clientes antigos.
        bv = self.request.query_params.get('book_version_id') or self.request.query_params.get(
            'book_version'
        )
        if bv:
            qs = qs.filter(book_version_id=bv)

        page = self.request.query_params.get('page_number')
        if page:
            try:
                qs = qs.filter(page_number=int(page))
            except ValueError:
                # Se vier lixo, não filtra por page (não quebra list).
                pass

        return qs

    def perform_create(self, serializer):
        """Força o vínculo da anotação ao usuário autenticado."""
        serializer.save(user=self.request.user)
