#!/usr/bin/env python3
"""
초음파 산업 & 인간공학 연구 뉴스레터
- 지난 24시간 내 신뢰 가능한 주요 초음파 회사 뉴스 수집
- 중복 이슈 제거 및 회사별 그룹핑
- 기사별 영문 1줄 요약 + 한국어 1줄 요약 제공
- 인간공학 논문: 초록 한국어 번역 / 주요 연구 방법 / 핵심 연구 결과 / 삼성메디슨 UX 인사이트 제공
- GitHub Actions 5분 내 실행 지향
"""

import os
import re
import json
import html
import time
import math
import smtplib
import datetime as dt
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

import feedparser
import requests

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

# ── 환경 설정 ──────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "j0503.kim@gmail.com")
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "")

REQUEST_TIMEOUT = (4, 10)
GEMINI_TIMEOUT = 22
MAX_WORKERS = 8
MAX_NEWS_PER_QUERY = 6
MAX_NEWS_PER_COMPANY = 4
MAX_TOTAL_NEWS = 36
MAX_PAPERS = 5

USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (compatible; UltrasoundErgoDigest/1.0; +https://github.com/)"
}

SESSION = requests.Session()
SESSION.headers.update(USER_AGENT)

# ── 신뢰 가능한 뉴스 출처 ────────────────────────────────────
TRUSTED_SOURCES = {
    # company / official style names that can appear in Google News source field
    "GE HealthCare", "Philips", "Siemens Healthineers", "Samsung Medison", "Samsung Healthcare",
    "Canon Medical Systems", "Mindray", "FUJIFILM Healthcare", "FUJIFILM Sonosite", "Sonosite",
    "Esaote", "Butterfly Network", "Exo", "Clarius", "EchoNous", "Healcerion",
    "Alpinion", "SonoScape", "CHISON", "VINNO", "SIUI", "Wisonic", "Edan", "Landwind Medical",
    # specialist / trade media
    "AuntMinnie", "Imaging Technology News", "ITN", "MassDevice", "MedTech Dive",
    "Medical Device Network", "Diagnostic Imaging", "Medgadget", "Healthcare-in-Europe",
    # regulators
    "FDA", "U.S. Food and Drug Administration", "openFDA",
}

