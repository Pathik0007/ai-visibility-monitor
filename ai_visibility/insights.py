"""
Turns a finished report's raw results into the short, specific read a
business owner actually needs: one headline, a few findings with real
numbers, a results grid, and a prioritised action list where every item is
tied to something that happened in *this* check (a question they were
missed on, an assistant that never named them, a competitor that out-ranked
them) -- instead of the same generic advice for everyone.

Computed from `report["results"]` alone, so it also works for reports that
were saved before this existed (see ensure_insights()).
"""

from __future__ import annotations
from collections import OrderedDict
from .query_generator import question_theme, question_category
from .solutions import match_category_playbook

# Assistants that mostly answer from training data vs. ones that search the
# live web / Google's own data in a normal chat. Hedged on purpose: the
# exact behaviour isn't published and changes.
_TRAINING_DATA_ENGINES = {"Claude", "DeepSeek"}
_ENGINE_FIX = {
    "training": ("Get cited on well-known sites",
                 "{engines} mostly {answer} from what {they} learned from the web, so {they} {favour} businesses "
                 "that appear on established directories, review sites and local press. Get listed on 3-5 "
                 "of the biggest ones for your industry and area."),
    "Gemini": ("Complete your Google Business Profile",
               "Gemini leans on Google's own data. Fill in every field of your Google Business Profile "
               "(primary + secondary categories, hours, services, photos) and reply to recent reviews."),
    "Perplexity": ("Rank for the search itself",
                   "Perplexity searches the live web and cites what ranks. Add a page to your site that "
                   "targets \"{noun} in {location}\" and get it linked from local sites."),
    "ChatGPT": ("Be findable on the open web",
                "ChatGPT mixes training data with live search. An indexable website with your services, "
                "suburb and contact details, plus current mentions on other sites, covers both."),
}

_THEME_FIX = {
    "price": ("Publish your prices",
              "You were missed on “{q}”. Assistants can only call you affordable if prices are "
              "published -- add price ranges or a menu/price list to your website and Google profile."),
    "hours": ("Show your weekend hours everywhere",
              "You were missed on “{q}”. Add Saturday/Sunday hours to your Google profile, "
              "website and directory listings, and keep them identical."),
    "reviews": ("Get more recent, detailed reviews",
                "You were missed on “{q}”. Ask recent customers for reviews that mention what "
                "they came in for -- assistants weigh recent, specific reviews, not just the star average."),
    "audience": ("Say who you're great for",
                 "You were missed on “{q}”. Say it plainly on your site and profile (e.g. "
                 "\"family-friendly\", \"same-day appointments\") -- assistants match these phrases."),
    "comparison": ("Get into comparison and “best of” articles",
                   "You were missed on “{q}”. Local roundups and comparison pages are what "
                   "assistants draw on for these -- pitch 2-3 local blogs or news sites."),
}
_DEFAULT_THEME_FIX = ("Get into local “best of” lists",
                      "You were missed on “{q}”. Aim for local \"best {noun} in {location}\" lists "
                      "and directories -- the pages assistants cite for exactly this question.")


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _short_q(q: str, limit: int = 70) -> str:
    return q if len(q) <= limit else q[: limit - 1].rstrip() + "…"


