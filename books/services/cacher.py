"""Fetches book content from Project Gutenberg mirrors.

Implements retry-with-different-mirror logic so a single mirror outage
doesn't block content delivery. NEVER fetches from www.gutenberg.org
directly — always uses the configured mirror list.
"""

import logging
import random
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Mapping of common MIME types to Gutenberg file extensions / path patterns
MIME_TO_EXTENSION = {
    'application/epub+zip': '.epub',
    'text/plain': '.txt',
    'text/plain; charset=utf-8': '.txt',
    'text/plain; charset=us-ascii': '.txt',
    'text/html': '.htm',
    'text/html; charset=utf-8': '.htm',
    'application/x-mobipocket-ebook': '.kindle',
    'application/rdf+xml': '.rdf',
    'image/jpeg': '.jpg',
}

# Preferred format order when a specific format is requested but not found
PREFERRED_FORMATS = [
    'application/epub+zip',
    'text/plain; charset=utf-8',
    'text/plain; charset=us-ascii',
    'text/plain',
    'text/html; charset=utf-8',
    'text/html',
    'application/x-mobipocket-ebook',
]


def fetch_from_mirrors(gutenberg_id, format_url, mirrors=None, timeout=None):
    """Try to download a book file, falling back across mirrors on failure.

    Args:
        gutenberg_id: The Project Gutenberg book ID.
        format_url: The original URL from the Gutendex format field (e.g.
            'https://www.gutenberg.org/files/84/84-0.txt'). Used to derive
            the path component for each mirror.
        mirrors: List of mirror base URLs. Defaults to settings.GUTENBERG_MIRRORS.
        timeout: Request timeout in seconds. Defaults to settings.CONTENT_FETCH_TIMEOUT.

    Returns:
        tuple: (file_bytes, content_type, mirror_used) on success.

    Raises:
        ContentFetchError: If all mirrors fail.
    """
    if mirrors is None:
        mirrors = list(settings.GUTENBERG_MIRRORS)
    if timeout is None:
        timeout = settings.CONTENT_FETCH_TIMEOUT

    # Derive the path from the original URL
    path = _extract_path(format_url, gutenberg_id)

    # Shuffle mirrors to distribute load and avoid hammering one
    random.shuffle(mirrors)

    errors = []
    for mirror in mirrors:
        mirror_url = f'{mirror.rstrip("/")}/{path.lstrip("/")}'
        try:
            logger.info(
                'Fetching book %s from mirror: %s', gutenberg_id, mirror_url
            )
            response = requests.get(mirror_url, timeout=timeout, stream=True)
            response.raise_for_status()

            content = response.content
            content_type = response.headers.get('Content-Type', 'application/octet-stream')

            logger.info(
                'Successfully fetched book %s (%d bytes) from %s',
                gutenberg_id, len(content), mirror_url
            )
            return content, content_type, mirror_url

        except requests.RequestException as e:
            error_msg = f'Mirror {mirror_url} failed: {e}'
            logger.warning(error_msg)
            errors.append(error_msg)
            continue

    raise ContentFetchError(
        f'All {len(mirrors)} mirrors failed for book {gutenberg_id}:\n'
        + '\n'.join(errors)
    )


def try_direct_url(url, timeout=None):
    """Try fetching directly from the URL in the Gutendex format field.

    This is a fallback for when the mirror-based approach doesn't work
    (e.g. the file path structure doesn't match the mirror layout).

    Args:
        url: The direct URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        tuple: (file_bytes, content_type, url_used) on success.

    Raises:
        ContentFetchError: If the fetch fails.
    """
    if timeout is None:
        timeout = settings.CONTENT_FETCH_TIMEOUT

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', 'application/octet-stream')
        return response.content, content_type, url
    except requests.RequestException as e:
        raise ContentFetchError(f'Direct URL fetch failed for {url}: {e}')


def _extract_path(original_url, gutenberg_id):
    """Extract the path component to append to a mirror base URL.

    Gutenberg URLs have various patterns:
    - https://www.gutenberg.org/cache/epub/84/pg84.epub  →  84/pg84.epub
    - https://www.gutenberg.org/files/84/84-0.txt        →  84/84-0.txt
    - https://www.gutenberg.org/ebooks/84.epub.images     →  84/pg84.epub

    For the /cache/epub/ pattern (most common for epub/kindle), we strip
    the mirror prefix and keep the relative path.
    """
    parsed = urlparse(original_url)
    path = parsed.path

    # /cache/epub/84/pg84.epub → 84/pg84.epub
    if '/cache/epub/' in path:
        return path.split('/cache/epub/')[-1]

    # /files/84/84-0.txt → try constructing a cache/epub path instead
    # since most mirrors serve from /cache/epub/
    if '/files/' in path:
        relative = path.split('/files/')[-1]
        return relative

    # /ebooks/84.epub.images → construct standard cache path
    if '/ebooks/' in path:
        return f'{gutenberg_id}/pg{gutenberg_id}.epub'

    # Unknown pattern — use the path as-is (minus leading /)
    return path.lstrip('/')


def get_s3_key(gutenberg_id, mime_type):
    """Generate a consistent S3 object key for a cached book file.

    Args:
        gutenberg_id: The Gutenberg book ID.
        mime_type: The MIME type of the file.

    Returns:
        str: S3 key like 'books/84/pg84.epub'
    """
    ext = MIME_TO_EXTENSION.get(mime_type, '.bin')
    return f'books/{gutenberg_id}/pg{gutenberg_id}{ext}'


class ContentFetchError(Exception):
    """Raised when content cannot be fetched from any mirror."""
    pass