SPECIALIST_RSS_FEEDS = [
    ("AuntMinnie", "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("MassDevice", "https://www.massdevice.com/feed/"),
    ("MedTech Dive", "https://www.medtechdive.com/feeds/news/"),
    ("Medical Device Network", "https://www.medicaldevice-network.com/feed/"),
]

# 주요 회사별 검색 질의. Google News RSS에서 회사+초음파/의료영상 문맥을 함께 잡는다.
COMPANY_QUERIES = {
    "GE HealthCare": '"GE HealthCare" (ultrasound OR BK Medical OR Voluson OR LOGIQ OR Vscan OR imaging)',
    "Philips": 'Philips (ultrasound OR EPIQ OR Affiniti OR Compact OR imaging)',
    "Siemens Healthineers": '"Siemens Healthineers" (ultrasound OR ACUSON OR imaging)',
    "Samsung Medison": '"Samsung Medison" OR "Samsung HME America" OR "Boston Imaging" OR NeuroLogica (ultrasound OR imaging OR medical imaging)',
    "Canon Medical": '"Canon Medical" (ultrasound OR Aplio OR Viamo OR imaging)',
    "Mindray": 'Mindray (ultrasound OR Resona OR TEX OR TE Air OR imaging)',
    "FUJIFILM / Sonosite": '"FUJIFILM Sonosite" OR Sonosite OR "FUJIFILM Healthcare" (ultrasound OR POCUS OR imaging)',
    "Esaote": 'Esaote (ultrasound OR MyLab OR imaging)',
    "Butterfly Network": '"Butterfly Network" OR "Butterfly iQ" (ultrasound OR handheld OR POCUS)',
    "Clarius": 'Clarius (ultrasound OR handheld OR POCUS)',
    "EchoNous": 'EchoNous OR Kosmos (ultrasound OR POCUS OR imaging)',
    "Exo": 'Exo OR "Exo Iris" (ultrasound OR handheld OR imaging)',
    "Alpinion": 'Alpinion (ultrasound OR imaging)',
    "Healcerion": 'Healcerion OR SONON (ultrasound OR handheld)',
    "SonoScape": 'SonoScape (ultrasound OR imaging)',
    "CHISON": 'CHISON (ultrasound OR imaging)',
    "VINNO": 'VINNO (ultrasound OR imaging)',
    "SIUI": 'SIUI (ultrasound OR imaging)',
    "Wisonic": 'Wisonic (ultrasound OR imaging)',
    "Edan": 'Edan (ultrasound OR imaging)',
    "Landwind Medical": '"Landwind Medical" (ultrasound OR imaging)',
}

GENERAL_QUERIES = [
    'ultrasound company launch OR clearance OR partnership OR acquisition OR imaging',
    'POCUS company launch OR FDA clearance OR partnership OR imaging',
]

NOISE_KEYWORDS = [
    "ultrasonic cleaner", "ultrasonic welder", "cleaner", "welding", "industrial", "non-destructive",
    "audio", "speaker", "toothbrush", "humidifier", "sensor", "flow meter", "beauty device",
]

# 기사와 회사 매핑용 별칭
COMPANY_ALIASES = {
    "GE HealthCare": ["ge healthcare", "bk medical", "voluson", "logiq", "vscan"],
    "Philips": ["philips", "epiq", "affiniti"],
    "Siemens Healthineers": ["siemens healthineers", "acuson"],
    "Samsung Medison": ["samsung medison", "samsung hme america", "boston imaging", "neurologica", "v8", "hs40", "hera"],
    "Canon Medical": ["canon medical", "aplio", "viamo"],
    "Mindray": ["mindray", "resona", "tex20", "te air"],
    "FUJIFILM / Sonosite": ["fujifilm sonosite", "fujifilm healthcare", "sonosite", "sonosite lx", "visualsonics"],
    "Esaote": ["esaote", "mylab"],
    "Butterfly Network": ["butterfly network", "butterfly iq", "butterfly iQ", "bfly"],
    "Clarius": ["clarius"],
    "EchoNous": ["echonous", "kosmos"],
    "Exo": ["exo", "exo iris"],
    "Alpinion": ["alpinion"],
    "Healcerion": ["healcerion", "sonon"],
    "SonoScape": ["sonoscape"],
    "CHISON": ["chison"],
    "VINNO": ["vinno"],
    "SIUI": ["siui"],
    "Wisonic": ["wisonic"],
    "Edan": ["edan"],
    "Landwind Medical": ["landwind"],
}

TOPIC_MAP = {
    "초음파 인간공학": ["ultrasound", "sonographer", "transducer", "probe", "scan", "echography"],
    "근골격계질환": ["musculoskeletal", "shoulder", "neck", "wrist", "pain", "tendon", "injury"],
    "작업부하·인지부하": ["workload", "cognitive", "mental demand", "nasa-tlx", "attention", "fatigue"],
    "작업환경 개선": ["workstation", "workplace", "posture", "usability", "interface", "workflow"],
    "생체역학": ["biomechanics", "kinematics", "emg", "force", "motion"],
    "역학·설문": ["survey", "cross-sectional", "cohort", "prevalence", "questionnaire"],
    "AI·기술": ["machine learning", "deep learning", "algorithm", "ai", "computer vision"],
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def safe_html(text: str) -> str:
    return html.escape(text or "")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_html_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return normalize_space(html.unescape(text))


def trim_title_suffix(title: str) -> str:
    title = normalize_space(title)
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def cutoff_24h() -> dt.datetime:
    return now_utc() - dt.timedelta(hours=24)


def parse_entry_datetime(entry) -> dt.datetime | None:
    for key in ["published_parsed", "updated_parsed"]:
        value = entry.get(key)
        if value:
            try:
                return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
    return None


def looks_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def ensure_sentence(text: str, korean_preferred: bool = False) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    if korean_preferred and not looks_korean(text):
        text = translate_ko(text)
        text = normalize_space(text)
    if text and text[-1] not in ".?!…다요":
        if looks_korean(text):
            text += "합니다."
        else:
            text += "."
    return text


def shorten_one_line(text: str, limit: int = 180) -> str:
    text = normalize_space(text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip() + "..."
    return text


def translate_ko(text: str) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    if GoogleTranslator is None:
        return text
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:3200])
    except Exception:
        return text


def source_is_trusted(source: str) -> bool:
    source = normalize_space(source)
    if not source:
        return False
    src_lower = source.lower()
    return any(src_lower == s.lower() or src_lower in s.lower() or s.lower() in src_lower for s in TRUSTED_SOURCES)


def detect_company(text: str) -> str:
    t = (text or "").lower()
    for company, aliases in COMPANY_ALIASES.items():
        if any(alias.lower() in t for alias in aliases):
            return company
    return "기타 초음파 동향"


def news_is_relevant(title: str, snippet: str, company_hint: str = "") -> bool:
    text = f"{title} {snippet} {company_hint}".lower()
    if any(noise in text for noise in NOISE_KEYWORDS):
        return False
    if detect_company(text) != "기타 초음파 동향":
        return True
    keywords = [
        "ultrasound", "sonography", "pocus", "point-of-care", "probe", "transducer", "medical imaging",
        "diagnostic imaging", "echocardiography", "ceus",
    ]
    return any(k in text for k in keywords)


def classify_news_category(title: str, snippet: str) -> str:
    text = f"{title} {snippet}".lower()
    if any(k in text for k in ["510(k)", "clearance", "approval", "de novo", "ce mark", "fda"]):
        return "인허가 승인"
    if any(k in text for k in ["acquisition", "acquire", "merger", "unify", "integration", "partnership", "collaboration", "alliance"]):
        return "인수/합병/파트너십"
    if any(k in text for k in ["study", "clinical", "research", "validation", "trial"]):
        return "임상/연구"
    if any(k in text for k in ["launch", "launched", "introduce", "introduced", "release", "system", "platform", "software"]):
        return "신제품/기술"
    return "시장/경영"


def canonical_title(title: str) -> str:
    t = trim_title_suffix(title).lower()
    t = re.sub(r"[^a-z0-9가-힣 ]", " ", t)
    t = re.sub(r"\b(the|a|an|to|for|of|and|under|new|us)\b", " ", t)
    return normalize_space(t)


def company_priority(company: str) -> int:
    order = list(COMPANY_QUERIES.keys())
    try:
        return order.index(company)
    except ValueError:
        return len(order) + 1


def source_priority(source: str) -> int:
    source = (source or "").lower()
    if "fda" in source:
        return 0
    if any(k in source for k in ["auntminnie", "medical device network", "itn", "imaging technology news", "massdevice", "medtech dive"]):
        return 1
    if any(k in source for k in ["samsung", "philips", "siemens", "canon", "mindray", "fujifilm", "sonosite", "ge healthcare"]):
        return 2
    return 3


def call_gemini_json(prompt: str) -> str:
    if not GEMINI_API_KEY:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "maxOutputTokens": 3500,
            "responseMimeType": "application/json",
        },
    }
    for attempt in range(2):
        try:
            r = SESSION.post(url, json=payload, timeout=GEMINI_TIMEOUT)
            if r.status_code == 200:
                candidates = r.json().get("candidates", [])
                if candidates:
                    return candidates[0]["content"]["parts"][0]["text"].strip()
                return ""
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            return ""
        except Exception:
            return ""
    return ""


