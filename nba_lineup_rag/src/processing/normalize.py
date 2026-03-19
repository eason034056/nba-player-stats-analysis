"""
normalize.py - Text Normalization Module

This module is responsible for:
1. Converting HTML to plain text
2. Cleaning special characters and redundant whitespace
3. Unifying text format (e.g., date, team names)

The goal of normalization is to ensure consistent representation for identical content,
which is important both for hash computation and vector search.

Naming conventions:
- normalize_text(): The main text normalization function
- clean_html(): Extract plain text from HTML
- normalize_whitespace(): Unify whitespace
"""

import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup


def clean_html(html: str) -> str:
    """
    Extract plain text from HTML
    
    This function will:
    1. Remove script and style tags
    2. Extract all textual content
    3. Preserve paragraph structure (newlines)
    
    Args:
        html: HTML string
    
    Returns:
        str: The extracted plain text
    
    Example usage:
        text = clean_html("<p>Hello</p><p>World</p>")
        # Returns "Hello\n\nWorld"
    """
    if not html:
        return ""
    
    # Use lxml parser
    soup = BeautifulSoup(html, "lxml")
    
    # Remove script, style, nav, header, footer, aside tags
    # Content within these tags is not part of the article
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        # decompose() completely removes the tag and its content
        tag.decompose()
    
    # Convert <br> tags to newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")
    
    # Add newlines before and after paragraph and heading tags
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    
    # Extract all text
    text = soup.get_text()
    
    return text


def normalize_whitespace(text: str) -> str:
    """
    Unify whitespace characters
    
    1. Replace all kinds of whitespace (tab, full-width space, etc.) with normal spaces
    2. Collapse consecutive spaces into a single space
    3. Collapse consecutive newlines to a maximum of two
    4. Remove leading and trailing spaces from each line
    
    Args:
        text: Raw text
    
    Returns:
        str: Normalized text
    """
    if not text:
        return ""
    
    # Replace various whitespace with normal space
    # \u00a0 is non-breaking space
    # \u3000 is full-width space
    text = text.replace("\u00a0", " ")
    text = text.replace("\u3000", " ")
    text = text.replace("\t", " ")
    
    # Change Windows newlines to Unix newlines
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")
    
    # Remove leading and trailing space from every line
    lines = [line.strip() for line in text.split("\n")]
    
    # Filter empty lines, but keep only single blank lines between paragraphs
    result_lines = []
    prev_empty = False
    for line in lines:
        if line:
            result_lines.append(line)
            prev_empty = False
        elif not prev_empty:
            result_lines.append("")
            prev_empty = True
    
    text = "\n".join(result_lines)
    
    # Collapse consecutive spaces into a single space
    text = re.sub(r" +", " ", text)
    
    # Collapse consecutive newlines (three or more) into two newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    return text.strip()


def normalize_unicode(text: str) -> str:
    """
    Unicode normalization
    
    Use NFKC normalization form:
    - Converts full-width characters to half-width
    - Unifies different representations with the same meaning
    
    Args:
        text: Raw text
    
    Returns:
        str: Normalized text
    
    Note:
    NFKC = Compatibility Composition
    For example:
    - '１２３' -> '123'
    - 'ﬁ' -> 'fi'
    """
    if not text:
        return ""
    
    return unicodedata.normalize("NFKC", text)


def clean_special_chars(text: str) -> str:
    """
    Clean special characters
    
    Remove or replace special characters that may interfere with processing
    
    Args:
        text: Raw text
    
    Returns:
        str: Cleaned text
    """
    if not text:
        return ""
    
    # Remove zero-width characters
    # \u200b: zero-width space
    # \u200c: zero-width non-joiner
    # \u200d: zero-width joiner
    # \ufeff: byte order mark
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    
    # Remove control characters (except newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    
    return text


def normalize_text(text: str, source_is_html: bool = False) -> str:
    """
    Main text normalization function
    
    This is the main interface. It performs all normalization steps in order.
    
    Args:
        text: Raw text
        source_is_html: Whether the input is HTML
    
    Returns:
        str: Fully normalized text
    
    Example usage:
        # To handle HTML
        clean = normalize_text("<p>Hello  World</p>", source_is_html=True)
        # Returns "Hello World"
        
        # To handle plain text
        clean = normalize_text("Hello   World\\n\\n\\n")
        # Returns "Hello World"
    
    Processing steps:
    1. If HTML, convert to plain text first
    2. Unicode normalization
    3. Clean special characters
    4. Unify whitespace
    """
    if not text:
        return ""
    
    # 1. Convert HTML to plain text
    if source_is_html:
        text = clean_html(text)
    
    # 2. Unicode normalization
    text = normalize_unicode(text)
    
    # 3. Clean special characters
    text = clean_special_chars(text)
    
    # 4. Unify whitespace
    text = normalize_whitespace(text)
    
    return text


def normalize_for_hash(text: str) -> str:
    """
    Aggressive normalization for hash computation
    
    Stricter than general normalization to ensure the same content gives the same hash
    
    Args:
        text: Raw text
    
    Returns:
        str: Normalized text (all whitespace collapsed to single spaces)
    """
    text = normalize_text(text)
    # Collapse all whitespace (including newlines) into single spaces
    text = " ".join(text.split())
    return text.lower()

