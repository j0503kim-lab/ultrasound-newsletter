#!/usr/bin/env python3
"""
초음파 산업 & 인간공학 연구 뉴스레터
- 실행 시간 최적화 버전
- 회사별 그룹핑 강화
- 자연스러운 한국어 요약
"""

import os
import json
import html
import time
import datetime
import requests
import feedparser
import smtplib
import xml.etree.ElementTree as ET
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from deep_translator import GoogleTranslator

# ── 설정 ──────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "j0503.kim@gmail.com")
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PUBMED_API_KEY = os.environ.get("PUBMED_API_KEY", "")

REQUEST_TIMEOUT = 25
MAX_NEWS_FOR_GEMINI = 18
MAX_PAPERS_FOR_GEMINI = 6
MAX_NEWS_PER_COMPANY = 5

# ── 노이즈 필터 ────────────────────────────────────────────────
NOISE_KEYWORDS = [
    "cleaning", "welding", "industrial ndt", "non-destructive",
    "pest control", "humidifier", "jewelry cleaner", "rodent",
    "bark control", "ultrasonic cleaner", "ultrasonic welder",
    "oled tv", "boombox", "audio gear", "stereo", "headphone",
    "flow meter", "level sensor", "distance sensor"
]

def is_medical_news(title: str, snippet: str = "") -> bool:
    text = (title + " " + snippet).lower()
    return not any(noise in text for noise in NOISE_KEYWORDS)

def safe_html(text: str) -> str:
    return html.escape(text or "")

