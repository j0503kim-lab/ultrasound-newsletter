#!/usr/bin/env python3
"""
초음파 산업 & 인간공학 연구 뉴스레터
- 신뢰 가능한 출처 중심 필터링
- 초음파 회사별 그룹핑
- 인간공학 논문 한국어 번역 + 삼성메디슨 UX 적용 포인트 포함
- GitHub Actions 실행 시간 최적화
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
from urllib.parse import quote

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

# ── 설정 ──────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "j0503.kim@gmail.com")
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "")

REQUEST_TIMEOUT = (5, 12)
GEMINI_TIMEOUT = 35
MAX_WORKERS = 6
MAX_NEWS_PER_SOURCE = 5
MAX_NEWS_PER_COMPANY = 4
MAX_TOTAL_NEWS = 24
MAX_PAPERS = 6

USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (compatible; UltrasoundErgoDigest/1.0; +https://github.com/)"
}

# ── 신뢰 출처 필터 ────────────────────────────────────────────
TRUSTED_NEWS_SOURCES = {
    # 공식/기업
    "GE HealthCare", "Philips", "Siemens Healthineers", "Samsung Medison", "Canon Medical Systems",
    "Mindray", "FUJIFILM Healthcare", "FUJIFILM Sonosite", "Esaote", "Butterfly Network",
    "Exo", "Clarius", "EchoNous", "Healcerion", "Alpinion Medical Systems", "SonoScape",
    # 전문 매체
    "AuntMinnie", "ITN", "Imaging Technology News", "Diagnostic Imaging", "MassDevice",
    "MedTech Dive", "Medical Device Network", "Medgadget", "Healthcare-in-Europe",
    # 규제/공공
    "FDA", "U.S. Food and Drug Administration", "openFDA", "European Commission",
}

SPECIALIST_RSS_FEEDS = [
    ("AuntMinnie", "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("MedTech Dive", "https://www.medtechdive.com/feeds/news/"),
    ("MassDevice", "https://www.massdevice.com/feed/"),
    ("Medical Device Network", "https://www.medicaldevice-network.com/feed/"),
]

RSS_QUERIES = {
    "대형 초음파 기업": (
        '"GE HealthCare" OR "Philips" OR "Siemens Healthineers" OR "Samsung Medison" '
        'OR "Canon Medical" OR "Mindray" OR "FUJIFILM Sonosite" OR "FUJIFILM Healthcare" OR "Esaote"'
    ),
    "휴대형·POCUS": (
        '"Butterfly Network" OR "Butterfly iQ" OR "Exo" OR "Clarius" OR "EchoNous" '
        'OR "Vave Health" OR "Pulsenmore" OR "iSono Health" OR "Rivanna Medical"'
    ),
    "AI 초음파": (
        '"Ultromics" OR "Caption Health" OR "DiA Imaging" OR "UltraSight" OR "BrightHeart" '
        'OR "Sonio" OR "ThinkSono" OR "Ligence"'
    ),
    "중국 기업": (
        '"SonoScape" OR "CHISON" OR "Wisonic" OR "SIUI" OR "Edan" OR "VINNO" OR "Landwind Medical"'
    ),
    "규제·인허가": '(("FDA clearance" OR "510(k)" OR "CE mark" OR "De Novo") ultrasound)',
}

# ── 노이즈 필터 ────────────────────────────────────────────────
NOISE_KEYWORDS = [
    "cleaner", "cleaning", "welding", "ultrasonic cleaner", "ultrasonic welder",
    "non-destructive", "humidifier", "rodent", "audio", "speaker", "headphone",
    "distance sensor", "level sensor", "flow meter", "beauty device", "toothbrush",
]

COMPANY_MAP = {
    "GE HealthCare": ["ge healthcare", "bk medical", "caption health"],
    "Philips": ["philips"],
    "Siemens Healthineers": ["siemens healthineers"],
    "Samsung Medison": ["samsung medison", "samsung hme"],
    "Canon Medical": ["canon medical"],
    "FUJIFILM / Sonosite": ["fujifilm healthcare", "fujifilm sonosite", "sonosite", "visualsonics"],
    "Mindray": ["mindray"],
    "Esaote": ["esaote"],
    "Butterfly Network": ["butterfly network", "butterfly iq", "bfly"],
    "Exo": ["exo", "exo iris"],
    "Clarius": ["clarius"],
    "EchoNous": ["echonous", "kosmos"],
    "Alpinion": ["alpinion"],
    "Healcerion": ["healcerion", "sonon"],
    "SonoScape": ["sonoscape"],
    "CHISON": ["chison"],
    "Wisonic": ["wisonic"],
    "SIUI": ["siui"],
    "Edan": ["edan"],
    "VINNO": ["vinno"],
    "Landwind Medical": ["landwind"],
    "AI 초음파 솔루션": ["ultromics", "ultrasight", "dia imaging", "brightheart", "sonio", "thinksono", "ligence"],
    "FDA 인허가": ["fda", "510(k)", "de novo", "ce mark"],
}

TOPIC_MAP = {
    "초음파 인간공학": ["ultrasound", "sonographer", "transducer", "scanning", "echography"],
    "근골격계질환": ["musculoskeletal", "carpal tunnel", "shoulder", "wrist", "neck pain", "tendon"],
    "임상 인간공학": ["nurse", "physician", "surgeon", "clinician", "radiology", "echocardiography"],
    "작업환경 개선": ["workstation", "workplace", "posture", "sitting", "standing", "interface", "usability"],
    "생체역학": ["biomechanics", "kinematics", "emg", "force", "motion"],
    "역학·통계": ["prevalence", "survey", "cohort", "cross-sectional", "epidemiology"],
    "AI·기술": ["machine learning", "deep learning", "ai", "algorithm", "computer vision"],
}

SESSION = requests.Session()
SESSION.headers.update(USER_AGENT)


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


def is_medical_news(title: str, snippet: str = "") -> bool:
    text = (title + " " + snippet).lower()
    if any(noise in text for noise in NOISE_KEYWORDS):
        return False
    return "ultrasound" in text or "sonography" in text or "pocus" in text


def source_is_trusted(source: str) -> bool:
    source = normalize_space(source)
    if not source:
        return False
    return any(source.lower() == s.lower() or source.lower() in s.lower() or s.lower() in source.lower() for s in TRUSTED_NEWS_SOURCES)


def parse_entry_datetime(entry) -> dt.datetime | None:
    for key in ["published_parsed", "updated_parsed"]:
        value = entry.get(key)
        if value:
            try:
                return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
            except Exception:
                pass
    return None


def translate_ko(text: str) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    if GoogleTranslator is None:
        return text
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:3500])
    except Exception:
        return text


def call_gemini_json(prompt: str, schema_hint: str = "JSON") -> str:
    if not GEMINI_API_KEY:
        return ""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4000,
            "responseMimeType": "application/json",
        },
    }

    for attempt in range(2):
        try:
            r = SESSION.post(url, json=payload, timeout=GEMINI_TIMEOUT)
            if r.status_code == 200:
                candidates = r.json().get("candidates", [])
                if not candidates:
                    return ""
                return candidates[0]["content"]["parts"][0]["text"].strip()
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"Gemini 오류: {r.status_code} / {schema_hint}")
            return ""
        except Exception as e:
            print(f"Gemini 예외: {e} / {schema_hint}")
            return ""
    return ""


def get_company(item: dict) -> str:
    text = (item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("source", "")).lower()
    for company, keywords in COMPANY_MAP.items():
        if any(kw in text for kw in keywords):
            return company
    return "기타 초음파 동향"


def classify_news_category(item: dict) -> str:
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    if any(k in text for k in ["fda", "510(k)", "clearance", "approval", "de novo", "ce mark", "mfds"]):
        return "인허가 승인"
    if any(k in text for k in ["acquisition", "acquire", "merger", "partnership", "collaboration", "alliance"]):
        return "인수/합병/파트너십"
    if any(k in text for k in ["study", "clinical", "trial", "research", "validation"]):
        return "임상/연구"
    if any(k in text for k in ["launch", "launched", "introduce", "introduced", "release", "software", "platform", "system"]):
        return "신제품/기술"
    return "시장/경영"


def fetch_feed_with_timeout(url: str):
    r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_google_news_rss(query: str, label: str, max_items: int = MAX_NEWS_PER_SOURCE) -> list:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    items = []
    cutoff = now_utc() - dt.timedelta(hours=24)
    try:
        feed = fetch_feed_with_timeout(url)
        for entry in feed.entries[: max_items * 2]:
            pub_dt = parse_entry_datetime(entry)
            if pub_dt and pub_dt < cutoff:
                continue

            source = normalize_space((entry.get("source") or {}).get("title", "Google News"))
            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:280]
            link = entry.get("link", "")

            if not source_is_trusted(source):
                continue
            if not is_medical_news(title, snippet):
                continue

            items.append({
                "title": title,
                "snippet": snippet,
                "url": link,
                "date": entry.get("published", entry.get("updated", "")),
                "source": source,
                "category": label,
                "trust": "trusted_publisher",
            })
            if len(items) >= max_items:
                break
    except Exception as e:
        print(f"Google RSS 오류 [{label}]: {e}")
    return items


def fetch_specialist_feed(name: str, url: str) -> list:
    items = []
    cutoff = now_utc() - dt.timedelta(hours=24)
    try:
        feed = fetch_feed_with_timeout(url)
        for entry in feed.entries[:10]:
            pub_dt = parse_entry_datetime(entry)
            if pub_dt and pub_dt < cutoff:
                continue

            title = trim_title_suffix(entry.get("title", ""))
            snippet = clean_html_text(entry.get("summary", ""))[:280]
            if not is_medical_news(title, snippet):
                continue

            items.append({
                "title": title,
                "snippet": snippet,
                "url": entry.get("link", ""),
                "date": entry.get("published", entry.get("updated", "")),
                "source": name,
                "category": "전문매체",
                "trust": "trusted_specialist_media",
            })
            if len(items) >= MAX_NEWS_PER_SOURCE:
                break
    except Exception as e:
        print(f"전문매체 RSS 오류 [{name}]: {e}")
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
            device_name = normalize_space(rec.get("device_name", "N/A"))
            applicant = normalize_space(rec.get("applicant", "N/A"))
            k_number = normalize_space(rec.get("k_number", ""))
            items.append({
                "title": f"FDA 510(k) Cleared: {device_name}",
                "snippet": f"Applicant: {applicant} | K-number: {k_number}",
                "url": f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k_number}",
                "date": rec.get("decision_date", ""),
                "source": "FDA openFDA",
                "category": "FDA 인허가",
                "trust": "official_regulatory_source",
            })
    except Exception as e:
        print(f"FDA 오류: {e}")
    return items


def fetch_all_ultrasound_news() -> list:
    all_items = []
    seen = set()

    def fetch_google(args):
        label, query = args
        return fetch_google_news_rss(query, label)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(fetch_google, item) for item in RSS_QUERIES.items()]
        futures += [ex.submit(fetch_specialist_feed, name, url) for name, url in SPECIALIST_RSS_FEEDS]
        futures += [ex.submit(fetch_fda_510k)]

        for fut in as_completed(futures):
            try:
                batch = fut.result() or []
            except Exception as e:
                print(f"뉴스 수집 작업 오류: {e}")
                batch = []

            for item in batch:
                key = (trim_title_suffix(item.get("title", "")).lower(), item.get("url", ""))
                if key in seen:
                    continue
                seen.add(key)
                item["company"] = get_company(item)
                item["detail_category"] = classify_news_category(item)
                all_items.append(item)

    all_items.sort(key=lambda x: (x.get("company", ""), x.get("date", "")), reverse=True)
    return all_items[:MAX_TOTAL_NEWS]


def fetch_pubmed_papers(query: str = "ergonomics", max_results: int = 6) -> list:
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
        r = SESSION.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        time.sleep(0.34)
        params2 = {
            "db": "pubmed",
            "id": ",".join(ids),
            "rettype": "xml",
            "retmode": "xml",
        }
        if PUBMED_API_KEY:
            params2["api_key"] = PUBMED_API_KEY

        r2 = SESSION.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params=params2,
            timeout=REQUEST_TIMEOUT,
        )
        root = ET.fromstring(r2.content)
        papers = []

        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            art = medline.find(".//Article") if medline is not None else None
            if art is None:
                continue

            title = normalize_space("".join(art.findtext(".//ArticleTitle", "")))
            abstract = normalize_space(" ".join([(a.text or "") for a in art.findall(".//AbstractText")]))[:1400]
            if not abstract:
                continue

            authors = [
                normalize_space(f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}")
                for a in art.findall(".//Author")[:6]
                if a.findtext("LastName")
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
                "evidence": "peer_reviewed_or_indexed",
            })
        return papers
    except Exception as e:
        print(f"PubMed 오류: {e}")
        return []


def fetch_arxiv_papers(query: str = "ergonomics", max_results: int = 2) -> list:
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
        cutoff = now_utc() - dt.timedelta(days=3)
        papers = []
        for entry in root.findall("atom:entry", ns):
            pub = entry.findtext("atom:published", "", ns)
            try:
                if dt.datetime.fromisoformat(pub.replace("Z", "+00:00")) < cutoff:
                    continue
            except Exception:
                pass
            title = normalize_space(entry.findtext("atom:title", "", ns).replace("\n", " "))
            abstract = normalize_space(entry.findtext("atom:summary", "", ns))[:1200]
            if not abstract:
                continue
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
                "evidence": "preprint",
            })
        return papers
    except Exception as e:
        print(f"arXiv 오류: {e}")
        return []


def fetch_semantic_scholar(query: str = "ergonomics workplace", max_results: int = 2) -> list:
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
            abstract = normalize_space((p.get("abstract") or ""))[:1200]
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
                "evidence": "index_metadata",
            })
        return papers
    except Exception as e:
        print(f"Semantic Scholar 오류: {e}")
        return []


def get_topic(paper: dict) -> str:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    for topic, keywords in TOPIC_MAP.items():
        if any(kw in text for kw in keywords):
            return topic
    return "기타"


def fallback_paper_structured_summary(topic: str, title: str, abstract: str) -> dict:
    text = (title + " " + abstract).lower()

    topic_summary = {
        "초음파 인간공학": "초음파 검사 수행 과정에서 작업 자세, 반복 동작, 검사 흐름이 사용자 부담에 미치는 영향을 다룹니다.",
        "근골격계질환": "반복 사용 환경에서 발생하는 근골격계 부담 요인과 이를 줄이기 위한 설계·운영 개선점을 다룹니다.",
        "임상 인간공학": "임상 현장에서 의료진의 수행 오류, 피로, 인지 부담을 줄이기 위한 인간공학적 요인을 다룹니다.",
        "작업환경 개선": "작업 환경, 정보 배치, 절차 설계가 성능과 피로도에 주는 영향을 다룹니다.",
        "생체역학": "자세, 힘, 움직임 측정 기반으로 신체 부담과 수행 효율을 정량적으로 분석합니다.",
        "역학·통계": "특정 작업군의 위험요인과 관련 변수를 조사해 관리 우선순위를 정하는 데 초점을 둡니다.",
        "AI·기술": "AI 또는 자동화 기술이 사용자의 판단, 신뢰, 개입 방식에 미치는 영향을 다룹니다.",
    }

    method_bits = []
    if any(k in text for k in ["randomized", "trial", "controlled"]):
        method_bits.append("비교 실험 또는 무작위 시험 기반")
    if any(k in text for k in ["survey", "questionnaire", "cross-sectional"]):
        method_bits.append("설문 또는 단면 조사 기반")
    if any(k in text for k in ["review", "scoping review", "systematic review", "meta-analysis"]):
        method_bits.append("문헌고찰 기반")
    if any(k in text for k in ["emg", "kinematic", "biomechanics", "motion", "force"]):
        method_bits.append("생체역학·동작 측정 기반")
    if any(k in text for k in ["interview", "qualitative", "focus group"]):
        method_bits.append("정성 인터뷰 또는 관찰 기반")
    if any(k in text for k in ["machine learning", "deep learning", "model", "algorithm", "ai"]):
        method_bits.append("AI/모델 평가 기반")
    if not method_bits:
        method_bits.append("초록 기준으로 연구 설계와 핵심 변수를 정리")

    result_line = "초록에 제시된 비교 결과와 핵심 변수의 방향성을 중심으로, 실제 업무 설계에 참고할 만한 차이 또는 위험 요인을 확인할 수 있습니다."
    if any(k in text for k in ["significant", "improved", "improvement", "reduced", "lower"]):
        result_line = "개입 또는 조건 차이에 따라 작업부하, 수행 효율, 사용성 중 일부 지표가 개선되었음을 시사합니다."
    if any(k in text for k in ["no difference", "noninferiority", "non-inferiority"]):
        result_line = "기존 방식과 비교해 성능 저하 없이 대체 가능하거나 비열등함을 보였다는 해석이 가능합니다."
    if any(k in text for k in ["risk", "hazard", "burden", "fatigue", "pain"]):
        result_line = "작업부하·피로·통증 또는 위험 노출과 관련된 핵심 요인이 결과 변수로 제시됩니다."

    ux_points = []
    if topic == "초음파 인간공학":
        ux_points += [
            "검사 중 반복 입력과 손목 회전을 줄이도록 프리셋 진입, 측정, 저장까지의 탭 수를 축소하는 UI 검토가 필요합니다.",
            "프로브를 쥔 상태에서도 자주 쓰는 기능에 빠르게 접근할 수 있도록 물리 버튼·소프트키 역할 분담을 재정의할 수 있습니다.",
            "케이블, 프로브, 콘솔 조작이 동시에 발생하는 상황을 고려해 화면 전환을 줄이고 자동 상태 유지 기능을 강화할 근거로 활용할 수 있습니다.",
        ]
    elif topic == "근골격계질환":
        ux_points += [
            "반복 자세 부담이 큰 작업에서는 측정·주석·저장 절차를 단축해 동일 동작의 누적을 줄이는 것이 중요합니다.",
            "작은 클릭 타깃, 깊은 메뉴, 잦은 모드 전환처럼 상지 부담을 키우는 UI 패턴을 우선 제거할 수 있습니다.",
            "검사 시간 단축뿐 아니라 자세 변경 빈도를 줄이는 인터랙션 설계를 핵심 성과지표로 두는 방향이 적절합니다.",
        ]
    elif topic == "임상 인간공학":
        ux_points += [
            "임상 맥락에서 오류 가능성이 높은 단계에 대해 확인 피드백, 상태 가시성, 다음 행동 유도 문구를 더 명확히 설계할 수 있습니다.",
            "숙련도 차이가 큰 사용자군을 고려해 초심자용 가이드와 숙련자용 단축 흐름을 함께 제공하는 구조를 검토할 수 있습니다.",
            "복합 작업 중 인지 전환 비용을 줄이기 위해 검사 맥락에 맞는 정보 우선순위와 알림 밀도 조정이 필요합니다.",
        ]
    elif topic == "작업환경 개선":
        ux_points += [
            "모니터 시선 이동, 키보드/터치 전환, 입력 장치 왕복을 줄이도록 화면 배치와 정보 계층을 재설계할 수 있습니다.",
            "빈도가 높은 시나리오를 기준으로 홈·검사·리뷰 화면의 핵심 정보 배치를 표준화할 근거로 활용할 수 있습니다.",
            "사용자 피로를 줄이는 방향으로 불필요한 경고, 중복 확인, 시각적 잡음을 줄이는 정책을 검토할 수 있습니다.",
        ]
    elif topic == "생체역학":
        ux_points += [
            "신체 부담이 큰 순간에 어떤 조작이 겹치는지 분석해, 그 구간의 인터랙션 수를 줄이는 설계가 필요합니다.",
            "검사 자세 변화와 동기화되는 UI 요소를 줄여 한 손 또는 최소 시선 이동으로 끝나는 조작 흐름을 지향할 수 있습니다.",
            "정량 지표 기반으로 부담이 큰 시나리오를 우선순위화해 UX 개선 로드맵을 세우는 데 활용할 수 있습니다.",
        ]
    elif topic == "AI·기술":
        ux_points += [
            "AI 결과는 자동 표시만으로 끝내지 말고 근거, 신뢰도, 수정 경로를 함께 제공해 사용자가 판단권을 유지하도록 해야 합니다.",
            "자동화가 시간을 줄이더라도 재확인 비용이 커지면 체감 효율이 떨어지므로, 검증 인터랙션을 최소화하는 설계가 필요합니다.",
            "새 기술 도입 시 기존 검사 흐름을 크게 깨지 않는 점진적 개입 방식이 현장 수용성을 높일 수 있습니다.",
        ]
    else:
        ux_points += [
            "연구에서 제시한 부담 요인이나 성능 차이를 현재 초음파 검사 워크플로우의 병목 단계와 연결해 개선 우선순위를 정할 수 있습니다.",
            "복잡한 절차를 줄이고 핵심 결정 지점의 정보 가시성을 높이는 방향으로 UI를 재구성할 근거로 활용할 수 있습니다.",
            "시간 절감뿐 아니라 인지부하와 물리적 부담 감소를 함께 UX 성과지표에 포함시키는 데 참고할 수 있습니다.",
        ]

    if "fatigue" in text or "workload" in text or "burden" in text:
        ux_points.append("사용자 피로·작업부하 지표를 기능 성공률과 함께 추적해, 실제 현장 효율을 반영하는 UX 평가체계를 설계할 수 있습니다.")
    if "usability" in text or "interface" in text:
        ux_points.append("사용성 결과를 메뉴 구조 단순화, 정보 우선순위 조정, 학습 부담 감소 같은 구체적 UI 과제로 연결할 수 있습니다.")
    if "ultrasound" in text or "sonograph" in text or "transducer" in text:
        ux_points.append("프로브 조작과 화면 조작이 동시에 일어나는 초음파 특성을 반영해, 한 손 사용성과 빠른 복귀 흐름을 강화하는 데 직접 참고할 수 있습니다.")

    deduped = []
    for p in ux_points:
        if p not in deduped:
            deduped.append(p)

    return {
        "research_topic": topic_summary.get(topic, "논문 초록을 바탕으로 작업부하, 사용성, 수행 성능과 관련된 핵심 연구 질문을 정리합니다."),
        "methodology": " / ".join(method_bits[:3]),
        "key_result": result_line,
        "ux_insights": deduped[:4],
    }


def enrich_papers_with_korean_and_ux(papers: list) -> list:
    if not papers:
        return []

    compact = []
    for i, p in enumerate(papers, start=1):
        compact.append({
            "id": i,
            "topic": get_topic(p),
            "title": p.get("title", ""),
            "authors": p.get("authors", ""),
            "journal": p.get("journal", ""),
            "pub_date": p.get("pub_date", ""),
            "abstract": p.get("abstract", "")[:1400],
            "source": p.get("source", ""),
            "evidence": p.get("evidence", ""),
        })

    prompt = f"""
