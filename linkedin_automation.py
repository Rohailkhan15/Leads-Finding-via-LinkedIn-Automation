"""
LinkedIn Lead-Generation Automation (standalone repo)
=====================================================

Searches Google's public index of LinkedIn profile pages via the Searlo API,
filters results for genuine e-commerce store owners, and logs them into two
tabs of one Google Sheet:

    * "LinkedIn"        -> results that PASS the keyword filter
    * "LinkedIn-Backup" -> results that FAIL (parked for manual review)

This repo is completely independent of the Email automation. It happens to
write into the same spreadsheet, but only ever touches the two tabs above.
It never reads, writes, or references an "Email" tab.

Nothing here talks to LinkedIn's servers -- it only reads public Google
search results, so LinkedIn's Terms of Service are not implicated.

All secrets come from environment variables:
    SEARLO_API_KEY     -- Searlo API key (starts with "sk_")
    SHEET_ID           -- Google Sheet ID (between /d/ and /edit in the URL)
    GOOGLE_CREDS_JSON  -- full contents of the service-account JSON key

Searlo endpoint verified against https://searlo.tech/docs:
    Base URL  : https://api.searlo.tech/api/v1
    Endpoint  : GET /search/web   (current; "/search/simple" is now legacy)
    Auth      : "x-api-key" header
    Response  : { "success": true, "items": [ {title, link, snippet, ...} ] }
The parser below also understands the legacy {"data": {"results": [...]}}
shape so the script keeps working even if the endpoint format shifts.
"""

import json
import os
import re
import sys
import time
from datetime import date

import requests
from dotenv import load_dotenv
import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

# Load a local .env if present (used for local testing only; harmless in CI
# where the values are already provided as real environment variables).
load_dotenv()


# ----------------------------------------------------------------------------
# CONFIG -- edit these lists freely; the logic below does not need touching.
# ----------------------------------------------------------------------------

# Google dorks to run, in sequence. Add / remove / reword as needed.
SEARCH_QUERIES = [
    'site:linkedin.com/in "owner" "online store" Pakistan', 
    'site:linkedin.com/in "owner" "small business" "shop" Pakistan',
    'site:linkedin.com/in "owner" "e-commerce shop" Pakistan',
    'site:linkedin.com/in "owner" "e-commerce store" Pakistan',
    'site:linkedin.com/in "founder" "online store" Pakistan',
    'site:linkedin.com/in "started my own online store" Pakistan',
    'site:linkedin.com/in "founder" "e-commerce shop" Pakistan',
    'site:linkedin.com/in "owner" "online store" India',
    'site:linkedin.com/in "owner" "small business" "shop" India',
    'site:linkedin.com/in "owner" "e-commerce shop" India',
    'site:linkedin.com/in "owner" "e-commerce store" India',
    'site:linkedin.com/in "founder" "online store" India',
    'site:linkedin.com/in "started my own online store" India',
    'site:linkedin.com/in "founder" "e-commerce shop" India',
    'site:linkedin.com/in "owner" "online store"', 
    'site:linkedin.com/in "owner" "small business" "shop"',
    'site:linkedin.com/in "owner" "e-commerce shop"',
    'site:linkedin.com/in "owner" "e-commerce store"',
    'site:linkedin.com/in "founder" "online store"',
    'site:linkedin.com/in "started my own online store"',
    'site:linkedin.com/in "founder" "e-commerce shop"',
]

# A result must contain AT LEAST ONE ROLE keyword AND AT LEAST ONE
# SMALL_BUSINESS keyword to pass (case-insensitive substring). Missing either
# category = FAIL.
ROLE_KEYWORDS = [
    "owner",
    "founder",
    "co-founder",
]

SMALL_BUSINESS_KEYWORDS = [
    "small business",
    "boutique",
    "solopreneur",
    "independent",
    "one-person",
    "self-funded",
    "bootstrapped",
    "handmade",
    "my online store",
    "started my own",
]

# If ANY of these are present, the result auto-FAILS regardless of any
# role / small-business matches (case-insensitive substring).
EXCLUDE_KEYWORDS = [
    "agency",
    "consulting",
    "marketing",
    "freelance",
    "virtual assistant",
    "saas",
    "software",
    "developer",
    "consultant",
    "president",
    "vp",
    "vice president",
    "director",
    "head of",
    "shopify inc",
    "shopify partner",
    "team member",
    "employee",
]

