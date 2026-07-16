from django.test import TestCase
from django.urls import reverse
from django.conf import settings

from books.models import Book, Person, Summary, Subject, Bookshelf


class SearchTests(TestCase):
    """Verifies that the books endpoint search and search suggest autocomplete APIs work holistically."""

    def setUp(self):
        # Create Authors (Person)
        self.author_shakespeare = Person.objects.create(name="William Shakespeare", birth_year=1564, death_year=1616)
        self.author_fitzgerald = Person.objects.create(name="F. Scott Fitzgerald", birth_year=1896, death_year=1940)
        self.author_dewey = Person.objects.create(name="John Dewey", birth_year=1859, death_year=1952)

        # Create Subjects
        self.subject_tragedy = Subject.objects.create(name="Tragedy")
        self.subject_american = Subject.objects.create(name="American Literature")
        self.subject_science = Subject.objects.create(name="Science")

        # Create Bookshelves
        self.shelf_classic = Bookshelf.objects.create(name="Classic Drama")
        self.shelf_philosophy = Bookshelf.objects.create(name="Philosophy")

        # Create Book 1 (Romeo and Juliet)
        self.book_romeo = Book.objects.create(
            gutenberg_id=1513,
            title="Romeo and Juliet",
            download_count=1000,
            media_type="Text"
        )
        self.book_romeo.authors.add(self.author_shakespeare)
        self.book_romeo.subjects.add(self.subject_tragedy)
        self.book_romeo.bookshelves.add(self.shelf_classic)
        Summary.objects.create(book=self.book_romeo, text="A tragic love story of Romeo and Juliet in Verona.")

        # Create Book 2 (Macbeth)
        self.book_macbeth = Book.objects.create(
            gutenberg_id=1111,
            title="Macbeth",
            download_count=800,
            media_type="Text"
        )
        self.book_macbeth.authors.add(self.author_shakespeare)
        self.book_macbeth.subjects.add(self.subject_tragedy)
        self.book_macbeth.bookshelves.add(self.shelf_classic)
        Summary.objects.create(book=self.book_macbeth, text="A dark tragedy about ambition and greed.")

        # Create Book 3 (The Great Gatsby)
        self.book_gatsby = Book.objects.create(
            gutenberg_id=64317,
            title="The Great Gatsby",
            download_count=1200,
            media_type="Text"
        )
        self.book_gatsby.authors.add(self.author_fitzgerald)
        self.book_gatsby.subjects.add(self.subject_american)
        Summary.objects.create(book=self.book_gatsby, text="A story about wealthy people in Long Island during the Roaring Twenties.")

        # Create Book 4 (The Scientific Method)
        self.book_science = Book.objects.create(
            gutenberg_id=5555,
            title="The Scientific Method",
            download_count=500,
            media_type="Text"
        )
        self.book_science.authors.add(self.author_dewey)
        self.book_science.subjects.add(self.subject_science)
        self.book_science.bookshelves.add(self.shelf_philosophy)
        Summary.objects.create(book=self.book_science, text="An essay explaining logical inquiry and scientific progress.")

        # Prepare auth header if API Key is set in settings
        self.headers = {}
        api_key = getattr(settings, 'API_KEY', None)
        if api_key:
            self.headers['HTTP_X_API_KEY'] = api_key

    def test_search_by_title(self):
        """Verify we can search books by title."""
        response = self.client.get(reverse('book-list'), {'search': 'Gatsby'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 64317)

    def test_search_by_author(self):
        """Verify we can search books by author name."""
        response = self.client.get(reverse('book-list'), {'search': 'Shakespeare'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        # Should return both Romeo and Juliet and Macbeth, sorted by download count (Romeo 1000, Macbeth 800)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], 1513)
        self.assertEqual(results[1]['id'], 1111)

    def test_search_by_summary_text(self):
        """Verify we can search books by summary text content."""
        response = self.client.get(reverse('book-list'), {'search': 'ambition'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 1111)

    def test_search_by_subject(self):
        """Verify we can search books by subject name."""
        response = self.client.get(reverse('book-list'), {'search': 'American'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 64317)

    def test_search_by_bookshelf(self):
        """Verify we can search books by bookshelf name."""
        response = self.client.get(reverse('book-list'), {'search': 'Philosophy'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 5555)

    def test_search_multiple_whitespace_terms(self):
        """Verify search handles multiple terms separated by irregular whitespace gracefully."""
        response = self.client.get(reverse('book-list'), {'search': 'William    tragedy'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        # Both terms must match (William and tragedy). Both Romeo (Shakespeare + tragedy subject) and Macbeth (Shakespeare + tragedy subject) match.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['id'], 1513)
        self.assertEqual(results[1]['id'], 1111)

    def test_search_empty_query(self):
        """Verify search with spaces/empty string does not filter out all books or fail."""
        response = self.client.get(reverse('book-list'), {'search': '   '}, **self.headers)
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        # Should return all books sorted by download count: Gatsby (1200), Romeo (1000), Macbeth (800), Science (500)
        self.assertEqual(len(results), 4)

    def test_autocomplete_suggest_title(self):
        """Verify search suggest endpoint returns enriched autocomplete suggestions matching title."""
        response = self.client.get(reverse('v1-search-suggest'), {'q': 'Rome'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['gutenberg_id'], 1513)
        self.assertEqual(data[0]['title'], "Romeo and Juliet")
        self.assertEqual(data[0]['author'], "William Shakespeare")
        self.assertEqual(data[0]['match_field'], "title")
        self.assertIn('book', data[0])
        self.assertEqual(data[0]['book']['id'], 1513)
        self.assertEqual(data[0]['book']['title'], "Romeo and Juliet")
        self.assertEqual(data[0]['book']['authors'][0]['name'], "William Shakespeare")

    def test_autocomplete_suggest_author(self):
        """Verify search suggest endpoint returns autocomplete suggestions matching author name."""
        response = self.client.get(reverse('v1-search-suggest'), {'q': 'Scott'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['gutenberg_id'], 64317)
        self.assertEqual(data[0]['title'], "The Great Gatsby")
        self.assertEqual(data[0]['author'], "F. Scott Fitzgerald")
        self.assertEqual(data[0]['match_field'], "author")
        self.assertIn('book', data[0])
        self.assertEqual(data[0]['book']['id'], 64317)

    def test_autocomplete_suggest_summary(self):
        """Verify search suggest endpoint returns autocomplete suggestions matching summary text."""
        response = self.client.get(reverse('v1-search-suggest'), {'q': 'greed'}, **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['gutenberg_id'], 1111)
        self.assertEqual(data[0]['match_field'], "summary")
        self.assertIn('book', data[0])
        self.assertEqual(data[0]['book']['id'], 1111)
