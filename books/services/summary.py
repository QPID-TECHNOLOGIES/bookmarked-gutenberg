import logging
import threading
import requests
from django.db import close_old_connections

logger = logging.getLogger(__name__)


def fetch_open_library_summary(title, author_name):
    """Hits the Open Library API to search for a book summary/description.

    Args:
        title: The clean book title.
        author_name: The clean author name.

    Returns:
        str: Clean description if found, else None.
    """
    try:
        # Search for the book key using title and author
        search_url = 'https://openlibrary.org/search.json'
        params = {'title': title, 'author': author_name, 'limit': 1}
        response = requests.get(search_url, params=params, timeout=10)

        if response.status_code != 200:
            return None

        data = response.json()
        docs = data.get('docs', [])
        if not docs:
            return None

        # Extract the work key (e.g. "/works/OL27479W")
        work_key = docs[0].get('key')
        if not work_key:
            return None

        # Fetch the work details directly to read the description field
        work_url = f'https://openlibrary.org{work_key}.json'
        work_response = requests.get(work_url, timeout=10)
        if work_response.status_code != 200:
            return None

        work_data = work_response.json()
        description_data = work_data.get('description')

        if not description_data:
            return None

        # Open Library descriptions can be simple strings or structured dicts
        if isinstance(description_data, dict):
            return description_data.get('value', '').strip()
        elif isinstance(description_data, str):
            return description_data.strip()

    except Exception as e:
        logger.warning('Failed to fetch summary from Open Library: %s', e)

    return None


def _async_enrich_summary(book_id, title, author_name):
    """Background task to fetch and save book description."""
    close_old_connections()
    try:
        from books.models import Book, Summary

        logger.info('Background summary enrichment started for book %s', book_id)

        description = fetch_open_library_summary(title, author_name)
        if not description:
            logger.info('No Open Library summary found for book %s', book_id)
            return

        book = Book.objects.filter(gutenberg_id=book_id).first()
        if book:
            # Create the Summary record
            Summary.objects.create(
                book=book,
                text=description
            )
            logger.info('✓ Summary enriched successfully for book %s', book_id)
    except Exception as e:
        logger.error('Error during async summary enrichment: %s', e)
    finally:
        close_old_connections()


def enrich_summary_in_background(book_id, title, author_name):
    """Spawns a background thread to fetch book summaries from Open Library."""
    thread = threading.Thread(
        target=_async_enrich_summary,
        args=(book_id, title, author_name)
    )
    thread.daemon = True
    thread.start()
