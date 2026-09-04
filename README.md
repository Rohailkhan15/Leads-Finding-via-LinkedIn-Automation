# LinkedIn Lead-Generation Automation

Search Google's public index of LinkedIn profile pages (via the [Searlo](https://searlo.tech) API) for **e-commerce store owners**, filter them by keyword, and log the results into two tabs of a Google Sheet — qualified leads in one, filtered-out leads in another.

This is a **standalone repo**. It shares the same Google Spreadsheet as a separate Email automation, but only ever touches its own two tabs (`LinkedIn` and `LinkedIn-Backup`). It never reads, writes, or references the `Email` tab.

> **Nothing here talks to LinkedIn's servers.** It only reads public Google search results returned by Searlo, so LinkedIn's Terms of Service are not implicated.

Runs are **manual** — there is no schedule. Trigger it weekly from the GitHub Actions tab or run it locally.

---

## How it works

```
SEARCH_QUERIES (Google dorks)
        │
        ▼
   Searlo API  ── GET /search/web  (x-api-key header)
        │
        ▼
  Raw results  ──► keep only URLs containing "linkedin.com/in/"
        │
        ▼
  Keyword filter on (title + snippet)
        │
   ┌────┴─────────────────────────┐
   ▼                              ▼
 PASS                          FAIL
 (≥1 ROLE **and** ≥1 SMALL_BUSINESS   (anything else)
  **and** 0 EXCLUDE)
   │                              │
   ▼                              ▼
"LinkedIn" tab             "LinkedIn-Backup" tab
   │                              │
   └── deduped per-tab by profile URL (never cross-tab) ──┘
```

---

## Project structure

```
.
├── .github/
│   └── workflows/
│       └── linkedin_automation.yml   # manual (workflow_dispatch) trigger only
├── linkedin_automation.py            # the script
├── requirements.txt                  # requests, gspread, google-auth, python-dotenv
├── .gitignore                        # ignores .env, *.json, __pycache__/, .venv/
└── README.md
```

---

## Requirements

- Python **3.10+** (the GitHub Action uses 3.11)
- A **Searlo** account + API key (free tier works; keys start with `sk_`)
- A **Google Cloud service account** with a JSON key, and a **Google Sheet** the service account can edit
- Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration

All tunable values are plain Python lists/constants at the **top of `linkedin_automation.py`** — edit them without touching any logic.

### Search queries (`SEARCH_QUERIES`)

```python
SEARCH_QUERIES = [
    'site:linkedin.com/in "owner" "online store"',
    'site:linkedin.com/in "owner" "small business" "shop"',
    'site:linkedin.com/in "owner" "e-commerce shop"',
    'site:linkedin.com/in "owner" "e-commerce store"',
    'site:linkedin.com/in "founder" "online store"',
    'site:linkedin.com/in "started my own online store"',
    'site:linkedin.com/in "founder" "e-commerce shop"',
]
```

### Keyword filter

A result **PASSES** only if it contains **at least one `ROLE_KEYWORDS` term AND at least one `SMALL_BUSINESS_KEYWORDS` term AND no `EXCLUDE_KEYWORDS` term**. Matching is a **case-insensitive substring** search over the combined `title + snippet`. Missing either positive category, or hitting any exclude term → **FAIL** (goes to `LinkedIn-Backup`).

| List | Terms |
|---|---|
| `ROLE_KEYWORDS` | owner, founder, co-founder |
| `SMALL_BUSINESS_KEYWORDS` | small business, boutique, solopreneur, independent, one-person, self-funded, bootstrapped, handmade, my online store, started my own |
| `EXCLUDE_KEYWORDS` | agency, consulting, marketing, freelance, virtual assistant, saas, software, developer, consultant, president, vp, vice president, director, head of, shopify inc, shopify partner, team member, employee |

> **Substring caveat:** matching is by substring, so short/broad exclude terms like `vp`, `director`, `head of`, and `employee` (which also matches `employees`) can occasionally filter out a genuine owner. Tighten or loosen these lists based on real results.

---

## Environment variables

No secrets are hardcoded — everything comes from the environment.

| Variable | Description |
|---|---|
| `SEARLO_API_KEY` | Searlo API key (starts with `sk_`), sent as the `x-api-key` header |
| `SHEET_ID` | Google Sheet ID — the string between `/d/` and `/edit` in the Sheet URL |
| `GOOGLE_CREDS_JSON` | The **entire contents** of the service-account JSON key |

---

## Setup

### 1. Google Sheet

