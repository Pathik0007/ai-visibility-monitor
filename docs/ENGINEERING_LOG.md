# Engineering log

A pass-by-pass record of what was found and fixed while taking AI Visibility
Monitor from prototype to a live, multi-worker deployment on Render. Each
"pass" was driven by something concrete: a code audit, a bug seen on the
live site, or a real report reviewed with a business owner.

The most recent pass is at the bottom.

## First pass: fixes applied for going live

A pass specifically looking for correctness, performance and security
issues turned up (and fixed) these:

- **Score-deflation bug** -- a failed API call (network blip, bad key) used
  to count as "not mentioned," silently lowering a business's score for a
  reason unrelated to its real visibility. Errors are now excluded from
  scoring and surfaced separately in the report.
- **Latency** -- provider calls (up to 4 assistants x up to 10 questions =
  40 calls) ran one at a time; a real check could take a minute or more.
  They now run concurrently on a thread pool, so wall-clock time is closer
  to the slowest single call instead of the sum of all of them.
- **Misleading rankings** -- a business mentioned in a prose-style answer
  (no numbered list) used to be reported as "position #1" by a fallback
  guess. It now correctly shows as "mentioned, unranked" instead of a
  fabricated position.
- **Cost-abuse / DoS risk** -- once real API keys are added, the anonymous
  check and the "run now" button both call paid external APIs with no
  limit. Added rate limits (5/hour anonymous checks per IP, 6/hour manual
  reruns per user, 10/hour signup & login attempts).
- **CSRF** -- all POST forms (signup, login, add business, run check) now
  carry a CSRF token (Flask-WTF); the Stripe webhook is exempted since it
  authenticates via Stripe's own signature instead.
- **Debug mode / secrets** -- `debug=True` (a remote-code-execution risk if
  ever exposed) is now off unless explicitly enabled and never in
  production; the app refuses to start in production with the placeholder
  dev secret key instead of silently running insecurely.
- **Input validation** -- business/category/location/competitor fields now
  have length and count limits, enforced server-side (not just in the
  browser).
- **SEO fundamentals** -- the landing page was missing a viewport tag
  (breaks mobile rendering, and mobile-friendliness is a ranking factor),
  a meta description, and Open Graph tags; added those plus `robots.txt`
  and `sitemap.xml`, and marked account/report pages `noindex` so search
  engines only index the one page meant to rank.
- **Multi-worker scheduler duplication** -- the original in-process
  scheduler would run once *per worker process*, so any real deployment
  with more than one worker would check (and email) every business
  multiple times over. See "Going live" below for the fix.

**Second pass** (SEO/AI-optimisation/security/traffic-handling audit, applied
in full):

- **Gemini API key leak** -- the key traveled in the request URL, so a
  failed call's error text (shown directly on the public report page) could
  echo it back. Moved to the `x-goog-api-key` header; every provider error
  message is also now scrubbed of any configured secret as a second line of
  defense.
- **Security headers** -- added `Content-Security-Policy`, `X-Frame-Options`,
  `X-Content-Type-Options`, `Strict-Transport-Security` and
  `Referrer-Policy` on every response. All inline `<script>` blocks were
  moved into external `/static/*.js` files (auto-initializing from `data-*`
  attributes) so `script-src` can stay locked to `'self'` with no
  `'unsafe-inline'` exception.
- **Wrong client IP / scheme behind the proxy** -- Render (and most PaaS
  hosts) terminate TLS at a reverse proxy in front of the app, so without
  `ProxyFix` every request looked like it came from the proxy's own IP
  (breaking per-visitor rate limiting) and over plain HTTP (breaking
  `https://` canonical/sitemap URLs). Added `werkzeug.middleware.proxy_fix`.
- **Broken rate-limit page** -- hitting a rate limit used to `redirect(...),
  429`, which does nothing useful: browsers only follow redirects on 3xx
  responses, so visitors saw a bare, unstyled "Redirecting..." page. Now
  renders a proper branded error page directly, alongside new custom 404 and
  500 pages.
