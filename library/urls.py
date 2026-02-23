from django.urls import path
from .views import (
    BookListView,
    CurrentBookChapterBySlugView,
    CurrentBookChapterSummaryView,
    CurrentBookVersionView,
    BookVersionDownloadView,
    BookVersionDownloadUrlView,
    BookVersionListView,
    BookVersionPageTextView,
    SearchView,
)

urlpatterns = [
    path('search/', SearchView.as_view(), name='search'),
    path('books/', BookListView.as_view(), name='book-list'),
    path('books/<int:book_id>/search/', SearchView.as_view(), name='book-search'),
    path('books/<int:book_id>/versions/', BookVersionListView.as_view(), name='book-versions'),
    path(
        'books/<int:book_id>/current-version/',
        CurrentBookVersionView.as_view(),
        name='book-current-version',
    ),
    path(
        'books/<int:book_id>/current-version/chapters/',
        CurrentBookChapterSummaryView.as_view(),
        name='book-current-version-chapters',
    ),
    path(
        'books/<int:book_id>/current-version/chapters/<slug:chapter_slug>/',
        CurrentBookChapterBySlugView.as_view(),
        name='book-current-version-chapter-by-slug',
    ),

    path(
        'books/<int:book_id>/versions/<int:version_id>/download-url/',
        BookVersionDownloadUrlView.as_view(),
        name='book-version-download-url',
    ),
    path(
        'books/<int:book_id>/versions/<int:version_id>/download/',
        BookVersionDownloadView.as_view(),
        name='book-version-download',
    ),
    path(
        'books/<int:book_id>/versions/<int:version_id>/pages/<int:page_number>/',
        BookVersionPageTextView.as_view(),
        name='book-version-page-text',
    ),
]