def fetch_feed(url: str):
    r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_google_news_rss(query: str, company_label: str) -> list:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    out = []
    try:
        feed = fetch_feed(url)
        for entry in feed.entries[: MAX_NEWS_PER_QUERY * 3]:
            pub_dt = parse_entry_datetime(entry)
            if pub_dt and pub_dt < cutoff_24h():
                continue
            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:360]
            source = normalize_space((entry.get("source") or {}).get("title", "Google News"))
            link = entry.get("link", "")
            if not source_is_trusted(source):
                continue
            if not news_is_relevant(title, snippet, company_label):
                continue
            company = detect_company(f"{company_label} {title} {snippet} {source}")
            if company == "기타 초음파 동향":
                company = company_label
            out.append({
                "title": title,
                "snippet": snippet,
                "url": link,
                "date": entry.get("published", entry.get("updated", "")),
                "source": source,
                "company": company,
                "category": classify_news_category(title, snippet),
                "trust": "trusted_google_news_source",
            })
            if len(out) >= MAX_NEWS_PER_QUERY:
                break
    except Exception as e:
        print(f"Google News RSS 오류 [{company_label}]: {e}")
    return out


def fetch_specialist_feed(name: str, url: str) -> list:
    out = []
    try:
        feed = fetch_feed(url)
        for entry in feed.entries[:18]:
            pub_dt = parse_entry_datetime(entry)
            if pub_dt and pub_dt < cutoff_24h():
                continue
            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:360]
            if not news_is_relevant(title, snippet):
                continue
            company = detect_company(f"{title} {snippet}")
            if company == "기타 초음파 동향" and not any(k in (title + ' ' + snippet).lower() for k in ["ultrasound", "imaging", "pocus", "probe", "transducer"]):
                continue
            out.append({
                "title": title,
                "snippet": snippet,
                "url": entry.get("link", ""),
                "date": entry.get("published", entry.get("updated", "")),
                "source": name,
                "company": company,
                "category": classify_news_category(title, snippet),
                "trust": "trusted_specialist_media",
            })
    except Exception as e:
        print(f"전문매체 RSS 오류 [{name}]: {e}")
    return out


def fetch_fda_510k() -> list:
    today = dt.date.today()
    week_ago = today - dt.timedelta(days=7)
    url = (
        "https://api.fda.gov/device/510k.json?"
        f"search=openfda.device_name:ultrasound+AND+decision_date:[{week_ago:%Y%m%d}+TO+{today:%Y%m%d}]&limit=12"
    )
    out = []
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return out
        for rec in r.json().get("results", []):
            device_name = normalize_space(rec.get("device_name", "N/A"))
            applicant = normalize_space(rec.get("applicant", "N/A"))
            k_number = normalize_space(rec.get("k_number", ""))
            decision_date = normalize_space(rec.get("decision_date", ""))
            # 24시간 규칙에 맞지 않으면 제외
            try:
                d = dt.datetime.strptime(decision_date, "%Y%m%d").replace(tzinfo=dt.timezone.utc)
                if d < cutoff_24h():
                    continue
            except Exception:
                pass
            company = detect_company(f"{device_name} {applicant}")
            out.append({
                "title": f"FDA 510(k) cleared: {device_name}",
                "snippet": f"Applicant: {applicant}; K-number: {k_number}.",
                "url": f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k_number}",
                "date": decision_date,
                "source": "FDA openFDA",
                "company": company if company != "기타 초음파 동향" else "FDA 인허가",
                "category": "인허가 승인",
                "trust": "official_regulatory_source",
            })
    except Exception as e:
        print(f"FDA 오류: {e}")
    return out


def dedupe_news(items: list) -> list:
    best = {}
    for item in items:
        comp = item.get("company", "기타 초음파 동향")
        title_key = canonical_title(item.get("title", ""))
        date_key = normalize_space(item.get("date", ""))[:16]
        key = (comp, title_key, date_key)
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        cur_score = (source_priority(current.get("source", "")), -len(current.get("snippet", "")))
        new_score = (source_priority(item.get("source", "")), -len(item.get("snippet", "")))
        if new_score < cur_score:
            best[key] = item

    # 유사 제목 중복 2차 제거
    grouped = defaultdict(list)
    for item in best.values():
        grouped[item.get("company", "기타 초음파 동향")].append(item)

    final = []
    for company, rows in grouped.items():
        rows = sorted(rows, key=lambda x: (x.get("date", ""), -len(x.get("snippet", ""))), reverse=True)
        seen_title_keys = []
        for row in rows:
            tkey = canonical_title(row.get("title", ""))
            if any(tkey == prev or tkey in prev or prev in tkey for prev in seen_title_keys if len(prev) > 18 and len(tkey) > 18):
                continue
            seen_title_keys.append(tkey)
            final.append(row)
    final.sort(key=lambda x: (company_priority(x.get("company", "")), source_priority(x.get("source", "")), x.get("date", "")), reverse=False)
    return final[:MAX_TOTAL_NEWS]


