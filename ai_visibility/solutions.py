"""
Turns the raw score into an actual plan: what to do about it, tailored to
what kind of business this is and to which specific assistants are missing
it. This is deliberately framed as general, defensible guidance rather than
a precise diagnosis -- no outside tool can see exactly why a given model
did or didn't mention a business, and that mechanism changes over time. The
value here is category-specific concreteness, not false certainty.
"""

from __future__ import annotations

# (keywords to match against the free-text category field, label used in the
# UI, ordered list of the highest-leverage actions for that kind of business)
_CATEGORY_PLAYBOOKS: list[tuple[list[str], str, list[str]]] = [
    (["restaurant", "cafe", "café", "coffee", "bar", "pub", "bakery", "diner", "pizza", "food truck"], "restaurants & cafes", [
        "Complete Google Business Profile, Yelp and TripAdvisor listings with your full menu, price range, photos and current hours.",
        "Get onto delivery-app listings (UberEats/DoorDash/Menulog) if relevant -- these get scraped and cited too.",
        "Ask happy customers to leave reviews that name specific dishes, not just star ratings -- assistants latch onto specifics.",
        "Pitch local food bloggers or your city's \"best [cuisine] in [area]\" roundup articles -- these listicles are exactly the kind of page AI assistants learn to cite.",
        "Add Restaurant structured data (JSON-LD schema) to your website: cuisine, price range, opening hours.",
    ]),
    (["dentist", "dental"], "dental practices", [
        "Complete your Google Business Profile: services offered, insurance accepted, hours, photos of the practice.",
        "List on health directories relevant to your area (Healthgrades, Zocdoc, or your country's equivalent).",
        "Encourage patients to leave reviews naming specific treatments (e.g. \"root canal\", \"Invisalign\") -- generic 5-star reviews carry less signal than specific ones.",
        "Try to get featured in local \"best dentist in [suburb]\" articles or your local paper's health/wellness coverage.",
        "Add MedicalBusiness/Dentist structured data to your site.",
    ]),
    (["doctor", "physician", "clinic", "medical centre", "medical center", "gp "], "medical practices", [
        "Complete your Google Business Profile with services, hours, and accepted insurance/health funds.",
        "List on relevant local health directories.",
        "Encourage patients to review specific aspects of care (wait times, bedside manner, specific services) rather than generic ratings.",
        "Ensure your practice appears in local health directories and any hospital/network \"find a doctor\" pages that link back to you.",
        "Add MedicalBusiness structured data to your website.",
    ]),
    (["lawyer", "attorney", "legal", "law firm"], "law firms", [
        "Complete profiles on legal directories (Avvo, FindLaw, or your region's equivalent) and Google Business Profile.",
        "Get reviews that name the specific practice area handled (e.g. \"family law\", \"conveyancing\").",
        "Contribute a quote or article to local news or legal blogs covering your practice area -- press mentions get picked up broadly.",
        "Add LegalService structured data to your website listing practice areas.",
    ]),
    (["salon", "spa", "barber", "hair", "nail", "beauty"], "salons & spas", [
        "Complete Google Business Profile and booking-platform listings (Booksy, Fresha, or similar) with services and pricing.",
        "Keep an active, tagged Instagram/social presence -- image-heavy platforms get referenced in broader web content about local businesses.",
        "Ask clients for reviews naming specific services (balayage, gel manicure, etc.).",
        "Pitch local \"best salons in [area]\" style roundups.",
    ]),
    (["gym", "fitness", "yoga", "pilates", "crossfit", "personal train"], "fitness studios", [
        "Complete Google Business Profile and class-booking platform listings (Mindbody, ClassPass) with class types and schedule.",
        "Encourage reviews naming specific classes, instructors or programs.",
        "Get listed in local \"best gyms/studios in [area]\" articles.",
        "Add LocalBusiness/ExerciseGym structured data to your site.",
    ]),
    (["hotel", "motel", "resort", "accommodation", "bnb", "b&b", "inn"], "accommodation", [
        "Keep Google Business Profile, Booking.com, TripAdvisor and Expedia listings fully complete with current photos and amenities.",
        "Encourage reviews mentioning specific amenities (pool, breakfast, parking, room type).",
        "Respond to reviews -- assistants and travel platforms both weight active, responsive listings.",
        "Add Hotel/LodgingBusiness structured data to your website.",
    ]),
    (["plumb", "electric", "hvac", "roofing", "landscap", "handyman", "contractor", "builder", "renovat", "clean"], "home services / trades", [
        "Google Business Profile is the single highest-leverage thing here -- keep service area, hours and services offered complete and current.",
        "List on trade directories relevant to your country (Angi, HomeAdvisor, Thumbtack, hipages, Airtasker) and Nextdoor.",
        "Get reviews naming the specific job done and how fast you responded -- \"same-day\" and specific fixes are exactly what local-intent questions ask about.",
        "Add clear, separate service-area and service-type pages to your website (e.g. \"emergency plumber in [suburb]\") rather than one generic page.",
    ]),
    (["mechanic", "auto repair", "car repair", "tyre", "tire", "panel beat", "smash repair"], "auto repair", [
        "Complete Google Business Profile with the specific services and vehicle makes you handle.",
        "List on auto-specific directories (RepairPal, or your region's equivalent) and Yelp.",
        "Encourage reviews naming the specific repair or service done.",
        "Get featured in local \"best mechanic in [area]\" content if any exists.",
    ]),
    (["real estate", "realtor", "property agent", "estate agent"], "real estate agents", [
        "Complete your Zillow/Realtor.com/Domain/REA profile and Google Business Profile.",
        "Collect client reviews that name specific suburbs/neighbourhoods you closed deals in.",
        "Contribute local market commentary to news outlets or your own blog covering specific suburbs -- this is exactly the locally-specific content assistants draw on.",
    ]),
    (["account", "bookkeep", "tax agent", "tax prep", "financial advis"], "accounting & financial services", [
        "Complete your Google Business Profile and any relevant professional directory listing.",
        "Encourage reviews naming the specific service used (tax return, bookkeeping, BAS, SMSF, etc.).",
        "Contribute commentary to local business news covering topics in your specialty.",
    ]),
    (["vet", "veterinar", "animal hospital", "pet"], "veterinary practices", [
        "Complete Google Business Profile with services, emergency availability, and hours.",
        "List on local pet-care directories.",
        "Encourage reviews naming the specific pet care provided.",
        "Get featured in local \"best vet in [area]\" content if it exists.",
    ]),
    (["tutor", "school", "education", "training", "course", "academy"], "education & tutoring", [
        "Complete Google Business Profile with subjects/programs offered.",
        "Encourage parent/student reviews naming specific subjects or outcomes.",
        "Get listed on local parent-community forums or school-recommendation lists -- these get referenced widely.",
    ]),
]