def derive_insights(report: dict, location: str = "") -> dict:
    business = report.get("business", "")
    category = report.get("category", "")
    results = report.get("results") or []
    noun = question_category(category) or "business"

    providers: list[str] = []
    for r in results:
        if r["provider"] not in providers:
            providers.append(r["provider"])

    # ---- grid: one row per question, one cell per assistant ----
    grouped: "OrderedDict[str, dict]" = OrderedDict()
    for r in results:
        row = grouped.setdefault(r["query"], {"query": r["query"], "cells": {}, "answers": []})
        row["cells"][r["provider"]] = (
            {"state": "error"} if r.get("error")
            else {"state": "hit" if r.get("mentioned") else "miss", "position": r.get("position")}
        )
        row["answers"].append(r)
    rows = []
    for row in grouped.values():
        ok = [c for c in row["cells"].values() if c["state"] != "error"]
        hits = sum(1 for c in ok if c["state"] == "hit")
        rows.append({
            "query": row["query"],
            "theme": question_theme(row["query"]),
            "cells": [row["cells"].get(p, {"state": "none"}) for p in providers],
            "hits": hits,
            "ok": len(ok),
            "answers": row["answers"],
        })

    # ---- per assistant ----
    engines = []
    for p in providers:
        rs = [r for r in results if r["provider"] == p]
        ok = [r for r in rs if not r.get("error")]
        m = sum(1 for r in ok if r.get("mentioned"))
        engines.append({
            "name": p, "mentioned": m, "total": len(ok), "errors": len(rs) - len(ok),
            "rate": round(100 * m / len(ok)) if ok else None,
            "is_demo": any(r.get("is_demo") for r in rs),
        })

    ok_results = [r for r in results if not r.get("error")]
    total_ok = len(ok_results)
    your_mentions = sum(1 for r in ok_results if r.get("mentioned"))
    score = report.get("visibility_score")

    # ---- competitors, merged case-insensitively ----
    comp_counts: "OrderedDict[str, list]" = OrderedDict()
    for r in ok_results:
        seen_here = set()  # count each business once per answer, whatever its casing
        for name in (n.strip() for n in r.get("competitors_mentioned") or []):
            key = name.lower()
            if not name or key == business.lower() or key in seen_here:
                continue
            seen_here.add(key)
            entry = comp_counts.setdefault(key, [name, 0])
            entry[1] += 1
    competitors = sorted(((n, c) for n, c in comp_counts.values()), key=lambda x: -x[1])[:6]
    leader = competitors[0] if competitors else None

    # ---- headline ----
    if score is None or not total_ok:
        headline = "No assistant returned an answer this time, so there's nothing to score yet -- try again shortly."
    elif your_mentions == 0:
        headline = f"None of the {total_ok} AI answers named {business}."
    else:
        headline = f"{business} was named in {your_mentions} of {total_ok} AI answers."

    # ---- findings (each one a concrete number from this check) ----
    findings = []
    scored = [e for e in engines if e["total"]]
    if scored and total_ok:
        best = max(scored, key=lambda e: e["rate"])
        best_all = [e["name"] for e in scored if e["rate"] == best["rate"]]
        best_txt = (f"{_join(best_all)} ({best['mentioned']}/{best['total']}"
                    f"{' each' if len(best_all) > 1 else ''})")
        zero = [e["name"] for e in scored if e["mentioned"] == 0]
        if zero and len(zero) < len(scored):
            findings.append(f"Best on {best_txt}. Never named by {_join(zero)}.")
        elif not zero:
            worst = min(scored, key=lambda e: e["rate"])
            if worst["rate"] < best["rate"]:
                findings.append(f"Best on {best_txt}, weakest on {worst['name']} "
                                f"({worst['mentioned']}/{worst['total']}).")
            else:
                findings.append(f"Every assistant named you at the same rate ({best['mentioned']}/{best['total']}).")

    if leader and total_ok:
        name, count = leader
        if count > your_mentions:
            findings.append(f"{name} was named {count} times -- {count - your_mentions} more than you.")
        else:
            findings.append(f"You were named more than any competitor (you {your_mentions}, "
                            f"next best {name} {count}).")

    missed_all = [r for r in rows if r["ok"] and r["hits"] == 0]
    if missed_all and len(missed_all) < len(rows):
        findings.append(f"No assistant named you for {len(missed_all)} of {len(rows)} questions, e.g. "
                        f"“{_short_q(missed_all[0]['query'])}”.")

    avg = report.get("avg_position")
    if avg is not None:
        if avg <= 1.5:
            findings.append(f"When named, you were usually listed first (average #{avg:.1f}).")
        else:
            findings.append(f"When named, you averaged #{avg:.1f} -- people mostly act on the first one or two.")

    errors = len(results) - total_ok
    if errors:
        findings.append(f"{errors} answer(s) failed with an API error and aren't counted in the score.")

    # ---- prioritised actions, most specific first ----
    actions = []
    used_themes = set()
    weak_rows = sorted((r for r in rows if r["ok"] and r["hits"] / r["ok"] < 0.5), key=lambda r: r["hits"])
    for r in weak_rows:
        theme = r["theme"] if r["theme"] in _THEME_FIX else "default"
        if theme in used_themes:
            continue
        used_themes.add(theme)
        title, detail = _THEME_FIX.get(theme, _DEFAULT_THEME_FIX)
        actions.append({"title": title, "detail": detail.format(q=_short_q(r["query"]), noun=noun,
                                                               location=location or "your area"),
                        "why": f"{r['hits']}/{r['ok']} named you"})
        if len(used_themes) >= 2:
            break

    if leader and leader[1] > your_mentions:
        name, count = leader
        actions.insert(0 if your_mentions == 0 else len(actions), {
            "title": f"Close the gap on {name}",
            "detail": f"{name} was named {count} times vs your {your_mentions}. Compare their Google profile "
                      f"with yours -- categories, number and recency of reviews, photos, hours -- and match "
                      f"anything they have that you don't.",
            "why": f"{count} vs {your_mentions}",
        })

    if scored:
        overall = your_mentions / total_ok if total_ok else 0
        weak = [e for e in scored if e["rate"] is not None and (e["mentioned"] == 0 or e["rate"] / 100 < overall - 0.25)]
        training = [e for e in weak if e["name"] in _TRAINING_DATA_ENGINES]
        if training:
            title, detail = _ENGINE_FIX["training"]
            one = len(training) == 1
            actions.append({"title": title, "detail": detail.format(
                                engines=_join([e["name"] for e in training]), answer="answers" if one else "answer",
                                they="it" if one else "they", favour="favours" if one else "favour"),
                            "why": ", ".join(f"{e['name']} {e['mentioned']}/{e['total']}" for e in training)})
        for e in weak:
            if e["name"] in _ENGINE_FIX and e["name"] not in _TRAINING_DATA_ENGINES:
                title, detail = _ENGINE_FIX[e["name"]]
                actions.append({"title": title, "detail": detail.format(noun=noun, location=location or "your area"),
                                "why": f"{e['name']} {e['mentioned']}/{e['total']}"})

    if score is not None and score >= 80 and not actions:
        actions.append({"title": "Hold your position",
                        "detail": "You're named in most answers. Keep reviews coming in and your hours and "
                                  "details current, and re-check monthly -- rankings shift as assistants update.",
                        "why": f"{score}% visibility"})

    label, playbook = match_category_playbook(category)
    return {
        "providers": providers,
        "rows": rows,
        "engines": engines,
        "competitors": competitors,
        "your_mentions": your_mentions,
        "total_ok": total_ok,
        "headline": headline,
        "findings": findings[:4],
        "actions": actions[:4],
        "playbook_label": label,
        "playbook": playbook,
        "all_demo": bool(results) and all(r.get("is_demo") for r in results),
    }


def ensure_insights(report: dict, location: str = "") -> dict:
    """Adds `insights` to a report dict (idempotent; works on old reports)."""
    if report and "insights" not in report:
        report["insights"] = derive_insights(report, location=location)
    return report
