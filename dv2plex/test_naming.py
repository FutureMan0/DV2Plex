import pytest

from dv2plex.naming import InvalidName, clean_title, clean_year, movie_folder_name, parse_movie_folder_name


@pytest.mark.parametrize("title,expected", [
    ("Sommerurlaub", "Sommerurlaub"),
    ("  Urlaub:  Rom  ", "Urlaub - Rom"),
    ("Rom / Neapel", "Rom - Neapel"),
    ("..\\..\\etc", "etc"),
    ("Teil 1...", "Teil 1"),
    ('Anna "&" Tom?', "Anna & Tom"),
    ("Ende.", "Ende"),
])
def test_titles_become_folder_safe(title, expected):
    assert clean_title(title) == expected


@pytest.mark.parametrize("title", ["", "   ", "..", "/", "CON", "nul.txt", '?*"'])
def test_unusable_titles_are_refused(title):
    with pytest.raises(InvalidName):
        clean_title(title)


def test_long_titles_are_shortened():
    assert len(clean_title("x" * 300)) == 120


@pytest.mark.parametrize("year", ["2003", " 1999 ", "1900", "2100"])
def test_valid_years(year):
    assert clean_year(year) == year.strip()


@pytest.mark.parametrize("year", ["98", "20003", "abcd", "1899", "2101", "2003/2004"])
def test_invalid_years(year):
    with pytest.raises(InvalidName):
        clean_year(year)


def test_year_may_be_optional():
    assert clean_year("", required=False) == ""
    with pytest.raises(InvalidName):
        clean_year("")


def test_folder_name_cannot_leave_the_import_folder():
    name = movie_folder_name("../../../etc", "2003")
    assert "/" not in name and "\\" not in name
    assert not name.startswith(".")


def test_folder_name_round_trip():
    name = movie_folder_name("Hochzeit: Anna und Tom", "1999")
    assert name == "Hochzeit - Anna und Tom (1999)"
    assert parse_movie_folder_name(name) == ("Hochzeit - Anna und Tom", "1999")
    assert parse_movie_folder_name("Ohne Jahr") == ("Ohne Jahr", "")
