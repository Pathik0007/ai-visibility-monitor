"""How one raw assistant answer is read: was the business recommended,
at what rank, and who else was named."""

import pytest

from ai_visibility.analyzer import analyze_answer, names_match


@pytest.mark.parametrize("text,business,mentioned,position", [
    # spelling variants of the same business
    ("1. **Kickin'Inn** - seafood boil", "Kickin' Inn", True, 1),
    ("1. **Aces Deep Seafood** - fish", "Ace's Deep Sea Food", True, 1),
    ("I'd go with Joe’s Fish & Chips.", "Joe's Fish and Chips", True, None),
    # names containing a full stop are not split mid-name
    ("1. **Dr. Kim Dental** - gentle care\n2. **Smile Co** - cheap", "Dr. Kim Dental", True, 1),
    ("Try St. Ives Physio. It's great.", "St. Ives Physio", True, None),
    # rank comes from the item that IS the business, not one that mentions it
    ("1. **Smile Co** - like Ryde Dental but cheaper\n2. **Ryde Dental** - great", "Ryde Dental", True, 2),
    # sub-bullets are not separate recommendations
    ("1. **A Cafe**\n   - Address: 1 St\n   - Hours: 7-3\n2. **Ryde Brew** - good", "Ryde Brew", True, 2),
])
def test_mentions_and_rank(text, business, mentioned, position):
    r = analyze_answer(text, business, [])
    assert (r["mentioned"], r["position"]) == (mentioned, position)


@pytest.mark.parametrize("text", [
    "I couldn't find any information about Ryde Dental.",
    "I don't have information on Smile Co, Ryde Dental or others in the area.",
    "1. **Ryde Dental** - top pick\n2. **Smile Co** - ok\n\nNote: Ryde Dental is permanently closed.",
])
def test_negative_or_closed_is_not_a_recommendation(text):
    r = analyze_answer(text, "Ryde Dental", [])
    assert r["mentioned"] is False


@pytest.mark.parametrize("text", [
    "If you're not familiar with the area, Ryde Dental is a great choice.",
    "I'd suggest Ryde Dental, which has no reviews complaining about wait times.",
])
def test_negative_words_about_something_else_still_count(text):
    assert analyze_answer(text, "Ryde Dental", [])["mentioned"] is True


@pytest.mark.parametrize("text,business", [
    ("1. **Palace Cafe** - great", "Ace"),                         # short names need word boundaries
    ("1. **Smith Family Lawyers** - good", "Smith, Jones & Partners"),
    ("1. **Smith and Jones Plumbing** - good", "Smith & Co."),
])
def test_no_false_positive_matches(text, business):
    assert analyze_answer(text, business, [])["mentioned"] is False


def test_headings_and_tips_are_not_competitors():
    text = ("1. Best Overall\n   - **Smile Co** - great\n2. Budget Friendly\n   - **Cheap Teeth** - cheap\n\n"
            "Tips:\n- Check Google reviews before booking")
    assert analyze_answer(text, "Ryde Dental", [])["competitors_mentioned"] == ["Smile Co", "Cheap Teeth"]


def test_citation_markers_are_stripped_from_names():
    r = analyze_answer("1. **Smile Dental**[1][3] - good\n2. **Ocean Grill** - ok", "Ryde", [])
    assert r["competitors_mentioned"] == ["Smile Dental", "Ocean Grill"]


def test_names_match_is_symmetric_and_forgiving():
    assert names_match("Kickin' Inn", "Kickin'Inn")
    assert names_match("The Burger Boys", "Burger Boys")
    assert not names_match("Ace", "Palace")


@pytest.mark.parametrize("text,business,expected", [
    ("1. **Smilecare** - great", "Smilecare Pty Ltd", (True, 1)),                 # legal suffix dropped
    ("For cleaning I'd suggest Ezyclean.", "Ezyclean Pty Ltd", (True, None)),
    ("Ryde Dental Care has closed its Gladesville branch, but the Ryde clinic remains excellent.",
     "Ryde Dental Care", (True, None)),                                            # a branch closed, not the business
    ("Ryde Dental Care has closed.", "Ryde Dental Care", (False, None)),
    ("1. **Best for families** – Ryde Dental Care: gentle\n2. **Smile Co** - ok", "Ryde Dental Care", (True, 1)),
    ("I couldn't find pricing for most clinics, but Ryde Dental Care is consistently well reviewed.",
     "Ryde Dental Care", (True, None)),                                            # "but" ends the negative lead-in
])
def test_recommendations_are_not_missed(text, business, expected):
    r = analyze_answer(text, business, [])
    assert (r["mentioned"], r["position"]) == expected
