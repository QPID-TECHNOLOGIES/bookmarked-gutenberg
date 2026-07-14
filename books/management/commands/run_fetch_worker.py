"""Background worker that processes pending content fetch requests.

Runs as a separate Heroku worker dyno (declared in Procfile). Polls the
CachedContent table for pending records, downloads from Gutenberg mirrors,
uploads to S3-compatible storage, and updates the record status.

This worker is exempt from Heroku's 30-second router timeout since it's
not a web process — it can take as long as needed per fetch.

Usage:
    python manage.py run_fetch_worker           # run continuously
    python manage.py run_fetch_worker --once    # process one batch and exit
"""

import logging
import signal
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from books.services.cacher import (
    ContentFetchError,
    fetch_from_mirrors,
    get_s3_key,
    try_direct_url,
)
from books.models import Book, CachedContent, Format
from books.services.storage import upload_file_to_s3

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Runs the background content fetch worker that processes pending book downloads.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Process one batch of pending items and exit (useful for testing).',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=5,
            help='Number of pending items to process per batch (default: 5).',
        )

    def handle(self, *args, **options):
        # Graceful shutdown on SIGTERM (Heroku sends this before dyno restart)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        run_once = options['once']
        batch_size = options['batch_size']
        poll_interval = settings.CONTENT_WORKER_POLL_INTERVAL

        self.stdout.write(self.style.SUCCESS(
            f'Content fetch worker started (batch_size={batch_size}, '
            f'poll_interval={poll_interval}s, once={run_once})'
        ))

        while not self._shutdown:
            processed = self._process_batch(batch_size)

            if run_once:
                self.stdout.write(self.style.SUCCESS(
                    f'Processed {processed} items. Exiting (--once mode).'
                ))
                break

            if processed == 0:
                # Nothing to do — sleep before polling again
                time.sleep(poll_interval)

        self.stdout.write(self.style.SUCCESS('Worker shutting down gracefully.'))

    def _handle_shutdown(self, signum, frame):
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        self.stdout.write(self.style.WARNING(
            f'Received signal {signum}, initiating graceful shutdown...'
        ))
        self._shutdown = True

    def _process_batch(self, batch_size):
        """Claim and process a batch of pending content requests.

        Uses SELECT ... FOR UPDATE SKIP LOCKED to allow multiple workers
        (if scaled) without conflicts.
        """
        processed = 0

        # Claim pending items atomically
        with transaction.atomic():
            pending = list(
                CachedContent.objects.select_for_update(skip_locked=True)
                .filter(status=CachedContent.Status.PENDING)
                .order_by('requested_at')[:batch_size]
            )

            # Mark them as fetching so no other worker picks them up
            for item in pending:
                item.status = CachedContent.Status.FETCHING
                item.save(update_fields=['status'])

        # Process each item outside the transaction (long-running I/O)
        for item in pending:
            self._fetch_and_cache(item)
            processed += 1

        return processed

    def _fetch_and_cache(self, cached_content):
        """Fetch a single book file from mirrors and upload to S3.

        Args:
            cached_content: A CachedContent instance in FETCHING status.
        """
        book = cached_content.book
        mime_type = cached_content.format_mime_type
        gutenberg_id = book.gutenberg_id

        self.stdout.write(
            f'  Fetching book {gutenberg_id} ({mime_type})...'
        )

        # Find the original URL from the Gutendex format table
        format_entry = Format.objects.filter(
            book=book, mime_type=mime_type
        ).first()

        if not format_entry:
            self._mark_failed(
                cached_content,
                f'No format entry found for mime_type={mime_type}'
            )
            return

        original_url = format_entry.url

        # Try fetching from mirrors first
        try:
            file_bytes, content_type, mirror_used = fetch_from_mirrors(
                gutenberg_id, original_url
            )
        except ContentFetchError as mirror_error:
            # All mirrors failed — try the direct URL as last resort
            self.stdout.write(self.style.WARNING(
                f'  All mirrors failed for book {gutenberg_id}, '
                f'trying direct URL: {original_url}'
            ))
            try:
                file_bytes, content_type, mirror_used = try_direct_url(original_url)
            except ContentFetchError as direct_error:
                self._mark_failed(
                    cached_content,
                    f'Mirror errors: {mirror_error}\nDirect URL error: {direct_error}'
                )
                return

        # Upload to S3
        s3_key = get_s3_key(gutenberg_id, mime_type)
        try:
            storage_url = upload_file_to_s3(file_bytes, s3_key, content_type)
        except Exception as e:
            self._mark_failed(
                cached_content,
                f'S3 upload failed: {e}'
            )
            return

        # Mark as ready
        cached_content.status = CachedContent.Status.READY
        cached_content.storage_url = storage_url
        cached_content.mirror_used = mirror_used
        cached_content.file_size_bytes = len(file_bytes)
        cached_content.completed_at = timezone.now()
        cached_content.error_message = ''
        cached_content.save()

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ Book {gutenberg_id} ({mime_type}) cached: '
            f'{len(file_bytes)} bytes → {storage_url}'
        ))

    def _mark_failed(self, cached_content, error_message):
        """Mark a content fetch as failed."""
        cached_content.status = CachedContent.Status.FAILED
        cached_content.error_message = error_message
        cached_content.completed_at = timezone.now()
        cached_content.save()

        self.stderr.write(self.style.ERROR(
            f'  ✗ Book {cached_content.book.gutenberg_id} '
            f'({cached_content.format_mime_type}) failed: {error_message}'
        ))