- **`num_queries` could 500** -- a non-numeric value crashed with an
  unhandled `ValueError`; now falls back to the default instead.
- **Analyzer false positives/negatives** -- name matching is now
  whole-word (so "Ace" no longer matches inside "Palace"), normalizes curly
  quotes and "&"/"and", detects markdown-heading-prefixed list items
  (`### 1. Foo`), and discovers competitors the assistant named that the
  user never typed in.
- **`num_queries` silently ignored** -- with a Claude key configured, the
  truncation logic only fired when there were *fewer* queries than
  requested, so the optional LLM-generated extras could push the total over
  (or leave it under) what was asked for. Now always truncates to exactly
  `num_queries`.
- **Self-naming query inflated scores** -- one template literally asked "Is
  {business} a good {category}...", which obviously always mentions the
  business. Removed -- every query now tests whether the assistant
  recommends the business *unprompted*.
- **Category-matching false positives** -- plain substring matching mapped
  "barber" to restaurants (via "bar"), "chair hire" to salons (via "hair"),
  "carpet store" and "corvette repairs" to veterinary (via "pet"/"vet"),
  "publishing house" to restaurants (via "pub"), and "dinner cruise" to
  accommodation (via "inn"). Switched to whole-word/whole-phrase matching
  and added missing coverage (seafood/sushi, physio/chiropractic, florists).
- **Non-shareable, resubmission-prone reports** -- the anonymous report used
  to render straight from the `POST /check` handler, so refreshing the page
  re-ran (and would re-bill) the whole check, and the URL couldn't be
  bookmarked or shared. Now post/redirect/get: `report_cache.py` stores the
  finished report under a short-lived id and `GET /check/<id>` renders it.
- **SEO** -- trimmed the title/description to search-engine length limits,
  added Open Graph + Twitter Card tags and a generated share image, JSON-LD
  (`SoftwareApplication` on the homepage, `FAQPage` on `/faq`), a proper
  favicon, and real indexable marketing pages (`/pricing`, `/faq`, `/about`,
  `/how-it-works`, `/privacy`, `/terms`), all listed in `sitemap.xml`.
- **AI-crawler optimisation** -- added `/llms.txt`, a plain-language summary
  of what the product does, for assistants/crawlers that read it.
- **Accessibility** -- `--muted-dim` text failed WCAG AA contrast (3.67:1)
  against the card background; lightened to pass (5.7:1+). The autocomplete
  dropdown now exposes proper ARIA combobox/listbox roles.
- **UX polish** -- submit buttons show a spinner and disable themselves
  while a check runs (a real check takes several seconds); the "every
  question asked" section is now grouped by question instead of one long
  flat list; dev-facing "see README.md"/".env" hints are hidden once
  `FLASK_ENV=production`.
- **Traffic-handling** -- switched Gunicorn to threaded workers (better for
  I/O-bound provider calls), reduced each provider's timeout from 30s to
  15s, pinned every dependency version (and added `.python-version`) so a
  deploy can't silently pick up an untested Python/library version.
- **Billing cost-exposure guard** -- once a real (paid) AI provider key is
  configured, `/billing/checkout` no longer auto-grants a free "demo"
  subscription when Stripe isn't configured -- that combination would let
  anyone rack up metered API cost with no payment ever collected.

**Third pass** (found on the actual multi-worker Render deployment, applied
in full):

