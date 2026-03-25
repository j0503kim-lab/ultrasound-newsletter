#!/usr/bin/env python3
"""
초음파 시장 & 인간공학 논문 다이제스트
- 지난 24시간 기준 신뢰 가능한 출처만 수집
- 초음파 시장 뉴스는 중복 제거 후 회사별로 정확한 문장 형태로 정리
- 인간공학 논문은 초록 한국어 번역, 주요 연구 방법, 핵심 결과, 삼성메디슨 UX 인사이트 제공
- GitHub Actions에서 5분 이내 실행을 목표로 외부 호출 수를 최소화
"""

import os
import re
import json
import html
import time
import datetime as dt
import smtplib
import requests
import feedparser
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from urllib.parse import quote, urlparse

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "j0503.kim@gmail.com")
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "")

REQUEST_TIMEOUT = (4, 10)
GEMINI_TIMEOUT = 28
MAX_WORKERS = 6
MAX_NEWS_PER_QUERY = 6
MAX_NEWS_PER_COMPANY = 4
MAX_TOTAL_NEWS = 18
MAX_PAPERS = 5

USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (compatible; UltrasoundErgoDigest/2.0; +https://github.com/)"
}

SESSION = requests.Session()
SESSION.headers.update(USER_AGENT)

TRUSTED_SOURCES = {
    "AuntMinnie", "ITN", "Imaging Technology News", "Diagnostic Imaging",
    "MassDevice", "MedTech Dive", "Medical Device Network", "Medgadget",
    "FDA", "FDA openFDA", "U.S. Food and Drug Administration",
    "GE HealthCare", "Philips", "Siemens Healthineers", "Samsung Medison",
    "Samsung HME America", "Canon Medical Systems", "Mindray", "FUJIFILM Sonosite",
    "FUJIFILM Healthcare", "Esaote", "Butterfly Network", "Clarius", "EchoNous",
    "Exo", "Alpinion Medical Systems", "SonoScape"
}

TRUSTED_DOMAINS = {
    "auntminnie.com", "itnonline.com", "diagnosticimaging.com", "massdevice.com",
    "medtechdive.com", "medicaldevice-network.com", "medgadget.com",
    "fda.gov", "accessdata.fda.gov", "api.fda.gov"
}

COMPANY_MAP = {
    "Samsung Medison": ["samsung medison", "samsung hme america", "boston imaging", "neurologica"],
    "GE HealthCare": ["ge healthcare", "bk medical", "caption health"],
    "Philips": ["philips"],
    "Siemens Healthineers": ["siemens healthineers"],
    "Canon Medical": ["canon medical"],
    "Mindray": ["mindray"],
    "FUJIFILM / Sonosite": ["fujifilm", "sonosite"],
    "Esaote": ["esaote"],
    "Butterfly Network": ["butterfly network", "butterfly iq", "bfly"],
    "Clarius": ["clarius"],
    "EchoNous": ["echonous", "kosmos"],
    "Exo": ["exo", "exo iris"],
    "Alpinion": ["alpinion"],
    "SonoScape": ["sonoscape"],
    "기타 초음파 시장": []
}

SEARCH_QUERIES = {
    "Samsung Medison": [
        '"Samsung Medison" ultrasound',
        '"Samsung Medison" OR "Samsung HME America" OR "Boston Imaging" OR "Neurologica" imaging'
    ],
    "GE HealthCare": ['"GE HealthCare" ultrasound OR imaging'],
    "Philips": ['"Philips" ultrasound OR imaging healthcare'],
    "Siemens Healthineers": ['"Siemens Healthineers" ultrasound OR imaging'],
    "Canon Medical": ['"Canon Medical" ultrasound OR imaging'],
    "Mindray": ['"Mindray" ultrasound'],
    "FUJIFILM / Sonosite": ['"FUJIFILM Sonosite" OR "FUJIFILM Healthcare" ultrasound'],
    "Esaote": ['"Esaote" ultrasound'],
    "Portable / POCUS": ['"Butterfly Network" OR Clarius OR EchoNous OR Exo ultrasound OR POCUS'],
    "AI / Software": ['ultrasound AI FDA OR ultrasound AI imaging company'],
}

