from django.db.models import Q

from rest_framework import viewsets
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CaseLaw
from .serializers import CaseLawSerializer

class CaseLawPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 50

    def get_paginated_response(self, data):
        return Response(
            {
                'q': (self.request.query_params.get('q') or '').strip(),
                'count': self.count,
                'limit': self.get_limit(self.request),
                'offset': self.get_offset(self.request),
                'results': data,
            }
        )

class CaseLawViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /caselaw/?q=...&court=STJ&limit=20&offset=0
    """

    serializer_class = CaseLawSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CaseLawPagination

    queryset = CaseLaw.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()

        q = (self.request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(court__icontains=q)
                | Q(case_number__icontains=q)
                | Q(summary__icontains=q)
            )
        court = (self.request.query_params.get('court') or '').strip()
        if court:
            qs = qs.filter(court__iexact=court)
        
        return qs