def trim_title_suffix(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title.strip()

# ── RSS 쿼리 ───────────────────────────────────────────────────
RSS_QUERIES = {
    "글로벌 대형사": (
        '"GE HealthCare" OR "Philips" OR "Siemens Healthineers" '
        'OR "Samsung Medison" OR "Canon Medical" OR "Mindray" '
        'OR "Fujifilm Sonosite" OR "FUJIFILM Healthcare" OR "Esaote"'
    ),
    "POCUS·스타트업": (
        '"Butterfly Network" OR "Butterfly iQ" OR "Exo Imaging" OR "Exo Iris" '
        'OR "Clarius Mobile Health" OR "EchoNous" OR "Vave Health" '
        'OR "Pulsenmore" OR "iSono Health" OR "Rivanna Medical"'
    ),
    "AI 초음파": (
        '"Ultromics" OR "Caption Health" OR "DiA Imaging" OR "UltraSight" '
        'OR "iCardio.ai" OR "BrightHeart" OR "Sonio" OR "ThinkSono" '
        'OR "SmartAlpha" OR "Nerveblox" OR "Ligence" OR "Diagnoly"'
    ),
    "중국 회사": (
        '"SonoScape" OR "CHISON" OR "Wisonic" OR "SIUI" '
        'OR "Edan Instruments" OR "VINNO Technology" OR "Landwind Medical"'
    ),
    "유럽·이스라엘": (
        '"Echosens" OR "FibroScan" OR "Echolight" OR "PIUR Imaging" '
        'OR "Sonoscanner" OR "SuperSonic Imagine" '
        'OR "TechsoMed" OR "Alpinion Medical"'
    ),
    "한국 회사": (
        '"Samsung Medison" OR "Alpinion Medical" OR "Healcerion" '
        'OR "SG Healthcare" ultrasound OR "Bistos"'
    ),
    "규제·인허가": (
        '("FDA clearance" OR "510k" OR "FDA approval" OR "CE mark" '
        'OR "De Novo" OR "MFDS") ultrasound'
    ),
    "AI·혁신 트렌드": (
        '"ultrasound AI" OR "AI ultrasound" OR "handheld ultrasound" '
        'OR "portable ultrasound" OR "POCUS" OR "point-of-care ultrasound"'
    ),
    "전문매체": (
        'ultrasound (site:auntminnie.com OR site:itnonline.com '
        'OR site:diagnosticimaging.com OR site:massdevice.com '
        'OR site:medtechdive.com)'
    ),
}

SPECIALIST_RSS_FEEDS = [
    ("AuntMinnie", "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("MedTech Dive", "https://www.medtechdive.com/feeds/news/"),
    ("MassDevice", "https://www.massdevice.com/feed/"),
    ("Medical Device Network", "https://www.medicaldevice-network.com/feed/"),
]

# ── 회사 분류 맵 ───────────────────────────────────────────────
COMPANY_MAP = {
    "GE HealthCare": ["ge healthcare", "gehc", "intelerad", "bk medical", "caption health"],
    "Philips": ["philips"],
    "Siemens Healthineers": ["siemens healthineers"],
    "Samsung Medison": ["samsung medison", "samsung hme"],
    "Canon Medical": ["canon medical"],
    "FUJIFILM / Sonosite": ["fujifilm", "sonosite", "visualsonics"],
    "Mindray": ["mindray"],
    "Esaote": ["esaote"],
    "Butterfly Network": ["butterfly network", "butterfly iq", "bfly"],
    "Exo Imaging": ["exo imaging", "exo iris"],
    "Clarius": ["clarius mobile", "clarius"],
    "EchoNous": ["echonous", "kosmos ultrasound"],
    "Alpinion": ["alpinion"],
    "Healcerion": ["healcerion", "sonon"],
    "SG Healthcare": ["sg healthcare"],
    "Bistos": ["bistos"],
    "SonoScape": ["sonoscape"],
    "CHISON": ["chison"],
    "Wisonic": ["wisonic"],
    "SIUI": ["siui"],
    "Edan": ["edan instruments", "edan"],
    "VINNO": ["vinno"],
    "Landwind Medical": ["landwind medical"],
    "Echosens": ["echosens", "fibroscan"],
    "Echolight": ["echolight"],
    "PIUR Imaging": ["piur imaging"],
    "Sonoscanner": ["sonoscanner"],
    "SuperSonic Imagine": ["supersonic imagine", "hologic supersonic"],
    "TechsoMed": ["techsomed"],
    "AI 초음파 솔루션": [
        "ultromics", "ultrasight", "dia imaging", "icardio", "brightheart",
        "thinksono", "smartalpha", "nerveblox", "ligence", "diagnoly", "sonio"
    ],
    "FDA 인허가": ["fda 510", "510(k)", "ce mark", "de novo", "fda approval", "fda clearance"],
}

def get_company(item: dict) -> str:
    text = (item.get("title", "") + " " + item.get("snippet", "") + " " + item.get("source", "")).lower()
    for company, keywords in COMPANY_MAP.items():
        if any(kw in text for kw in keywords):
            return company
    return "기타 초음파 동향"

def classify_news_category(item: dict) -> str:
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    if any(k in text for k in ["fda", "510(k)", "ce mark", "approval", "clearance", "de novo", "mfds"]):
        return "인허가 승인"
    if any(k in text for k in ["acquire", "acquisition", "merger", "partner", "partnership", "collaboration", "alliance"]):
        return "인수/합병/파트너십"
    if any(k in text for k in ["study", "trial", "clinical", "research", "validation"]):
        return "임상/연구"
    if any(k in text for k in ["launch", "introduce", "unveil", "release", "new system", "platform", "software"]):
        return "신제품/기술"
    return "시장/경영"

# ── 1. 데이터 수집 ─────────────────────────────────────────────
def fetch_google_news_rss(query: str, label: str, max_items: int = 10) -> list:
    url = (
        f"https://news.google.com/rss/search?"
        f"q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    feed = feedparser.parse(url)
    items = []

    for e in feed.entries[:max_items]:
        title = e.get("title", "")
        snippet = e.get("summary", "")[:280]
        if not is_medical_news(title, snippet):
            continue

        items.append({
            "title": title,
            "snippet": snippet,
            "url": e.get("link", ""),
            "date": e.get("published", ""),
            "source": e.get("source", {}).get("title", "Google News"),
            "category": label,
        })
    return items

def fetch_all_ultrasound_news() -> list:
    all_items = []
    seen = set()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    for label, query in RSS_QUERIES.items():
        items = fetch_google_news_rss(query, label, 10)
        for item in items:
            key = (trim_title_suffix(item["title"]).lower(), item.get("url", ""))
            if key not in seen:
                seen.add(key)
                all_items.append(item)

    for name, url in SPECIALIST_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:12]:
                pub = e.get("published_parsed")
                if pub:
                    pub_dt = datetime.datetime(*pub[:6], tzinfo=datetime.timezone.utc)
                    if pub_dt < cutoff:
                        continue

                title = e.get("title", "")
                snippet = e.get("summary", "")[:280]

                if "ultrasound" not in (title + snippet).lower():
                    continue
                if not is_medical_news(title, snippet):
                    continue

                key = (trim_title_suffix(title).lower(), e.get("link", ""))
                if key not in seen:
                    seen.add(key)
                    all_items.append({
                        "title": title,
                        "snippet": snippet,
                        "url": e.get("link", ""),
                        "date": e.get("published", ""),
                        "source": f"STAR {name}",
                        "category": "전문매체",
                    })
        except Exception as ex:
            print(f"{name} RSS 오류: {ex}")

    print(f"뉴스 총 {len(all_items)}건 수집")
    return all_items

def fetch_fda_510k() -> list:
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    url = (
        f"https://api.fda.gov/device/510k.json?"
        f"search=openfda.device_name:ultrasound"
        f"+AND+decision_date:[{week_ago:%Y%m%d}+TO+{today:%Y%m%d}]&limit=8"
    )

    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            items = []
            for rec in r.json().get("results", []):
                items.append({
                    "title": f"FDA 510(k) Cleared: {rec.get('device_name', 'N/A')}",
                    "snippet": f"Applicant: {rec.get('applicant', 'N/A')} | K-number: {rec.get('k_number', 'N/A')}",
                    "url": f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={rec.get('k_number', '')}",
                    "date": rec.get("decision_date", ""),
                    "source": "FDA openFDA",
                    "category": "FDA 인허가",
                })
            print(f"FDA 510k {len(items)}건")
            return items
    except Exception as e:
        print(f"FDA 오류: {e}")
    return []

def fetch_pubmed_papers(query="ergonomics", max_results=10) -> list:
    params = {
        "db": "pubmed",
        "term": query,
        "datetype": "edat",
        "reldate": 2,
        "retmax": max_results,
        "retmode": "json",
        "sort": "date"
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY

    r = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        print("PubMed 논문 없음")
        return []

    time.sleep(0.34)

    params2 = {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "xml",
        "retmode": "xml"
    }
    if PUBMED_API_KEY:
        params2["api_key"] = PUBMED_API_KEY

    r2 = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params=params2,
        timeout=REQUEST_TIMEOUT
    )

    root = ET.fromstring(r2.content)
    papers = []

    for article in root.findall(".//PubmedArticle"):
        medline = article.find(".//MedlineCitation")
        art = medline.find(".//Article") if medline is not None else None
        if art is None:
            continue

        title = art.findtext(".//ArticleTitle", "")
        abstract = " ".join([a.text or "" for a in art.findall(".//AbstractText")])[:900]
        authors = [
            f"{a.findtext('ForeName', '')} {a.findtext('LastName', '')}".strip()
            for a in art.findall(".//Author")[:6]
            if a.findtext("LastName")
        ]
        affil_el = art.find(".//AffiliationInfo/Affiliation")
        affil = affil_el.text[:220] if affil_el is not None and affil_el.text else ""
        journal = art.findtext(".//Journal/Title", "")
        pmid = medline.findtext(".//PMID", "")
        doi_el = art.find(".//ELocationID[@EIdType='doi']")
        doi = doi_el.text if doi_el is not None else ""

        pub = art.find(".//Journal/JournalIssue/PubDate")
        pub_date = " ".join(filter(None, [
            pub.findtext("Year", "") if pub is not None else "",
            pub.findtext("Month", "") if pub is not None else ""
        ]))

        papers.append({
            "title": title,
            "authors": ", ".join(authors),
            "affiliations": affil,
            "abstract": abstract,
            "doi": doi,
            "journal": journal,
            "pub_date": pub_date,
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        })

    print(f"PubMed 논문 {len(papers)}편")
    return papers

def fetch_arxiv_papers(query="ergonomics", max_results=5) -> list:
    r = requests.get(
        "http://export.arxiv.org/api/query",
        params={
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending"
        },
        timeout=REQUEST_TIMEOUT
    )
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.content)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)

    papers = []
    for entry in root.findall("atom:entry", ns):
        pub = entry.findtext("atom:published", "", ns)
        try:
            if datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")) < cutoff:
                continue
        except Exception:
            pass

        authors = [a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)]
        papers.append({
            "title": entry.findtext("atom:title", "", ns).strip().replace("\n", " "),
            "authors": ", ".join(authors[:6]),
            "affiliations": "",
            "abstract": entry.findtext("atom:summary", "", ns).strip()[:900],
            "doi": "",
            "journal": "arXiv preprint",
            "pub_date": pub[:10],
            "link": entry.findtext("atom:id", "", ns)
        })

    print(f"arXiv 논문 {len(papers)}편")
    return papers