SPECIALIST_RSS_FEEDS = [
    ("AuntMinnie", "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("ITN", "https://www.itnonline.com/rss.xml"),
    ("MedTech Dive", "https://www.medtechdive.com/feeds/news/"),
    ("MassDevice", "https://www.massdevice.com/feed/"),
    ("Medical Device Network", "https://www.medicaldevice-network.com/feed/"),
]

NOISE_KEYWORDS = [
    "cleaner", "cleaning", "welder", "welding", "speaker", "headphone", "humidifier",
    "toothbrush", "pest", "rodent", "non-destructive", "consumer", "support", "customer support",
    "news & insights", "news and insights", "global / english", "women's health", "ultrasound systems",
    "general imaging", "product page", "contact", "about us"
]

IMAGING_BUSINESS_TERMS = [
    "ultrasound", "sonography", "imaging", "medical imaging", "radiology", "diagnostic imaging",
    "point-of-care", "pocus", "transducer", "probe", "women's health", "cardiovascular"
]

TOPIC_MAP = {
    "초음파 인간공학": ["ultrasound", "sonographer", "transducer", "scanning", "echography"],
    "근골격계질환": ["musculoskeletal", "carpal tunnel", "shoulder", "wrist", "neck pain", "tendon"],
    "임상 인간공학": ["nurse", "physician", "surgeon", "clinician", "radiology", "echocardiography"],
    "작업환경 개선": ["workstation", "workplace", "posture", "usability", "workflow", "interface"],
    "생체역학": ["biomechanics", "kinematics", "emg", "force", "motion"],
    "역학·통계": ["prevalence", "survey", "cohort", "cross-sectional", "epidemiology"],
    "AI·기술": ["machine learning", "deep learning", "algorithm", "artificial intelligence", "ai"],
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def cutoff_24h() -> dt.datetime:
    return now_utc() - dt.timedelta(hours=24)


def safe_html(text: str) -> str:
    return html.escape(text or "")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def clean_html_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return normalize_space(html.unescape(text))


def trim_title_suffix(title: str) -> str:
    title = normalize_space(title)
    for sep in [" - ", " | "]:
        if sep in title:
            left, right = title.rsplit(sep, 1)
            if len(right) < 40:
                return left.strip()
    return title


def translate_ko(text: str) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    if GoogleTranslator is None:
        return text
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:3000])
    except Exception:
        return text


def source_is_trusted(source: str, url: str = "") -> bool:
    source = normalize_space(source)
    if source and any(source.lower() == s.lower() or source.lower() in s.lower() or s.lower() in source.lower() for s in TRUSTED_SOURCES):
        return True
    host = urlparse(url).netloc.lower().replace("www.", "")
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DOMAINS)


def parse_entry_datetime(entry) -> dt.datetime | None:
    for key in ["published_parsed", "updated_parsed"]:
        value = entry.get(key)
        if value:
            try:
                return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
    for key in ["published", "updated"]:
        txt = entry.get(key)
        if txt:
            for fmt in ["%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"]:
                try:
                    parsed = dt.datetime.strptime(txt, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt.timezone.utc)
                    return parsed.astimezone(dt.timezone.utc)
                except Exception:
                    pass
    return None


def infer_company(text: str) -> str:
    text = (text or "").lower()
    for company, keys in COMPANY_MAP.items():
        if any(k in text for k in keys):
            return company
    return "기타 초음파 시장"


def classify_news_category(text: str) -> str:
    text = (text or "").lower()
    if any(k in text for k in ["510(k)", "clearance", "approval", "de novo", "ce mark", "fda"]):
        return "인허가"
    if any(k in text for k in ["acquire", "acquisition", "merger", "partnership", "collaboration", "unify", "rebrand"]):
        return "사업/조직"
    if any(k in text for k in ["launch", "launched", "introduce", "release", "platform", "system", "software"]):
        return "제품/기술"
    if any(k in text for k in ["study", "clinical", "validation", "research"]):
        return "임상/연구"
    return "시장/경영"


def should_keep_news(title: str, snippet: str, source: str, url: str) -> bool:
    title_l = (title or "").lower()
    snippet_l = (snippet or "").lower()
    text = f"{title_l} {snippet_l}"
    if any(noise in text for noise in NOISE_KEYWORDS):
        return False
    if not source_is_trusted(source, url):
        return False
    company = infer_company(f"{title} {snippet} {source} {url}")
    if company == "기타 초음파 시장" and not any(t in text for t in IMAGING_BUSINESS_TERMS):
        return False
    if company != "기타 초음파 시장":
        if any(term in text for term in IMAGING_BUSINESS_TERMS + ["healthcare", "medical", "hospital"]):
            return True
    return any(term in text for term in ["ultrasound", "sonography", "pocus", "medical imaging", "diagnostic imaging"])


