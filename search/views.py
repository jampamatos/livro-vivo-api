from __future__ import annotations

from datetime import date, datetime

from django.db.models import Q, TextField
from django.db.models.functions import Cast
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from caselaw.models import CaseLaw
from community.models import Post
from community.services import user_is_banned_from_community
from entitlements.models import Subscription
from entitlements.services import entitled_book_ids, get_effective_tier, user_has_subscription
from library.models import Book, BookChapter, BookVersion

from .serializers import GlobalSearchResultSerializer


MAX_RESULTS_PER_SOURCE = 60


def _parse_int_or_default(raw_value, default: int) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _normalize_whitespace(value: str | None) -> str:
    return ' '.join((value or '').split()).strip()


def _extract_snippet(text: str | None, query: str, *, max_length: int = 180, radius: int = 72) -> str:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return ''

    query_normalized = _normalize_whitespace(query).lower()
    if not query_normalized:
        return normalized[:max_length]

    lower_text = normalized.lower()
    index = lower_text.find(query_normalized)
    if index < 0:
        snippet = normalized[:max_length]
        if len(normalized) > max_length:
            snippet = f'{snippet.rstrip()}…'
        return snippet

    start = max(0, index - radius)
    end = min(len(normalized), index + len(query_normalized) + radius)
    snippet = normalized[start:end].strip()
    if len(snippet) > max_length:
        snippet = snippet[:max_length].rstrip()

    if start > 0:
        snippet = f'…{snippet}'
    if end < len(normalized):
        snippet = f'{snippet}…'
    return snippet


def _to_sort_timestamp(value) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return value.toordinal()
    return 0


def _search_library(*, query: str, query_lower: str, user) -> list[dict]:
    chapters_qs = (
        BookChapter.objects.select_related('book_version', 'book_version__book')
        .filter(
            Q(title__icontains=query)
            | Q(content_plain__icontains=query)
            | Q(book_version__book__title__icontains=query)
        )
    )

    if not user.is_staff:
        chapters_qs = chapters_qs.filter(
            book_version__status=BookVersion.Status.PUBLISHED,
            book_version__book__status=Book.Status.PUBLISHED,
        )
        if user_has_subscription(user):
            pass
        else:
            allowed_book_ids = entitled_book_ids(user)
            if not allowed_book_ids:
                return []
            chapters_qs = chapters_qs.filter(book_version__book_id__in=allowed_book_ids)

    chapters = chapters_qs.order_by('-updated_at', 'book_version__book_id', 'order', 'id')[
        :MAX_RESULTS_PER_SOURCE
    ]

    results: list[dict] = []
    for chapter in chapters:
        book = chapter.book_version.book
        chapter_title = chapter.title or ''
        book_title = book.title or ''
        chapter_body = chapter.content_plain or ''
        chapter_body_lower = chapter_body.lower()
        match_start = chapter_body_lower.find(query_lower)
        match_end = match_start + len(query_lower) if match_start >= 0 else -1

        score = 0
        if query_lower in chapter_title.lower():
            score += 3
        if query_lower in book_title.lower():
            score += 2
        if query_lower in chapter_body.lower():
            score += 1
        if score == 0:
            score = 1

        results.append(
            {
                '_sort': (-score, 0, -_to_sort_timestamp(chapter.updated_at), -chapter.id),
                'type': 'library_chapter',
                'source': 'library',
                'title': f'{book_title} · {chapter_title}',
                'subtitle': f'{chapter.book_version.version} · Capítulo {chapter.order}',
                'snippet': _extract_snippet(chapter_body, query),
                'target': {
                    'route': 'library',
                    'params': {
                        'book_id': book.id,
                        'book_version_id': chapter.book_version_id,
                        'chapter_id': chapter.id,
                        'chapter_slug': chapter.slug,
                        'q': query,
                        **(
                            {
                                'match_start': match_start,
                                'match_end': match_end,
                            }
                            if match_start >= 0 and match_end >= 0
                            else {}
                        ),
                    },
                },
                'metadata': {
                    'book_id': book.id,
                    'book_version_id': chapter.book_version_id,
                    'chapter_id': chapter.id,
                    **(
                        {
                            'match_start': match_start,
                            'match_end': match_end,
                        }
                        if match_start >= 0 and match_end >= 0
                        else {}
                    ),
                },
            }
        )

    return results


