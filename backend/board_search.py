"""Job board search adapters. Each returns (jobs, error) where jobs are normalized dicts."""

import json
import logging
import re
from urllib.parse import quote, quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

BOARDS = {
    "linkedin": {"label": "LinkedIn", "search": True},
    "naukri": {"label": "Naukri", "search": True},
    "indeed": {"label": "Indeed", "search": True},
    "internshala": {"label": "Internshala", "search": True},
    "wellfound": {"label": "Wellfound", "search": True},
    "instahyre": {"label": "Instahyre", "search": True},
    "remotive": {"label": "Remotive (remote jobs)", "search": True},
    "arbeitnow": {"label": "Arbeitnow", "search": True},
    "other": {"label": "Other job sites", "search": False},
}

HOST_TO_BOARD = [
    ("linkedin.", "linkedin"), ("naukri.", "naukri"), ("indeed.", "indeed"),
    ("internshala.", "internshala"), ("wellfound.", "wellfound"), ("angel.co", "wellfound"),
    ("instahyre.", "instahyre"), ("remotive.", "remotive"), ("arbeitnow.", "arbeitnow"),
]


def board_from_url(url: str) -> str:
    host = re.sub(r"^https?://", "", (url or "").lower()).split("/")[0]
    return next((b for key, b in HOST_TO_BOARD if key in host), "other")


def _job(board, url, title, company="", location="", description="", skills=None, external_id=""):
    return {
        "board": board, "url": url, "external_id": str(external_id or url),
        "title": (title or "").strip()[:200], "company": (company or "").strip()[:200],
        "location": (location or "").strip()[:200], "description": (description or "").strip()[:20000],
        "skills": [s for s in (skills or []) if s][:30],
    }


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


async def _get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    return await client.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                                          **kw.pop("headers", {})}, **kw)