- **"That report has expired" on every real check** -- the shareable report
  link introduced in the second pass stored reports in an in-process dict.
  Render's Gunicorn config runs more than one worker, so the worker that
  handled `POST /check` was very often not the one the redirected
  `GET /check/<id>` landed on, which had never heard of that report id --
  meaning shared/bookmarked/even just-refreshed report links failed
  constantly in production (they happened to work in local single-process
  testing, which is why this wasn't caught earlier). Moved to a database
  table (`anonymous_report`) so every worker process sees every saved
  report; verified with two separate Python processes writing/reading the
  same SQLite file to confirm it actually survives a cross-process handoff.
- **Autocomplete suggestions were geographically irrelevant** -- searching a
  business name with no location context ranks purely on Photon's text-match
  fuzziness, so e.g. "nene chicken" surfaced branches in Singapore, Toronto
  and Melbourne with no preference for the user's own area. Added
  `/api/geocode` (debounced on the Location field) and pass the resulting
  lat/lon as a bias into every Business-name and Competitors search; also
  reordered the form so Location comes first, since the bias only helps once
  it's filled in.
- **No autocomplete on the Competitors field** -- it was a plain text input.
  Added a multi-value-aware mode that searches and replaces only the
  comma-separated segment currently being typed, leaving earlier entries
  alone, and skips the category/location autofill (a competitor is just a
  name).

**Fourth pass** (a real business name legitimately not in Photon's free
database looked identical to a broken search -- dug into why and found two
related bugs alongside it):

- **A failed lookup was cached as if it were a real empty result** --
  `search_places`/`geocode_location` cached whatever came back even when the
  request itself had thrown (timeout, rate limit, transient network error),
  so one blip made every identical query return nothing for the full 5-minute
  cache TTL even after the provider recovered. Now only a lookup that
  actually completed gets cached -- including a genuine zero-result answer,
  which is still worth caching -- so a failure is retried on the very next
  keystroke instead of being remembered as "no results" for 5 minutes.
- **No feedback when a search genuinely finds nothing** -- a small business
  that just isn't in Photon's OpenStreetMap-backed dataset (a known,
  documented coverage limit, not a bug) rendered identically to "haven't
  typed enough yet": nothing at all. Added a plain "No matches -- you can
  still type it in manually" note so a real completed-but-empty search is
  distinguishable from a search that hasn't run yet, and reads as expected
  behavior rather than a broken widget.
- **Race condition: a slow, stale response could overwrite a faster, newer
  one** -- typing quickly (e.g. finishing a longer name after an initial
  slower search was already in flight) had no guarantee responses would
  render in the order they were sent. Added a per-field request sequence
  number so only the most recently *fired* search is ever allowed to render;
  an older one that resolves late is silently dropped.

**Fifth pass** (live-site feedback: missing businesses, generic report):

- **Google business search** -- Business name + Competitors now search
  Google's listings via Places API (New) when `GOOGLE_PLACES_API_KEY` is
  set (see above). The previous Google code used the legacy endpoint, which
  new Google Cloud projects can't enable -- a new key would have silently
  never worked.
- **Category field suggestions** -- built-in category list plus Google's
  category autofill.
- **Questions read naturally** -- "I need a fast food in Sydney" is now "I
  need a fast food restaurant in Sydney"; cuisines are capitalised; the
  "for {audience}" question uses audiences that fit the business type (no
  more "seafood restaurant for urgent appointments").
- **Demo mode no longer fakes 100%** -- with no competitors typed in, every
  simulated answer named the business at #1. Demo answers now include
  clearly-labelled "Sample Rival" placeholders and the whole report is
  marked as a sample.
- **Report rebuilt around this check's actual data** -- headline + findings
  with real counts (best/never-named assistants, top competitor vs you,
  questions nobody named you for, average rank), a prioritised "What to do
  next" where each step cites what triggered it, a question x assistant
  grid, and a "who else gets named" comparison including you. The generic
  per-assistant essays and duplicate "General fixes" list are gone.
- **Subscribers see the full report too** -- the paid business page used to
  show only the fix lists; it now renders the same report as the free check,
  plus score change since the previous check.
- Competitor counts merged case-insensitively and counted once per answer;
  OSM suburbs/streets filtered out of business suggestions; "Copy link"
  button on reports; places autocomplete rate limit raised (normal typing
  across two fields could hit the old 30/min).

**Sixth pass** (accuracy, real-world data, plans):

- **Retired AI models replaced** -- `gemini-2.0-flash` was shut down on 1 June
  2026 and DeepSeek retired `deepseek-chat`, so live checks on those would
  have errored. Defaults are now `claude-sonnet-4-6`, `gpt-5.4-mini`,
  `sonar`, `gemini-3.5-flash`, `deepseek-flash`, each overridable with
  `CLAUDE_MODEL` / `OPENAI_MODEL` / `PERPLEXITY_MODEL` / `GEMINI_MODEL` /
  `DEEPSEEK_MODEL`. `/healthz` shows which model each assistant uses.
- **Answers use live web search, localised** -- ChatGPT now goes through the
  Responses API with `web_search` (Chat Completions only used training
  data). ChatGPT, Claude and Perplexity get the customer's country, city and
  region, geocoded from the Location field. Gemini is grounded in Google
  Search. DeepSeek has no search API, and the report says so.
- **Sources captured** -- every answer keeps the pages the assistant read or
  cited. The report shows "Where the assistants got their information" and
  turns the top sites that didn't mention you into an action.
- **Stricter, fairer matching** -- "Ace's Deep Sea Food" now matches "Aces
  Deep Seafood" and "Kickin'Inn" matches "Kickin' Inn". Legal suffixes and
  "The" are ignored. An answer that only says "I couldn't find information
  about X" no longer counts as a recommendation; it gets its own finding and
  fix. Sub-bullets ("- Address: ...") no longer inflate rank numbers or
  appear as competitors.
- **"What the assistants say"** -- the actual words used about you and your
  top competitors, pulled from their answers.
- **Google profile benchmark (Pro)** -- Places API (New) Text Search looks up
  you and the most-recommended competitors: rating, review count, primary
  category, website and weekend hours. It produces specific actions such as
  "change your category to Seafood restaurant", "1,154 fewer reviews" or
  "no website listed", plus a "not found on Google Maps" warning.
- **Checks don't time out** -- all provider calls run at once with one
  80-second deadline (`CHECK_TIMEOUT`), and Gunicorn's timeout is now 120s.
  Live web-search answers take 20-40s each; the old 8-thread pool plus the
  30s Gunicorn timeout would have killed real checks.
- **Business suggestions stay in-country** -- the geocoded country goes to
  Google as `includedRegionCodes`. `/healthz` shows the active search
  backend and the last Google error (e.g. API not enabled).
- **Navigation** -- a shared top bar on every page; the logo always goes
  home. Logged-in users used to be redirected away from `/`, so the
  homepage and free check were unreachable.
- **Plans** -- Starter $29 and Pro $49 (see `plans.py`), with Stripe
  `STRIPE_PRICE_ID` / `STRIPE_PRICE_ID_PRO`, a billing portal for switching
  plan, and a webhook that syncs the plan.
  - Pro adds: Google benchmark, up to 5 custom questions, 10 questions per
    check, twice-weekly checks, 3 businesses, 10 competitors and CSV export.
  - Subscribers can now edit or remove businesses and see a score chart.
  - The scheduler runs every 6 hours in-process (or twice daily via cron)
    and only re-checks businesses that are due.
- **Free check is capped** at 6 questions and 5 competitors to control cost.
- **Wasted API call removed** -- an optional Claude "extra questions" call
  ran on every check, but its output was always discarded.

**Seventh pass** (search suggestions -- "nene chicken macquarie center"
returned an auto shop in Aruba):

- **Root causes**:
  - Photon's `location_bias_scale` was 1.0, which means *maximum prominence,
    minimum location bias* (the opposite of the intent).
  - Raw provider results were shown unfiltered, so a result matching one
    word ("center") got through.
  - A place typed inside the business query was treated as part of the
    business name.
- **New `search_engine.py`**, modelled on how map search engines handle
  typeahead:
  - query understanding: trailing words that geocode to a real place near
    the user become the search centre;
  - multi-angle candidate generation: the full query plus the name near the
    detected place, merged and de-duplicated;
  - re-ranking: typo-tolerant name relevance, proximity, same-country;
  - junk filter: a result's name must contain the typed name (fully for 1-2
    words, 2/3 for longer names);
  - overseas namesakes are dropped when local matches exist;
  - Google results are filtered by the same rule.
