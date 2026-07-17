from django.db.models import Q
from django.http import JsonResponse
from django.views import View

from rest_framework import exceptions as drf_exceptions, viewsets

from books.models import *
from books.serializers import *

import re

def get_search_matching_book_ids(search_string):
    """Finds book IDs that match the search string by querying each field/relationship
    separately. This avoids massive PostgreSQL OR joins on multiple relations, which
    causes timeouts on large datasets.
    """
    if not search_string:
        return None

    # Split on any non-alphanumeric characters (including punctuation, hyphens, and whitespace)
    # This automatically strips SQL injection characters and punctuation.
    raw_terms = [t for t in re.split(r'[^\w]+', search_string) if t]
    
    # Filter out extremely short terms (1 character) if there are longer terms to prevent massive scans
    if len(raw_terms) > 1:
        terms = [t for t in raw_terms if len(t) > 1]
        if not terms:
            terms = raw_terms
    else:
        terms = raw_terms

    if not terms:
        return None

    final_ids = None

    for term in terms[:5]:  # limit the number of terms to prevent CPU abuse
        term_ids = set()

        # 1. Matching titles
        term_ids.update(Book.objects.filter(title__icontains=term).values_list('id', flat=True))

        # 2. Matching authors
        term_ids.update(Book.objects.filter(authors__name__icontains=term).values_list('id', flat=True))

        # 3. Matching summaries
        term_ids.update(Book.objects.filter(summaries__text__icontains=term).values_list('id', flat=True))

        # 4. Matching subjects
        term_ids.update(Book.objects.filter(subjects__name__icontains=term).values_list('id', flat=True))

        # 5. Matching bookshelves
        term_ids.update(Book.objects.filter(bookshelves__name__icontains=term).values_list('id', flat=True))

        if final_ids is None:
            final_ids = term_ids
        else:
            final_ids.intersection_update(term_ids)

        if not final_ids:
            break

    return list(final_ids) if final_ids is not None else []


class BookViewSet(viewsets.ModelViewSet):
    """ This is an API endpoint that allows books to be viewed. """

    lookup_field = 'gutenberg_id'

    queryset = Book.objects.exclude(download_count__isnull=True).exclude(title__isnull=True).prefetch_related(
        'authors', 'editors', 'translators', 'languages', 'bookshelves', 'subjects'
    )

    serializer_class = BookSerializer

    def get_queryset(self):
        queryset = self.queryset

        sort = self.request.GET.get('sort')
        if sort == 'ascending':
            queryset = queryset.order_by('id')
        elif sort == 'descending':
            queryset = queryset.order_by('-id')
        else:
            queryset = queryset.order_by('-download_count')

        author_year_end = self.request.GET.get('author_year_end')
        try:
            author_year_end = int(author_year_end)
        except:
            author_year_end = None
        if author_year_end is not None:
            queryset = queryset.filter(
                Q(authors__birth_year__lte=author_year_end) |
                Q(authors__death_year__lte=author_year_end)
            )

        author_year_start = self.request.GET.get('author_year_start')
        try:
            author_year_start = int(author_year_start)
        except:
            author_year_start = None
        if author_year_start is not None:
            queryset = queryset.filter(
                Q(authors__birth_year__gte=author_year_start) |
                Q(authors__death_year__gte=author_year_start)
            )

        copyright_parameter = self.request.GET.get('copyright')
        if copyright_parameter is not None:
            copyright_strings = copyright_parameter.split(',')
            copyright_values = set()
            for copyright_string in copyright_strings:
                if copyright_string == 'true':
                    copyright_values.add(True)
                elif copyright_string == 'false':
                    copyright_values.add(False)
                elif copyright_string == 'null':
                    copyright_values.add(None)
            for value in [True, False, None]:
                if value not in copyright_values:
                    queryset = queryset.exclude(copyright=value)

        id_string = self.request.GET.get('ids')
        if id_string is not None:
            ids = id_string.split(',')

            try:
                ids = [int(id) for id in ids]
            except ValueError:
                pass
            else:
                queryset = queryset.filter(gutenberg_id__in=ids)

        language_string = self.request.GET.get('languages')
        if language_string is not None:
            language_codes = [code.lower() for code in language_string.split(',')]
            queryset = queryset.filter(languages__code__in=language_codes)

        mime_type = self.request.GET.get('mime_type')
        if mime_type is not None:
            queryset = queryset.filter(format__mime_type__startswith=mime_type)

        search_string = self.request.GET.get('search')
        if search_string is not None:
            matching_ids = get_search_matching_book_ids(search_string)
            if matching_ids is not None:
                queryset = queryset.filter(id__in=matching_ids)

        topic = self.request.GET.get('topic')
        if topic is not None:
            queryset = queryset.filter(
                Q(bookshelves__name__icontains=topic) | Q(subjects__name__icontains=topic)
            )

        return queryset.distinct()


class LanguageViewSet(viewsets.ReadOnlyModelViewSet):
    """Exposes all available languages for UI filter dropdowns."""
    queryset = Language.objects.all().order_by('code')
    serializer_class = LanguageSerializer
    pagination_class = None  # Typically <100 languages, no paging needed


class BookshelfViewSet(viewsets.ReadOnlyModelViewSet):
    """Exposes all bookshelves for navigation categories."""
    queryset = Bookshelf.objects.all().order_by('name')
    serializer_class = BookshelfSerializer
    pagination_class = None


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    """Exposes all subjects for topic exploration."""
    queryset = Subject.objects.all().order_by('name')
    serializer_class = SubjectSerializer


class SearchSuggestView(View):
    """Exposes rapid search suggestions for search-as-you-type input.

    Returns the top 10 matching books sorted by download popularity.
    """

    def get(self, request):
        query = request.GET.get('q', '').strip()
        if len(query) < 2:
            return JsonResponse([], safe=False)

        # Retrieve top 10 matching books using optimized queries
        matching_ids = get_search_matching_book_ids(query)
        if matching_ids is not None:
            books = Book.objects.filter(id__in=matching_ids).prefetch_related(
                'authors', 'editors', 'translators', 'languages', 'bookshelves', 'subjects', 'summaries'
            ).order_by('-download_count')[:10]
        else:
            books = []

        suggestions = []
        q_lower = query.lower()
        for book in books:
            # Determine which field matched first (in order of priority: title, author, summary, subject, bookshelf)
            match_field = 'title'
            if book.title and q_lower in book.title.lower():
                match_field = 'title'
            elif any(author.name and q_lower in author.name.lower() for author in book.authors.all()):
                match_field = 'author'
            elif any(summary.text and q_lower in summary.text.lower() for summary in book.summaries.all()):
                match_field = 'summary'
            elif any(subj.name and q_lower in subj.name.lower() for subj in book.subjects.all()):
                match_field = 'subject'
            elif any(shelf.name and q_lower in shelf.name.lower() for shelf in book.bookshelves.all()):
                match_field = 'bookshelf'

            primary_author = book.authors.first()
            author_name = primary_author.name if primary_author else None

            suggestions.append({
                'gutenberg_id': book.gutenberg_id,
                'title': book.title,
                'author': author_name,
                'match_field': match_field,
                'book': BookSerializer(book, context={'request': request}).data
            })

        return JsonResponse(suggestions, safe=False)


