from django.utils.dateparse import parse_date

from rest_framework import filters, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from .models import CourseAsset, CoursePost, LiveEvent, PublicationStatus
from .permissions import IsProfessionalSubscriberOrStaff
from .serializers import CourseAssetSerializer, CoursePostSerializer, LiveEventSerializer


def _parse_date_or_error(raw_value: str | None, *, field_name: str):
    if not raw_value:
        return None
    parsed = parse_date(raw_value)
    if parsed is None:
        raise ValidationError({field_name: f"Data invalida para '{field_name}'. Use YYYY-MM-DD."})
    return parsed


class ProfessionalReadStaffWriteViewSet(viewsets.ModelViewSet):
    """
    Regra de acesso:
    - list/retrieve: profissional (ou staff)
    - create/update/delete: apenas staff
    """

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), IsProfessionalSubscriberOrStaff()]
        return [IsAuthenticated(), IsAdminUser()]


class CoursePostViewSet(ProfessionalReadStaffWriteViewSet):
    serializer_class = CoursePostSerializer
    queryset = CoursePost.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['published_at', 'updated_at', 'created_at']
    ordering = ['-published_at', '-updated_at', '-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_staff:
            qs = qs.filter(status=PublicationStatus.PUBLISHED)

        status_value = (self.request.query_params.get('status') or '').strip()
        if status_value:
            qs = qs.filter(status=status_value)

        post_type = (self.request.query_params.get('type') or '').strip()
        if post_type:
            qs = qs.filter(post_type=post_type)

        date_from = _parse_date_or_error(self.request.query_params.get('date_from'), field_name='date_from')
        if date_from:
            qs = qs.filter(published_at__date__gte=date_from)

        date_to = _parse_date_or_error(self.request.query_params.get('date_to'), field_name='date_to')
        if date_to:
            qs = qs.filter(published_at__date__lte=date_to)

        return qs


class CourseAssetViewSet(ProfessionalReadStaffWriteViewSet):
    serializer_class = CourseAssetSerializer
    queryset = CourseAsset.objects.select_related('post').all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['published_at', 'updated_at', 'created_at']
    ordering = ['-published_at', '-updated_at', '-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_staff:
            qs = qs.filter(status=PublicationStatus.PUBLISHED)

        status_value = (self.request.query_params.get('status') or '').strip()
        if status_value:
            qs = qs.filter(status=status_value)

        asset_type = (self.request.query_params.get('type') or '').strip()
        if asset_type:
            qs = qs.filter(asset_type=asset_type)

        date_from = _parse_date_or_error(self.request.query_params.get('date_from'), field_name='date_from')
        if date_from:
            qs = qs.filter(published_at__date__gte=date_from)

        date_to = _parse_date_or_error(self.request.query_params.get('date_to'), field_name='date_to')
        if date_to:
            qs = qs.filter(published_at__date__lte=date_to)

        return qs


class LiveEventViewSet(ProfessionalReadStaffWriteViewSet):
    serializer_class = LiveEventSerializer
    queryset = LiveEvent.objects.select_related('post').all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['starts_at', 'updated_at', 'created_at']
    ordering = ['-starts_at', '-updated_at', '-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user.is_staff:
            qs = qs.filter(status__in=[LiveEvent.Status.SCHEDULED, LiveEvent.Status.LIVE, LiveEvent.Status.FINISHED])

        status_value = (self.request.query_params.get('status') or '').strip()
        if status_value:
            qs = qs.filter(status=status_value)

        event_type = (self.request.query_params.get('type') or '').strip()
        if event_type:
            qs = qs.filter(event_type=event_type)

        date_from = _parse_date_or_error(self.request.query_params.get('date_from'), field_name='date_from')
        if date_from:
            qs = qs.filter(starts_at__date__gte=date_from)

        date_to = _parse_date_or_error(self.request.query_params.get('date_to'), field_name='date_to')
        if date_to:
            qs = qs.filter(starts_at__date__lte=date_to)

        return qs