- **No Location typed yet?** The browser's time zone (e.g. Australia/Sydney)
  is used as a permission-free "near me" hint, the stand-in search engines
  use for IP location.
- **Location field now autocompletes** suburbs/towns/cities (Google
  "(regions)" when configured, otherwise OSM places, AU/US states
  abbreviated). Picking one sets the search centre for Business name and
  Competitors instantly.
- **Category field** adds synonyms ("doctor" -> general practitioner,
  "mechanic" -> car repair shop) and typo tolerance ("resturant").
- **UI**: matched words are bolded, distance is shown ("Herring Road,
  Macquarie Park - 200 m"), and a "Searching..." state appears.

**Eighth pass** (Google Maps links, competitor sanity checks):

- **Paste a Google Maps link** in the new box at the top of every business
  form (free check, add business, edit), or paste it straight into Business
  name / Competitors. `links.py` reads it right away and fills name,
  category and suburb; a competitor link adds that competitor.
  - Link types: long `/maps/place/...` URLs, `maps.app.goo.gl` / `goo.gl`
    share links, `g.page`, `g.co/kgs`, `share.google`, `?q=Name, Address`,
    `/maps/search/...` and `query_place_id` / `place_id:`.
  - Safety: short links are expanded one redirect at a time and only to
    Google hosts (never an arbitrary URL; tested). Google's consent page is
    unwrapped.
  - With `GOOGLE_PLACES_API_KEY`, the place is looked up in Places API (New)
    (place ID, or name + the link's coordinates) for the exact category and
    suburb.
  - Without a key: the name comes from the link, the suburb from free
    reverse geocoding, and the category from OSM or guessed from the name.
  - Links that carry no business information (e.g. `?cid=` only) get a clear
    "use the Share button" message.
- **Competitor category check** (`category_match.py`): every competitor with
  a known category is compared with yours by industry group.
  - A different industry (cafe vs car wash) is a **mismatch**: flagged live
    with a Remove button, left out of tracking, and explained in the report
    under "About your competitor list".
  - The same industry but a different specialty (plumber vs electrician,
    dentist vs physio) gets a softer note.
  - Categories travel in a hidden `competitor_meta` field, so the server
    makes the same call. They're stored per monitored business and applied
    on every scheduled re-check.

**Ninth pass** (from reviewing a real sample report for The Burger Boys):

- **Sample reports no longer present made-up evidence.** "What the
  assistants say" and praise-based advice only use real answers. On a
  sample report the action list is labelled "example".
- **Sample answers are realistic.** Reasons now fit the business type (no
  more "fast response times" for a fish and chip shop), and every name has
  a fair chance of being listed. A single typed competitor used to appear
  in 30 of 30 answers.
- **Broad categories are narrowed from the name.** "restaurant" + "The
  Burger Boys" is checked as "burger restaurant"; "salon" + "Lux Nails" as
  "nail salon". The report says so. This applies to free checks,
  monitored businesses and competitor comparisons, and never overrides a
  specific category the user chose.
- **Different food counts as partial competition.** Burger vs fish and
  chips gets a soft "partial competitor" note; cafe and bakery count as the
  same thing.
- **Name-only guesses never remove a competitor.** A competitor typed
  without a known category gets a "possible mismatch" hint only; it is
  never excluded.
- **Fixes:**
  - Enter in the Google Maps link box no longer submits the form.
  - A link that reaches the server inside the name or competitor fields is
    resolved there (unreadable links are dropped rather than tracked as a
    business name).
  - Live warnings use the refined category.

**Tenth pass** (built around how business owners think and buy):

- **Foundations.** Visibility rests on three pillars, and the report scores
  each one: Listings & profiles, Reviews, and Website. A Google Business
  Profile alone isn't enough, because each assistant reads different
  sources:
  - Gemini reads Google Maps data.
  - ChatGPT's local answers lean on Bing / Bing Places, websites and
    directories.
  - Claude and Perplexity search the live web.
  - Siri uses Apple Business Connect.

  This is explained on How it works and in the FAQ.
- **Niche library (`niches.py`).** 28 business types (cafes, takeaway,
  restaurants, bars, dentists, GPs, allied health, vets, barbers, salons,
  gyms, emergency trades, builders, home services, mechanics, car care,
  lawyers, accountants, real estate, childcare, tutoring, hotels, venues,
  shops and more). Each has:
  - the questions its customers actually ask AI, tagged by intent: urgent,
    price, specialty, booking, audience, reviews;
  - the listing platforms that matter for it, by country (AU/US/UK/...),
    e.g. HotDoc, hipages, OpenTable, Fresha, Checkatrade, Zocdoc;
  - pillar-tagged fixes.

  A miss on an intent maps to a specific fix ("Make it obvious you take
  urgent jobs", "Name the service you were missed for", ...).
- **Website AI-readiness check (`website_audit.py`).** This runs in every
  check when a website is given, and as a free stand-alone tool at
  `/website-check`. It checks:
  - AI search crawlers allowed in robots.txt: OAI-SearchBot,
    Claude-SearchBot, PerplexityBot, Googlebot, Bingbot. Training bots are
    shown as info only, because blocking them doesn't affect search.
  - noindex, HTTPS, and name / suburb / services / phone / hours in plain
    text.
  - JavaScript-only pages.
  - LocalBusiness JSON-LD and an FAQ, weighted as helpful, not required,
    per Google's guidance.

  Every fetch is guarded against SSRF: public IPs only, re-checked on every
  redirect, ports 80/443, size and time caps.
- **Gemini also uses Google Maps grounding**, with the customer's location.
  If Maps grounding is rejected, it retries with Search only.
- **The website field** is auto-filled from Google when a Maps link is
  pasted (if Places is connected), and stored per monitored business.

**Eleventh pass** (full audit before real API keys go live; three parallel
reviews of the backend, the AI pipeline, and every outbound-HTTP path. Each
finding was reproduced before fixing, and each fix now has a test):

*Security*
- **SSRF through the Maps-link resolver.** `is_google_host` checked the
  whole netloc, so `https://maps.google.com:@169.254.169.254/` passed: the
  part before `@` is a *username*, and the real host is the metadata
  address. The error messages also made it usable as an internal port
  scanner. Fix: compare `urlparse().hostname`, reject any userinfo and
  non-80/443 ports, check every redirect hop.
- **DNS rebinding.** The website check resolved a hostname to validate it,
  then `requests` resolved it *again* to connect, so a short-TTL domain
  could answer "public" then "127.0.0.1". The new `safe_http.py` mounts a
  urllib3 connection class that resolves once *inside* the connect call,
  rejects any non-public answer (including IPv4-mapped IPv6, NAT64, 6to4,
  CGNAT), and connects to that exact address. TLS still verifies the
  original hostname.
- **Regex denial of service.** The HTML checks used backtracking regexes on
  attacker-controlled pages (up to 2.5 MB). A 7 KB page of
  `<meta name=robots ` took over a second, and the growth was roughly
  cubic. Replaced with one linear `html.parser` pass.
- **Slow-drip responses.** Per-socket timeouts let a server that sends one
  byte every few seconds hold a worker thread indefinitely. Each fetch now
  has one deadline, checked after every socket read (`read1`).
- **Billing.** `/billing/success` activated a plan from any checkout session
  id belonging to the user, so an abandoned or replayed checkout unlocked
  Pro for free. It now requires `status=complete`, a paid
  `payment_status`, and a live subscription fetched from Stripe.
- **Webhooks.** These now re-fetch the subscription (Stripe doesn't
  guarantee event order), ignore events about an older subscription, and
  are exempt from the global rate limit.
- **Information leaks.** `/healthz` no longer returns raw database errors
  (host and user name). Provider error text shown on public reports is
  scrubbed of organisation, project and key identifiers.
- **Production detection.** Also reads Render's `RENDER` variable, so a
  missing `FLASK_ENV` can no longer start the app with the dev secret key.

*Correctness: the score*
- **Empty answers counted as misses.** An empty, refused or truncated
  answer (Claude `pause_turn`/`max_tokens`, OpenAI `status: incomplete`,
  DeepSeek `content: null`) used to count as "not mentioned", wrongly
  lowering the score. It's now an excluded error, the same as a failed
  call.
- **Names with a full stop.** "Dr. Kim Dental" and "St. Ives Physio" were
  never matched, because sentence splitting cut the name at the full stop.
- **Negative phrases about something else.** "If you're not familiar with
  the area, Ryde Dental is great" read as "couldn't find you". A negative
  phrase now has to be about the business. "Permanently closed" always
  overrides.
- **Rank taken from the wrong item.** Position came from any list item
  that *mentioned* the business ("like Ryde Dental but cheaper"), not the
  item that *is* it.
- **Fake competitors.** Headings ("Best Overall") and tips ("Check Google
  reviews…") became competitors. Perplexity citation markers
  (`Smile Dental[1]`) and spelling variants (`Kickin'Inn`) split one
  business into several, which picked the wrong leader and sent false
  "new top competitor" alerts.
- **Name variants too loose.** "Smith, Jones & Partners" produced the
  variant "Smith", which matched every Smith in town.
- **Advice from failed calls.** A provider whose calls all *failed* was
  flagged as "weak", and a check where every call failed still gave
  generic advice.
- **"Wagga Wagga" became "Wagga".** The duplicate-word fix ran over the
  location. The location is now inserted after the grammar clean-up.
- **Wrong niche.** Niche regexes caught look-alike words: "taxi" → tax,
  "veteran" → vet, "automation" → auto, "Chinese medicine" → restaurant,
  "plant nursery" → childcare.
- **Branches merged.** Google suggestions for different branches of a
  chain were merged into one.

*Reliability and multi-worker behaviour*
- **Retries and rate limits.** Provider calls retry on 429/5xx with backoff
  (honouring `Retry-After`) under a per-provider concurrency cap.
- **One deadline for the whole check.** Every timeout and retry is bounded
  by the check's single deadline, so calls that miss it stop instead of
  running on (and billing).
- **Cross-process locks (`locks.py`).** These use a Postgres advisory lock,
  or a file lock on SQLite. Schema migration and the scheduled run now
  happen once even with several workers. Previously each worker ran its
  own scheduler (duplicate checks and emails) and two booting workers
  could race on `ALTER TABLE`.
- **Plan limits.** These are enforced under a per-user lock (parallel
  submits can't exceed the plan) and in the scheduler (a Pro → Starter
  downgrade stops checking the extra businesses).
- **Demo plans after real keys.** Free "demo" plans stop running checks
  once real (paid) AI keys are configured. Owner/test accounts can be
  listed in `COMPLIMENTARY_EMAILS`.
- **Smaller races.** Signups and report-cache expiry no longer return 500s
  under concurrent requests.
- **Front end.** Stale geocode responses could overwrite a picked location,
  and Enter could pick a suggestion for text the user had already changed.

*Engineering*
- A pytest suite (`tests/`, 169 tests, about 7 s, no network) and GitHub
  Actions CI.
