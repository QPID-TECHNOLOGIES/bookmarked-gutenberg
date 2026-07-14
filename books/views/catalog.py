from django.db.models import Q
from django.http import JsonResponse
from django.views import View

from rest_framework import exceptions as drf_exceptions, viewsets

from books.models import *
from books.serializers import *


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
            search_terms = search_string.split(' ')
            for term in search_terms[:32]:
                queryset = queryset.filter(
                    Q(authors__name__icontains=term) | Q(title__icontains=term)
                )

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

        # Uses database values query for extremely light response footprint
        suggestions = list(
            Book.objects.filter(title__icontains=query)
            .order_by('-download_count')
            .values('gutenberg_id', 'title')[:10]
        )

        return JsonResponse(suggestions, safe=False)