# --- Searlo API -------------------------------------------------------------
SEARLO_BASE_URL = "https://api.searlo.tech/api/v1"
SEARLO_SEARCH_ENDPOINT = "/search/web"   # current recommended endpoint
RESULTS_PER_QUERY = 10                    # API maximum per page is 10
REQUEST_TIMEOUT = 30                      # seconds
MAX_RETRIES = 3                           # per query, for rate-limit/5xx
REQUEST_DELAY = 1.0                       # polite pause between queries (s)

# --- Google Sheets ----------------------------------------------------------
PASS_TAB = "LinkedIn"          # qualified leads
FAIL_TAB = "LinkedIn-Backup"   # filtered-out leads, parked for review
PLATFORM_LABEL = "LinkedIn"
SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order for both tabs. "Business/Profile" holds the profile URL.
SHEET_HEADER = [
    "Name",
    "Business/Profile",
    "Platform",
    "Date Found",
    "Message Sent",
    "Response",
    "Follow-up 1",
    "Follow-up 2",
    "Status",
]


# ----------------------------------------------------------------------------
# Searlo search
# ----------------------------------------------------------------------------

def _retry_delay(response, default=5.0):
    """Best-effort delay (seconds) before retrying a rate-limited request."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("retryAfter"):
            return float(body["retryAfter"])
    except (ValueError, AttributeError):
        pass
    header = response.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return default


def _extract_items(data):
    """
    Pull the result list out of a Searlo response. Searlo has used more than
    one envelope shape, so probe several known containers in priority order
    instead of assuming a single "items" key. Returns [] if none hold a list.
    """
    if not isinstance(data, dict):
        return []
    if data.get("success") is False:
        print(f"    ! Searlo reported success=false: {data.get('message', '(no message)')}")
        return []

    # Top-level containers (covers "items", legacy "data" as a list, etc.).
    for key in ("items", "results", "organic", "web", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    # Results nested under a "data" object.
    payload = data.get("data")
    if isinstance(payload, dict):
        for key in ("items", "results", "organic", "web"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

    return []


def _dump_empty_response(payload, raw_text):
    """
    Called when a 200 OK response yields zero parsed items. Prints enough of
    the real response to reveal its actual shape (or confirm the search truly
    found nothing), so the parser or query can be corrected without guesswork.
    Set the DEBUG environment variable for a longer body dump.
    """
    if isinstance(payload, dict):
        print(f"    i HTTP 200 but parsed 0 items. Top-level keys: {list(payload.keys())}")
        info = payload.get("searchInformation")
        if isinstance(info, dict):
            print(f"    i searchInformation: totalResults={info.get('totalResults')!r}, "
                  f"query={info.get('query')!r}")
        data = payload.get("data")
        if isinstance(data, dict):
            print(f"    i 'data' keys: {list(data.keys())}")
        if payload.get("message"):
            print(f"    i message: {payload.get('message')!r}")
    limit = 2000 if os.environ.get("DEBUG") else 900
    print(f"    i Raw response body (first {limit} chars):")
    print("      " + raw_text[:limit].replace("\n", "\n      "))


def searlo_search(query, api_key):
    """
    Run one query against Searlo and return a list of raw result dicts
    (each typically containing title / link / snippet). Returns [] on any
    non-retryable failure so the run continues with the remaining queries.
    """
    url = SEARLO_BASE_URL + SEARLO_SEARCH_ENDPOINT
    headers = {"x-api-key": api_key}
    params = {"q": query, "limit": RESULTS_PER_QUERY, "page": 1}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params,
                                    timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            print(f"    ! Network error (attempt {attempt}/{MAX_RETRIES}): {exc}")
            time.sleep(REQUEST_DELAY * attempt)
            continue

        if response.status_code == 200:
            raw_text = response.text
            try:
                payload = response.json()
            except ValueError:
                print("    ! Could not parse Searlo response as JSON.")
                print(f"    ! Raw body (first 900 chars): {raw_text[:900]}")
                return []
            items = _extract_items(payload)
            if not items:
                _dump_empty_response(payload, raw_text)
            return items

        # Retryable: rate limit or upstream warming/unavailable.
        if response.status_code in (429, 502, 503):
            delay = _retry_delay(response)
            print(f"    ! HTTP {response.status_code} (attempt {attempt}/{MAX_RETRIES}); "
                  f"retrying in {delay:.0f}s")
            time.sleep(delay)
            continue

        # Non-retryable: surface a clear, actionable message and stop.
        if response.status_code == 401:
            print("    ! HTTP 401 -- invalid or missing SEARLO_API_KEY.")
        elif response.status_code == 402:
            print("    ! HTTP 402 -- Searlo out of credits (INSUFFICIENT_CREDITS).")
        elif response.status_code == 403:
            print("    ! HTTP 403 -- Searlo account disabled/forbidden.")
        else:
            print(f"    ! HTTP {response.status_code}: {response.text[:200]}")
        return []

    print(f"    ! Giving up on query after {MAX_RETRIES} attempts.")
    return []


# ----------------------------------------------------------------------------
# Result parsing & filtering
# ----------------------------------------------------------------------------

def is_linkedin_profile(url):
    """True only for real LinkedIn profile URLs."""
    return "linkedin.com/in/" in url.lower()


def normalize_url(url):
    """
    Normalize a profile URL for dedup: lowercase, drop query string/fragment
    and any trailing slash so cosmetic differences don't defeat dedup.
    """
    u = url.strip().lower()
    u = u.split("?", 1)[0].split("#", 1)[0]
    return u.rstrip("/")


def parse_name_from_title(title):
    """
    Searlo does not return a separate name field, so parse it from the title.
    LinkedIn titles look like:
        "Jane Doe - Founder, Acme Co - LinkedIn"
        "Jane Doe | Owner | Acme | LinkedIn"
        "Jane Doe – Acme – LinkedIn"
    Take the first segment (the name) and strip a trailing "LinkedIn" marker.
    """
    if not title:
        return ""
    text = title.strip()
    # Remove a trailing "LinkedIn" and any separator right before it.
    text = re.sub(r"[\s|·–—-]+linkedin\s*$", "", text, flags=re.IGNORECASE).strip()
    # Treat spaced dashes / pipes / middots as segment separators, then split.
    text = re.sub(r"\s+[-–—|·]\s+|\s*[|·]\s*", " | ", text)
    first = text.split("|")[0].strip()
    return first or title.strip()


def passes_filter(text):
    """
    PASS = at least one ROLE keyword AND at least one SMALL_BUSINESS keyword
    AND no EXCLUDE keyword. Matching is a case-insensitive substring search
    over the combined title + snippet. Missing either positive category, or
    hitting any exclude term, = FAIL.
    """
    lowered = text.lower()
    has_role = any(kw.lower() in lowered for kw in ROLE_KEYWORDS)
    has_small_business = any(kw.lower() in lowered for kw in SMALL_BUSINESS_KEYWORDS)
    has_exclude = any(kw.lower() in lowered for kw in EXCLUDE_KEYWORDS)
    return has_role and has_small_business and not has_exclude


def make_row(name, url, today):
    """Build one sheet row in the required column order."""
    return [name, url, PLATFORM_LABEL, today, "", "", "", "", ""]


# ----------------------------------------------------------------------------
# Google Sheets helpers
# ----------------------------------------------------------------------------

def connect_spreadsheet():
    """Authorize with the service account and open the target spreadsheet."""
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    sheet_id = os.environ.get("SHEET_ID")
    if not creds_json or not sheet_id:
        sys.exit("ERROR: GOOGLE_CREDS_JSON and SHEET_ID environment variables are required.")

    try:
        creds_info = json.loads(creds_json)
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: GOOGLE_CREDS_JSON is not valid JSON: {exc}")

    credentials = Credentials.from_service_account_info(creds_info, scopes=SHEET_SCOPES)
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def get_or_create_worksheet(spreadsheet, title):
    """Return the tab, creating it (with a header row) if it doesn't exist."""
    try:
        return spreadsheet.worksheet(title)
    except WorksheetNotFound:
        print(f"  + Tab '{title}' not found -- creating it with a header row.")
        worksheet = spreadsheet.add_worksheet(title=title, rows=200,
                                              cols=len(SHEET_HEADER))
        worksheet.append_row(SHEET_HEADER)
        return worksheet