async def search_linkedin(client, keyword, location, limit):
    r = await _get(client, "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                           f"?keywords={quote_plus(keyword)}&location={quote_plus(location or 'India')}&start=0")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    jobs = []
    for card in soup.select("div.base-card")[:limit]:
        link = card.select_one("a.base-card__full-link")
        urn = card.get("data-entity-urn", "")
        job_id = urn.split(":")[-1] if urn else ""
        if not link or not job_id:
            continue
        jobs.append(_job("linkedin", f"https://www.linkedin.com/jobs/view/{job_id}/",
                         _text(card.select_one("h3")), _text(card.select_one("h4")),
                         _text(card.select_one(".job-search-card__location")), external_id=job_id))
    return jobs


async def linkedin_description(client, job_id: str) -> str:
    try:
        r = await _get(client, f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
        if r.status_code != 200:
            return ""
        return _text(BeautifulSoup(r.text, "lxml").select_one(".show-more-less-html__markup"))
    except Exception:
        return ""


async def search_internshala(client, keyword, location, limit):
    slug = quote(re.sub(r"\s+", "-", keyword.strip().lower()))
    r = await _get(client, f"https://internshala.com/jobs/keywords-{slug}/")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    jobs = []
    for card in soup.select(".individual_internship")[:limit]:
        href = card.get("data-href") or ""
        if not href:
            continue
        jobs.append(_job("internshala", f"https://internshala.com{href}",
                         _text(card.select_one(".job-internship-name")), _text(card.select_one(".company-name")),
                         _text(card.select_one(".locations")), _text(card.select_one(".about_job .text")),
                         [_text(s) for s in card.select(".job_skill")], external_id=card.get("internshipid", href)))
    return jobs


async def search_wellfound(client, keyword, location, limit):
    slug = quote(re.sub(r"\s+", "-", keyword.strip().lower()))
    r = await _get(client, f"https://wellfound.com/role/{slug}")
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("Wellfound page format changed or access was blocked")
    data = json.loads(m.group(1))["props"]["pageProps"].get("apolloState", {}).get("data", {})
    company_of = {}
    for key, val in data.items():
        if key.startswith("StartupResult"):
            for ref in val.get("highlightedJobListings", []):
                company_of[ref.get("__ref")] = val.get("name", "")
    jobs = []
    for key, val in data.items():
        if not key.startswith("JobListing") or len(jobs) >= limit:
            continue
        jobs.append(_job("wellfound", f"https://wellfound.com/jobs/{val.get('id')}-{val.get('slug', '')}",
                         val.get("title"), company_of.get(key, ""), ", ".join(val.get("locationNames") or []),
                         val.get("description", ""), external_id=val.get("id")))
    return jobs


async def search_instahyre(client, keyword, location, limit):
    r = await _get(client, f"https://www.instahyre.com/api/v1/job_search?skills={quote_plus(keyword)}&limit={limit}")
    r.raise_for_status()
    jobs = []
    for o in r.json().get("objects", [])[:limit]:
        emp = o.get("employer") or {}
        jobs.append(_job("instahyre", o.get("public_url", ""), o.get("title"), emp.get("company_name", ""),
                         o.get("locations", ""), emp.get("instahyre_note", ""), o.get("keywords", []),
                         external_id=o.get("id")))
    return [j for j in jobs if j["url"]]


async def search_remotive(client, keyword, location, limit):
    r = await _get(client, f"https://remotive.com/api/remote-jobs?search={quote_plus(keyword)}&limit={limit}")
    r.raise_for_status()
    words = [w for w in keyword.lower().split() if len(w) > 2]
    hits = [j for j in r.json().get("jobs", [])
            if not words or any(w in (j.get("title", "") + " " + " ".join(j.get("tags", []))).lower() for w in words)]
    return [_job("remotive", j.get("url", ""), j.get("title"), j.get("company_name"),
                 j.get("candidate_required_location", ""),
                 BeautifulSoup(j.get("description", ""), "lxml").get_text(" ", strip=True),
                 j.get("tags", []), external_id=j.get("id")) for j in hits[:limit]]


async def search_arbeitnow(client, keyword, location, limit):
    r = await _get(client, "https://www.arbeitnow.com/api/job-board-api")
    r.raise_for_status()
    words = [w for w in keyword.lower().split() if w]
    jobs = []
    for j in r.json().get("data", []):
        hay = (j.get("title", "") + " " + " ".join(j.get("tags", []))).lower()
        if words and not all(w in hay for w in words):
            continue
        jobs.append(_job("arbeitnow", j.get("url", ""), j.get("title"), j.get("company_name"), j.get("location", ""),
                         BeautifulSoup(j.get("description", ""), "lxml").get_text(" ", strip=True),
                         j.get("tags", []), external_id=j.get("slug")))
        if len(jobs) >= limit:
            break
    return jobs


async def search_naukri(client, keyword, location, limit):
    r = await _get(client, "https://www.naukri.com/jobapi/v3/search?noOfResults=20&urlType=search_by_keyword"
                           f"&searchType=adv&keyword={quote_plus(keyword)}&pageNo=1",
                   headers={"appid": "109", "systemid": "Naukri", "Accept": "application/json"})
    if r.status_code == 406 or "recaptcha" in r.text.lower():
        raise RuntimeError("Naukri requires a captcha for automated search - save Naukri jobs with the browser helper")
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobDetails", [])[:limit]:
        jobs.append(_job("naukri", "https://www.naukri.com" + j.get("jdURL", ""), j.get("title"),
                         j.get("companyName"), "", BeautifulSoup(j.get("jobDescription", ""), "lxml").get_text(" ", strip=True),
                         (j.get("tagsAndSkills") or "").split(","), external_id=j.get("jobId")))
    return jobs


async def search_indeed(client, keyword, location, limit):
    r = await _get(client, f"https://in.indeed.com/jobs?q={quote_plus(keyword)}&l={quote_plus(location or '')}")
    if r.status_code in (403, 429) or "captcha" in r.text.lower()[:5000]:
        raise RuntimeError("Indeed blocks automated search - save Indeed jobs with the browser helper")
    r.raise_for_status()
    m = re.search(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]=(\{.*?\});', r.text, re.S)
    if not m:
        raise RuntimeError("Indeed page format changed - save Indeed jobs with the browser helper")
    results = json.loads(m.group(1)).get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
    return [_job("indeed", f"https://in.indeed.com/viewjob?jk={j.get('jobkey')}", j.get("title"), j.get("company"),
                 j.get("formattedLocation", ""), j.get("snippet", ""), external_id=j.get("jobkey"))
            for j in results[:limit]]


SEARCHERS = {
    "linkedin": search_linkedin, "internshala": search_internshala, "wellfound": search_wellfound,
    "instahyre": search_instahyre, "remotive": search_remotive, "arbeitnow": search_arbeitnow,
    "naukri": search_naukri, "indeed": search_indeed,
}


async def search_board(board: str, keyword: str, location: str, limit: int = 10) -> tuple[list, str | None]:
    fn = SEARCHERS.get(board)
    if not fn:
        return [], "Automatic search is not available for this board"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            jobs = await fn(client, keyword, location, limit)
            if board == "linkedin":
                for job in jobs[:limit]:
                    job["description"] = await linkedin_description(client, job["external_id"])
            return jobs, None
    except Exception as exc:
        logger.info("Board search %s failed: %s", board, exc)
        return [], str(exc)[:200]
