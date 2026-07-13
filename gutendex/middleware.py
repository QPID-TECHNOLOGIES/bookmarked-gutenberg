import logging

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class JsonExceptionMiddleware:
    """Middleware to catch uncaught exceptions and return JSON error responses in production.

    Ensures that mobile client apps receive clean JSON error structures
    instead of raw HTML error/traceback screens when unexpected errors happen.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # Log the stack trace automatically
        logger.exception('Unhandled exception in request %s: %s', request.path, exception)

        # In local debug mode, return None to let Django's interactive traceback view run
        if settings.DEBUG:
            return None

        # Return a structured JSON response in production
        return JsonResponse(
            {
                'error': 'Internal Server Error',
                'message': 'An unexpected error occurred on the server. Please check the logs or contact support.',
                'path': request.path,
            },
            status=500,
        )


class ApiKeyMiddleware:
    """Middleware to enforce API key security for mobile client requests.

    Verifies that requests carry a valid API key inside the 'X-Api-Key' header
    (or 'Authorization: Bearer <key>'). Exempts static assets and the index page
    so the developer portal and public documentation remain visible.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        expected_key = getattr(settings, 'API_KEY', None)

        # If no API_KEY env var is configured, bypass check (inactive in local dev unless set)
        if not expected_key:
            return self.get_response(request)

        # Exempt homepage, static assets, admin, and health check paths
        path = request.path
        if path == '/' or path.startswith('/static/') or path.startswith('/admin/') or path == '/health/':
            return self.get_response(request)

        # Look for API key in X-Api-Key header
        provided_key = request.headers.get('X-Api-Key')

        # Fallback check for Authorization: Bearer <key> or Authorization: <key>
        if not provided_key:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                provided_key = auth_header[7:]
            elif auth_header.startswith('Api-Key '):
                provided_key = auth_header[8:]
            elif auth_header:
                provided_key = auth_header

        if not provided_key or provided_key != expected_key:
            logger.warning(
                'Unauthorized access attempt to %s from IP %s',
                path,
                request.META.get('REMOTE_ADDR'),
            )
            return JsonResponse(
                {
                    'error': 'Unauthorized',
                    'message': 'Missing or invalid API key. Set X-Api-Key in request headers.',
                },
                status=401,
            )

        return self.get_response(request)