_GENERIC_PLAYBOOK = ("local businesses", [
    "Complete and verify your Google Business Profile -- hours, services, service area and photos current.",
    "Get listed on the directories most relevant to your industry (search \"best [your category] directories\" for your country).",
    "Encourage recent reviews that name specific services or products, not just star ratings -- assistants weight specificity and recency.",
    "Try to get featured in local \"best [category] in [location]\" articles or blog roundups -- these are exactly the pages AI assistants learn to cite.",
    "Keep your name, address and phone number (NAP) identical across every listing on the web -- inconsistency is a common reason assistants under-recommend an otherwise good business.",
])

# General, deliberately hedged notes on how each assistant tends to source
# its answers. Framed as "generally"/"tends to" because the exact mechanism
# is not published and changes over time -- these are patterns worth acting
# on, not a diagnosis of exactly what happened in any one answer.
_ENGINE_MECHANISM_NOTES = {
    "Claude": "Claude typically draws on what it learned from a broad web crawl up to its training "
              "cutoff, rather than searching the live web in a normal chat. Being included on pages "
              "that get broadly crawled and cited -- established review sites, local directories, "
              "press coverage -- matters more here than very recent changes.",
    "ChatGPT": "ChatGPT can supplement its training knowledge with live web search in some modes. "
               "General SEO fundamentals (an indexable, well-linked website) plus current web mentions "
               "both help.",
    "Perplexity": "Perplexity is built around live web search with citations, so it's usually pulling "
                  "from whatever ranks well right now for a normal web search of your category and "
                  "location. Freshness and ordinary search visibility matter most here.",
    "Gemini": "Gemini is tightly integrated with Google's own index, Maps and Business Profile data. "
              "A complete, active Google Business Profile is probably the single highest-leverage thing "
              "for improving here specifically.",
    "DeepSeek": "DeepSeek answers mostly from its training data rather than a live web search in a normal "
                "chat, so like Claude it leans on being broadly present and cited across the web -- "
                "directories, review sites and press -- rather than on very recent changes.",
}

_DISCLAIMER = ("Exactly how each assistant decides what to mention isn't published and changes over "
               "time -- treat the notes above as general, defensible patterns to act on, not a precise "
               "diagnosis of this one report.")


def match_category_playbook(category: str) -> tuple[str, list[str]]:
    category_lower = (category or "").lower()
    for keywords, label, actions in _CATEGORY_PLAYBOOKS:
        if any(kw in category_lower for kw in keywords):
            return label, actions
    return _GENERIC_PLAYBOOK


def build_action_plan(category: str, by_engine: dict, mention_rate: float,
                       top_competitors: list[tuple[str, int]]) -> dict:
    label, quick_wins = match_category_playbook(category)

    engine_notes = []
    for name, stats in by_engine.items():
        total = stats.get("total", 0)
        rate = (stats["mentioned"] / total) if total else None
        underperforming = rate is not None and rate < max(mention_rate - 0.2, 0) and rate < 0.5
        note = _ENGINE_MECHANISM_NOTES.get(name)
        if not note:
            continue
        engine_notes.append({
            "provider": name,
            "mention_rate": round(rate * 100) if rate is not None else None,
            "underperforming": underperforming,
            "note": note,
        })
    # Show the assistants you're doing worst on first -- that's the useful order to read in.
    engine_notes.sort(key=lambda n: (n["mention_rate"] if n["mention_rate"] is not None else 999))

    competitor_note = None
    if top_competitors:
        leader, count = top_competitors[0]
        competitor_note = (
            f"\"{leader}\" came up most often instead of you ({count} time(s) across these checks). "
            "Worth checking whether they're listed on directories you're missing, have more recent/"
            "detailed reviews, or show up in a local \"best of\" article you don't -- that's usually "
            "the real gap, not anything about your business itself."
        )

    return {
        "category_label": label,
        "quick_wins": quick_wins,
        "engine_notes": engine_notes,
        "competitor_note": competitor_note,
        "disclaimer": _DISCLAIMER,
    }