def ensure_header(worksheet):
    """Write the header row if the tab is currently empty."""
    values = worksheet.get_all_values()
    if not values or not any(str(cell).strip() for cell in values[0]):
        worksheet.append_row(SHEET_HEADER)


def existing_profile_urls(worksheet):
    """
    Set of normalized profile URLs already in THIS tab (column B), skipping
    the header row. Used to dedup a tab against its own rows only.
    """
    values = worksheet.get_all_values()
    urls = set()
    for row in values[1:]:  # skip header
        if len(row) >= 2:
            normalized = normalize_url(str(row[1]))
            if normalized:
                urls.add(normalized)
    return urls


def append_rows(worksheet, rows):
    """Append rows (if any) and return how many were written."""
    if not rows:
        return 0
    worksheet.append_rows(rows, value_input_option="RAW")
    return len(rows)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("LinkedIn Lead-Generation Automation")
    print("=" * 70)

    api_key = os.environ.get("SEARLO_API_KEY")
    if not api_key:
        sys.exit("ERROR: SEARLO_API_KEY environment variable is required.")

    # 1) Run every query and collect raw results.
    raw_items = []
    for index, query in enumerate(SEARCH_QUERIES, start=1):
        print(f"\n[{index}/{len(SEARCH_QUERIES)}] Searching: {query}")
        items = searlo_search(query, api_key)
        print(f"    -> {len(items)} raw result(s)")
        raw_items.extend(items)
        time.sleep(REQUEST_DELAY)

    print("\n" + "-" * 70)
    print(f"Total queries run        : {len(SEARCH_QUERIES)}")
    print(f"Total raw results fetched: {len(raw_items)}")

    # 2) Clean, classify, and de-duplicate within this run.
    today = date.today().strftime("%Y-%m-%d")
    seen_urls = set()
    pass_rows = []
    fail_rows = []
    discarded_non_linkedin = 0
    intra_run_duplicates = 0

    for item in raw_items:
        url = str(item.get("link") or item.get("url") or "").strip()
        if not is_linkedin_profile(url):
            discarded_non_linkedin += 1
            continue

        normalized = normalize_url(url)
        if normalized in seen_urls:
            intra_run_duplicates += 1
            continue
        seen_urls.add(normalized)

        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or item.get("description") or "").strip()
        name = parse_name_from_title(title)

        if passes_filter(f"{title} {snippet}"):
            pass_rows.append(make_row(name, url, today))
        else:
            fail_rows.append(make_row(name, url, today))

    print(f"Discarded (not linkedin.com/in/): {discarded_non_linkedin}")
    print(f"Duplicate URLs within this run  : {intra_run_duplicates}")
    print(f"PASS (qualified)   : {len(pass_rows)}")
    print(f"FAIL (backup)      : {len(fail_rows)}")

    # 3) Connect to the Sheet and dedup each tab against its OWN rows only.
    print("\n" + "-" * 70)
    spreadsheet = connect_spreadsheet()

    pass_ws = get_or_create_worksheet(spreadsheet, PASS_TAB)
    fail_ws = get_or_create_worksheet(spreadsheet, FAIL_TAB)
    ensure_header(pass_ws)
    ensure_header(fail_ws)

    existing_pass = existing_profile_urls(pass_ws)
    existing_fail = existing_profile_urls(fail_ws)

    new_pass = [r for r in pass_rows if normalize_url(r[1]) not in existing_pass]
    new_fail = [r for r in fail_rows if normalize_url(r[1]) not in existing_fail]

    dupes_pass_skipped = len(pass_rows) - len(new_pass)
    dupes_fail_skipped = len(fail_rows) - len(new_fail)

    # 4) Append the new rows to each tab.
    added_pass = append_rows(pass_ws, new_pass)
    added_fail = append_rows(fail_ws, new_fail)

    # 5) Final summary.
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Tab '{PASS_TAB}':")
    print(f"    duplicates skipped (already in tab): {dupes_pass_skipped}")
    print(f"    new rows added                     : {added_pass}")
    print(f"Tab '{FAIL_TAB}':")
    print(f"    duplicates skipped (already in tab): {dupes_fail_skipped}")
    print(f"    new rows added                     : {added_fail}")
    print("=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
