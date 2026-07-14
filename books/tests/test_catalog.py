import unittest
from unittest.mock import patch

from django.test import TestCase

from books.services.preprocessor import (
    clean_title,
    clean_author_name,
    clean_subject,
    get_full_language_name,
)
from books.services.summary import fetch_open_library_summary
from books.models import Book, Summary


class PreprocessingTests(TestCase):
    """Verifies that text normalization functions clean raw metadata correctly."""

    def test_clean_title(self):
        self.assertEqual(clean_title("Moby Dick; Or, The Whale"), "Moby Dick; Or, The Whale")
        self.assertEqual(clean_title("Alice's Adventures in Wonderland / by Lewis Carroll"), "Alice's Adventures in Wonderland")
        self.assertEqual(clean_title("Pride and Prejudice by Jane Austen"), "Pride and Prejudice")
        self.assertEqual(clean_title("   Ethan Frome  \n"), "Ethan Frome")

    def test_clean_author_name(self):
        self.assertEqual(clean_author_name("Carroll, Lewis"), "Lewis Carroll")
        self.assertEqual(clean_author_name("Austen, Jane"), "Jane Austen")
        self.assertEqual(clean_author_name("Forster, E. M. (Edward Morgan)"), "E. M. Forster")
        self.assertEqual(clean_author_name("Melville, Herman, 1819-1891"), "Herman Melville")
        self.assertEqual(clean_author_name("Chrétien, de Troyes, active 12th century"), "de Troyes Chrétien")

    def test_clean_subject(self):
        self.assertEqual(clean_subject("Adventure stories -- Fiction"), "Adventure stories")
        self.assertEqual(clean_subject("PR"), "")
        self.assertEqual(clean_subject("PZ"), "")
        self.assertEqual(clean_subject("Conflict of generations -- Drama"), "Conflict of generations")

    def test_language_expansion(self):
        self.assertEqual(get_full_language_name("en"), "English")
        self.assertEqual(get_full_language_name("fr"), "French")
        self.assertEqual(get_full_language_name("es"), "Spanish")
        self.assertEqual(get_full_language_name("xyz"), "XYZ")


class OpenLibraryEnricherTests(TestCase):
    """Tests summary fetcher integrations and mock API responses."""

    @patch('requests.get')
    def test_fetch_summary_success_string(self, mock_get):
        """Test fetching a summary when Open Library returns a plain string description."""
        # Mock Search response
        mock_search_response = unittest.mock.Mock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            'docs': [{'key': '/works/OL1234W'}]
        }

        # Mock Work details response
        mock_work_response = unittest.mock.Mock()
        mock_work_response.status_code = 200
        mock_work_response.json.return_value = {
            'description': 'This is a classic novel about the sea.'
        }

        # Side effects for calls to requests.get
        mock_get.side_effects = [mock_search_response, mock_work_response]
        mock_get.side_effect = lambda url, *args, **kwargs: (
            mock_search_response if 'search.json' in url else mock_work_response
        )

        summary = fetch_open_library_summary("Moby Dick", "Herman Melville")
        self.assertEqual(summary, "This is a classic novel about the sea.")

    @patch('requests.get')
    def test_fetch_summary_success_dict(self, mock_get):
        """Test fetching when Open Library returns a dictionary description."""
        mock_search_response = unittest.mock.Mock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            'docs': [{'key': '/works/OL1234W'}]
        }

        mock_work_response = unittest.mock.Mock()
        mock_work_response.status_code = 200
        mock_work_response.json.return_value = {
            'description': {
                'type': '/text/markdown',
                'value': 'Detailed description text here.'
            }
        }

        mock_get.side_effect = lambda url, *args, **kwargs: (
            mock_search_response if 'search.json' in url else mock_work_response
        )

        summary = fetch_open_library_summary("Pride and Prejudice", "Jane Austen")
        self.assertEqual(summary, "Detailed description text here.")

    @patch('requests.get')
    def test_fetch_summary_empty_docs(self, mock_get):
        """Test fetch fails gracefully when search returns no matching documents."""
        mock_search_response = unittest.mock.Mock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {'docs': []}

        mock_get.return_value = mock_search_response

        summary = fetch_open_library_summary("Nonexistent Book 12345", "No Author")
        self.assertIsNone(summary)

    @patch('requests.get')
    def test_fetch_summary_api_error(self, mock_get):
        """Test fetch fails gracefully when API returns an HTTP error code."""
        mock_search_response = unittest.mock.Mock()
        mock_search_response.status_code = 500

        mock_get.return_value = mock_search_response

        summary = fetch_open_library_summary("Moby Dick", "Herman Melville")
        self.assertIsNone(summary)
