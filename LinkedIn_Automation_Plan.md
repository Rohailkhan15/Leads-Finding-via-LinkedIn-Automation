# LinkedIn Lead Generation Automation — Python + Searlo + GitHub Actions

## 1. What This Automation Does

Unlike Email, LinkedIn has no official API for searching/discovering people as a third party — so this automation works by searching Google's index of public LinkedIn profile pages (via the Searlo API, a Google-results API), not by talking to LinkedIn directly. This avoids LinkedIn's Terms of Service entirely, since nothing ever touches LinkedIn's own servers.

Every week, the script:
1. Runs a set of targeted Google searches (via Searlo) restricted to `site:linkedin.com/in`, looking for e-commerce store owners/founders.
2. Runs each result's title/snippet text through a keyword filter — genuine owner-signal keywords must be present, and agency/freelancer-type keywords must be absent.
3. Rows that **pass** the filter go into the `LinkedIn` tab (your outreach queue).
4. Rows that **fail** the filter go into a `LinkedIn-Backup` tab — not deleted, just parked. You review this manually if the main tab comes up short some week.
5. Both tabs are deduped separately, checking only against their own tab (not cross-platform, not cross-tab).

This is fully automatable end to end (unlike Email, which needs a manual CSV export step) — so this one runs on a real weekly schedule via GitHub Actions, no manual intervention needed. Ishmal still does all actual outreach manually — this only finds and logs candidates.