당신은 인간공학 분야 연구 편집자이자 의료기기 UX 전략가입니다.
아래 논문 목록을 읽고 각 논문마다 다음을 작성하세요.

규칙:
- 반드시 JSON 배열만 출력합니다.
- 각 항목에는 id, ko_title, research_topic, methodology, key_result, ux_insights 를 포함합니다.
- ko_title: 자연스러운 한국어 제목 1개
- research_topic: 핵심 연구 주제를 한국어 1~2문장으로 정리
- methodology: 주요 방법론을 한국어 1~2문장으로 정리. 연구 설계, 참가자/데이터, 측정 방식이 보이면 반영
- key_result: 핵심 결과를 한국어 1~2문장으로 정리. 초록에 없는 결론은 쓰지 않음
- ux_insights: 삼성메디슨 UX 업무에 적용 가능한 인사이트 3~4개 배열
- 4번이 가장 중요합니다. 각 인사이트는 반드시 초음파 진단 장비 UX, 검사 워크플로우, 자동 측정/판독 보조, 정보 구조, 버튼/터치 조작, 인지부하, 작업부하 감소 중 하나 이상과 연결해 구체적으로 씁니다.
- 추상적 표현(예: "사용성을 높일 수 있다")만 쓰지 말고, 어떤 화면/기능/조작 원칙에 연결되는지 구체적으로 적습니다.
- 논문 초록 범위를 벗어난 과장, 임상적 단정, 회사 내부 사정을 가정한 제안은 금지합니다.