def _search_caselaw(*, query: str, query_lower: str, user) -> list[dict]:
    if not user.is_staff and get_effective_tier(user) != Subscription.Tier.PROFESSIONAL:
        return []

    queryset = (
        CaseLaw.objects.annotate(
            tags_text=Cast('tags', TextField()),
            anchors_text=Cast('anchors', TextField()),
        )
        .filter(
            Q(court__icontains=query)
            | Q(case_number__icontains=query)
            | Q(ementa_plain__icontains=query)
            | Q(tags_text__icontains=query)
            | Q(anchors_text__icontains=query)
        )
        .order_by('-decision_date', '-updated_at', '-created_at', '-id')[:MAX_RESULTS_PER_SOURCE]
    )

    results: list[dict] = []
    for item in queryset:
        court = (item.court or '').strip()
        case_number = (item.case_number or '').strip()
        ementa_plain = item.ementa_plain or ''

        score = 0
        if query_lower in court.lower():
            score += 3
        if query_lower in case_number.lower():
            score += 3
        if query_lower in ementa_plain.lower():
            score += 1
        if score == 0:
            score = 1

        results.append(
            {
                '_sort': (-score, 1, -_to_sort_timestamp(item.decision_date), -item.id),
                'type': 'caselaw',
                'source': 'caselaw',
                'title': f'{court} {case_number}'.strip(),
                'subtitle': f'Decisão em {item.decision_date.isoformat()}',
                'snippet': _extract_snippet(ementa_plain, query),
                'target': {
                    'route': 'caselaw',
                    'params': {
                        'caselaw_id': item.id,
                        'q': query,
                    },
                },
                'metadata': {
                    'caselaw_id': item.id,
                    'court': item.court,
                    'decision_date': item.decision_date.isoformat(),
                },
            }
        )

    return results


def _search_community(*, query: str, query_lower: str, user) -> list[dict]:
    if not user.is_staff:
        if not user_has_subscription(user):
            return []
        if user_is_banned_from_community(user):
            return []

    posts_qs = Post.objects.select_related('category').filter(
        Q(title__icontains=query) | Q(body__icontains=query)
    )
    if not user.is_staff:
        posts_qs = posts_qs.filter(moderation_state=Post.ModerationState.ACTIVE)

    posts = posts_qs.order_by('-updated_at', '-created_at', '-id')[:MAX_RESULTS_PER_SOURCE]

    results: list[dict] = []
    for post in posts:
        title = post.title or ''
        body = post.body or ''

        score = 0
        if query_lower in title.lower():
            score += 3
        if query_lower in body.lower():
            score += 1
        if score == 0:
            score = 1

        results.append(
            {
                '_sort': (-score, 2, -_to_sort_timestamp(post.updated_at), -post.id),
                'type': 'community_post',
                'source': 'community',
                'title': title,
                'subtitle': post.category.name if post.category_id else 'Comunidade',
                'snippet': _extract_snippet(body, query),
                'target': {
                    'route': 'community_post',
                    'params': {
                        'post_id': post.id,
                    },
                },
                'metadata': {
                    'post_id': post.id,
                    'category_id': post.category_id,
                },
            }
        )

    return results


class GlobalSearchView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'global_search'

    def get(self, request):
        query = (request.query_params.get('q') or '').strip()
        limit = _parse_int_or_default(request.query_params.get('limit', 20), 20)
        offset = _parse_int_or_default(request.query_params.get('offset', 0), 0)

        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        if not query:
            return Response(
                {'detail': "Query param 'q' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(query) < 2:
            return Response(
                {'detail': "Query param 'q' must have at least 2 character."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query_lower = query.lower()

        combined_results = [
            *_search_library(query=query, query_lower=query_lower, user=request.user),
            *_search_caselaw(query=query, query_lower=query_lower, user=request.user),
            *_search_community(query=query, query_lower=query_lower, user=request.user),
        ]
        combined_results.sort(key=lambda row: row['_sort'])

        total = len(combined_results)
        page = combined_results[offset : offset + limit]
        payload = [{key: value for key, value in row.items() if key != '_sort'} for row in page]

        return Response(
            {
                'q': query,
                'count': total,
                'limit': limit,
                'offset': offset,
                'results': GlobalSearchResultSerializer(payload, many=True).data,
            }
        )
