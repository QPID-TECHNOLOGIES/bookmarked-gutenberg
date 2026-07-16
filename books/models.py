from django.db import models
from django.contrib.postgres.indexes import GinIndex


class Book(models.Model):
    authors = models.ManyToManyField('Person')
    bookshelves = models.ManyToManyField('Bookshelf')
    copyright = models.BooleanField(null=True)
    download_count = models.PositiveIntegerField(blank=True, null=True, db_index=True)
    editors = models.ManyToManyField("Person", related_name="books_edited")
    gutenberg_id = models.PositiveIntegerField(unique=True)
    languages = models.ManyToManyField('Language')
    media_type = models.CharField(max_length=16)
    subjects = models.ManyToManyField('Subject')
    title = models.CharField(blank=True, max_length=1024, null=True)
    translators = models.ManyToManyField(
        'Person', related_name='books_translated')

    def __str__(self):
        if self.title:
            return self.title
        else:
            return str(self.id)

    def get_formats(self):
        return Format.objects.filter(book_id=self.id)

    def get_summaries(self):
        return Summary.objects.filter(book_id=self.id)

    class Meta:
        indexes = [
            GinIndex(fields=['title'], name='book_title_trgm_idx', opclasses=['gin_trgm_ops']),
        ]


class Bookshelf(models.Model):
    name = models.CharField(max_length=64, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            GinIndex(fields=['name'], name='bookshelf_name_trgm_idx', opclasses=['gin_trgm_ops']),
        ]


class Format(models.Model):
    book = models.ForeignKey('Book', on_delete=models.CASCADE)
    mime_type = models.CharField(max_length=32)
    url = models.CharField(max_length=256)

    def __str__(self):
        return "%s (%s)" % (
            self.mime_type,
            self.book.__str__()
        )


class Language(models.Model):
    code = models.CharField(max_length=4, unique=True)

    def __str__(self):
        return self.code


class Person(models.Model):
    birth_year = models.SmallIntegerField(blank=True, null=True)
    death_year = models.SmallIntegerField(blank=True, null=True)
    name = models.CharField(max_length=128)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            GinIndex(fields=['name'], name='person_name_trgm_idx', opclasses=['gin_trgm_ops']),
        ]


class Subject(models.Model):
    name = models.CharField(max_length=256)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            GinIndex(fields=['name'], name='subject_name_trgm_idx', opclasses=['gin_trgm_ops']),
        ]


class Summary(models.Model):
    book = models.ForeignKey('Book', on_delete=models.CASCADE, related_name='summaries')
    text = models.TextField()

    def __str__(self):
        preview_len = 24
        return f'{self.text[:preview_len]}...' if len(self.text) > preview_len else self.text

    class Meta:
        indexes = [
            GinIndex(fields=['text'], name='summary_text_trgm_idx', opclasses=['gin_trgm_ops']),
        ]


class CachedContent(models.Model):
    """Tracks fetch-and-cache status of individual book files in object storage.

    Lifecycle: pending → fetching → ready | failed
    - Web endpoint creates a record with status=PENDING when a cache miss occurs.
    - Worker dyno picks it up, sets FETCHING, downloads from a Gutenberg mirror,
      uploads to S3-compatible storage, and sets READY (or FAILED on error).
    - Flutter client polls the status endpoint until it flips to READY, then
      downloads from storage_url.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        FETCHING = 'fetching', 'Fetching'
        READY = 'ready', 'Ready'
        FAILED = 'failed', 'Failed'

    book = models.ForeignKey(
        Book, on_delete=models.CASCADE, related_name='cached_contents'
    )
    format_mime_type = models.CharField(max_length=64)
    storage_url = models.URLField(max_length=512, blank=True, default='')
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    error_message = models.TextField(blank=True, default='')
    mirror_used = models.CharField(max_length=256, blank=True, default='')
    file_size_bytes = models.PositiveIntegerField(blank=True, null=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('book', 'format_mime_type')
        verbose_name_plural = 'cached contents'

    def __str__(self):
        return f'{self.book.gutenberg_id} ({self.format_mime_type}) - {self.status}'