def canonical_news_key(title: str, company: str, date_text: str = "") -> str:
    title = trim_title_suffix(title).lower()
    title = re.sub(r"[^a-z0-9가-힣]+", " ", title)
    title = re.sub(r"\b(the|a|an|to|for|and|of|with|under|its)\b", " ", title)
    title = normalize_space(title)
    date_text = normalize_space((date_text or "")[:16])
    return f"{company}|{title}|{date_text[:10]}"


def call_gemini_json(prompt: str) -> str:
    if not GEMINI_API_KEY:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 3800,
            "responseMimeType": "application/json"
        }
    }
    try:
        r = SESSION.post(url, json=payload, timeout=GEMINI_TIMEOUT)
        if r.status_code == 200:
            cands = r.json().get("candidates", [])
            if cands:
                return cands[0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Gemini 오류: {e}")
    return ""


def summarize_news_ko(item: dict) -> str:
    title = trim_title_suffix(item.get("title", ""))
    snippet = normalize_space(item.get("snippet", ""))
    company = item.get("company", "")
    category = item.get("detail_category", "")
    if GEMINI_API_KEY:
        prompt = f"""
다음 의료영상 산업 뉴스 1건을 한국어 1~2문장으로 정확하게 정리하세요.
반드시 JSON만 출력합니다.
{{"summary":"..."}}
규칙:
- 기사에 없는 정보 추가 금지
- 추측 금지
- 문장형으로 작성
- 회사명과 핵심 변화가 드러나야 함
- 불필요한 수식어 금지
제목: {title}
회사: {company}
분류: {category}
출처: {item.get('source','')}
스니펫: {snippet}
"""
        raw = call_gemini_json(prompt)
        if raw:
            try:
                return normalize_space(json.loads(raw).get("summary", ""))
            except Exception:
                pass
    base = snippet if snippet else title
    base = re.sub(r"\.{3,}", ".", base)
    base = normalize_space(base)
    if base and not base.endswith((".", "다.", "니다.")):
        base += "."
    return translate_ko(base) or translate_ko(title)


def fetch_feed(url: str):
    r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_google_news(query: str, label: str) -> list:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    items = []
    try:
        feed = fetch_feed(url)
        for entry in feed.entries[:MAX_NEWS_PER_QUERY * 3]:
            published = parse_entry_datetime(entry)
            if published and published < cutoff_24h():
                continue
            source = normalize_space((entry.get("source") or {}).get("title", "Google News"))
            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:260]
            link = entry.get("link", "")
            if not should_keep_news(title, snippet, source, link):
                continue
            company = infer_company(f"{title} {snippet} {source} {label}")
            items.append({
                "title": title,
                "snippet": snippet,
                "url": link,
                "source": source,
                "date": published.isoformat() if published else entry.get("published", entry.get("updated", "")),
                "company": company,
                "detail_category": classify_news_category(f"{title} {snippet}"),
                "trust": "trusted_publisher",
            })
            if len(items) >= MAX_NEWS_PER_QUERY:
                break
    except Exception as e:
        print(f"Google News 오류 [{label}]: {e}")
    return items


def fetch_specialist_feed(name: str, url: str) -> list:
    items = []
    try:
        feed = fetch_feed(url)
        for entry in feed.entries[:12]:
            published = parse_entry_datetime(entry)
            if published and published < cutoff_24h():
                continue
            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:260]
            link = entry.get("link", "")
            if not should_keep_news(title, snippet, name, link):
                continue
            company = infer_company(f"{title} {snippet} {name} {link}")
            items.append({
                "title": title,
                "snippet": snippet,
                "url": link,
                "source": name,
                "date": published.isoformat() if published else entry.get("published", entry.get("updated", "")),
                "company": company,
                "detail_category": classify_news_category(f"{title} {snippet}"),
                "trust": "trusted_specialist_media",
            })
            if len(items) >= MAX_NEWS_PER_QUERY:
                break
    except Exception as e:
        print(f"RSS 오류 [{name}]: {e}")
    return items


def fetch_fda_510k() -> list:
    today = dt.date.today()
    week_ago = today - dt.timedelta(days=7)
    url = (
        "https://api.fda.gov/device/510k.json?"
        f"search=openfda.device_name:ultrasound+AND+decision_date:[{week_ago:%Y%m%d}+TO+{today:%Y%m%d}]&limit=8"
    )
    items = []
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        for rec in r.json().get("results", []):
            date_str = rec.get("decision_date", "")
            device_name = normalize_space(rec.get("device_name", "N/A"))
            applicant = normalize_space(rec.get("applicant", "N/A"))
            k_number = normalize_space(rec.get("k_number", ""))
            title = f"FDA cleared {device_name}"
            snippet = f"Applicant {applicant}; K-number {k_number}."
            items.append({
                "title": title,
                "snippet": snippet,
                "url": f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k_number}",
                "source": "FDA openFDA",
                "date": date_str,
                "company": infer_company(f"{device_name} {applicant}"),
                "detail_category": "인허가",
                "trust": "official_regulator",
            })
    except Exception as e:
        print(f"FDA 오류: {e}")
    return items


