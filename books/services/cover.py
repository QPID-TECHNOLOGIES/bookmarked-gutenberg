import logging
import threading
import requests
from django.db import close_old_connections

logger = logging.getLogger(__name__)


def _async_cache_cover(book_id, original_url, format_id):
    """Downloads the cover image from Gutenberg and uploads it to S3.

    Updates the database Format URL to point to the cached S3 location.
    """
    close_old_connections()
    try:
        from books.models import Format
        from books.services.storage import upload_file_to_s3
        from urllib.parse import urlparse

        logger.info('Background cover caching started for book %s', book_id)

        # Download the cover image from Gutenberg
        # Try mirrors if the URL is from www.gutenberg.org
        parsed_url = urlparse(original_url)
        path = parsed_url.path

        # We can try fetching from mirrors first
        from django.conf import settings
        import random

        mirrors = list(settings.GUTENBERG_MIRRORS)
        random.shuffle(mirrors)

        file_bytes = None
        for mirror in mirrors:
            mirror_url = f'{mirror.rstrip("/")}{path}'
            try:
                response = requests.get(mirror_url, timeout=10)
                if response.status_code == 200:
                    file_bytes = response.content
                    break
            except Exception as e:
                logger.warning('Failed to fetch cover from mirror %s: %s', mirror, e)

        # Fallback to direct URL if mirrors failed
        if file_bytes is None:
            try:
                response = requests.get(original_url, timeout=15)
                if response.status_code == 200:
                    file_bytes = response.content
            except Exception as e:
                logger.error('Failed to fetch cover directly from %s: %s', original_url, e)

        if not file_bytes:
            logger.error('Could not download cover for book %s', book_id)
            return

        # Upload the cover image to S3
        s3_key = f'covers/{book_id}_cover.jpg'
        storage_url = upload_file_to_s3(file_bytes, s3_key, 'image/jpeg')

        # Update the Format URL in the database
        format_entry = Format.objects.filter(id=format_id).first()
        if format_entry:
            format_entry.url = storage_url
            format_entry.save(update_fields=['url'])
            logger.info('✓ Cover cached successfully for book %s: %s', book_id, storage_url)
    except Exception as e:
        logger.error('Error during async cover caching: %s', e)
    finally:
        close_old_connections()


def cache_cover_in_background(book_id, original_url, format_id):
    """Spawns a background thread to cache the cover image."""
    thread = threading.Thread(
        target=_async_cache_cover,
        args=(book_id, original_url, format_id)
    )
    thread.daemon = True
    thread.start()