def build_one_line_summary(item: dict) -> dict:
    title = trim_title_suffix(item.get("title", ""))
    snippet = clean_html_text(item.get("snippet", ""))
    source = item.get("source", "")
    prompt = f"""
다음 기사 1건을 사실 범위를 벗어나지 않고 한 줄로만 요약하세요.
반드시 JSON만 출력합니다.
{{
  "en_one_line": "...",
  "ko_one_line": "..."
}}
규칙:
- 기사 핵심 내용만 1문장으로 요약
- 영어 1문장, 한국어 1문장
- 과장, 추측, 평가 표현 금지
- 한국어는 자연스럽고 매끄러운 문장으로 작성
- 제목과 스니펫에 없는 내용 추가 금지

제목: {title}
출처: {source}
스니펫: {snippet}
"""
    raw = call_gemini_json(prompt)
    if raw:
        try:
            parsed = json.loads(raw)
            en = ensure_sentence(shorten_one_line(parsed.get("en_one_line", ""), 180), korean_preferred=False)
            ko = ensure_sentence(shorten_one_line(parsed.get("ko_one_line", ""), 180), korean_preferred=True)
            if en and ko:
                return {"en": en, "ko": ko}
        except Exception:
            pass

    base = snippet or title
    base = shorten_one_line(base, 170)
    return {
        "en": ensure_sentence(base, korean_preferred=False),
        "ko": ensure_sentence(shorten_one_line(translate_ko(base), 180), korean_preferred=True),
    }


def fetch_all_ultrasound_news() -> list:
    items = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = []
        for company, query in COMPANY_QUERIES.items():
            futures.append(ex.submit(fetch_google_news_rss, query, company))
        for q in GENERAL_QUERIES:
            futures.append(ex.submit(fetch_google_news_rss, q, "기타 초음파 동향"))
        for name, url in SPECIALIST_RSS_FEEDS:
            futures.append(ex.submit(fetch_specialist_feed, name, url))
        futures.append(ex.submit(fetch_fda_510k))

        for fut in as_completed(futures):
            try:
                items.extend(fut.result() or [])
            except Exception as e:
                print(f"뉴스 수집 작업 오류: {e}")

    items = dedupe_news(items)
    # 기사별 1줄 요약 생성
    for item in items:
        summary = build_one_line_summary(item)
        item["one_line_en"] = summary["en"]
        item["one_line_ko"] = summary["ko"]
    return items


# ── 논문 수집 ─────────────────────────────────────────────────
def fetch_pubmed_papers(query: str = "ergonomics", max_results: int = 5) -> list:
    params = {
        "db": "pubmed",
        "term": query,
        "datetype": "edat",
        "reldate": 2,
        "retmax": max_results,
        "retmode": "json",
        "sort": "date",
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY
    try:
        r = SESSION.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, timeout=REQUEST_TIMEOUT)
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        time.sleep(0.34)
        params2 = {"db": "pubmed", "id": ",".join(ids), "rettype": "xml", "retmode": "xml"}
        if PUBMED_API_KEY:
            params2["api_key"] = PUBMED_API_KEY
        r2 = SESSION.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", params=params2, timeout=REQUEST_TIMEOUT)
        root = ET.fromstring(r2.content)
        papers = []
        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            art = medline.find(".//Article") if medline is not None else None
            if art is None:
                continue
            title = normalize_space("".join(art.findtext(".//ArticleTitle", "")))
            abstract = normalize_space(" ".join((a.text or "") for a in art.findall(".//AbstractText")))[:1700]
            if not title or not abstract:
                continue
            authors = []
            for a in art.findall(".//Author")[:8]:
                if a.findtext("LastName"):
                    authors.append(normalize_space(f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}"))
            affil_el = art.find(".//AffiliationInfo/Affiliation")
            affil = normalize_space(affil_el.text if affil_el is not None and affil_el.text else "")[:240]
            journal = normalize_space(art.findtext(".//Journal/Title", ""))
            doi_el = art.find(".//ELocationID[@EIdType='doi']")
            doi = normalize_space(doi_el.text if doi_el is not None else "")
            pmid = medline.findtext(".//PMID", "")
            pub = art.find(".//Journal/JournalIssue/PubDate")
            pub_date = normalize_space(" ".join(filter(None, [
                pub.findtext("Year", "") if pub is not None else "",
                pub.findtext("Month", "") if pub is not None else "",
            ])))
            papers.append({
                "title": title,
                "authors": ", ".join(authors),
                "affiliations": affil,
                "abstract": abstract,
                "doi": doi,
                "journal": journal,
                "pub_date": pub_date,
                "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "PubMed",
                "evidence": "peer_reviewed_or_indexed",
            })
        return papers
    except Exception as e:
        print(f"PubMed 오류: {e}")
        return []


def fetch_arxiv_papers(query: str = "ergonomics", max_results: int = 1) -> list:
    try:
        r = SESSION.get(
            "http://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            timeout=REQUEST_TIMEOUT,
        )
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.content)
        papers = []
        for entry in root.findall("atom:entry", ns):
            pub = entry.findtext("atom:published", "", ns)
            try:
                if dt.datetime.fromisoformat(pub.replace("Z", "+00:00")) < now_utc() - dt.timedelta(days=2):
                    continue
            except Exception:
                pass
            title = normalize_space(entry.findtext("atom:title", "", ns).replace("\n", " "))
            abstract = normalize_space(entry.findtext("atom:summary", "", ns))[:1600]
            if not title or not abstract:
                continue
            authors = [normalize_space(a.findtext("atom:name", "", ns)) for a in entry.findall("atom:author", ns)[:8]]
            papers.append({
                "title": title,
                "authors": ", ".join(authors),
                "affiliations": "",
                "abstract": abstract,
                "doi": "",
                "journal": "arXiv preprint",
                "pub_date": pub[:10],
                "link": entry.findtext("atom:id", "", ns),
                "source": "arXiv",
                "evidence": "preprint",
            })
        return papers
    except Exception as e:
        print(f"arXiv 오류: {e}")
        return []


