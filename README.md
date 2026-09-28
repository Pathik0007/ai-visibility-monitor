# AI Visibility Monitor

Checks whether ChatGPT, Claude, Perplexity, Gemini and DeepSeek recommend a
local business (or a competitor) for realistic "best X near me" questions,
turns that into a visibility score and a plain-English fix list, and -- for
subscribed accounts -- re-checks automatically every week and emails an
alert when something meaningful changes.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # optional, see below
python app.py
```

Open http://localhost:5000. A SQLite file (`data.db`) is created automatically
on first run.

## Two ways to use it

- **Anonymous quick check** (the homepage form) -- one-off report, no
  account needed. Good for a landing-page demo.
- **Account + saved businesses** (sign up / log in) -- save a business,
  see its score history over time, and get it re-checked weekly with an
  email alert on a meaningful change. Adding a business requires an active
  subscription.

## About API keys -- everything runs in demo mode with zero setup

Nothing here requires a key to try. Anything left blank in `.env` falls
back to clearly-labeled simulated behaviour, so the whole flow -- checking,
subscribing, saving a business, the weekly job, the alert email -- is
testable end to end right now.

**AI assistants being monitored** -- missing key -> that assistant's answers
are simulated (tagged "demo" in the UI):

| Provider   | Env var              | Get a key                                     |
|------------|-----------------------|------------------------------------------------|
| Claude     | `ANTHROPIC_API_KEY`   | https://console.anthropic.com/settings/keys    |
| ChatGPT    | `OPENAI_API_KEY`      | https://platform.openai.com/api-keys           |
| Perplexity | `PERPLEXITY_API_KEY`  | https://www.perplexity.ai/settings/api         |
| Gemini     | `GOOGLE_API_KEY`      | https://aistudio.google.com/apikey             |
| DeepSeek   | `DEEPSEEK_API_KEY`    | https://platform.deepseek.com/api_keys         |

Each is a paid, pay-as-you-go API (small cents-per-query cost) -- not the
same login as the consumer chat apps.

**How each one actually answers**: Claude and Gemini are called with their
live web-search tool turned on, so their answers reflect the current web,
not just training data. ChatGPT and DeepSeek are called via their plain
chat-completions APIs, which answer from training data only -- there's no
web-search tool available on those endpoints the way there is for Claude and
Gemini today. Perplexity is inherently search-based. This is noted directly
on each report (see the per-assistant "why a specific assistant might be
missing you" notes) so a low ChatGPT/DeepSeek score isn't mistaken for a
website problem when it's really a training-data-recency one.

**Stripe billing** -- no `STRIPE_SECRET_KEY`/`STRIPE_PRICE_ID` -> clicking
"Subscribe" instantly flips the account to a demo subscription, no charge,
clearly labeled "(demo)" on the dashboard. Add real keys from
https://dashboard.stripe.com/apikeys and a recurring Price from
https://dashboard.stripe.com/products to take real payments; also set
`STRIPE_WEBHOOK_SECRET` so cancellations/lapses stay in sync.

**Email alerts** -- no SMTP creds -> alerts are written to
`alerts_outbox.log` instead of sent, so you can see exactly what would have
gone out. Set `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` /
`ALERT_FROM_EMAIL` (any provider -- Gmail app password, Postmark, SES, etc.)
to send real emails.

## The action plan (not just a score)

Every report includes a "Your action plan" section, tailored two ways:

- **By business type** -- `ai_visibility/solutions.py` has playbooks for ~15
  common local-business categories (restaurants, dentists, lawyers, salons,
  trades, auto repair, real estate, etc.), each with the specific
  directories/platforms and content moves that matter most for that kind of
  business, falling back to solid general advice for anything unmatched.
- **By which assistant is missing you** -- flags whichever of Claude/ChatGPT/
  Perplexity/Gemini scored worst for this specific business, with a plain-
  English (and deliberately hedged) note on how that assistant generally
  tends to source its answers, so the advice points at the right lever
  (e.g. Gemini leans on Google Business Profile; Perplexity leans on live
  web search rankings; Claude leans on what's broadly crawled/cited).

This is framed as general, defensible guidance, not a definitive diagnosis
-- no outside tool can see exactly why a given model did or didn't mention a
business, and that mechanism isn't published and changes over time.

Reports saved before this feature existed are backfilled automatically the
next time they're viewed (see `CheckRun.report` in `models.py`) -- no
database migration needed.

## Business-name autocomplete

The "Business name" and "Competitors" fields (homepage and "add a business
to monitor") search as you type. Picking a Business-name result also fills
in category and location; the Competitors field is comma-separated, so
picking a result there only fills in the entry currently being typed,
leaving earlier entries in the list untouched.

- No setup needed: it uses Photon (photon.komoot.io), a free OpenStreetMap-based
  search API built for exactly this search-as-you-type use case, by default.
- **Location-biased**: typing into the Location field geocodes it (debounced,
  via `/api/geocode`) and that lat/lon is sent along with every Business-name
  and Competitors search, so results are ranked toward the user's actual area
  instead of purely on text-match fuzziness with no geography at all -- fill
  in Location first (it's the first field for exactly this reason) for
  meaningfully better results; a query like "nene chicken" without a location
  bias can rank a branch on the other side of the world above the one
  actually nearby.
- Coverage caveat: the free path only suggests places that exist in
  OpenStreetMap's database. Well-known chains are reliably there; a small
  independent business may return zero suggestions even when everything is
  working correctly -- try a well-known chain first if you want to sanity-check
  the feature itself.
- Set `GOOGLE_PLACES_API_KEY` in `.env` to use Google Places (and Google's
  Geocoding API for the location bias) instead, for a much larger place
  database; it automatically falls back to the free path if the Google
  lookup ever fails.
- Entirely optional -- if the lookup is slow, blocked, or down, the fields
  just behave like plain text inputs. Nothing about submitting the form
  depends on it.

## How it works

**Core engine** (used by both the anonymous check and saved businesses):

1. **`ai_visibility/query_generator.py`** -- builds realistic customer
   questions from the business's category + location.
2. **`ai_visibility/providers/`** -- one module per assistant; sends the
   question, returns the raw answer. Missing key -> `demo_mode.py` simulates
   one instead, tagged so the UI never presents it as real.
3. **`ai_visibility/analyzer.py`** -- parses each raw answer: was the
   business mentioned, how prominently, which competitors came up instead.
4. **`ai_visibility/report.py`** -- rolls that up into a visibility score, a
   per-assistant breakdown, a competitor leaderboard, and a fix list.
5. **`ai_visibility/pipeline.py`** -- runs all of the above for one business
   and returns the finished report dict.

**SaaS shell around it:**

6. **`models.py`** -- SQLAlchemy models: `User`, `Business` (a saved
   business to monitor), `CheckRun` (one historical report snapshot).
7. **`auth.py`** -- signup/login/logout (Flask-Login, hashed passwords).
8. **`billing.py`** -- Stripe Checkout to subscribe, a webhook to keep
   subscription status in sync, demo-mode bypass when unconfigured.
9. **`alerts.py`** -- re-runs the pipeline for a business, stores a new
   `CheckRun`, compares it to the previous one (`detect_meaningful_change`:
   a 15+ point score drop, or a new competitor taking the top spot), and
   emails the owner if so.
10. **`app.py`** -- the Flask site tying it all together, plus an
    in-process scheduler (single-process only -- see "Going live" below)
    that calls `alerts.run_weekly_checks` every 7 days for every saved
    business.
11. **`extensions.py`** -- shared CSRF protection and rate limiting,
    factored out so both `app.py` and `auth.py` can use them without a
    circular import.
12. **`scheduled_job.py`** -- the multi-worker-safe alternative to the
    in-process scheduler; a one-shot script meant to be triggered by your
    host's own cron/scheduler feature.

## Fixes applied for going live

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

## Going live -- checklist

This runs correctly today with `python app.py` as a single process. Before
pointing real traffic at it:

1. **Run multiple workers with a real WSGI server**, not Flask's dev
   server: `pip install -r requirements-prod.txt` then use the included
   `Procfile` (`gunicorn app:app --workers 2 --threads 4 --worker-class
   gthread --timeout 30 --graceful-timeout 30`) for Render/Heroku-style
   platforms. Threaded workers suit this app well since each request mostly
   waits on outbound AI-API calls rather than using CPU; raise `--timeout`
   or lower `num_queries` if your host's own reverse proxy has a shorter
   timeout than the providers' now-15s-each call budget needs.
2. **Turn off the in-process scheduler and use `scheduled_job.py` instead**:
   set `ENABLE_INPROCESS_SCHEDULER=0` and point your host's cron/scheduled-job
   feature (or a plain crontab) at `python scheduled_job.py` weekly. Running
   more than one worker with the in-process scheduler still on means every
   business gets checked and emailed once per worker.
3. **Move off SQLite to Postgres** for real concurrent traffic --
   `DATABASE_URL` is already read from the environment
   (`postgresql://user:pass@host/dbname`); SQLite's single-writer model
   will start serializing/blocking under concurrent signups and checks.