def fetch_semantic_scholar(query="ergonomics workplace", max_results=5) -> list:
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=3)

    try:
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "fields": "title,authors,abstract,publicationDate,journal,externalIds",
                "limit": max_results,
                "publicationDateOrYear": f"{yesterday}:{today}"
            },
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code != 200:
            return []

        papers = []
        for p in r.json().get("data", []):
            doi = (p.get("externalIds") or {}).get("DOI", "")
            papers.append({
                "title": p.get("title", ""),
                "authors": ", ".join([a.get("name", "") for a in (p.get("authors") or [])[:6]]),
                "affiliations": "",
                "abstract": (p.get("abstract") or "")[:900],
                "doi": doi,
                "journal": (p.get("journal") or {}).get("name", ""),
                "pub_date": p.get("publicationDate", ""),
                "link": f"https://doi.org/{doi}" if doi else ""
            })

        print(f"Semantic Scholar 논문 {len(papers)}편")
        return papers
    except Exception as e:
        print(f"Semantic Scholar 오류: {e}")
        return []

# ── 2. Gemini 호출 ─────────────────────────────────────────────
def call_gemini(prompt: str, data_json: str = "") -> str:
    if not GEMINI_API_KEY:
        return ""

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )

    final_prompt = prompt.replace("{{DATA_JSON}}", data_json)

    payload = {
        "contents": [{"parts": [{"text": final_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 7000
        }
    }

    for attempt in range(2):
        try:
            r = requests.post(url, json=payload, timeout=90)
            if r.status_code == 200:
                candidates = r.json().get("candidates", [])
                if candidates:
                    text = candidates[0]["content"]["parts"][0]["text"]
                    return text.replace("```html", "").replace("```json", "").replace("```", "").strip()
            elif r.status_code == 429:
                wait = 8 * (attempt + 1)
                print(f"Gemini 429 — {wait}초 대기 후 재시도")
                time.sleep(wait)
            else:
                print(f"Gemini 오류: {r.status_code}")
                return ""
        except Exception as e:
            print(f"Gemini 예외: {e}")
            return ""

    return ""

def translate_ko(text: str) -> str:
    if not text:
        return ""
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:3500])
    except Exception:
        return text

def natural_korean_summary(title: str, abstract: str, authors: str = "", journal: str = "") -> dict:
    if GEMINI_API_KEY:
        prompt = f"""
당신은 인간공학 분야 학술 편집자입니다.
아래 논문의 제목과 초록을 바탕으로 한국어 독자가 자연스럽게 읽을 수 있도록 정리하세요.

규칙:
- 직역투 금지
- 한국 연구자가 읽는 학술 요약문처럼 작성
- 제목은 짧고 자연스럽게
- 요약은 3문장 이내
- 문장 종결은 "~했습니다 / ~나타났습니다 / ~시사합니다" 중심
- 저자명, 기관명, 저널명, DOI는 번역하지 않음
- 과장 금지, 초록에 없는 내용 추가 금지
- 반드시 JSON만 출력

JSON 형식:
{{
  "ko_title": "...",
  "ko_summary": "..."
}}

제목: {title}
저자: {authors}
저널: {journal}
초록: {abstract[:1500]}
"""
        result = call_gemini(prompt, "")
        if result:
            try:
                parsed = json.loads(result)
                return {
                    "ko_title": parsed.get("ko_title", "").strip() or translate_ko(title),
                    "ko_summary": parsed.get("ko_summary", "").strip() or translate_ko(abstract[:500]),
                }
            except Exception:
                pass

    return {
        "ko_title": translate_ko(title),
        "ko_summary": translate_ko(abstract[:500]),
    }

def news_summary_bilingual(item: dict) -> dict:
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    source = item.get("source", "")
    date = item.get("date", "")
    category = classify_news_category(item)

    if GEMINI_API_KEY:
        prompt = f"""
당신은 의료기기 산업 애널리스트입니다.
아래 뉴스 항목을 자연스럽고 짧게 요약하세요.

규칙:
- 영어 요약 2문장 이하
- 한국어 요약 2문장 이하
- 한국어는 자연스럽고 간결하게
- 기사에 없는 내용 추가 금지
- 반드시 JSON만 출력

JSON 형식:
{{
  "en_summary": "...",
  "ko_summary": "..."
}}

제목: {title}
출처: {source}
날짜: {date}
분류: {category}
스니펫: {snippet}
"""
        result = call_gemini(prompt, "")
        if result:
            try:
                parsed = json.loads(result)
                return {
                    "en_summary": parsed.get("en_summary", "").strip(),
                    "ko_summary": parsed.get("ko_summary", "").strip(),
                }
            except Exception:
                pass

    base_en = snippet.replace("<b>", "").replace("</b>", "").strip()
    if len(base_en) > 220:
        base_en = base_en[:220] + "..."
    base_ko = translate_ko(base_en)

    return {
        "en_summary": base_en or title,
        "ko_summary": base_ko or translate_ko(title)
    }

# ── 3. Gemini용 배치 프롬프트 ─────────────────────────────────
NEWS_BATCH_PROMPT = """
당신은 초음파 의료기기 산업 전문 애널리스트입니다.
아래 뉴스를 회사별로 그룹핑하여 HTML 뉴스레터 본문을 만드세요.

규칙:
1. 회사별로 묶어서 출력
2. 회사명은 가능한 한 명확하게 표기
3. 각 회사 아래 기사 수는 최대 5건
4. 각 기사마다:
   - 영어 요약 1~2문장
   - 자연스러운 한국어 요약 1~2문장
5. 카테고리는 신제품/기술, 인허가 승인, 인수/합병/파트너십, 시장/경영, 임상/연구 중 하나
6. HTML만 출력
7. <html>, <body> 태그는 만들지 말 것

회사 헤더 형식:
<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">COMPANY_NAME (N건)</h3>
</div>

기사 카드 형식:
<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">CATEGORY</span>
  <h4 style="margin:4px 0;font-size:14px;"><a href="URL" style="color:#1a5276;text-decoration:none;">TITLE</a></h4>
  <p style="font-size:11px;color:#777;margin:2px 0;">DATE · SOURCE</p>
  <p style="font-size:13px;color:#333;line-height:1.6;">ENGLISH_SUMMARY</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;">KOREAN_SUMMARY</p>
</div>

{{DATA_JSON}}
"""

PAPERS_BATCH_PROMPT = """
당신은 인간공학 분야 전문 연구자이자 한국어 학술 편집자입니다.
아래 논문들을 읽고 HTML 뉴스레터 본문을 만드세요.

규칙:
1. 각 논문마다 주제를 하나 분류: 근골격계질환 / 임상 인간공학 / 작업환경 개선 / 생체역학 / 역학·통계 / AI·기술 / 초음파 인간공학 / 기타
2. 영어 제목은 원문 유지
3. 한국어 제목은 자연스럽게 작성
4. 한국어 요약은 2~3문장
5. 직역투 금지
6. HTML만 출력
7. <html>, <body> 태그는 만들지 말 것

논문 카드 형식:
<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">TOPIC</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">ENGLISH_TITLE</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">KOREAN_TITLE</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">AUTHORS<br/>AFFILIATION<br/>JOURNAL · DATE · LINK</p>
  <p style="font-size:13px;color:#333;line-height:1.7;"><strong>Summary:</strong> ENGLISH_SUMMARY</p>
  <p style="font-size:13px;color:#444;background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;"><strong>요약:</strong> KOREAN_SUMMARY</p>
</div>

{{DATA_JSON}}
"""

# ── 4. 뉴스 HTML ──────────────────────────────────────────────
def group_news_by_company(items: list) -> dict:
    grouped = defaultdict(list)
    for item in items:
        item["company"] = get_company(item)
        item["detail_category"] = classify_news_category(item)
        grouped[item["company"]].append(item)

    for company in grouped:
        grouped[company] = sorted(
            grouped[company],
            key=lambda x: (x.get("date", ""), x.get("title", "")),
            reverse=True
        )
    return grouped

def build_news_html(items: list) -> str:
    if not items:
        return "<p>오늘 관련 뉴스가 없습니다.</p>"

    grouped = group_news_by_company(items)
    compact_items = []
    sorted_companies = sorted(
        grouped.items(),
        key=lambda x: (0 if x[0] != "기타 초음파 동향" else 1, -len(x[1]), x[0])
    )

    for company, co_items in sorted_companies:
        for item in co_items[:MAX_NEWS_PER_COMPANY]:
            compact_items.append({
                "company": company,
                "detail_category": item["detail_category"],
                "title": trim_title_suffix(item["title"]),
                "snippet": item["snippet"],
                "url": item["url"],
                "date": item["date"][:16],
                "source": item["source"],
            })

    compact_items = compact_items[:MAX_NEWS_FOR_GEMINI]

    if GEMINI_API_KEY and compact_items:
        result = call_gemini(NEWS_BATCH_PROMPT, json.dumps(compact_items, ensure_ascii=False))
        if result:
            return result

    html_blocks = []
    for company, co_items in sorted_companies:
        html_blocks.append(
            f'''
<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">{safe_html(company)} ({len(co_items)}건)</h3>
</div>
'''.strip()
        )

        for item in co_items[:MAX_NEWS_PER_COMPANY]:
            title = trim_title_suffix(item["title"])
            summaries = news_summary_bilingual(item)

            html_blocks.append(
                f'''
<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">{safe_html(item["detail_category"])}</span>
  <h4 style="margin:4px 0;font-size:14px;">
    <a href="{safe_html(item["url"])}" style="color:#1a5276;text-decoration:none;">{safe_html(title)}</a>
  </h4>
  <p style="font-size:11px;color:#777;margin:2px 0;">{safe_html(item.get("date", "")[:16])} · {safe_html(item.get("source", ""))}</p>
  <p style="font-size:13px;color:#333;line-height:1.6;">{safe_html(summaries["en_summary"])}</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;">{safe_html(summaries["ko_summary"])}</p>
</div>
'''.strip()
            )

    return "\n".join(html_blocks)

# ── 5. 논문 HTML ──────────────────────────────────────────────
TOPIC_MAP = {
    "초음파 인간공학": ["ultrasound", "sonographer", "transducer", "scanning"],
    "근골격계질환": ["musculoskeletal", "carpal tunnel", "shoulder", "wrist", "tendon", "repetitive"],
    "임상 인간공학": ["surgeon", "physician", "nurse", "clinician", "echocardiograph", "radiology"],
    "작업환경 개선": ["workstation", "workplace", "posture", "pointing device", "mouse", "sitting", "standing"],
    "생체역학": ["biomechanics", "muscle activity", "emg", "force", "kinematics"],
    "역학·통계": ["epidemiology", "prevalence", "survey", "cohort", "cross-sectional", "retrospective"],
    "AI·기술": ["machine learning", "deep learning", "algorithm", "artificial intelligence", "ai"],
}

def get_topic(paper: dict) -> str:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    for topic, kws in TOPIC_MAP.items():
        if any(kw in text for kw in kws):
            return topic
    return "기타"

def build_papers_html(papers: list) -> str:
    if not papers:
        return "<p>오늘 새 논문이 없습니다.</p>"

    papers = papers[:MAX_PAPERS_FOR_GEMINI]

    compact_papers = []
    for p in papers:
        doi_or_link = f"https://doi.org/{p['doi']}" if p.get("doi") else p.get("link", "")
        compact_papers.append({
            "topic": get_topic(p),
            "title": p.get("title", ""),
            "authors": p.get("authors", ""),
            "affiliations": p.get("affiliations", "") or "소속 정보 없음",
            "abstract": p.get("abstract", "")[:1000],
            "journal": p.get("journal", ""),
            "pub_date": p.get("pub_date", ""),
            "link": doi_or_link,
        })

    if GEMINI_API_KEY and compact_papers:
        result = call_gemini(PAPERS_BATCH_PROMPT, json.dumps(compact_papers, ensure_ascii=False))
        if result:
            return result

    html_blocks = []
    for p in papers:
        topic = get_topic(p)
        korean = natural_korean_summary(
            title=p.get("title", ""),
            abstract=p.get("abstract", ""),
            authors=p.get("authors", ""),
            journal=p.get("journal", "")
        )

        abstract_en = (p.get("abstract", "") or "").strip()
        if len(abstract_en) > 500:
            abstract_en = abstract_en[:500] + "..."

        if p.get("doi"):
            link_html = f' · <a href="https://doi.org/{safe_html(p["doi"])}" style="color:#2e86c1;">원문 보기</a>'
        elif p.get("link"):
            link_html = f' · <a href="{safe_html(p["link"])}" style="color:#2e86c1;">원문 보기</a>'
        else:
            link_html = ""

        affiliation = p.get("affiliations", "")[:180] if p.get("affiliations") else "소속 정보 없음"

        html_blocks.append(
            f'''
<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">{safe_html(topic)}</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">{safe_html(p.get("title", ""))}</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">{safe_html(korean["ko_title"])}</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">
    {safe_html(p.get("authors", ""))}<br/>
    {safe_html(affiliation)}<br/>
    {safe_html(p.get("journal", ""))} · {safe_html(p.get("pub_date", ""))}{link_html}
  </p>
  <p style="font-size:13px;color:#333;line-height:1.7;"><strong>Summary:</strong> {safe_html(abstract_en)}</p>
  <p style="font-size:13px;color:#444;background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;"><strong>요약:</strong> {safe_html(korean["ko_summary"])}</p>
</div>
'''.strip()
        )

    return "\n".join(html_blocks)

# ── 6. 이메일 조합 & 발송 ──────────────────────────────────────
def assemble_email(news_html, papers_html, n_news, n_papers):
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;">
<tr><td align="center" style="padding:20px 10px;">
<table width="700" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <tr><td style="background:linear-gradient(135deg,#1a5276,#2e86c1);padding:30px 40px;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;">초음파 산업 &amp; 인간공학 연구 다이제스트</h1>
    <p style="color:#aed6f1;margin:6px 0 0;font-size:13px;">회사별 그룹핑 · 실행 시간 최적화</p>
    <p style="color:#d4e6f1;margin:4px 0 0;font-size:12px;">{today}</p>
  </td></tr>
  <tr><td style="padding:16px 40px;background:#eaf2f8;">
    <table width="100%"><tr>
      <td width="50%" style="text-align:center;padding:8px;">
        <p style="margin:0;font-size:26px;color:#2e86c1;font-weight:bold;">{n_news}</p>
        <p style="margin:2px 0 0;font-size:12px;color:#555;">산업 뉴스</p></td>
      <td width="50%" style="text-align:center;padding:8px;">
        <p style="margin:0;font-size:26px;color:#27ae60;font-weight:bold;">{n_papers}</p>
        <p style="margin:2px 0 0;font-size:12px;color:#555;">연구 논문</p></td>
    </tr></table>
  </td></tr>
  <tr><td style="padding:20px 30px;">
    <h2 style="color:#1a5276;border-bottom:2px solid #2e86c1;padding-bottom:8px;">초음파 산업 동향</h2>
    {news_html}
  </td></tr>
  <tr><td style="padding:0 40px;"><hr style="border:none;border-top:2px solid #eee;"/></td></tr>
  <tr><td style="padding:20px 30px;">
    <h2 style="color:#1a5276;border-bottom:2px solid #27ae60;padding-bottom:8px;">인간공학 논문 동향</h2>
    {papers_html}
  </td></tr>
  <tr><td style="background:#2c3e50;padding:20px 40px;color:#bdc3c7;font-size:11px;line-height:1.6;">
    <p style="margin:0;">AI 생성 요약입니다. 중요 의사결정 전에는 원문을 확인하세요.</p>
    <p style="margin:4px 0 0;">Powered by GitHub Actions + Gemini API</p>
    <p style="margin:4px 0 0;">Sources: Google News RSS + 전문매체 RSS + FDA openFDA + PubMed + arXiv + Semantic Scholar</p>
  </td></tr>
</table></td></tr></table></body></html>"""

def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Ultrasound Digest <{GMAIL_ADDRESS}>"
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText("HTML 이메일 클라이언트에서 확인하세요.", "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [RECIPIENT_EMAIL], msg.as_string())

    print(f"이메일 발송 완료 -> {RECIPIENT_EMAIL}")

# ── 메인 ──────────────────────────────────────────────────────
def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"뉴스레터 생성 시작: {today}")

    print("초음파 뉴스 수집 중...")
    all_news = fetch_all_ultrasound_news() + fetch_fda_510k()

    print("인간공학 논문 수집 중...")
    papers_raw = fetch_pubmed_papers("ergonomics", 10)
    papers_raw += fetch_arxiv_papers("ergonomics", 5)
    papers_raw += fetch_semantic_scholar("ergonomics workplace", 5)

    seen = set()
    all_papers = []
    for p in papers_raw:
        key = p["title"].strip().lower()[:120]
        if key not in seen:
            seen.add(key)
            all_papers.append(p)

    print(f"수집 완료: 뉴스 {len(all_news)}건, 논문 {len(all_papers)}편")
    print("HTML 생성 중...")

    news_html = build_news_html(all_news)
    papers_html = build_papers_html(all_papers)

    html_body = assemble_email(news_html, papers_html, len(all_news), len(all_papers))
    subject = f"초음파 & 인간공학 다이제스트 | {today} | 뉴스 {len(all_news)}건, 논문 {len(all_papers)}편"

    send_email(subject, html_body)
    print("완료!")

if __name__ == "__main__":
    main()
