"""API views for the book content caching layer.

Endpoints:
    GET /content/{gutenberg_id}/         - Request cached content (returns 200 or 202)
    GET /content/{gutenberg_id}/status/  - Poll fetch status (Flutter polls this)

Design rationale:
    Heroku's router hard-kills web requests at 30 seconds (H12 error). A cache-miss
    fetch from a Gutenberg mirror can easily exceed that. So we return 202 Accepted
    immediately on a cache miss and let the worker dyno handle the actual fetch
    asynchronously. The Flutter client polls /status/ until it flips to 'ready'.
"""

import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from .models import Book, CachedContent, Format
from .storage import get_presigned_download_url
from .content_fetcher import get_s3_key

logger = logging.getLogger(__name__)

# Default format to request if none specified
DEFAULT_FORMAT = 'application/epub+zip'

# Map of short aliases to MIME types for friendlier query params
FORMAT_ALIASES = {
    'epub': 'application/epub+zip',
    'text': 'text/plain; charset=utf-8',
    'txt': 'text/plain; charset=utf-8',
    'plain': 'text/plain',
    'html': 'text/html; charset=utf-8',
    'kindle': 'application/x-mobipocket-ebook',
}


class ContentView(View):
    """Handle content requests for a specific book.

    GET /content/{gutenberg_id}/?format=epub

    Response codes:
        200 + redirect: Content is cached → redirect to S3 URL
        202 Accepted:   Cache miss → fetch enqueued, poll /status/
        404:            Book not found or requested format unavailable
    """

    def get(self, request, gutenberg_id):
        # Look up the book
        book = get_object_or_404(Book, gutenberg_id=gutenberg_id)

        # Resolve the requested format
        format_param = request.GET.get('format', 'epub')
        mime_type = FORMAT_ALIASES.get(format_param, format_param)

        # Verify this format exists in the catalog
        format_entry = Format.objects.filter(
            book=book, mime_type__startswith=mime_type.split(';')[0]
        ).first()

        if not format_entry:
            available = list(
                Format.objects.filter(book=book)
                .values_list('mime_type', flat=True)
            )
            return JsonResponse(
                {
                    'error': f'Format "{mime_type}" not available for this book.',
                    'available_formats': available,
                },
                status=404,
            )

        # Check if we already have a cached version
        cached, created = CachedContent.objects.get_or_create(
            book=book,
            format_mime_type=format_entry.mime_type,
            defaults={'status': CachedContent.Status.PENDING},
        )

        if cached.status == CachedContent.Status.READY:
            # Cache hit — generate a secure presigned download link and redirect to S3
            s3_key = get_s3_key(book.gutenberg_id, cached.format_mime_type)
            presigned_url = get_presigned_download_url(s3_key)
            return redirect(presigned_url)

        if cached.status == CachedContent.Status.FAILED:
            # Previous attempt failed — reset to pending for retry
            cached.status = CachedContent.Status.PENDING
            cached.error_message = ''
            cached.save(update_fields=['status', 'error_message'])

        # Cache miss or still in progress — return 202
        return JsonResponse(
            {
                'status': cached.status,
                'gutenberg_id': gutenberg_id,
                'format': format_entry.mime_type,
                'message': 'Content is being prepared. Poll /status/ for updates.',
                'status_url': f'/content/{gutenberg_id}/status/?format={format_param}',
            },
            status=202,
        )


class ContentStatusView(View):
    """Poll endpoint for content fetch status.

    GET /content/{gutenberg_id}/status/?format=epub

    Response:
        {
            "status": "pending" | "fetching" | "ready" | "failed",
            "url": "https://s3.../books/84/pg84.epub",  // only when ready
            "error": "..."  // only when failed
        }
    """

    def get(self, request, gutenberg_id):
        book = get_object_or_404(Book, gutenberg_id=gutenberg_id)

        format_param = request.GET.get('format', 'epub')
        mime_type = FORMAT_ALIASES.get(format_param, format_param)

        # Find matching cached content
        cached = CachedContent.objects.filter(
            book=book,
            format_mime_type__startswith=mime_type.split(';')[0],
        ).first()

        if not cached:
            return JsonResponse(
                {
                    'status': 'not_requested',
                    'message': 'No content fetch has been requested for this format. '
                               'Call /content/{id}/?format=... first.',
                },
                status=404,
            )

        response_data = {
            'status': cached.status,
            'gutenberg_id': gutenberg_id,
            'format': cached.format_mime_type,
        }

        if cached.status == CachedContent.Status.READY:
            # Generate temporary secure link for downloads
            s3_key = get_s3_key(book.gutenberg_id, cached.format_mime_type)
            response_data['url'] = get_presigned_download_url(s3_key)
            if cached.file_size_bytes:
                response_data['file_size_bytes'] = cached.file_size_bytes

        if cached.status == CachedContent.Status.FAILED:
            response_data['error'] = cached.error_message

        if cached.completed_at:
            response_data['completed_at'] = cached.completed_at.isoformat()

        return JsonResponse(response_data)
