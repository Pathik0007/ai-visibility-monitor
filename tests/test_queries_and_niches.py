"""The questions we ask, and which business niche a category falls in."""

import pytest

import niches
from ai_visibility.query_generator import generate_queries


@pytest.mark.parametrize("category,expected", [
    ("dentist", "dentist"), ("thai restaurant", "restaurant"), ("indian", "restaurant"),
    ("nail salon", "beauty"), ("thai massage", "beauty"), ("day spa", "beauty"),
    ("wedding venue", "venue"), ("tax agent", "finance"), ("plant nursery", "retail"),
    ("indian grocery store", "retail"), ("japanese language school", "tutoring"),
    ("chinese medicine", "allied"),
    # look-alike words that used to be misfiled
    ("taxi service", None), ("innovation consultant", None), ("co-working space", None),
    ("veteran car restorer", None), ("automation consultant", None), ("wedding photographer", None),
])
def test_niche_classification(category, expected):
    n = niches.niche_for(category)
    assert (n and n["key"]) == expected


def test_place_names_with_repeated_words_survive():
    qs = generate_queries("X", "dentist", "Wagga Wagga, NSW", 6)
    assert all("Wagga Wagga" in q for q in qs)


def test_grammar_fixes():
    qs = " ".join(generate_queries("X", "accountant", "Sydney", 12) + generate_queries("X", "emergency plumber", "Ryde", 8))
    assert "a accountant" not in qs and "a emergency" not in qs
    assert "emergency emergency" not in qs.lower()


def test_never_names_the_business():
    assert not any("Riverside Dental" in q for q in generate_queries("Riverside Dental", "dentist", "Sydney", 10))


def test_count_is_respected():
    assert len(generate_queries("B", "cafe", "Sydney", 4)) == 4
