"""
Project and Plex folder names.

A project is called "Title (Year)", the way Plex expects films. Titles come from the user,
so they are turned into names that are valid folder names on Linux, Windows and macOS and
cannot point outside the import or library folder.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Characters Windows does not allow in file names; "/" and "\" would also leave the folder.
_FORBIDDEN = re.compile(r'[<>"|?*\x00-\x1f]')
_SEPARATORS = re.compile(r"[\\/]+")
_SPACES = re.compile(r"\s+")
# Names Windows reserves for devices, also with an extension
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)
_FOLDER = re.compile(r"^(.+?)\s*\((\d{4})\)$")

MAX_TITLE_LENGTH = 120
MIN_YEAR = 1900
MAX_YEAR = 2100


class InvalidName(ValueError):
    """A title or year that cannot become a folder name; the message is shown to the user."""


def clean_title(title: str) -> str:
    """
    Turns a title into a folder-safe one: "Urlaub: Rom / Neapel" -> "Urlaub - Rom - Neapel".

    Raises InvalidName if nothing usable is left.
    """
    text = (title or "").strip()
    text = re.sub(r"\.{2,}", "", text)  # ".." could only mean "the folder above"
    text = text.replace(":", " -")
    text = _SEPARATORS.sub(" - ", text)
    text = _FORBIDDEN.sub("", text)
    text = _SPACES.sub(" ", text).strip()
    # Windows drops trailing dots and spaces; leading dots make hidden folders
    text = text.strip(" .-")
    if len(text) > MAX_TITLE_LENGTH:
        text = text[:MAX_TITLE_LENGTH].rstrip(" .-")
    if not re.search(r"\w", text) or _RESERVED.match(text):
        raise InvalidName("Please enter a title with letters or digits.")
    return text


def clean_year(year: Optional[str], required: bool = True) -> str:
    """A four-digit year between 1900 and 2100, or "" if not required and empty."""
    text = (str(year) if year is not None else "").strip()
    if not text:
        if required:
            raise InvalidName("Please enter the year as four digits, for example 2003.")
        return ""
    if not re.fullmatch(r"\d{4}", text) or not (MIN_YEAR <= int(text) <= MAX_YEAR):
        raise InvalidName(f"The year has to be four digits between {MIN_YEAR} and {MAX_YEAR}, for example 2003.")
    return text


def movie_folder_name(title: str, year: Optional[str], year_required: bool = True) -> str:
    """'Title (Year)', or 'Title' if the year may be empty and is."""
    clean = clean_title(title)
    y = clean_year(year, required=year_required)
    return f"{clean} ({y})" if y else clean


def parse_movie_folder_name(folder_name: str) -> Tuple[str, str]:
    """Splits 'Title (Year)' into title and year; without a year the year is ''."""
    match = _FOLDER.match(folder_name)
    if match:
        return match.group(1).strip(), match.group(2)
    return folder_name, ""
