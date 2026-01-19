from django.urls import path
from .views import BookListView, BookVersionListView

urlpatterns = [
    path('books/', BookListView.as_view(), name='book-list'),
    path('books/<int:book_id>/versions/', BookVersionListView.as_view(), name='book-versions'),
]