4. **Point rate limiting at Redis**, not in-memory storage, once you run
   more than one worker: set `RATELIMIT_STORAGE_URI=redis://<host>:6379` --
   otherwise each worker enforces limits separately and the real limit is
   effectively `limit x worker_count`.
5. **Set `FLASK_ENV=production`** and a real random `FLASK_SECRET_KEY`
   (`python -c "import secrets; print(secrets.token_hex(32))"`) -- the app
   will refuse to start in production without one.
6. **Add real Stripe and SMTP credentials** (see above) once you're ready
   to actually bill and email people instead of running in demo mode.
7. **Point an uptime monitor at `/healthz`**.
8. **Shareable report links are database-backed** (`report_cache.py` writes
   to the `anonymous_report` table via `models.py`) specifically so they
   survive running behind more than one Gunicorn worker -- an earlier
   in-memory version broke exactly this way: whichever worker handled the
   `POST /check` was the only one that knew about the report, so the
   redirected `GET /check/<id>` 404'd ("report expired") whenever it landed
   on a different worker. No extra setup needed; it just rides on whatever
   `DATABASE_URL` is already configured (SQLite locally, Postgres once you
   move to it per item 3 above).

## What's still deliberately out of scope

Password reset emails, plan tiers/usage limits, and a full test suite.
Worth building once you've got a handful of real paying businesses
confirming the core loop is worth scaling further.
