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
from .analyzer import names_match
import niches as _niches

_PILLAR_BY_TITLE = [
    ("Get your business onto Google Maps", "listings"), ("Fix your Google business status", "listings"),
    ("Make your details easy to find", "website"), ("Change your Google category", "listings"),
    ("Close the Google review gap", "reviews"), ("Lift your Google rating", "reviews"),
    ("Add your website to your Google profile", "listings"), ("Add your opening hours on Google", "listings"),
    ("Weekend hours", "listings"), ("Get onto the sites the assistants read", "mentions"),
    ("Publish your prices", "website"), ("Show your opening hours", "listings"),
    ("Make it obvious you take urgent", "listings"), ("Name the service", "website"),
    ("Make booking", "listings"), ("Answer your own question", "website"),
    ("Get more recent, detailed reviews", "reviews"), ("Say who you're great for", "website"),
    ("Get into comparison", "mentions"), ("Get into local", "mentions"), ("Close the gap on", "listings"),
    ("Get cited on well-known sites", "mentions"), ("Complete your Google Business Profile", "listings"),
    ("Rank for the search itself", "website"), ("Be on Bing Places", "listings"), ("Hold your position", "reviews"),
    ("Fix your website", "website"), ("Unblock AI search", "website"), ("Remove the noindex", "website"),
    ("Be listed where", "listings"), ("Fix your website's", "website"),
]


def _pillar_for(title: str) -> str:
    for prefix, pillar in _PILLAR_BY_TITLE:
        if title.startswith(prefix):
            return pillar
    return "listings"


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
    "ChatGPT": ("Be on Bing Places",
                "ChatGPT's local answers lean on Bing rather than Google Business Profile. Claim and complete "
                "Bing Places (bingplaces.com -- it can import your Google profile), and keep your website's "
                "services, suburb and hours in plain text."),
}

