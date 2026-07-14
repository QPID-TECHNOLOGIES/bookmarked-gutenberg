import re

# Mapping of common 2-letter language codes to their full English names
LANGUAGE_MAP = {
    'en': 'English',
    'fr': 'French',
    'es': 'Spanish',
    'de': 'German',
    'it': 'Italian',
    'pt': 'Portuguese',
    'nl': 'Dutch',
    'sv': 'Swedish',
    'fi': 'Finnish',
    'da': 'Danish',
    'no': 'Norwegian',
    'ru': 'Russian',
    'zh': 'Chinese',
    'ja': 'Japanese',
    'la': 'Latin',
    'el': 'Greek',
    'he': 'Hebrew',
    'ar': 'Arabic',
    'eo': 'Esperanto',
}


def clean_title(title):
    """Clean up Project Gutenberg book titles.

    - Removes trailing author credits (e.g., "Title / by Author")
    - Cleans up duplicate spaces and newlines
    - Strips brackets or edition noise
    """
    if not title:
        return ''

    # Remove '/ by Author' or 'by Author'
    title = re.sub(r'\s*/\s*by\s+.*$', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s+by\s+.*$', '', title, flags=re.IGNORECASE)

    # Remove extra spaces/newlines
    title = ' '.join(title.split())

    return title.strip()


def clean_author_name(raw_name):
    """Convert Gutenberg inverted names ("Last, First") to natural format ("First Last").

    Examples:
        "Carroll, Lewis" -> "Lewis Carroll"
        "Austen, Jane" -> "Jane Austen"
        "Lewis, M. G. (Matthew Gregory)" -> "M. G. Lewis"
    """
    if not raw_name:
        return ''

    # Remove dates (e.g., "1835-1910" or "active 12th century")
    name_clean = re.sub(r',?\s*\d{4}-\d{4}', '', raw_name)
    name_clean = re.sub(r',?\s*active\s+.*$', '', name_clean, flags=re.IGNORECASE)

    # Remove parentheses notes (e.g., "(Matthew Gregory)" or "(pseudonym)")
    name_clean = re.sub(r'\s*\(.*?\)', '', name_clean)

    # Strip duplicate whitespace
    name_clean = ' '.join(name_clean.split()).strip()

    # Split by comma for inversion
    parts = [p.strip() for p in name_clean.split(',') if p.strip()]

    if len(parts) == 2:
        # "Carroll, Lewis" -> "Lewis Carroll"
        return f'{parts[1]} {parts[0]}'
    elif len(parts) > 2:
        # Keep original but reverse first two: "Lewis, M. G., other" -> "M. G. Lewis"
        return f'{parts[1]} {parts[0]}'

    return raw_name.strip()


def clean_subject(subject):
    """Normalize subject tags by stripping classification codes and subdivisions.

    Examples:
        "PR" -> None (discard raw LC codes)
        "Adventure stories -- Fiction" -> "Adventure stories"
        "Monks -- Fiction" -> "Monks"
    """
    if not subject:
        return ''

    # Discard single/double character Library of Congress codes (e.g., "PR", "PZ")
    if re.match(r'^[A-Z]{1,2}$', subject):
        return ''

    # Strip "-- Fiction" or "-- Translations into English" subdivisions
    subject_clean = re.split(r'\s*--\s*', subject)[0]

    return subject_clean.strip()


def get_full_language_name(code):
    """Convert language code to full language name (e.g. 'en' -> 'English')."""
    if not code:
        return 'Unknown'
    return LANGUAGE_MAP.get(code.lower(), code.upper())