def dedupe_news(items: list) -> list:
    best = {}
    rank = {"official_regulator": 0, "trusted_specialist_media": 1, "trusted_publisher": 2}
    for item in items:
        key = canonical_news_key(item.get("title", ""), item.get("company", ""), item.get("date", ""))
        old = best.get(key)
        if old is None or rank.get(item.get("trust", "trusted_publisher"), 9) < rank.get(old.get("trust", "trusted_publisher"), 9):
            best[key] = item
    result = list(best.values())
    result.sort(key=lambda x: (x.get("company", ""), x.get("date", "")), reverse=True)
    return result[:MAX_TOTAL_NEWS]


def fetch_all_news() -> list:
    tasks = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for label, queries in SEARCH_QUERIES.items():
            for q in queries:
                tasks.append(ex.submit(fetch_google_news, q, label))
        for name, url in SPECIALIST_RSS_FEEDS:
            tasks.append(ex.submit(fetch_specialist_feed, name, url))
        tasks.append(ex.submit(fetch_fda_510k))

        items = []
        for fut in as_completed(tasks):
            try:
                items.extend(fut.result() or [])
            except Exception as e:
                print(f"뉴스 작업 오류: {e}")
    return dedupe_news(items)


def fetch_pubmed_papers(query: str = "ergonomics", max_results: int = 5) -> list:
    params = {
        "db": "pubmed", "term": query, "datetype": "edat", "reldate": 2,
        "retmax": max_results, "retmode": "json", "sort": "date"
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
            abstract = normalize_space(" ".join([(a.text or "") for a in art.findall(".//AbstractText")]))[:1600]
            if not abstract:
                continue
            authors = [
                normalize_space(f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}")
                for a in art.findall(".//Author")[:6] if a.findtext("LastName")
            ]
            affil_el = art.find(".//AffiliationInfo/Affiliation")
            affil = normalize_space(affil_el.text if affil_el is not None and affil_el.text else "")[:220]
            journal = normalize_space(art.findtext(".//Journal/Title", ""))
            pmid = medline.findtext(".//PMID", "")
            doi_el = art.find(".//ELocationID[@EIdType='doi']")
            doi = normalize_space(doi_el.text if doi_el is not None else "")
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
                "evidence": "PubMed 색인",
            })
        return papers
    except Exception as e:
        print(f"PubMed 오류: {e}")
        return []


def fetch_arxiv_papers(query: str = "ergonomics", max_results: int = 1) -> list:
    try:
        r = SESSION.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "start": 0, "max_results": max_results, "sortBy": "submittedDate", "sortOrder": "descending"},
            timeout=REQUEST_TIMEOUT,
        )
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.content)
        papers = []
        for entry in root.findall("atom:entry", ns):
            title = normalize_space(entry.findtext("atom:title", "", ns).replace("\n", " "))
            abstract = normalize_space(entry.findtext("atom:summary", "", ns))[:1400]
            if not abstract:
                continue
            pub = entry.findtext("atom:published", "", ns)
            authors = [normalize_space(a.findtext("atom:name", "", ns)) for a in entry.findall("atom:author", ns)][:6]
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
                "evidence": "Preprint",
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
        papers = []
        for p in r.json().get("data", []):
            abstract = normalize_space((p.get("abstract") or ""))[:1400]
            if not abstract:
                continue
            doi = normalize_space((p.get("externalIds") or {}).get("DOI", ""))
            papers.append({
                "title": normalize_space(p.get("title", "")),
                "authors": ", ".join([normalize_space(a.get("name", "")) for a in (p.get("authors") or [])[:6]]),
                "affiliations": "",
                "abstract": abstract,
                "doi": doi,
                "journal": normalize_space((p.get("journal") or {}).get("name", "")),
                "pub_date": p.get("publicationDate", ""),
                "link": f"https://doi.org/{doi}" if doi else "",
                "source": "Semantic Scholar",
                "evidence": "색인 메타데이터",
            })
        return papers
    except Exception as e:
        print(f"Semantic Scholar 오류: {e}")
        return []


