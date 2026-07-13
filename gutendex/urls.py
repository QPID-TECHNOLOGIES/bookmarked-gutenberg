from django.urls import include, re_path
from django.views.generic import TemplateView

from rest_framework import routers

from books import views
from books.content_views import ContentView, ContentStatusView
from books.health_views import HealthCheckView


router = routers.DefaultRouter()
router.register(r'books', views.BookViewSet)
router.register(r'languages', views.LanguageViewSet)
router.register(r'bookshelves', views.BookshelfViewSet)
router.register(r'subjects', views.SubjectViewSet)


urlpatterns = [
    re_path(r'^$', TemplateView.as_view(template_name='home.html')),
    
    # Industry-standard health check
    re_path(r'^health/$', HealthCheckView.as_view(), name='health-check'),

    # API Version 1 Namespace
    re_path(
        r'^api/v1/content/(?P<gutenberg_id>\d+)/status/$',
        ContentStatusView.as_view(),
        name='v1-content-status',
    ),
    re_path(
        r'^api/v1/content/(?P<gutenberg_id>\d+)/$',
        ContentView.as_view(),
        name='v1-content-request',
    ),
    re_path(r'^api/v1/', include(router.urls)),

    # Legacy Fallback Namespace (Backwards compatibility for existing mobile builds)
    re_path(
        r'^content/(?P<gutenberg_id>\d+)/status/$',
        ContentStatusView.as_view(),
        name='legacy-content-status',
    ),
    re_path(
        r'^content/(?P<gutenberg_id>\d+)/$',
        ContentView.as_view(),
        name='legacy-content-request',
    ),
    re_path(r'^', include(router.urls)),
]