def fetch_semantic_scholar(query: str = "ergonomics workplace", max_results: int = 1) -> list:
    today = dt.date.today()
    start_day = today - dt.timedelta(days=3)
    try:
        r = SESSION.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "fields": "title,authors,abstract,publicationDate,journal,externalIds",
                "limit": max_results,
                "publicationDateOrYear": f"{start_day}:{today}",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("data", []):
            abstract = normalize_space(p.get("abstract", ""))[:1600]
            if not abstract:
                continue
            doi = normalize_space((p.get("externalIds") or {}).get("DOI", ""))
            out.append({
                "title": normalize_space(p.get("title", "")),
                "authors": ", ".join(normalize_space(a.get("name", "")) for a in (p.get("authors") or [])[:8]),
                "affiliations": "",
                "abstract": abstract,
                "doi": doi,
                "journal": normalize_space((p.get("journal") or {}).get("name", "")),
                "pub_date": p.get("publicationDate", ""),
                "link": f"https://doi.org/{doi}" if doi else "",
                "source": "Semantic Scholar",
                "evidence": "index_metadata",
            })
        return out
    except Exception as e:
        print(f"Semantic Scholar 오류: {e}")
        return []


def get_topic(paper: dict) -> str:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    for topic, keywords in TOPIC_MAP.items():
        if any(k in text for k in keywords):
            return topic
    return "기타"


def extract_sample_info(text: str) -> str:
    t = text.replace("\n", " ")
    m = re.search(r"\b(n\s*=\s*\d+|\d+\s+(participants|patients|subjects|workers|students|clinicians|sonographers))\b", t, re.I)
    if m:
        return normalize_space(m.group(0))
    m2 = re.search(r"\b(\d+)\b", t)
    if m2:
        num = int(m2.group(1))
        if 5 <= num <= 5000:
            return f"표본 약 {num}명"
    return ""


def infer_method_detail(title: str, abstract: str) -> str:
    text = (title + " " + abstract).lower()
    sample = extract_sample_info(abstract)

    if any(k in text for k in ["systematic review", "scoping review", "narrative review", "review", "meta-analysis"]):
        line = "문헌고찰 설계로 관련 선행연구를 선별·검토해 핵심 주제와 설계 요소를 비교했습니다."
        if sample:
            line = f"문헌고찰 설계로 관련 연구를 선별·검토했으며, {sample} 수준의 개별 표본이 아니라 연구 논문들을 비교 대상으로 삼았습니다."
        return line
    if any(k in text for k in ["cross-sectional", "survey", "questionnaire"]):
        base = "단면 설문연구로 참가자의 작업 특성, 증상 또는 인식 변수를 수집해 집단 간 차이와 관련 요인을 분석했습니다."
        if sample:
            base = f"단면 설문연구로 {sample}의 응답을 수집하고, 작업 특성·증상·인식 지표의 차이와 관련 요인을 분석했습니다."
        return base
    if any(k in text for k in ["randomized", "controlled", "trial", "experiment"]):
        base = "비교 실험 또는 시험 설계로 두 개 이상의 조건을 나누어 수행했고, 성능·오류·작업부하 지표를 비교했습니다."
        if sample:
            base = f"비교 실험 또는 시험 설계로 {sample}을 조건별로 비교했고, 수행 성능·오류·작업부하 지표를 평가했습니다."
        return base
    if any(k in text for k in ["emg", "kinematic", "biomechanics", "motion", "force"]):
        base = "생체역학 측정 연구로 자세, 움직임, 힘 또는 근활성도 지표를 수집해 신체 부담을 정량적으로 평가했습니다."
        if sample:
            base = f"생체역학 측정 연구로 {sample}에서 자세·움직임·힘 또는 근활성도 지표를 수집해 신체 부담을 평가했습니다."
        return base
    if any(k in text for k in ["interview", "qualitative", "focus group", "thematic analysis"]):
        base = "정성연구 설계로 인터뷰나 관찰 자료를 수집하고, 반복적으로 나타나는 경험과 문제 패턴을 주제별로 정리했습니다."
        if sample:
            base = f"정성연구 설계로 {sample}을 대상으로 인터뷰·관찰 자료를 수집하고, 반복되는 문제 패턴을 주제별로 정리했습니다."
        return base
    if any(k in text for k in ["machine learning", "deep learning", "algorithm", "model", "classifier"]):
        base = "모델 평가 연구로 알고리즘을 적용해 예측 또는 분류 성능을 비교하고, 정확도 등 핵심 성능 지표를 확인했습니다."
        if sample:
            base = f"모델 평가 연구로 {sample} 또는 해당 데이터셋을 사용해 알고리즘 성능을 비교하고, 정확도 등 지표를 확인했습니다."
        return base
    return "초록에 제시된 연구 대상, 비교 조건, 측정 지표를 바탕으로 연구 설계의 핵심 흐름을 정리했습니다."