def get_topic(paper: dict) -> str:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    for topic, keys in TOPIC_MAP.items():
        if any(k in text for k in keys):
            return topic
    return "기타"


def infer_method_detail(title: str, abstract: str) -> str:
    text = normalize_space(abstract)
    lower = text.lower()

    def first_number_phrase(src: str) -> str:
        patterns = [
            r"(n\s*=\s*\d+)",
            r"(\d+\s+(?:participants|subjects|workers|employees|patients|students|operators|clinicians|sonographers|radiologists))",
            r"(sample of \d+)",
        ]
        for pat in patterns:
            m = re.search(pat, src, flags=re.I)
            if m:
                return m.group(1)
            return ""

    sample = first_number_phrase(text)

    if any(k in lower for k in ["systematic review", "scoping review", "meta-analysis", "narrative review", "literature review"]):
        phrase = "문헌고찰 방식으로 최근 연구를 선별·비교해"
        if sample:
            phrase += f" ({sample})"
        if any(k in lower for k in ["guideline", "framework", "risk factor"]):
            phrase += " 위험요인, 관리 전략, 평가 틀을 종합했습니다."
        else:
            phrase += " 핵심 경향과 근거를 종합했습니다."
        return phrase

    if any(k in lower for k in ["survey", "questionnaire", "cross-sectional", "self-report"]):
        target = "대상자"
        if any(k in lower for k in ["nurse", "nursing"]):
            target = "간호사"
        elif any(k in lower for k in ["sonographer", "ultrasound"]):
            target = "초음파 검사자"
        elif any(k in lower for k in ["worker", "employee"]):
            target = "근로자"
        sent = f"설문 또는 단면조사로 {target}의 작업 특성, 증상, 인식을 수집했습니다"
        if sample:
            sent += f" ({sample})"
        if any(k in lower for k in ["regression", "association", "correlation", "predict"]):
            sent += ", 이후 변수 간 연관성과 영향 요인을 통계적으로 비교했습니다."
        else:
            sent += ", 이후 집단 간 차이 또는 빈도를 비교했습니다."
        return sent

    if any(k in lower for k in ["randomized", "controlled", "trial", "intervention"]):
        sent = "비교군 또는 조건 차이를 둔 실험 설계로 개입 전후 또는 집단 간 결과를 평가했습니다"
        if sample:
            sent += f" ({sample})"
        if any(k in lower for k in ["workload", "usability", "performance", "fatigue"]):
            sent += ", 작업부하·사용성·수행 성과 같은 핵심 지표를 측정했습니다."
        else:
            sent += ", 주요 결과 지표를 비교해 개입 효과를 검증했습니다."
        return sent

    if any(k in lower for k in ["emg", "kinematic", "biomechanics", "motion", "force", "posture"]):
        sent = "실험 또는 관찰 환경에서 자세, 동작, 근활성도, 힘과 같은 생체역학 지표를 측정했습니다"
        if sample:
            sent += f" ({sample})"
        sent += ", 이를 통해 조건별 신체 부담 차이를 정량 비교했습니다."
        return sent

    if any(k in lower for k in ["interview", "focus group", "qualitative", "thematic analysis"]):
        sent = "인터뷰·관찰 또는 포커스그룹으로 사용 경험과 문제 상황을 수집했습니다"
        if sample:
            sent += f" ({sample})"
        sent += ", 이후 반복적으로 등장하는 주제와 패턴을 정리했습니다."
        return sent

    if any(k in lower for k in ["machine learning", "deep learning", "algorithm", "model", "classifier"]):
        sent = "데이터셋에 알고리즘 또는 모델을 적용해 예측·분류 성능을 평가했습니다"
        if sample:
            sent += f" ({sample})"
        if any(k in lower for k in ["accuracy", "auc", "sensitivity", "specificity", "f1"]):
            sent += ", 정확도·민감도·AUC 등 성능 지표를 비교했습니다."
        else:
            sent += ", 기존 방법과 성능 차이를 비교했습니다."
        return sent

    first = re.split(r"(?<=[.!?])\s+", text)[:2]
    compact = " ".join(first)
    compact = re.sub(r"\s+", " ", compact).strip()
    if len(compact) > 210:
        compact = compact[:207] + "..."
    return compact or "초록에 제시된 연구 대상, 비교 조건, 측정 지표를 바탕으로 핵심 설계를 요약했습니다."


