# AI Visibility Monitor

Checks whether ChatGPT, Claude, Perplexity and Gemini recommend a local
business (or a competitor) for realistic "best X near me" questions, turns
that into a visibility score and a plain-English fix list, and -- for
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

Each is a paid, pay-as-you-go API (small cents-per-query cost) -- not the
same login as the consumer chat apps.

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

## Business-name autocomplete

The "Business name" field (on the homepage and on "add a business to
monitor") searches as you type and, when you pick a result, also fills in
category and location -- so you usually only type the name.

- No setup needed: it uses free OpenStreetMap (Nominatim) search by default.
- Set `GOOGLE_PLACES_API_KEY` in `.env` to use Google Places instead (usually
  broader coverage); it automatically falls back to OpenStreetMap if the
  Google lookup ever fails.
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

## Going live -- checklist

This runs correctly today with `python app.py` as a single process. Before
pointing real traffic at it:

1. **Run multiple workers with a real WSGI server**, not Flask's dev
   server: `pip install -r requirements-prod.txt` then
   `gunicorn app:app --workers 3 --timeout 60` (a `Procfile` is included
   for Render/Heroku-style platforms). `--timeout 60` gives headroom for a
   real multi-provider check; if your host's own reverse proxy has a
   shorter timeout (many default to ~30s), raise it or lower `num_queries`.
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

## What's still deliberately out of scope

Password reset emails, plan tiers/usage limits, and a full test suite.
Worth building once you've got a handful of real paying businesses
confirming the core loop is worth scaling further.