def fallback_paper_structured(paper: dict) -> dict:
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    topic = get_topic(paper)
    text = (title + " " + abstract).lower()

    topic_map = {
        "초음파 인간공학": "초음파 검사 과정에서 작업 자세, 조작 방식, 검사 흐름이 사용자 부담에 미치는 영향을 다뤘습니다.",
        "근골격계질환": "반복 작업 환경에서 통증·부담을 유발하는 요인과 이를 줄이기 위한 조건을 다뤘습니다.",
        "작업부하·인지부하": "작업 수행 중 인지부하, 정신적 부담, 피로에 영향을 주는 요인을 다뤘습니다.",
        "작업환경 개선": "작업환경, 인터페이스, 워크플로우 개선이 성능과 부담에 미치는 영향을 다뤘습니다.",
        "생체역학": "자세, 움직임, 힘, 근활성도 같은 생체역학 지표를 통해 작업 부담을 평가했습니다.",
        "역학·설문": "작업 관련 증상과 위험요인을 조사해 우선 관리 대상과 연관 요인을 파악했습니다.",
        "AI·기술": "AI 또는 기술 시스템이 수행 효율과 사용 경험에 미치는 영향을 다뤘습니다.",
    }

    result = "초록에 따르면 조건 차이, 위험요인 또는 설계 요소에 따라 작업부하나 수행 차이가 나타났음을 시사합니다."
    if any(k in text for k in ["improved", "improvement", "reduced", "lower", "decrease"]):
        result = "초록에 따르면 개입 또는 설계 차이에 따라 작업부하, 수행 효율 또는 사용성이 개선됐습니다."
    if any(k in text for k in ["no difference", "noninferiority", "non-inferiority"]):
        result = "초록에 따르면 비교 조건 간 핵심 성능 차이가 크지 않거나, 대체 가능성을 시사하는 결과가 확인됐습니다."
    if any(k in text for k in ["risk", "hazard", "fatigue", "pain", "burden"]):
        result = "초록에 따르면 피로, 통증, 부담 또는 위험 노출과 관련된 핵심 요인이 결과로 제시됐습니다."

    ux = []
    if topic == "초음파 인간공학":
        ux += [
            "검사 중 반복 입력을 줄이도록 측정·주석·저장 흐름을 단축하고, 자주 쓰는 기능을 화면 상단 또는 물리 키에 우선 배치할 필요가 있습니다.",
            "프로브를 쥔 상태에서 한 손으로 조작 가능한 UI를 우선 설계해 손목 회전과 시선 이동을 줄이는 방향으로 개선할 수 있습니다.",
        ]
    elif topic in ["근골격계질환", "생체역학"]:
        ux += [
            "상지 부담을 키우는 작은 클릭 타깃, 깊은 메뉴 구조, 잦은 모드 전환을 줄이는 것이 중요합니다.",
            "검사 시간이 아니라 자세 변화 횟수와 반복 조작 수까지 UX 성과지표에 포함해 개선 우선순위를 정할 수 있습니다.",
        ]
    elif topic in ["작업부하·인지부하", "작업환경 개선"]:
        ux += [
            "핵심 정보의 우선순위를 다시 정해 시선 이동과 인지 전환 비용을 줄이는 화면 구성이 필요합니다.",
            "알림과 확인 단계의 밀도를 줄여 검사 흐름을 끊지 않도록 워크플로우를 정리할 수 있습니다.",
        ]
    elif topic == "AI·기술":
        ux += [
            "AI 결과는 자동 제시만이 아니라 근거, 신뢰도, 수정 경로를 함께 보여 사용자의 판단권을 유지하도록 설계해야 합니다.",
            "자동화 기능 도입 시 기존 검사 흐름을 크게 바꾸지 않는 점진적 인터랙션이 현장 수용성을 높일 수 있습니다.",
        ]
    else:
        ux += [
            "연구에서 제시한 부담 요인과 성능 차이를 실제 초음파 검사 워크플로우의 병목 단계와 연결해 개선 우선순위를 정할 수 있습니다.",
            "시간 절감뿐 아니라 인지부하와 물리적 부담 감소를 함께 UX 성과지표로 관리할 수 있습니다.",
        ]

    return {
        "ko_abstract": ensure_sentence(translate_ko(abstract[:1800]), korean_preferred=True),
        "research_method": ensure_sentence(infer_method_detail(title, abstract), korean_preferred=True),
        "key_result": ensure_sentence(result, korean_preferred=True),
        "research_topic": ensure_sentence(topic_map.get(topic, "논문 초록을 바탕으로 작업부하, 사용성, 수행 성능과 관련된 연구 주제를 다뤘습니다."), korean_preferred=True),
        "ux_insights": [ensure_sentence(x, korean_preferred=True) for x in ux[:3]],
    }


def enrich_papers(papers: list) -> list:
    if not papers:
        return []
    compact = []
    for i, p in enumerate(papers, start=1):
        compact.append({
            "id": i,
            "title": p.get("title", ""),
            "authors": p.get("authors", ""),
            "journal": p.get("journal", ""),
            "pub_date": p.get("pub_date", ""),
            "abstract": p.get("abstract", "")[:1600],
            "topic": get_topic(p),
        })

    parsed = {}
    if GEMINI_API_KEY:
        prompt = f"""
당신은 인간공학 분야 학술 편집자이자 의료기기 UX 전략가입니다.
아래 논문 목록을 읽고 각 논문에 대해 반드시 JSON 배열만 출력하세요.
각 객체 필드:
- id
- ko_title: 자연스러운 한국어 제목
- ko_abstract: 초록의 자연스러운 한국어 번역
- research_method: 주요 연구 방법. 1~3문장. 연구 대상, 실험/조사/문헌고찰 설계, 측정 지표 또는 비교 조건이 드러나야 함.
- key_result: 핵심 연구 결과 1~2문장. 초록 근거만 사용.
- ux_insights: 삼성메디슨 UX 업무 적용 인사이트 2~3개 배열. 구체적으로 작성.

규칙:
- research_method는 처음 보는 사람도 이것만 읽으면 어떤 연구가 어떻게 진행됐는지 이해할 수 있어야 함
- 한국어는 완결 문장으로 쓰고 문장 끝을 마침표로 끝낼 것
- 영어 문장을 그대로 남기지 말 것
- 과장 금지, 초록에 없는 내용 추가 금지

입력 데이터:
{json.dumps(compact, ensure_ascii=False)}
"""
        raw = call_gemini_json(prompt)
        if raw:
            try:
                for row in json.loads(raw):
                    parsed[row.get("id")] = row
            except Exception:
                parsed = {}

    enriched = []
    for i, p in enumerate(papers, start=1):
        fb = fallback_paper_structured(p)
        row = parsed.get(i, {})
        ko_title = ensure_sentence(normalize_space(row.get("ko_title", "")) or translate_ko(p.get("title", "")), korean_preferred=True)
        ko_title = ko_title[:-1] if ko_title.endswith(".") else ko_title
        ko_abstract = ensure_sentence(normalize_space(row.get("ko_abstract", "")) or fb["ko_abstract"], korean_preferred=True)
        research_method = ensure_sentence(normalize_space(row.get("research_method", "")) or fb["research_method"], korean_preferred=True)
        key_result = ensure_sentence(normalize_space(row.get("key_result", "")) or fb["key_result"], korean_preferred=True)
        ux_arr = row.get("ux_insights", []) if isinstance(row.get("ux_insights", []), list) else []
        if not ux_arr:
            ux_arr = fb["ux_insights"]
        ux_arr = [ensure_sentence(x, korean_preferred=True) for x in ux_arr if normalize_space(x)][:3]
        enriched.append({
            **p,
            "topic": get_topic(p),
            "ko_title": ko_title,
            "ko_abstract": ko_abstract,
            "research_method": research_method,
            "key_result": key_result,
            "research_topic": fb["research_topic"],
            "ux_insights": ux_arr,
        })
    return enriched