입력 데이터:
{json.dumps(compact, ensure_ascii=False)}
"""

    parsed_map = {}
    raw = call_gemini_json(prompt, "papers_enrichment")
    if raw:
        try:
            parsed = json.loads(raw)
            for item in parsed:
                parsed_map[item.get("id")] = item
        except Exception as e:
            print(f"논문 배치 JSON 파싱 오류: {e}")

    enriched = []
    for i, p in enumerate(papers, start=1):
        topic = get_topic(p)
        row = parsed_map.get(i, {})
        ko_title = normalize_space(row.get("ko_title", "")) or translate_ko(p.get("title", ""))
        structured = {
            "research_topic": normalize_space(row.get("research_topic", "")),
            "methodology": normalize_space(row.get("methodology", "")),
            "key_result": normalize_space(row.get("key_result", "")),
            "ux_insights": row.get("ux_insights", []) if isinstance(row.get("ux_insights", []), list) else [],
        }

        fallback = fallback_paper_structured_summary(topic, p.get("title", ""), p.get("abstract", ""))
        if not structured["research_topic"]:
            structured["research_topic"] = fallback["research_topic"]
        if not structured["methodology"]:
            structured["methodology"] = fallback["methodology"]
        if not structured["key_result"]:
            structured["key_result"] = fallback["key_result"]
        if not structured["ux_insights"]:
            structured["ux_insights"] = fallback["ux_insights"]

        structured["ux_insights"] = [normalize_space(x) for x in structured["ux_insights"] if normalize_space(x)][:4]

        enriched.append({
            **p,
            "topic": topic,
            "ko_title": ko_title,
            "research_topic": structured["research_topic"],
            "methodology": structured["methodology"],
            "key_result": structured["key_result"],
            "ux_insights": structured["ux_insights"],
        })
    return enriched


def group_news_by_company(items: list) -> dict:
    grouped = defaultdict(list)
    for item in items:
        grouped[item.get("company", get_company(item))].append(item)

    for company in grouped:
        grouped[company] = sorted(
            grouped[company],
            key=lambda x: (x.get("date", ""), x.get("title", "")),
            reverse=True,
        )
    return grouped


def news_summary_bilingual(item: dict) -> dict:
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    source = item.get("source", "")
    category = item.get("detail_category", classify_news_category(item))

    prompt = f"""