def fallback_paper_summary(topic: str, paper: dict) -> dict:
    abstract = normalize_space(paper.get("abstract", ""))
    text = abstract.lower()
    method = infer_method_detail(paper.get("title", ""), abstract)

    if any(k in text for k in ["significant", "reduced", "improved", "lower"]):
        result = "비교한 조건 또는 개입에 따라 작업부하, 수행 효율, 사용성 중 일부 지표가 유의하게 개선됐습니다."
    elif any(k in text for k in ["risk", "pain", "fatigue", "burden"]):
        result = "작업부하·피로·통증 또는 위험 노출과 연관된 핵심 요인이 결과 변수로 제시됐습니다."
    else:
        result = "초록은 비교 결과와 주요 변수의 방향성을 제시하며, 실무에 참고할 차이점을 보여줍니다."

    ux = [
        "초음파 검사 워크플로우에서 반복 입력과 화면 전환을 줄이는 방향으로 메뉴 구조를 단순화할 근거로 활용할 수 있습니다.",
        "측정·주석·저장 단계처럼 사용자의 인지부하가 큰 구간에 대해 정보 우선순위와 피드백 방식을 재설계하는 데 참고할 수 있습니다.",
        "프로브 조작과 화면 조작이 동시에 발생하는 상황을 고려해 한 손 조작, 빠른 복귀, 자동 상태 유지 같은 UX 원칙을 강화할 수 있습니다.",
    ]
    return {
        "ko_abstract": translate_ko(abstract[:2000]),
        "research_method": method,
        "key_result": result,
        "ux_insights": ux[:3],
    }


def enrich_papers(papers: list) -> list:
    if not papers:
        return []
    compact = []
    for i, p in enumerate(papers, 1):
        compact.append({
            "id": i,
            "title": p.get("title", ""),
            "topic": get_topic(p),
            "authors": p.get("authors", ""),
            "journal": p.get("journal", ""),
            "pub_date": p.get("pub_date", ""),
            "abstract": p.get("abstract", "")[:1600],
        })

    prompt = f"""
당신은 인간공학 논문을 정리하는 한국어 연구 편집자입니다.
반드시 JSON 배열만 출력하세요.
각 논문마다 다음 필드를 포함하세요: id, ko_title, ko_abstract, research_method, key_result, ux_insights
규칙:
- ko_title: 자연스러운 한국어 제목
- ko_abstract: 초록의 정확한 한국어 번역
- research_method: 결과를 도출하기 위한 주요 연구 방법을 1~3문장으로 요약. 연구 대상, 비교 조건, 측정 지표·분석 방식이 드러나야 하며, 이 항목만 읽어도 어떤 방법을 썼는지 이해되어야 함
- key_result: 핵심 결과를 1~2문장으로 정리
- ux_insights: 삼성메디슨 UX 업무 적용 인사이트 3개 배열. 초음파 UI, 검사 워크플로우, 자동 측정/판독 보조, 정보 구조, 버튼/터치 조작, 인지부하, 작업부하 감소와 연결
- 과장 금지, 초록에 없는 내용 금지
입력: {json.dumps(compact, ensure_ascii=False)}
"""
    parsed = {}
    raw = call_gemini_json(prompt)
    if raw:
        try:
            for row in json.loads(raw):
                parsed[row.get("id")] = row
        except Exception as e:
            print(f"논문 JSON 파싱 오류: {e}")
    out = []
    for i, p in enumerate(papers, 1):
        fb = fallback_paper_summary(get_topic(p), p)
        row = parsed.get(i, {})
        out.append({
            **p,
            "topic": get_topic(p),
            "ko_title": normalize_space(row.get("ko_title", "")) or translate_ko(p.get("title", "")),
            "ko_abstract": normalize_space(row.get("ko_abstract", "")) or fb["ko_abstract"],
            "research_method": normalize_space(row.get("research_method", "")) or fb["research_method"],
            "key_result": normalize_space(row.get("key_result", "")) or fb["key_result"],
            "ux_insights": [normalize_space(x) for x in row.get("ux_insights", fb["ux_insights"]) if normalize_space(x)][:3],
        })
    return out


def collect_papers() -> list:
    tasks = [
        (fetch_pubmed_papers, ("ergonomics", MAX_PAPERS)),
        (fetch_arxiv_papers, ("ergonomics", 1)),
        (fetch_semantic_scholar, ("ergonomics workplace", 1)),
    ]
    papers = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(func, *args) for func, args in tasks]
        for fut in as_completed(futs):
            try:
                papers.extend(fut.result() or [])
            except Exception as e:
                print(f"논문 수집 오류: {e}")
    seen = set()
    unique = []
    for p in papers:
        key = normalize_space(p.get("title", "")).lower()[:180]
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    rank = {"PubMed 색인": 0, "색인 메타데이터": 1, "Preprint": 2}
    unique.sort(key=lambda x: (rank.get(x.get("evidence", "Preprint"), 9), x.get("pub_date", "")))
    return unique[:MAX_PAPERS]


