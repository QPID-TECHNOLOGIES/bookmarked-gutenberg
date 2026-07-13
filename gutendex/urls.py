from django.urls import include, re_path
from django.views.generic import TemplateView

from rest_framework import routers

from books import views
from books.content_views import ContentView, ContentStatusView


router = routers.DefaultRouter()
router.register(r'books', views.BookViewSet)
router.register(r'languages', views.LanguageViewSet)
router.register(r'bookshelves', views.BookshelfViewSet)
router.register(r'subjects', views.SubjectViewSet)


urlpatterns = [
    re_path(r'^$', TemplateView.as_view(template_name='home.html')),

    # Book content caching endpoints (async fetch + poll pattern)
    re_path(
        r'^content/(?P<gutenberg_id>\d+)/status/$',
        ContentStatusView.as_view(),
        name='content-status',
    ),
    re_path(
        r'^content/(?P<gutenberg_id>\d+)/$',
        ContentView.as_view(),
        name='content-request',
    ),

    re_path(r'^', include(router.urls)),
]