다음 뉴스 1건을 사실 범위를 벗어나지 않게 매우 짧게 요약하세요.
반드시 JSON만 출력합니다.
{{
  "en_summary": "...",
  "ko_summary": "..."
}}
규칙:
- 영어 1~2문장, 한국어 1~2문장
- 과장 금지, 추측 금지
- 기사에 없는 정보 추가 금지

제목: {title}
출처: {source}
분류: {category}
본문 스니펫: {snippet}
"""
    raw = call_gemini_json(prompt, "news_item")
    if raw:
        try:
            parsed = json.loads(raw)
            en_summary = normalize_space(parsed.get("en_summary", ""))
            ko_summary = normalize_space(parsed.get("ko_summary", ""))
            if en_summary and ko_summary:
                return {"en_summary": en_summary, "ko_summary": ko_summary}
        except Exception:
            pass

    base_en = snippet or title
    if len(base_en) > 220:
        base_en = base_en[:220] + "..."
    return {"en_summary": base_en, "ko_summary": translate_ko(base_en)}


def build_news_html(items: list) -> str:
    if not items:
        return "<p>지난 24시간 내 조건에 맞는 신뢰 출처 뉴스가 없습니다.</p>"

    grouped = group_news_by_company(items)
    sorted_companies = sorted(
        grouped.items(),
        key=lambda x: (x[0] == "기타 초음파 동향", -len(x[1]), x[0]),
    )

    blocks = []
    for company, company_items in sorted_companies:
        blocks.append(
            f'''<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">{safe_html(company)} ({len(company_items)}건)</h3>
</div>'''
        )
        for item in company_items[:MAX_NEWS_PER_COMPANY]:
            summary = news_summary_bilingual(item)
            trust_label = {
                "official_regulatory_source": "공식 규제기관",
                "trusted_specialist_media": "전문매체",
                "trusted_publisher": "신뢰 출처",
            }.get(item.get("trust", ""), "확인 출처")
            blocks.append(
                f'''<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">{safe_html(item.get("detail_category", "시장/경영"))}</span>
  <h4 style="margin:4px 0;font-size:14px;">
    <a href="{safe_html(item.get("url", ""))}" style="color:#1a5276;text-decoration:none;">{safe_html(trim_title_suffix(item.get("title", "")))}</a>
  </h4>
  <p style="font-size:11px;color:#777;margin:2px 0;">{safe_html(item.get("date", "")[:16])} · {safe_html(item.get("source", ""))} · {trust_label}</p>
  <p style="font-size:13px;color:#333;line-height:1.6;">{safe_html(summary["en_summary"])}</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;">{safe_html(summary["ko_summary"])}</p>
</div>'''
            )
    return "\n".join(blocks)


def build_papers_html(papers: list) -> str:
    if not papers:
        return "<p>지난 48시간 기준 신규 논문이 없습니다.</p>"

    enriched = enrich_papers_with_korean_and_ux(papers[:MAX_PAPERS])
    blocks = []
    for p in enriched:
        abstract_en = normalize_space(p.get("abstract", ""))
        if len(abstract_en) > 520:
            abstract_en = abstract_en[:520] + "..."
        if p.get("doi"):
            link = f'https://doi.org/{safe_html(p["doi"])}'
        else:
            link = safe_html(p.get("link", ""))
        ux_html = "".join([f"<li style=\"margin:0 0 6px;\">{safe_html(point)}</li>" for point in p.get("ux_insights", [])])
        evidence_label = {
            "peer_reviewed_or_indexed": "PubMed 색인",
            "preprint": "Preprint",
            "index_metadata": "색인 메타데이터",
        }.get(p.get("evidence", ""), p.get("source", ""))
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
  <div style="background:#eef6fb;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1a5276;">1) 핵심 연구 주제</p>
    <p style="margin:0;font-size:13px;color:#34495e;">{safe_html(p.get("research_topic", ""))}</p>
  </div>
  <div style="background:#f7fafc;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1a5276;">2) 주요 방법론</p>
    <p style="margin:0;font-size:13px;color:#34495e;">{safe_html(p.get("methodology", ""))}</p>
  </div>
  <div style="background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;margin-top:8px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#1f6f43;">3) 핵심 결과</p>
    <p style="margin:0;font-size:13px;color:#2f4f3e;">{safe_html(p.get("key_result", ""))}</p>
  </div>
  <div style="background:#fff7e8;border:1px solid #f4d08b;padding:10px 12px;border-radius:4px;margin-top:10px;">
    <p style="margin:0 0 6px;font-size:12px;font-weight:bold;color:#9a6700;">4) 삼성메디슨 UX 업무에 적용 가능한 인사이트</p>
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
      <p style="margin:0 0 10px;font-size:12px;color:#6b7280;">공식 기업 발표, 규제기관 데이터, 전문매체 등 출처가 확인되는 정보만 포함했습니다. 회사별로 그룹핑해 가독성을 높였습니다.</p>
      {news_html}
    </td>
  </tr>
  <tr><td style="padding:0 30px;"><hr style="border:none;border-top:1px solid #e8eef5;"/></td></tr>
  <tr>
    <td style="padding:20px 30px 24px;">
      <h2 style="margin:0 0 12px;color:#1a5276;border-bottom:2px solid #27ae60;padding-bottom:8px;">인간공학 논문 동향</h2>
      <p style="margin:0 0 10px;font-size:12px;color:#6b7280;">논문 초록을 바탕으로 핵심 연구 주제, 주요 방법론, 핵심 결과, 그리고 삼성메디슨 UX 업무에 적용 가능한 인사이트를 구조화해 정리했습니다.</p>
      {papers_html}
    </td>
  </tr>
  <tr>
    <td style="background:#2c3e50;padding:18px 30px;color:#bdc3c7;font-size:11px;line-height:1.7;">
      <p style="margin:0;">요약 문장은 AI를 사용해 정리했지만, 링크된 원문과 DOI/PMID 확인을 전제로 활용하는 것이 적절합니다.</p>
      <p style="margin:4px 0 0;">News sources: trusted publisher Google News RSS, specialist media RSS, FDA openFDA</p>
      <p style="margin:4px 0 0;">Paper sources: PubMed, arXiv, Semantic Scholar</p>
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


def collect_papers() -> list:
    tasks = [
        (fetch_pubmed_papers, ("ergonomics", 6)),
        (fetch_arxiv_papers, ("ergonomics", 2)),
        (fetch_semantic_scholar, ("ergonomics workplace", 2)),
    ]
    papers_raw = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = [ex.submit(func, *args) for func, args in tasks]
        for fut in as_completed(futures):
            try:
                papers_raw.extend(fut.result() or [])
            except Exception as e:
                print(f"논문 수집 작업 오류: {e}")

    seen = set()
    unique = []
    for p in papers_raw:
        key = normalize_space(p.get("title", "")).lower()[:180]
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    def paper_rank(p):
        evidence_order = {"peer_reviewed_or_indexed": 0, "index_metadata": 1, "preprint": 2}
        return (evidence_order.get(p.get("evidence", "preprint"), 9), p.get("pub_date", ""))

    unique.sort(key=paper_rank)
    return unique[:MAX_PAPERS]


def main():
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
    print("완료!")


if __name__ == "__main__":
    main()
