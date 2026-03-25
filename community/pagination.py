from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response


class CommunityPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 50

    def get_paginated_response(self, data):
        return Response(
            {
                'count': self.count,
                'limit': self.get_limit(self.request),
                'offset': self.get_offset(self.request),
                'results': data,
            }
        )