def collect_papers() -> list:
    tasks = [
        (fetch_pubmed_papers, ("ergonomics", 5)),
        (fetch_arxiv_papers, ("ergonomics", 1)),
        (fetch_semantic_scholar, ("ergonomics workplace", 1)),
    ]
    rows = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(func, *args) for func, args in tasks]
        for fut in as_completed(futures):
            try:
                rows.extend(fut.result() or [])
            except Exception as e:
                print(f"논문 수집 오류: {e}")
    seen = set()
    unique = []
    for p in rows:
        key = canonical_title(p.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    evidence_order = {"peer_reviewed_or_indexed": 0, "index_metadata": 1, "preprint": 2}
    unique.sort(key=lambda x: (evidence_order.get(x.get("evidence", "preprint"), 9), x.get("pub_date", "")))
    return unique[:MAX_PAPERS]


def group_news_by_company(items: list) -> dict:
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get("company", "기타 초음파 동향")].append(item)
    return grouped


def build_news_html(items: list) -> str:
    if not items:
        return "<p>지난 24시간 내 조건에 맞는 신뢰 출처 뉴스가 없습니다.</p>"
    grouped = group_news_by_company(items)
    html_blocks = []
    for company in sorted(grouped.keys(), key=company_priority):
        rows = grouped[company][:MAX_NEWS_PER_COMPANY]
        html_blocks.append(
            f'''<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">{safe_html(company)} ({len(rows)}건)</h3>
</div>'''
        )
        for item in rows:
            html_blocks.append(
                f'''<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">{safe_html(item.get("category", "시장/경영"))}</span>
  <h4 style="margin:4px 0;font-size:14px;"><a href="{safe_html(item.get("url", ""))}" style="color:#1a5276;text-decoration:none;">{safe_html(item.get("title", ""))}</a></h4>
  <p style="font-size:11px;color:#777;margin:2px 0;">{safe_html(item.get("date", "")[:16])} · {safe_html(item.get("source", ""))}</p>
  <p style="font-size:13px;color:#333;line-height:1.6;"><strong>One-line summary:</strong> {safe_html(item.get("one_line_en", ""))}</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;"><strong>한글 요약:</strong> {safe_html(item.get("one_line_ko", ""))}</p>
</div>'''
            )
    return "\n".join(html_blocks)


def build_papers_html(papers: list) -> str:
    if not papers:
        return "<p>지난 48시간 기준 신규 논문이 없습니다.</p>"
    enriched = enrich_papers(papers)
    blocks = []
    for p in enriched:
        abstract_en = shorten_one_line(normalize_space(p.get("abstract", "")), 520)
        abstract_ko = shorten_one_line(normalize_space(p.get("ko_abstract", "")), 700)
        link = f'https://doi.org/{safe_html(p["doi"])}' if p.get("doi") else safe_html(p.get("link", ""))
        evidence_label = {
            "peer_reviewed_or_indexed": "PubMed 색인",
            "preprint": "Preprint",
            "index_metadata": "색인 메타데이터",
        }.get(p.get("evidence", ""), p.get("source", ""))
        ux_html = "".join(f'<li style="margin:0 0 6px;">{safe_html(x)}</li>' for x in p.get("ux_insights", []))
        blocks.append(
            f'''<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">{safe_html(p.get("topic", "기타"))}</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">{safe_html(p.get("title", ""))}</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">{safe_html(p.get("ko_title", ""))}</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">
    {safe_html(p.get("authors", ""))}<br/>
    {safe_html(p.get("affiliations", "") or "소속 정보 없음")}<br/>
    {safe_html(p.get("journal", ""))} · {safe_html(p.get("pub_date", ""))} · {safe_html(evidence_label)}
    {' · <a href="' + link + '" style="color:#2e86c1;">원문 보기</a>' if link else ''}
  </p>
  <p style="font-size:13px;color:#333;line-height:1.7;"><strong>Abstract:</strong> {safe_html(abstract_en)}</p>
  <div style="background:#fdf7ea;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#9a6700;">(1) 초록의 한국어 번역</p>
    <p style="margin:0;font-size:13px;color:#5b4a1f;">{safe_html(abstract_ko)}</p>
  </div>
  <div style="background:#eef6fb;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1a5276;">(2) 주요 연구 방법</p>
    <p style="margin:0;font-size:13px;color:#34495e;">{safe_html(p.get("research_method", ""))}</p>
  </div>
  <div style="background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1f6f43;">(3) 핵심 연구 결과</p>
    <p style="margin:0;font-size:13px;color:#2f4f3e;">{safe_html(p.get("key_result", ""))}</p>
  </div>
  <div style="background:#fff7e8;border:1px solid #f4d08b;padding:10px 12px;border-radius:4px;margin-top:10px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#9a6700;">(4) 삼성메디슨 UX 업무에 적용 가능한 인사이트</p>
    <ul style="margin:0;padding-left:18px;font-size:13px;color:#5b4a1f;line-height:1.8;">{ux_html}</ul>
  </div>
</div>'''
        )
    return "\n".join(blocks)