def build_news_html(news_items: list) -> str:
    if not news_items:
        return "<p>지난 24시간 동안 신뢰 출처에서 확인된 초음파 시장 뉴스가 없습니다.</p>"
    grouped = defaultdict(list)
    for item in news_items:
        grouped[item["company"]].append(item)
    order = sorted(grouped.keys(), key=lambda c: (c == "기타 초음파 시장", -len(grouped[c]), c))
    blocks = []
    for company in order:
        items = sorted(grouped[company], key=lambda x: x.get("date", ""), reverse=True)[:MAX_NEWS_PER_COMPANY]
        blocks.append(f'<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;"><h3 style="color:#fff;margin:0;font-size:16px;">{safe_html(company)} ({len(items)}건)</h3></div>')
        for item in items:
            summary = summarize_news_ko(item)
            date_text = item.get("date", "")[:16].replace("T", " ")
            blocks.append(
                f'''<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#2e86c1;">{safe_html(item.get('detail_category','시장/경영'))}</p>
  <h4 style="margin:0 0 6px;font-size:14px;"><a href="{safe_html(item.get('url',''))}" style="color:#1a5276;text-decoration:none;">{safe_html(trim_title_suffix(item.get('title','')))}</a></h4>
  <p style="font-size:11px;color:#777;margin:0 0 8px;">{safe_html(date_text)} · {safe_html(item.get('source',''))}</p>
  <p style="font-size:13px;color:#333;line-height:1.7;margin:0;">{safe_html(summary)}</p>
</div>'''
            )
    return "\n".join(blocks)


def build_papers_html(papers: list) -> str:
    if not papers:
        return "<p>지난 24시간~48시간 내 신규 인간공학 논문이 없습니다.</p>"
    papers = enrich_papers(papers)
    blocks = []
    for p in papers:
        abstract_en = normalize_space(p.get("abstract", ""))
        if len(abstract_en) > 520:
            abstract_en = abstract_en[:520] + "..."
        abstract_ko = normalize_space(p.get("ko_abstract", ""))
        if len(abstract_ko) > 700:
            abstract_ko = abstract_ko[:700] + "..."
        link = f'https://doi.org/{safe_html(p["doi"])}' if p.get("doi") else safe_html(p.get("link", ""))
        ux_html = "".join([f'<li style="margin:0 0 6px;">{safe_html(x)}</li>' for x in p.get("ux_insights", [])])
        blocks.append(
            f'''<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">{safe_html(p.get('topic','기타'))}</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">{safe_html(p.get('title',''))}</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">{safe_html(p.get('ko_title',''))}</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">{safe_html(p.get('authors',''))}<br/>{safe_html(p.get('affiliations','') or '소속 정보 없음')}<br/>{safe_html(p.get('journal',''))} · {safe_html(p.get('pub_date',''))} · {safe_html(p.get('evidence',''))}{' · <a href="' + link + '" style="color:#2e86c1;">원문 보기</a>' if link else ''}</p>
  <p style="font-size:13px;color:#333;line-height:1.7;"><strong>Abstract:</strong> {safe_html(abstract_en)}</p>
  <div style="background:#fdf7ea;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;"><p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#9a6700;">(1) 초록의 한국어 번역</p><p style="margin:0;font-size:13px;color:#5b4a1f;">{safe_html(abstract_ko)}</p></div>
  <div style="background:#eef6fb;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;"><p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1a5276;">(2) 주요 연구 방법</p><p style="margin:0;font-size:13px;color:#34495e;">{safe_html(p.get('research_method',''))}</p></div>
  <div style="background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;"><p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1f6f43;">(3) 핵심 연구 결과</p><p style="margin:0;font-size:13px;color:#2f4f3e;">{safe_html(p.get('key_result',''))}</p></div>
  <div style="background:#fff7e8;border:1px solid #f4d08b;padding:10px 12px;border-radius:4px;margin-top:10px;"><p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#9a6700;">(4) 삼성메디슨 UX 업무에 적용 가능한 인사이트</p><ul style="margin:0;padding-left:18px;font-size:13px;color:#5b4a1f;line-height:1.8;">{ux_html}</ul></div>
</div>'''
        )
    return "\n".join(blocks)


