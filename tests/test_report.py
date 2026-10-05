"""Rolling many answers into a score: failed calls must never look like
'not mentioned', and one business written two ways is one competitor."""

from ai_visibility.report import build_report


def _r(provider, mentioned, comps=(), error=False, position=None):
    return {"provider": provider, "query": "q", "mentioned": mentioned, "position": position,
            "competitors_mentioned": list(comps), "is_demo": False, "error": error, "raw_text": ""}


def test_errors_are_excluded_from_the_score():
    rep = build_report("Ryde Dental", "dentist", [], [_r("Claude", True), _r("Gemini", False, error=True)])
    assert rep["visibility_score"] == 100
    assert rep["error_count"] == 1


def test_failed_engine_is_not_called_weak():
    results = [_r("Claude", True), _r("ChatGPT", True), _r("Perplexity", False), _r("Gemini", False, error=True)]
    recs = " ".join(build_report("Ryde Dental", "dentist", [], results)["recommendations"])
    assert "Gemini" not in recs


def test_all_failed_gives_no_score_and_no_generic_advice():
    rep = build_report("X", "cafe", [], [_r("Claude", False, error=True), _r("Gemini", False, error=True)])
    assert rep["visibility_score"] is None
    assert len(rep["recommendations"]) == 1 and "try again" in rep["recommendations"][0]


def test_competitor_spelling_variants_are_merged():
    results = [_r("Claude", False, ["Kickin' Inn"]), _r("ChatGPT", False, ["Kickin'Inn"]),
               _r("Gemini", False, ["Ocean Grill"])]
    top = build_report("Ace's", "seafood", [], results)["top_competitors"]
    assert top[0] == ("Kickin' Inn", 2)
