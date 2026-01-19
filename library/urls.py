from django.urls import path
from .views import(
    BookListView,
    BookVersionListView,
    BookVersionDownloadUrlView,
    BookVersionDownloadView,
    SearchView
)

urlpatterns = [
    path('search/', SearchView.as_view(), name='search'),
    path('books/', BookListView.as_view(), name='book-list'),
    path('books/<int:book_id>/versions/', BookVersionListView.as_view(), name='book-versions'),

    path(
        'books/<int:book_id>/versions/<int:version_id>/download-url/',
        BookVersionDownloadUrlView.as_view(),
        name='book-version-download-url'
    ),
    path(
        'books/<int:book_id>/versions/<int:version_id>/download/',
        BookVersionDownloadView.as_view(),
        name='book-version-download',
    ),
]