_THEME_FIX = {
    "price": ("Publish your prices",
              "You were missed on “{q}”. Assistants can only call you affordable if prices are "
              "published -- add price ranges or a menu/price list to your website and Google profile."),
    "hours": ("Show your opening hours everywhere",
              "You were missed on “{q}”. Put complete hours (including weekends, late nights and "
              "holidays) on Google, Bing, Apple Maps and your website -- identical everywhere."),
    "urgent": ("Make it obvious you take urgent jobs",
               "You were missed on “{q}”. Say “same-day” / “emergency” / “available today” "
               "in your Google services and business description, on your website, and keep a phone number "
               "one tap away -- assistants only suggest businesses that say they're available."),
    "specialty": ("Name the service you were missed for",
                  "You were missed on “{q}”. If you offer it, give it its own page on your website and add "
                  "it to your Google services list using the same words customers use -- assistants match exact services."),
    "booking": ("Make booking and ordering easy",
                "You were missed on “{q}”. Link online booking/ordering from Google and your website, and be on "
                "the booking or delivery platforms your customers use."),
    "custom": ("Answer your own question on your website",
               "You were missed on your question “{q}”. Add a short page or FAQ that answers it directly, "
               "mentioning your suburb -- that's the text assistants can quote."),
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
            "theme": (report.get("question_themes") or {}).get(row["query"]) or question_theme(row["query"]),
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

    # ---- competitors, merged across spelling variants ----
    # ("Kickin' Inn", "Kickin'Inn" and "Kickin' Inn Ryde" are one business)
    comp_entries: list[dict] = []
    for r in ok_results:
        seen_here = set()
        for name in (n.strip() for n in r.get("competitors_mentioned") or []):
            if not name or names_match(name, business):
                continue
            entry = next((e for e in comp_entries if names_match(name, e["name"])), None)
            if entry is None:
                entry = {"name": name, "count": 0}
                comp_entries.append(entry)
            if id(entry) in seen_here:
                continue
            seen_here.add(id(entry))
            entry["count"] += 1
    comp_entries.sort(key=lambda e: -e["count"])
    competitors = [(e["name"], e["count"]) for e in comp_entries[:6]]
    leader = competitors[0] if competitors else None

    # ---- what the assistants actually said ----
    # Only real answers are quoted: sample (demo) answers use stock phrases,
    # and quoting them back as "what assistants say" -- or building advice
    # on them -- would present made-up praise as evidence.
    real_results = [r for r in ok_results if not r.get("is_demo")]
    you_quotes, seen_q = [], set()
    for r in real_results:
        snip = (r.get("business_snippet") or "").strip()
        if r.get("mentioned") and snip and snip.lower() not in seen_q and len(you_quotes) < 3:
            seen_q.add(snip.lower())
            you_quotes.append({"provider": r["provider"], "text": snip})
    competitor_quotes = []
    for name, count in competitors[:3]:
        quotes, seen_c = [], set()
        for r in real_results:
            for d in r.get("item_details") or []:
                det = (d.get("detail") or "").strip()
                if det and len(det) > 8 and not d.get("is_you") and names_match(d.get("name", ""), name) \
                        and det.lower() not in seen_c and len(quotes) < 2:
                    seen_c.add(det.lower())
                    quotes.append({"provider": r["provider"], "text": det})
        if quotes:
            competitor_quotes.append({"name": name, "count": count, "quotes": quotes})
    negatives_all = [{"provider": r["provider"], "text": r["negative_mention"]}
                     for r in ok_results if r.get("negative_mention")]
    negatives, seen_n = [], set()  # same sentence from the same assistant shown once
    for n in negatives_all:
        key = (n["provider"], n["text"].lower())
        if key not in seen_n:
            seen_n.add(key)
            negatives.append(n)

    # ---- where the assistants got their information ----
    domains: "OrderedDict[str, dict]" = OrderedDict()
    for r in ok_results:
        seen_d = set()
        for src in r.get("sources") or []:
            dom = (src.get("domain") or "").lower()
            if not dom or "vertexaisearch" in dom or dom in seen_d:
                continue
            seen_d.add(dom)
            d = domains.setdefault(dom, {"domain": dom, "count": 0, "missed": 0,
                                         "url": src.get("url"), "title": src.get("title", "")})
            d["count"] += 1
            if not r.get("mentioned"):
                d["missed"] += 1
    sources = sorted(domains.values(), key=lambda d: (-d["count"], d["domain"]))[:8]
    answers_with_sources = sum(1 for r in ok_results if r.get("sources"))

    profiles = report.get("profiles") or {}
    you_p = profiles.get("you") if profiles.get("available") else None
    comp_p = [c for c in (profiles.get("competitors") or []) if c.get("found")] if you_p else []

    # ---- headline ----
    if score is None or not total_ok:
        headline = "No assistant returned an answer this time, so there's nothing to score yet -- try again shortly."
    elif your_mentions == 0:
        headline = f"None of the {total_ok} AI answers recommended {business}."
    else:
        headline = f"{business} was recommended in {your_mentions} of {total_ok} AI answers."

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
            findings.append(f"Best on {best_txt}. Never recommended by {_join(zero)}.")
        elif not zero:
            worst = min(scored, key=lambda e: e["rate"])
            if worst["rate"] < best["rate"]:
                findings.append(f"Best on {best_txt}, weakest on {worst['name']} "
                                f"({worst['mentioned']}/{worst['total']}).")
            else:
                findings.append(f"Every assistant recommended you at the same rate ({best['mentioned']}/{best['total']}).")

    if negatives:
        findings.append(f"{len(negatives_all)} answer(s) said the assistant couldn't find reliable information "
                        f"about you -- e.g. {negatives[0]['provider']}: “{_short_q(negatives[0]['text'], 110)}”")

    if leader and total_ok:
        name, count = leader
        if count > your_mentions:
            findings.append(f"{name} was recommended in {count} of {total_ok} answers (you: {your_mentions}).")
        else:
            findings.append(f"You were recommended more than any competitor (you {your_mentions}, "
                            f"next best {name} {count}).")

    missed_all = [r for r in rows if r["ok"] and r["hits"] == 0]
    if missed_all and len(missed_all) < len(rows):
        findings.append(f"No assistant recommended you for {len(missed_all)} of {len(rows)} questions, e.g. "
                        f"“{_short_q(missed_all[0]['query'])}”.")

    if sources:
        top = sources[0]
        findings.append(f"The page assistants leaned on most was {top['domain']} "
                        f"(cited in {top['count']} answer{'s' if top['count'] != 1 else ''}).")

    avg = report.get("avg_position")
    if avg is not None:
        if avg <= 1.5:
            findings.append(f"When recommended, you were usually listed first (average #{avg:.1f}).")
        else:
            findings.append(f"When recommended, you averaged #{avg:.1f} -- people mostly act on the first one or two.")

    errors = len(results) - total_ok
    if errors:
        findings.append(f"{errors} answer(s) failed with an API error and aren't counted in the score.")

    # ---- prioritised actions: (priority, action) -- lower runs first ----
    cands: list[tuple[int, dict]] = []
    loc = location or "your area"

    if you_p is not None and not you_p.get("found"):
        cands.append((0, {"title": "Get your business onto Google Maps",
                          "detail": f"We couldn't find “{business}” on Google Maps near {loc}. Claim and verify "
                                    "your Google Business Profile (business.google.com) using exactly this name -- "
                                    "assistants, especially Gemini, lean heavily on it.",
                          "why": "not found on Google"}))
    elif you_p and you_p.get("status") and you_p["status"] != "OPERATIONAL":
        cands.append((0, {"title": "Fix your Google business status",
                          "detail": f"Google lists you as {you_p['status'].replace('_', ' ').lower()}. If you're open, "
                                    "correct it in Google Business Profile -- assistants won't recommend a closed business.",
                          "why": you_p["status"].lower()}))

    if negatives:
        cands.append((1, {"title": "Make your details easy to find",
                          "detail": f"{_join(sorted({n['provider'] for n in negatives}))} said "
                                    f"{'it' if len({n['provider'] for n in negatives}) == 1 else 'they'} couldn't find reliable "
                                    f"information about you. Make sure your website states your name, suburb, what you "
                                    f"do and your hours in plain text, and that the same details appear on Google "
                                    f"and the main directories.",
                          "why": f"{len(negatives_all)} “couldn't find” answer{'s' if len(negatives_all) != 1 else ''}"}))

    if you_p and you_p.get("found") and comp_p:
        # Category the recommended competitors use vs yours.
        cats = [c.get("category") for c in comp_p if c.get("category")]
        common = max(set(cats), key=cats.count) if cats else None
        if common and you_p.get("category") and common.lower() != you_p["category"].lower() and cats.count(common) >= 2:
            cands.append((1, {"title": f"Change your Google category to “{common}”",
                              "detail": f"Your Google primary category is “{you_p['category']}”, but "
                                        f"{cats.count(common)} of the businesses assistants recommend instead use "
                                        f"“{common}”. If it fits what you do, make it your primary category "
                                        f"and keep yours as a secondary one.",
                              "why": "category mismatch"}))
        top_rev = max(comp_p, key=lambda c: c.get("reviews") or 0)
        mine = you_p.get("reviews") or 0
        if (top_rev.get("reviews") or 0) >= max(20, mine * 1.5):
            gap = top_rev["reviews"] - mine
            cands.append((2, {"title": "Close the Google review gap",
                              "detail": f"{top_rev['name']} has {top_rev['reviews']:,} Google reviews"
                                        f"{' (' + format(top_rev['rating'], '.1f') + '★)' if top_rev.get('rating') else ''}; "
                                        f"you have {mine:,}{' (' + format(you_p['rating'], '.1f') + '★)' if you_p.get('rating') else ''}. "
                                        f"Ask every happy customer for a review (a QR code at the counter and a follow-up "
                                        f"text work best) and aim for a steady 5-10 new ones a month.",
                              "why": f"{gap:,} fewer reviews"}))
        better = [c for c in comp_p if c.get("rating") and you_p.get("rating") and c["rating"] - you_p["rating"] >= 0.3]
        if better:
            b = max(better, key=lambda c: c["rating"])
            cands.append((3, {"title": "Lift your Google rating",
                              "detail": f"You're at {you_p['rating']:.1f}★ vs {b['name']} at {b['rating']:.1f}★. "
                                        "Reply to every recent negative review and fix the complaint that repeats most "
                                        "-- assistants often summarise reviews when choosing who to recommend.",
                              "why": f"{you_p['rating']:.1f} vs {b['rating']:.1f}★"}))
        if not you_p.get("website") and any(c.get("website") for c in comp_p):
            cands.append((2, {"title": "Add your website to your Google profile",
                              "detail": "Your Google listing has no website, while the competitors being recommended "
                                        "do. Add one (even a simple one-page site with your services, suburb and hours).",
                              "why": "no website listed"}))
        weekend_open = [c for c in comp_p if c.get("open_sat") or c.get("open_sun")]
        if not you_p.get("hours_listed"):
            cands.append((2, {"title": "Add your opening hours on Google",
                              "detail": "Your Google listing shows no opening hours. Assistants answering "
                                        "“who's open now / on weekends” skip businesses with unknown hours.",
                              "why": "no hours listed"}))
        elif weekend_open and not (you_p.get("open_sat") or you_p.get("open_sun")):
            cands.append((4, {"title": "Weekend hours",
                              "detail": f"{_join([c['name'] for c in weekend_open[:2]])} list weekend hours on Google; "
                                        "you don't. If you open on weekends, add it -- if not, expect to miss "
                                        "“open on weekends” questions.",
                              "why": "weekend questions"}))

    if sources:
        missed_src = [d for d in sources if d["missed"]] or sources
        top3 = missed_src[:3]
        cands.append((2, {"title": "Get onto the sites the assistants read",
                          "detail": "These pages were cited in answers that " + ("didn't recommend you: " if missed_src is not sources else "you appeared in: ")
                                    + ", ".join(f"{d['domain']} ({d['count']}×)" for d in top3)
                                    + ". Claim or create your listing on each, keep details identical to Google, and "
                                      "ask customers to review you there.",
                          "why": f"{sum(d['count'] for d in top3)} citations"}))

    used_themes = set()
    weak_rows = sorted((r for r in rows if r["ok"] and r["hits"] / r["ok"] < 0.5), key=lambda r: r["hits"])
    for r in weak_rows:
        theme = r["theme"] if r["theme"] in _THEME_FIX else "default"
        if theme in used_themes:
            continue
        used_themes.add(theme)
        title, detail = _THEME_FIX.get(theme, _DEFAULT_THEME_FIX)
        cands.append((3, {"title": title, "detail": detail.format(q=_short_q(r["query"], 90), noun=noun, location=loc),
                          "why": f"{r['hits']}/{r['ok']} recommended you"}))
        if len(used_themes) >= 3:
            break

    if leader and leader[1] > your_mentions and not comp_p and not leader[0].lower().startswith("sample rival"):
        name, count = leader
        praise = next((cq["quotes"][0]["text"] for cq in competitor_quotes if cq["name"] == name), None)
        detail = (f"{name} was recommended in {count} answers vs your {your_mentions}. "
                  + (f"Assistants describe them as “{_short_q(praise, 100)}” -- if you offer something "
                     f"comparable, say so in the same words on your Google profile and website. " if praise else "")
                  + "Compare their Google listing with yours: category, number and recency of reviews, photos, hours.")
        cands.append((2 if your_mentions == 0 else 3, {"title": f"Close the gap on {name}", "detail": detail,
                                                       "why": f"{count} vs {your_mentions}"}))

    if scored:
        overall = your_mentions / total_ok if total_ok else 0
        weak = [e for e in scored if e["rate"] is not None and (e["mentioned"] == 0 or e["rate"] / 100 < overall - 0.25)]
        training = [e for e in weak if e["name"] in _TRAINING_DATA_ENGINES]
        if training:
            title, detail = _ENGINE_FIX["training"]
            one = len(training) == 1
            cands.append((4, {"title": title, "detail": detail.format(
                                  engines=_join([e["name"] for e in training]), answer="answers" if one else "answer",
                                  they="it" if one else "they", favour="favours" if one else "favour"),
                              "why": ", ".join(f"{e['name']} {e['mentioned']}/{e['total']}" for e in training)}))
        for e in weak:
            if e["name"] in _ENGINE_FIX and e["name"] not in _TRAINING_DATA_ENGINES:
                title, detail = _ENGINE_FIX[e["name"]]
                cands.append((4, {"title": title, "detail": detail.format(noun=noun, location=loc),
                                  "why": f"{e['name']} {e['mentioned']}/{e['total']}"}))

    if score is not None and score >= 80 and not cands:
        cands.append((5, {"title": "Hold your position",
                          "detail": "You're recommended in most answers. Keep reviews coming in and your hours and "
                                    "details current -- rankings shift as assistants update.",
                          "why": f"{score}% visibility"}))

    # ---- website (from the website check, when a site was given) ----
    website = report.get("website")
    if website and website.get("ok"):
        failed = {c["key"]: c for c in website.get("checks", []) if c["status"] == "fail"}
        if "ai_crawlers" in failed:
            cands.append((0, {"title": "Unblock AI search on your website",
                              "detail": failed["ai_crawlers"]["detail"] + ". " + failed["ai_crawlers"]["fix"],
                              "why": "robots.txt"}))
        if "indexable" in failed:
            cands.append((0, {"title": "Remove the noindex tag from your website",
                              "detail": failed["indexable"]["fix"], "why": "site hidden"}))
        rest = [c for k, c in failed.items() if k not in ("ai_crawlers", "indexable") and c["weight"] >= 4]
        if rest:
            rest.sort(key=lambda c: -c["weight"])
            cands.append((2, {"title": f"Fix your website's {len(rest)} gap{'s' if len(rest) != 1 else ''} for AI",
                              "detail": " ".join(f"{c['label']}: {c['fix']}" for c in rest[:3]),
                              "why": f"website {website['score']}/100"}))
    elif website and not website.get("ok"):
        cands.append((1, {"title": "Fix your website so it loads",
                          "detail": f"We couldn't check your site: {website.get('error')} If the address is right and it "
                                    f"opens fine for you, try the free website check again later -- otherwise AI crawlers "
                                    f"are hitting the same problem.", "why": "website"}))

    # ---- where this kind of business must be listed ----
    country = (report.get("location_context") or {}).get("country")
    niche = _niches.niche_for(noun)
    niche_platforms = _niches.platforms_for(niche, country)
    core_names = [p["name"] for p in _niches.CORE_PLATFORMS]
    cands.append((3, {"title": f"Be listed where {(niche or {}).get('label', 'customers').lower()} customers look",
                      "detail": "Same name, address, phone, hours and categories on: " + ", ".join(core_names)
                                + (" -- plus " + ", ".join(p["name"] for p in niche_platforms[:3]) if niche_platforms else "")
                                + ". Each assistant reads different ones (Gemini → Google, ChatGPT → Bing, Siri → Apple).",
                      "why": "listings"}))

    seen_titles, actions = set(), []
    for _prio, a in sorted(cands, key=lambda x: x[0]):
        if a["title"] in seen_titles:
            continue
        seen_titles.add(a["title"])
        a["pillar"] = _niches.PILLARS[_pillar_for(a["title"])]
        actions.append(a)

    # ---- the three things assistants rely on: status per pillar ----
    pillars = []
    if you_p is not None and you_p.get("found"):
        issues = sum(1 for k in ("website", "hours_listed") if not you_p.get(k))
        pillars.append({"key": "listings", "label": "Google profile", "status": "good" if not issues else "warn",
                        "detail": (you_p.get("category") or "Listed") + (" · missing " + ", ".join(
                            x for x, k in (("website", "website"), ("hours", "hours_listed")) if not you_p.get(k)) if issues else " · complete")})
        top = max(comp_p, key=lambda c: c.get("reviews") or 0) if comp_p else None
        mine = you_p.get("reviews") or 0
        ok_rev = not top or mine >= 0.7 * (top.get("reviews") or 0)
        pillars.append({"key": "reviews", "label": "Reviews", "status": "good" if ok_rev else "bad",
                        "detail": f"{mine:,} reviews" + (f" · {you_p['rating']:.1f}★" if you_p.get("rating") else "")
                                  + (f" (top competitor {top['reviews']:,})" if top else "")})
    elif you_p is not None:
        pillars.append({"key": "listings", "label": "Google profile", "status": "bad", "detail": "Not found on Google Maps"})
        pillars.append({"key": "reviews", "label": "Reviews", "status": "na", "detail": "No Google listing found"})
    else:
        pillars.append({"key": "listings", "label": "Google profile", "status": "na", "detail": "Compared on Pro"})
        pillars.append({"key": "reviews", "label": "Reviews", "status": "na", "detail": "Compared on Pro"})
    if website and website.get("ok"):
        ws = website["score"]
        pillars.append({"key": "website", "label": "Website", "status": "good" if ws >= 80 else "warn" if ws >= 50 else "bad",
                        "detail": f"{ws}/100 AI-readiness"})
    elif website:
        pillars.append({"key": "website", "label": "Website", "status": "bad", "detail": "Couldn't load"})
    else:
        pillars.append({"key": "website", "label": "Website", "status": "na", "detail": "Add your website to check it"})

    label, playbook = match_category_playbook(category)
    return {
        "providers": providers,
        "rows": rows,
        "engines": engines,
        "competitors": competitors,
        "your_mentions": your_mentions,
        "total_ok": total_ok,
        "headline": headline,
        "findings": findings[:5],
        "actions": actions[:6],
        "you_quotes": you_quotes,
        "competitor_quotes": competitor_quotes,
        "negatives": negatives[:3],
        "sources": sources,
        "answers_with_sources": answers_with_sources,
        "profiles": {"you": you_p, "competitors": comp_p} if you_p else None,
        "profiles_status": profiles.get("reason") if profiles and not profiles.get("available") else None,
        "live_search_engines": sorted({r["provider"] for r in ok_results if r.get("live_search")}),
        "competitor_flags": report.get("competitor_flags") or [],
        "category_note": report.get("category_note"),
        "playbook_label": (niche or {}).get("label") or label,
        "playbook": playbook if not niche else [],
        "niche_fixes": [{"pillar": _niches.PILLARS[p], "text": t.format(noun=noun, location=loc)}
                        for p, t in (niche or {}).get("fixes", [])],
        "platforms": [dict(p, core=True) for p in _niches.CORE_PLATFORMS] + niche_platforms,
        "pillars": pillars,
        "website": website,
        "all_demo": bool(results) and all(r.get("is_demo") for r in results),
    }


def ensure_insights(report: dict, location: str = "") -> dict:
    """Adds `insights` to a report dict (idempotent; works on old reports)."""
    if report and "insights" not in report:
        report["insights"] = derive_insights(report, location=location)
    return report