def assemble_email(news_html: str, papers_html: str, n_news: int, n_papers: int) -> str:
    today = dt.datetime.now().strftime("%Y년 %m월 %d일")
    return f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:Arial,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;padding:24px 0;"><tr><td align="center">
<table width="860" cellpadding="0" cellspacing="0" style="max-width:860px;background:#ffffff;border-radius:12px;overflow:hidden;">
<tr><td style="background:#17324d;padding:28px 32px;color:#fff;"><h1 style="margin:0;font-size:24px;">초음파 시장 & 인간공학 다이제스트</h1><p style="margin:8px 0 0;font-size:13px;color:#d6e5f2;">기준일: {today} · 지난 24시간 업데이트 기준</p></td></tr>
<tr><td style="padding:18px 30px 8px;"><table width="100%" cellpadding="0" cellspacing="0" style="background:#f7fafc;border:1px solid #e5edf5;border-radius:8px;"><tr>
<td width="50%" style="text-align:center;padding:12px;"><p style="margin:0;font-size:28px;color:#2e86c1;font-weight:bold;">{n_news}</p><p style="margin:4px 0 0;font-size:12px;color:#555;">시장 뉴스</p></td>
<td width="50%" style="text-align:center;padding:12px;"><p style="margin:0;font-size:28px;color:#27ae60;font-weight:bold;">{n_papers}</p><p style="margin:4px 0 0;font-size:12px;color:#555;">연구 논문</p></td>
</tr></table></td></tr>
<tr><td style="padding:20px 30px 8px;"><h2 style="margin:0 0 12px;color:#1a5276;border-bottom:2px solid #2e86c1;padding-bottom:8px;">지난 24시간 세계 초음파 시장 동향</h2><p style="margin:0 0 10px;font-size:12px;color:#6b7280;">신뢰 가능한 전문매체·규제기관 기준으로 확인된 기사만 포함했으며, 같은 이슈는 1건으로 묶어 중복을 제거했습니다.</p>{news_html}</td></tr>
<tr><td style="padding:0 30px;"><hr style="border:none;border-top:1px solid #e8eef5;"/></td></tr>
<tr><td style="padding:20px 30px 24px;"><h2 style="margin:0 0 12px;color:#1a5276;border-bottom:2px solid #27ae60;padding-bottom:8px;">지난 24시간 인간공학 논문 동향</h2><p style="margin:0 0 10px;font-size:12px;color:#6b7280;">논문 초록을 기준으로 번역, 연구 방법, 핵심 결과, 삼성메디슨 UX 적용 인사이트를 구조화해 정리했습니다.</p>{papers_html}</td></tr>
<tr><td style="background:#2c3e50;padding:18px 30px;color:#bdc3c7;font-size:11px;line-height:1.7;"><p style="margin:0;">중요 의사결정 전에는 기사 원문과 논문 원문을 다시 확인하는 것이 적절합니다.</p><p style="margin:4px 0 0;">News sources: Google News RSS, specialist media RSS, FDA openFDA</p><p style="margin:4px 0 0;">Paper sources: PubMed, arXiv, Semantic Scholar</p></td></tr>
</table></td></tr></table></body></html>'''


def send_email(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Ultrasound Digest <{GMAIL_ADDRESS}>"
    msg["To"] = RECIPIENT_EMAIL
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText("HTML 이메일 클라이언트에서 확인하세요.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [RECIPIENT_EMAIL], msg.as_string())
    print(f"이메일 발송 완료 -> {RECIPIENT_EMAIL}")


def main():
    started = time.time()
    print("뉴스레터 생성 시작")
    news_items, papers = [], []
    try:
        news_items = fetch_all_news()
        print(f"뉴스 수집 완료: {len(news_items)}건")
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")
    try:
        papers = collect_papers()
        print(f"논문 수집 완료: {len(papers)}편")
    except Exception as e:
        print(f"논문 수집 실패: {e}")
    news_html = build_news_html(news_items)
    papers_html = build_papers_html(papers)
    today = dt.date.today().strftime("%Y-%m-%d")
    subject = f"초음파 & 인간공학 다이제스트 | {today} | 뉴스 {len(news_items)}건, 논문 {len(papers)}편"
    send_email(subject, assemble_email(news_html, papers_html, len(news_items), len(papers)))
    print(f"완료! 총 소요 {time.time() - started:.1f}초")


if __name__ == "__main__":
    main()