The service account must have **edit** access to the target spreadsheet (share the Sheet with the service account's `client_email`). The script uses two tabs:

- **`LinkedIn`** — qualified (PASS) leads
- **`LinkedIn-Backup`** — filtered-out (FAIL) leads, parked for manual review

Both tabs are **auto-created with a header row** if they don't already exist. Column order (identical in both tabs):

| Name | Business/Profile | Platform | Date Found | Message Sent | Response | Follow-up 1 | Follow-up 2 | Status |
|---|---|---|---|---|---|---|---|---|

- **Business/Profile** = the LinkedIn profile URL
- **Platform** = `LinkedIn`
- **Date Found** = the run date (`YYYY-MM-DD`)
- The remaining columns are written as blank strings for you to fill in during outreach.

### 2. Searlo

Sign up at [dashboard.searlo.tech](https://dashboard.searlo.tech), create an API key, and keep it private.

| Detail | Value |
|---|---|
| Base URL | `https://api.searlo.tech/api/v1` |
| Endpoint | `GET /search/web` (current; `/search/simple` is legacy) |
| Auth | `x-api-key` header |
| Results | up to 10 per query |
| Cost | 1 credit per query → **~7 credits per run** with the default query list |

The parser also understands the legacy `{"data": {"results": [...]}}` shape as a fallback.

---

## Running locally

1. Create a `.env` file in the repo root (it is git-ignored):

   ```dotenv
   SEARLO_API_KEY=sk_your_key_here
   SHEET_ID=your_spreadsheet_id_here
   GOOGLE_CREDS_JSON={"type":"service_account","project_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n","client_email":"...@....iam.gserviceaccount.com","token_uri":"https://oauth2.googleapis.com/token"}
   ```

   > **Important:** `GOOGLE_CREDS_JSON` must be the **whole JSON on a single line** (as above), not pretty-printed, and keep the `\n` escapes inside `private_key` intact. Multi-line values break `python-dotenv` parsing.

2. Run the script:

   ```bash
   python linkedin_automation.py
   ```

   `load_dotenv()` picks up `.env` automatically — no need to export anything.

3. (Optional) For a verbose raw-response dump when a search returns nothing, set `DEBUG`:

   ```bash
   # PowerShell
   $env:DEBUG=1 ; python linkedin_automation.py

   # macOS / Linux
   DEBUG=1 python linkedin_automation.py
   ```

---

## Running via GitHub Actions (manual)

The workflow (`.github/workflows/linkedin_automation.yml`) has **no schedule** — it only runs on demand via `workflow_dispatch`.

1. In this repo, go to **Settings → Secrets and variables → Actions** and add three repository secrets:

   | Secret | Value |
   |---|---|
   | `SEARLO_API_KEY` | your Searlo key |
   | `SHEET_ID` | the spreadsheet ID |
   | `GOOGLE_CREDS_JSON` | full service-account JSON (single line) |

   > GitHub secrets are scoped **per repo** — they do not carry over from the Email repo, so add all three here.

2. Go to the **Actions** tab → **LinkedIn Lead Generation** → **Run workflow** → choose the branch → **Run workflow**.

You can also just run it locally (see above) whenever you prefer.

---

## Output / logging

Each run prints a clear summary:

```
[1/7] Searching: site:linkedin.com/in "owner" "online store"
    -> 10 raw result(s)
...
----------------------------------------------------------------------
Total queries run        : 7
Total raw results fetched: 70
Discarded (not linkedin.com/in/): 12
Duplicate URLs within this run  : 5
PASS (qualified)   : 18
FAIL (backup)      : 35
----------------------------------------------------------------------
SUMMARY
Tab 'LinkedIn':
    duplicates skipped (already in tab): 3
    new rows added                     : 15
Tab 'LinkedIn-Backup':
    duplicates skipped (already in tab): 0
    new rows added                     : 35
```

- **Total queries run / raw results fetched** — search coverage
- **Discarded** — results whose URL wasn't a `linkedin.com/in/` profile
- **Duplicate URLs within this run** — the same profile returned by multiple queries (counted once)
- **PASS / FAIL** — how many cleared vs. failed the keyword filter
- **duplicates skipped** — rows already present in that tab (deduped per-tab by profile URL)
- **new rows added** — rows actually appended to each tab

---

## Deduplication

Before appending, each tab is compared **only against its own existing rows**, by normalized profile URL (lowercased; query string, fragment, and trailing slash stripped). The `LinkedIn` tab is **never** compared against `LinkedIn-Backup`, and neither is compared against any `Email` tab.

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `HTTP 401` | Invalid/missing `SEARLO_API_KEY` | Check the key and the `x-api-key` header value |
| `HTTP 402` | Searlo out of credits | Top up your Searlo account |
| `HTTP 429` | Rate limit (free tier ≈ 10 req/min) | The script auto-retries with backoff; reduce query count if it persists |
| `200 OK but 0 items` | Response-shape mismatch or genuinely no results | Run with `DEBUG=1`; the dump shows the real response shape and `totalResults` |
| Almost everything FAILs | Filter too strict (needs a role **and** a small-business term) | Loosen `SMALL_BUSINESS_KEYWORDS` / `ROLE_KEYWORDS` |
| `LinkedIn` tab full of noise | Exclude list missing terms | Add the offending terms to `EXCLUDE_KEYWORDS` |
| Sheets permission error | Wrong `SHEET_ID`, incomplete `GOOGLE_CREDS_JSON`, or Sheet not shared with the service account | Re-verify all three; ensure the Sheet is shared with the service account's `client_email` |
| Duplicate rows | — | Dedup is per-tab by profile URL; confirm you're looking at the right tab |

---

## Notes

- **Cost:** ~7 Searlo credits per run with the default query list (1 credit per query).
- **Volume:** 7 queries × up to 10 results = up to ~70 raw candidates per run before filtering and dedup. Add more product-vertical dorks to `SEARCH_QUERIES` to increase yield.
- **Independent of the Email automation:** same spreadsheet, different tabs, zero interaction.
