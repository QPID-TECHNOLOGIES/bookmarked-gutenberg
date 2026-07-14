from rest_framework import serializers

from .models import *
from books.data_preprocessor import (
    clean_title,
    clean_author_name,
    clean_subject,
    get_full_language_name,
)
from books.storage import get_presigned_download_url


class BookshelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bookshelf
        fields = ('name',)


class FormatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Format
        fields = ('book', 'mime_type', 'url')


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = ('code',)


class PersonSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ('name', 'birth_year', 'death_year')

    def get_name(self, person):
        return clean_author_name(person.name)


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ('name',)


class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Summary
        fields = ('book', 'text')


class BookSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    authors = PersonSerializer(many=True)
    editors = PersonSerializer(many=True)
    bookshelves = serializers.SerializerMethodField()
    formats = serializers.SerializerMethodField()
    languages = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    summaries = serializers.SerializerMethodField()
    translators = PersonSerializer(many=True)

    lookup_field = 'gutenberg_id'

    class Meta:
        model = Book
        fields = (
            'id',
            'title',
            'authors',
            'summaries',
            'editors',
            'translators',
            'subjects',
            'bookshelves',
            'languages',
            'copyright',
            'media_type',
            'formats',
            'download_count'
        )

    def get_bookshelves(self, book):
        bookshelves = [bookshelf.name for bookshelf in book.bookshelves.all()]
        bookshelves.sort()
        return bookshelves

    def get_formats(self, book):
        formats_dict = {}
        for f in book.get_formats():
            url = f.url
            if f.mime_type == 'image/jpeg':
                if 's3.amazonaws.com' in url or 'bucketeer' in url:
                    # Generate secure presigned URL for private S3 cover image
                    s3_key = f'covers/{book.gutenberg_id}_cover.jpg'
                    url = get_presigned_download_url(s3_key)
                else:
                    # Gutenberg mirror URL — trigger background caching
                    from books.cover_cacher import cache_cover_in_background
                    cache_cover_in_background(book.gutenberg_id, f.url, f.id)
            formats_dict[f.mime_type] = url
        return formats_dict

    def get_id(self, book):
        return book.gutenberg_id

    def get_title(self, book):
        return clean_title(book.title)

    def get_languages(self, book):
        langs = [get_full_language_name(lang.code) for lang in book.languages.all()]
        langs.sort()
        return langs

    def get_subjects(self, book):
        cleaned = [clean_subject(subject.name) for subject in book.subjects.all()]
        # Filter out empty strings/None
        cleaned = [c for c in cleaned if c]
        # Remove duplicates
        cleaned = list(set(cleaned))
        cleaned.sort()
        return cleaned

    def get_summaries(self, book):
        summaries = [summary.text for summary in book.get_summaries()]
        if not summaries:
            author = book.authors.first()
            author_name = author.name if author else ''
            # Trigger background description lookup from Open Library API
            from books.summary_enricher import enrich_summary_in_background
            enrich_summary_in_background(book.gutenberg_id, clean_title(book.title), author_name)
        summaries.sort()
        return summaries