def assemble_email(news_html: str, papers_html: str, n_news: int, n_papers: int) -> str:
    today = dt.date.today().strftime("%Y년 %m월 %d일")
    return f'''<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:Arial,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:24px 0;">
<tr><td align="center">
<table width="860" cellpadding="0" cellspacing="0" style="max-width:860px;background:#ffffff;border-radius:12px;overflow:hidden;">
  <tr>
    <td style="background:#17324d;padding:28px 32px;color:#fff;">
      <h1 style="margin:0;font-size:24px;">초음파 회사 동향 & 인간공학 논문 다이제스트</h1>
      <p style="margin:8px 0 0;font-size:13px;color:#d6e5f2;">기준일: {today} · 지난 24시간 뉴스 / 최근 신규 논문</p>
    </td>
  </tr>
  <tr>
    <td style="padding:18px 30px 8px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;border:1px solid #e5edf5;border-radius:8px;">
        <tr>
          <td width="50%" style="text-align:center;padding:12px;">
            <p style="margin:0;font-size:28px;color:#2e86c1;font-weight:bold;">{n_news}</p>
            <p style="margin:4px 0 0;font-size:12px;color:#555;">산업 뉴스</p>
          </td>
          <td width="50%" style="text-align:center;padding:12px;">
            <p style="margin:0;font-size:28px;color:#27ae60;font-weight:bold;">{n_papers}</p>
            <p style="margin:4px 0 0;font-size:12px;color:#555;">연구 논문</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <tr>
    <td style="padding:20px 30px 8px;">
      <h2 style="margin:0 0 12px;color:#1a5276;border-bottom:2px solid #2e86c1;padding-bottom:8px;">초음파 회사 동향</h2>
      <p style="margin:0 0 10px;font-size:12px;color:#6b7280;">지난 24시간 내 신뢰 가능한 출처에서 확인된 주요 초음파 시장 동향을 회사별로 정리했습니다. 각 기사에는 영문 1줄 요약과 한국어 1줄 요약을 함께 제공합니다.</p>
      {news_html}
    </td>
  </tr>
  <tr><td style="padding:0 30px;"><hr style="border:none;border-top:1px solid #e8eef5;"/></td></tr>
  <tr>
    <td style="padding:20px 30px 24px;">
      <h2 style="margin:0 0 12px;color:#1a5276;border-bottom:2px solid #27ae60;padding-bottom:8px;">인간공학 논문 동향</h2>
      <p style="margin:0 0 10px;font-size:12px;color:#6b7280;">논문 초록의 한국어 번역, 연구 설계가 드러나는 주요 연구 방법, 핵심 결과, 삼성메디슨 UX 적용 인사이트를 함께 제공합니다.</p>
      {papers_html}
    </td>
  </tr>
  <tr>
    <td style="background:#2c3e50;padding:18px 30px;color:#bdc3c7;font-size:11px;line-height:1.7;">
      <p style="margin:0;">뉴스는 Google News RSS의 신뢰 출처, 전문매체 RSS, FDA 공개 데이터를 기준으로 수집했습니다. 논문은 PubMed, arXiv, Semantic Scholar를 사용했습니다.</p>
      <p style="margin:4px 0 0;">요약 문장은 자동 생성 보조를 사용했으므로, 중요한 의사결정에는 원문 링크 확인이 필요합니다.</p>
    </td>
  </tr>
</table>
</td></tr></table>
</body></html>'''


def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Ultrasound Digest <{GMAIL_ADDRESS}>"
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText("HTML 이메일 클라이언트에서 확인하세요.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [RECIPIENT_EMAIL], msg.as_string())
    print(f"이메일 발송 완료 -> {RECIPIENT_EMAIL}")


def main():
    start = time.time()
    today = dt.date.today().strftime("%Y-%m-%d")
    print(f"뉴스레터 생성 시작: {today}")

    all_news = []
    all_papers = []

    try:
        print("초음파 뉴스 수집 중...")
        all_news = fetch_all_ultrasound_news()
        print(f"뉴스 수집 완료: {len(all_news)}건")
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")

    try:
        print("인간공학 논문 수집 중...")
        all_papers = collect_papers()
        print(f"논문 수집 완료: {len(all_papers)}편")
    except Exception as e:
        print(f"논문 수집 실패: {e}")

    news_html = build_news_html(all_news)
    papers_html = build_papers_html(all_papers)
    html_body = assemble_email(news_html, papers_html, len(all_news), len(all_papers))
    subject = f"초음파 & 인간공학 다이제스트 | {today} | 뉴스 {len(all_news)}건, 논문 {len(all_papers)}편"
    send_email(subject, html_body)

    elapsed = time.time() - start
    print(f"완료! 총 소요 시간: {elapsed:.1f}초")


if __name__ == "__main__":
    main()