Target: 15-20 qualified leads/week (aim to raw-pull ~60-75 candidates/week to account for filter drop-off, per our earlier estimate — recalibrate after week one's actual pass rate).

---

## 2. Before You Start

- [ ] A GitHub account and repo (can be the same repo as the Email automation, or a new one — your call)
- [ ] A Searlo account (free tier)
- [ ] The same Google Sheet used for Email, or a shared one — just needs two new tabs
- [ ] Python 3.10+ for local testing

---

## 3. Step 1 — Set Up Searlo

1. Sign up at [searlo.tech](https://searlo.tech) (or via dashboard.searlo.tech), free tier.
2. Go to your dashboard and generate an API key (starts with `sk_`) — copy it and keep it private.
3. Check your dashboard for your actual monthly free credit allowance — confirm the number yourself rather than trusting anything written online, since free-tier terms shift.
4. Note: Searlo's documented endpoint is `GET /search/simple` (their simple web-search endpoint), authenticated via an `x-api-key` header. Double check this against their live docs (searlo.tech/docs) before building, since endpoint paths can change.

---

## 4. Step 2 — Add New Tabs to the Google Sheet

In the same Sheet used for Email, add two new tabs:

**Tab: `LinkedIn`** — same column structure as Email:

| Name | Business/Profile | Platform | Date Found | Message Sent | Response | Follow-up 1 | Follow-up 2 | Status |
|---|---|---|---|---|---|---|---|---|

- "Business/Profile" here = the LinkedIn profile URL (there's no email for this channel — outreach happens via LinkedIn DM/connection request, done manually by Ishmal).

**Tab: `LinkedIn-Backup`** — identical columns, same structure. This holds anything that didn't pass the keyword filter, for manual review later.

The same service account you set up for Email already has edit access to this Sheet, so no new Google Cloud setup needed — just make sure the new tabs exist before running the script.

---

## 5. Step 3 — Define Your Search Queries and Keyword Filters

This is the part most worth tuning carefully, based on what we learned from the Apollo keyword problem — a loose search catches agencies and freelancers, not just real store owners.

**Search queries (dorks) to run** — a handful of variations, not just one:
```
site:linkedin.com/in "founder" "shopify store"
site:linkedin.com/in "owner" "online store"
site:linkedin.com/in "founder" "ecommerce brand"
site:linkedin.com/in "co-founder" "apparel brand"
site:linkedin.com/in "founder" "skincare brand"
```
Running several narrower, product-specific dorks (apparel, skincare, jewelry, home goods, supplements) tends to surface real sellers better than one broad "ecommerce" query — the same lesson from the Apollo filtering problem applies here.

**Include keywords** (must appear in the result's title/snippet to pass):
`founder, owner, co-founder, ceo` (paired with) `shopify, ecommerce, online store, brand, boutique`

**Exclude keywords** (if present, auto-reject to Backup regardless of include matches):
`agency, consulting, marketing, freelance, virtual assistant, saas, software, developer, consultant`

Treat this list as a first draft — refine it after seeing real week-one results, exactly like we did with Apollo.

---

## 6. Step 4 — Project Structure

If adding to the same repo as Email:
```
trevolk-lead-gen/
├── .github/
│   └── workflows/
│       ├── email_automation.yml
│       └── linkedin_automation.yml
├── email_automation.py
├── linkedin_automation.py
├── requirements.txt
└── .gitignore
```

`requirements.txt` — add one new dependency to what Email already uses:
```
requests
gspread
google-auth
python-dotenv
```
(No new libraries needed — Searlo is a plain REST API, same as Apollo, called with `requests`.)

---

## 7. Step 5 — Script Logic (for the AI agent to build)

Rough logic outline — hand this section to Qoder along with the instructions in Section 9:

1. Loop through each search query in Section 5's list.
2. Call Searlo's search endpoint for each query, get back a list of results (each with a title, snippet, and URL).
3. For each result:
   - Confirm the URL actually matches a LinkedIn profile pattern (`linkedin.com/in/...`) — search results occasionally include unrelated matches.
   - Check the title+snippet text against the include/exclude keyword lists.
   - If it passes → mark for the `LinkedIn` tab. If it fails → mark for `LinkedIn-Backup`.
4. Before writing anything, read the existing rows in **both** tabs separately, and dedupe each list against its own tab only (by profile URL) — never cross-check between `LinkedIn` and `LinkedIn-Backup`, and never against the `Email` tab.
5. Append new rows to each tab as appropriate, using the same column format as Email (Name, Business/Profile, Platform="LinkedIn", Date Found, then blanks).
6. Log clearly: how many queries ran, how many raw results came back, how many passed vs failed the filter, how many were duplicates, how many new rows were actually added to each tab.

---

## 8. Step 6 — Store Secrets and Add the GitHub Actions Workflow

**New secret to add** (alongside the existing `SHEET_ID` and `GOOGLE_CREDS_JSON` from Email): `SEARLO_API_KEY`.

**`.github/workflows/linkedin_automation.yml`:**
```yaml
name: LinkedIn Lead Generation

on:
  schedule:
    - cron: "0 9 * * 1"   # Monday 9:00 AM UTC — adjust if you want a different day/time
  workflow_dispatch: {}

jobs:
  run-automation:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run LinkedIn automation script
        env:
          SEARLO_API_KEY: ${{ secrets.SEARLO_API_KEY }}
          SHEET_ID: ${{ secrets.SHEET_ID }}
          GOOGLE_CREDS_JSON: ${{ secrets.GOOGLE_CREDS_JSON }}
        run: python linkedin_automation.py
```

Since this one is fully automated (no manual export step needed, unlike Email), the scheduled trigger actually does its job here — this will genuinely run itself every week.

---

## 9. Step 7 — The Prompt for Qoder

```
Build a new script called linkedin_automation.py in this project, alongside the existing email_automation.py.

Purpose: search Google (via the Searlo API) for LinkedIn profiles of e-commerce store owners, filter them by keyword, and log qualified and unqualified results into two separate Google Sheets tabs.

Requirements:

1. Authenticate to Searlo using the SEARLO_API_KEY environment variable, sent as an x-api-key header. Confirm Searlo's exact current endpoint and request/response format from their live docs (searlo.tech/docs) before finalizing the request code — don't assume the shape without checking, since I've seen conflicting endpoint paths mentioned online (some sources reference /search/simple, others /api/v1/search).

2. Run these search queries in sequence (treat this list as configurable, e.g. a Python list at the top of the file, so I can edit it later without touching the logic):
   - site:linkedin.com/in "founder" "shopify store"
   - site:linkedin.com/in "owner" "online store"
   - site:linkedin.com/in "founder" "ecommerce brand"
   - site:linkedin.com/in "co-founder" "apparel brand"
   - site:linkedin.com/in "founder" "skincare brand"

3. For each search result returned, extract: the person's name (parse from the title if not given separately), the LinkedIn profile URL, and the snippet/description text. Discard any result whose URL doesn't contain "linkedin.com/in/".

4. Apply a keyword filter to the combined title+snippet text:
   - INCLUDE_KEYWORDS (must contain at least one): founder, owner, co-founder, ceo
   - EXCLUDE_KEYWORDS (if any present, auto-fail regardless of include match): agency, consulting, marketing, freelance, virtual assistant, saas, software, developer, consultant
   - Make both keyword lists easy-to-edit Python lists/constants at the top of the file.
   - Results that include-match AND have no exclude-match = PASS. Everything else = FAIL.

5. Connect to Google Sheets using the same service-account method as email_automation.py (GOOGLE_CREDS_JSON, SHEET_ID env vars). Read from and write to two tabs: "LinkedIn" (for PASS results) and "LinkedIn-Backup" (for FAIL results).

6. Deduplicate: before appending, check each tab against its own existing rows only (by LinkedIn profile URL) — never compare LinkedIn tab against LinkedIn-Backup tab, and never against the Email tab.

7. Column format for both tabs, in order: Name, Business/Profile (the LinkedIn profile URL), Platform ("LinkedIn"), Date Found (today's date), then blank strings for Message Sent, Response, Follow-up 1, Follow-up 2, Status.

8. Add clear print/log statements: total queries run, total raw results fetched, how many passed vs failed the filter, how many were skipped as duplicates, how many new rows were added to each tab.

9. No hardcoded secrets anywhere — everything from environment variables.

10. Also create .github/workflows/linkedin_automation.yml with a weekly cron trigger (Monday 9 AM UTC) plus a workflow_dispatch trigger for manual testing, following the same pattern as the existing email_automation.yml if one exists in this repo.

After building, tell me exactly what new GitHub secret I need to add (SEARLO_API_KEY) and how to test this locally before pushing, the same way we tested the email script.

Do not run or execute anything yourself — I will test locally with my own Searlo API key.
```

---

## 10. Step 8 — Test Locally Before Relying on the Schedule

1. Add `SEARLO_API_KEY` to your local `.env` file alongside the existing Email secrets.
2. Run `python linkedin_automation.py` locally.
3. Check both new tabs — did qualified leads land in `LinkedIn`, and did the filtered-out ones land in `LinkedIn-Backup` instead of being lost?
4. Spot-check a handful of `LinkedIn` rows manually — do these actually look like real store owners, or is the filter still letting noise through? Tighten the include/exclude lists if needed.
5. Run it a second time immediately — confirm dedup blocks repeats in both tabs.
6. Push to GitHub once it looks clean, trigger it manually once via the Actions tab (`workflow_dispatch`) to confirm it runs the same way in GitHub's environment as it did locally.

---

## 11. Weekly Maintenance

- [ ] Check Searlo's remaining credits monthly.
- [ ] Once a week, glance at `LinkedIn-Backup` — if it's much bigger than `LinkedIn`, your filter is too strict (or your search queries are too narrow) and it's worth loosening.
- [ ] If `LinkedIn` comes up short of 15-20 for the week, manually review `LinkedIn-Backup` for anything worth promoting by hand (per your own decision — no auto-promotion).
- [ ] Periodically revisit the search query list (Section 5) — add new product verticals, retire ones that aren't yielding results.

---

## 12. Common Issues

| Problem | Likely Cause | Fix |
|---|---|---|
| Almost everything fails the filter | Include keywords too narrow, or exclude list too aggressive | Loosen filters, re-test |
| Almost nothing gets excluded (LinkedIn tab full of agencies) | Exclude list missing common noise terms | Review a sample of bad results, add their common terms to EXCLUDE_KEYWORDS |
| Searlo API errors | Endpoint path or auth header mismatch | Recheck searlo.tech/docs for current spec |
| Duplicate rows | Dedup comparing wrong field or against wrong tab | Confirm profile-URL comparison is scoped to the correct tab only |
| GitHub Action doesn't fire on schedule | Repo inactive 60+ days | Push a commit or trigger manually to reset |
