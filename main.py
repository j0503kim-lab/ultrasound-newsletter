#!/usr/bin/env python3
"""
초음파 산업 & 인간공학 연구 뉴스레터
- 전 세계 90개+ 초음파 회사 모니터링 (9개 RSS 피드)
- 전문 미디어 직접 수집 (AuntMinnie, MedTech Dive 등)
- 산업용 초음파 노이즈 필터링
- Gemini AI 요약 + 한국어 번역
"""

import os, json, datetime, time, requests, feedparser
import smtplib, xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from deep_translator import GoogleTranslator

# ── 설정 ──────────────────────────────────────────────────────
RECIPIENT_EMAIL    = os.environ.get("RECIPIENT_EMAIL", "j0503.kim@gmail.com")
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
PUBMED_API_KEY     = os.environ.get("PUBMED_API_KEY", "")

# ── 노이즈 필터 (산업용 초음파 제거) ─────────────────────────
NOISE_KEYWORDS = [
    "cleaning", "welding", "industrial ndt", "non-destructive",
    "pest control", "humidifier", "jewelry cleaner", "rodent",
    "bark control", "ultrasonic cleaner", "ultrasonic welder",
    "flow meter", "level sensor", "distance sensor"
]

def is_medical_news(title: str, snippet: str = "") -> bool:
    text = (title + " " + snippet).lower()
    return not any(noise in text for noise in NOISE_KEYWORDS)

# ── Google News RSS 쿼리 (9개 피드) ──────────────────────────
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
        'OR "Sonoscanner" OR "SuperSonic Imagine" OR "Telemed" ultrasound '
        'OR "TechsoMed" OR "Alpinion Medical"'
    ),
    "한국 회사": (
        '"Samsung Medison" OR "Alpinion Medical" OR "Healcerion" '
        'OR "SONON ultrasound" OR "SG Healthcare" ultrasound OR "Bistos"'
    ),
    "규제·인허가": (
        '("FDA clearance" OR "510k" OR "FDA approval" OR "CE mark" '
        'OR "De Novo" OR "MFDS" OR "NMPA") ultrasound'
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

# ── 전문 미디어 RSS (신뢰도 높은 직접 수집) ──────────────────
SPECIALIST_RSS_FEEDS = [
    ("AuntMinnie",           "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("MedTech Dive",         "https://www.medtechdive.com/feeds/news/"),
    ("MassDevice",           "https://www.massdevice.com/feed/"),
    ("Medical Device Network","https://www.medicaldevice-network.com/feed/"),
    ("Fierce MedTech",       "https://www.fiercebiotech.com/rss/xml"),
]

# ── 1. 데이터 수집 ────────────────────────────────────────────
def fetch_google_news_rss(query: str, label: str, max_items: int = 15) -> list[dict]:
    url = (f"https://news.google.com/rss/search?"
           f"q={requests.utils.quote(query)}"
           f"&hl=en-US&gl=US&ceid=US:en")
    feed = feedparser.parse(url)
    items = []
    for e in feed.entries[:max_items]:
        title   = e.get("title", "")
        snippet = e.get("summary", "")[:300]
        if not is_medical_news(title, snippet):
            continue
        items.append({
            "title":    title,
            "snippet":  snippet,
            "url":      e.get("link", ""),
            "date":     e.get("published", ""),
            "source":   e.get("source", {}).get("title", "Google News"),
            "category": label,
        })
    return items


def fetch_all_ultrasound_news() -> list[dict]:
    """9개 RSS 피드 + 전문 미디어 RSS 수집 후 중복 제거"""
    all_items, seen_titles = [], set()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    # Google News RSS 9개 피드
    for label, query in RSS_QUERIES.items():
        items = fetch_google_news_rss(query, label, 15)
        for item in items:
            key = item["title"].lower()[:80]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)
        time.sleep(1)  # 요청 간격 조절

    # 전문 미디어 RSS 직접 수집
    for name, url in SPECIALIST_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:20]:
                pub = e.get("published_parsed")
                if pub:
                    pub_dt = datetime.datetime(*pub[:6],
                                               tzinfo=datetime.timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title   = e.get("title", "")
                snippet = e.get("summary", "")[:300]
                if "ultrasound" not in (title + snippet).lower():
                    continue
                if not is_medical_news(title, snippet):
                    continue
                key = title.lower()[:80]
                if key not in seen_titles:
                    seen_titles.add(key)
                    all_items.append({
                        "title":    title,
                        "snippet":  snippet,
                        "url":      e.get("link", ""),
                        "date":     e.get("published", ""),
                        "source":   f"⭐ {name}",
                        "category": "전문매체 직접수집",
                    })
        except Exception as ex:
            print(f"  {name} RSS 오류: {ex}")

    print(f"  뉴스 총 {len(all_items)}건 수집 (중복 제거 후)")
    return all_items


def fetch_fda_510k() -> list[dict]:
    today    = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    url = (f"https://api.fda.gov/device/510k.json?"
           f"search=openfda.device_name:ultrasound"
           f"+AND+decision_date:[{week_ago:%Y%m%d}+TO+{today:%Y%m%d}]"
           f"&limit=10")
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            items = []
            for rec in r.json().get("results", []):
                items.append({
                    "title":    f"✅ FDA 510(k) 승인: {rec.get('device_name','N/A')}",
                    "snippet":  (f"신청자: {rec.get('applicant','N/A')} | "
                                 f"K번호: {rec.get('k_number','N/A')} | "
                                 f"결정: {rec.get('decision_description','N/A')}"),
                    "url":      (f"https://www.accessdata.fda.gov/scripts/cdrh/"
                                 f"cfdocs/cfpmn/pmn.cfm?ID={rec.get('k_number','')}"),
                    "date":     rec.get("decision_date", ""),
                    "source":   "FDA openFDA (공식)",
                    "category": "규제·인허가",
                })
            print(f"  FDA 510k {len(items)}건 수집")
            return items
    except Exception as e:
        print(f"  FDA API 오류: {e}")
    return []


def fetch_pubmed_papers(query: str = "ergonomics", max_results: int = 15) -> list[dict]:
    params = {
        "db": "pubmed", "term": query,
        "datetype": "edat", "reldate": 2,
        "retmax": max_results, "retmode": "json", "sort": "date",
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY
    r   = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                       params=params, timeout=30)
    ids = r.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        print("  PubMed 논문 없음")
        return []
    time.sleep(0.5)
    params2 = {"db": "pubmed", "id": ",".join(ids),
               "rettype": "xml", "retmode": "xml"}
    if PUBMED_API_KEY:
        params2["api_key"] = PUBMED_API_KEY
    r2   = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        params=params2, timeout=30)
    root = ET.fromstring(r2.content)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find(".//MedlineCitation")
        art = medline.find(".//Article") if medline is not None else None
        if art is None:
            continue
        title    = art.findtext(".//ArticleTitle", "")
        abstract = " ".join([a.text or "" for a in
                             art.findall(".//AbstractText")])[:500]
        authors  = [f"{a.findtext('ForeName','')} "
                    f"{a.findtext('LastName','')}".strip()
                    for a in art.findall(".//Author")[:6]
                    if a.findtext("LastName")]
        affil_el = art.find(".//AffiliationInfo/Affiliation")
        affil    = affil_el.text[:200] if affil_el is not None and affil_el.text else ""
        journal  = art.findtext(".//Journal/Title", "")
        pmid     = medline.findtext(".//PMID", "")
        doi_el   = art.find(".//ELocationID[@EIdType='doi']")
        doi      = doi_el.text if doi_el is not None else ""
        pub      = art.find(".//Journal/JournalIssue/PubDate")
        pub_date = " ".join(filter(None, [pub.findtext("Year",""),
                                          pub.findtext("Month","")])) if pub else ""
        papers.append({
            "title": title, "authors": ", ".join(authors),
            "affiliations": affil, "abstract": abstract,
            "doi": doi, "journal": journal,
            "pub_date": pub_date,
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    print(f"  PubMed 논문 {len(papers)}편")
    return papers


def fetch_arxiv_papers(query: str = "ergonomics", max_results: int = 8) -> list[dict]:
    r = requests.get(
        "http://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "start": 0,
                "max_results": max_results,
                "sortBy": "submittedDate", "sortOrder": "descending"},
        timeout=30,
    )
    ns     = {"atom": "http://www.w3.org/2005/Atom"}
    root   = ET.fromstring(r.content)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
    papers = []
    for entry in root.findall("atom:entry", ns):
        pub = entry.findtext("atom:published", "", ns)
        try:
            if datetime.datetime.fromisoformat(
                    pub.replace("Z", "+00:00")) < cutoff:
                continue
        except ValueError:
            pass
        authors = [a.findtext("atom:name", "", ns)
                   for a in entry.findall("atom:author", ns)]
        papers.append({
            "title":        entry.findtext("atom:title","",ns).strip().replace("\n"," "),
            "authors":      ", ".join(authors[:6]),
            "affiliations": "",
            "abstract":     entry.findtext("atom:summary","",ns).strip()[:500],
            "doi": "", "journal": "arXiv preprint", "pub_date": pub[:10],
            "link":         entry.findtext("atom:id","",ns),
        })
    print(f"  arXiv 논문 {len(papers)}편")
    return papers


def fetch_semantic_scholar(query: str = "ergonomics workplace",
                           max_results: int = 10) -> list[dict]:
    today     = datetime.date.today()
    yesterday = today - datetime.timedelta(days=3)
    try:
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query":  query,
                "fields": "title,authors,abstract,publicationDate,journal,externalIds",
                "limit":  max_results,
                "publicationDateOrYear": f"{yesterday}:{today}",
            },
            timeout=30,
        )
        if r.status_code != 200:
            return []
        papers = []
        for p in r.json().get("data", []):
            doi = (p.get("externalIds") or {}).get("DOI", "")
            papers.append({
                "title":        p.get("title", ""),
                "authors":      ", ".join([a.get("name","")
                                           for a in (p.get("authors") or [])[:6]]),
                "affiliations": "",
                "abstract":     (p.get("abstract") or "")[:500],
                "doi":          doi,
                "journal":      (p.get("journal") or {}).get("name", ""),
                "pub_date":     p.get("publicationDate", ""),
                "link":         f"https://doi.org/{doi}" if doi else "",
            })
        print(f"  Semantic Scholar 논문 {len(papers)}편")
        return papers
    except Exception as e:
        print(f"  Semantic Scholar 오류: {e}")
        return []


# ── 2. AI 요약 + 번역 ─────────────────────────────────────────
def call_gemini(prompt: str, data_json: str) -> str:
    if not GEMINI_API_KEY:
        return ""
    time.sleep(5)  # Gemini 429 오류 방지
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}")
    payload = {
        "contents": [{"parts": [{"text": prompt.replace("{{DATA_JSON}}", data_json)}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000},
    }
    r = requests.post(url, json=payload, timeout=120)
    if r.status_code == 200:
        candidates = r.json().get("candidates", [])
        if candidates:
            return (candidates[0]["content"]["parts"][0]["text"]
                    .replace("```html","").replace("```","").strip())
    print(f"  Gemini 오류: {r.status_code}")
    return ""


def translate_ko(text: str) -> str:
    if not text:
        return ""
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:4500])
    except Exception:
        return ""


NEWS_PROMPT = """당신은 초음파 의료기기 산업 전문 애널리스트입니다. 아래 뉴스 데이터를 분석하여 HTML 뉴스레터 섹션을 만드세요.

## 핵심 규칙
1. **회사별로 그룹핑**하여 출력하세요. 각 회사마다 별도 섹션을 만드세요.
2. 회사와 무관한 뉴스(주가 분석, TV/오디오 제품 등 의료기기 무관 기사)는 **완전히 제외**하세요.
3. 각 기사마다 영어 요약 2문장 + 자연스러운 한국어 번역을 작성하세요.
4. 한국어는 자연스러운 구어체 문장으로 작성하세요 (기계 번역 금지).

## 출력 형식

회사 섹션 헤더:
<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">🏢 회사명 (국가)</h3>
</div>

각 기사:
<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:6px 0 6px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">카테고리</span>
  <h4 style="margin:4px 0;"><a href="URL" style="color:#1a5276;text-decoration:none;font-size:14px;">기사 제목</a></h4>
  <p style="font-size:12px;color:#777;margin:2px 0;">📅 날짜 · 📰 출처</p>
  <p style="font-size:13px;color:#333;line-height:1.6;">영어 요약 2문장</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;">🇰🇷 자연스러운 한국어 요약</p>
</div>

카테고리는 다음 중 하나로 표기:
🆕 신제품·기술  ✅ 인허가 승인  🤝 인수·합병·파트너십  📊 시장·경영 동향  🔬 임상·연구

## 중요
- 의료기기와 무관한 기사(TV, 오디오, 가전, 주가 분석만 있는 기사 등)는 반드시 제외
- 회사 섹션은 뉴스 건수가 많은 회사 순으로 정렬
- 한 회사에 뉴스가 1건뿐이면 헤더 없이 기사만 출력해도 됨
- HTML만 출력하고 다른 텍스트 포함 금지

뉴스 데이터:
{{DATA_JSON}}"""

PAPERS_PROMPT = """당신은 인간공학 및 직업건강 분야 전문 연구자입니다. 아래 논문 데이터를 분석하여 한국어 독자를 위한 HTML 뉴스레터 섹션을 만드세요.

## 번역 품질 기준 (매우 중요)
- 한국어 번역은 반드시 **자연스러운 한국어 문장**으로 작성하세요
- 기계 번역처럼 어색한 직역은 절대 금지입니다
- 연구 분야 전문가가 쓴 것처럼 매끄럽게 작성하세요
- 숫자, 통계, 고유명사(저자명, 기관명)는 영어 그대로 유지하세요
- 문장 끝은 "~했습니다", "~나타났습니다", "~시사합니다" 등 자연스러운 합니다체 사용

## 각 논문 처리 방법
1. 주제 분류: 🦴 근골격계질환 / 🏥 임상 인간공학 / 🔧 작업환경 개선 / 📐 생체역학 / 📊 역학·통계 / 🧠 AI·기술 / 🩺 초음파 인간공학 / 🔬 기타 의학연구
2. 제목 번역: 자연스러운 한국어 제목으로 의역 가능
3. 요약 작성: 영어로 연구 목적·방법·주요 결과·의의를 3~4문장으로 작성
4. 한국어 요약: 위 영어 요약을 자연스러운 한국어로 번역 (직역 금지)

## 출력 형식
<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">주제분류</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">📎 영어 제목</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">🇰🇷 자연스러운 한국어 제목</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">
    👤 저자명<br/>
    🏛️ 소속기관<br/>
    📖 저널명 · 📅 출판일
    [DOI 링크 있으면: · <a href="https://doi.org/DOI번호" style="color:#2e86c1;">원문 보기</a>]
  </p>
  <p style="font-size:13px;color:#333;line-height:1.7;margin:0 0 6px;"><strong>Summary:</strong> 영어 요약 3~4문장</p>
  <p style="font-size:13px;color:#444;background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;">🇰🇷 <strong>요약:</strong> 자연스러운 한국어 요약</p>
</div>

HTML만 출력하고 다른 텍스트는 절대 포함하지 마세요.

논문 데이터:
{{DATA_JSON}}"""

def build_news_html(items: list[dict]) -> str:
    if not items:
        return "<p>오늘 관련 뉴스가 없습니다.</p>"
    result = call_gemini(NEWS_PROMPT, json.dumps(items, ensure_ascii=False))
    if result:
        return result
    # Gemini 실패 시 기본 포맷
    html = ""
    for item in items[:20]:
        kr = translate_ko(item["title"])
        html += (
            f'<div style="background:#f8f9fa;border-left:4px solid #2e86c1;'
            f'padding:12px 16px;margin:10px 0;">'
            f'<h4 style="margin:0 0 4px;"><a href="{item["url"]}" '
            f'style="color:#1a5276;text-decoration:none;">{item["title"]}</a></h4>'
            f'<p style="font-size:12px;color:#777;">📅 {item["date"]} · '
            f'📰 {item["source"]} · 🏷️ {item.get("category","")}</p>'
            f'<p style="font-size:13px;color:#555;">{item["snippet"][:200]}</p>'
            f'<p style="font-size:13px;color:#444;background:#eef6fb;'
            f'padding:8px;border-radius:4px;">🇰🇷 {kr}</p></div>'
        )
    return html


def build_papers_html(papers: list[dict]) -> str:
    if not papers:
        return "<p>오늘 새 논문이 없습니다.</p>"
    result = call_gemini(PAPERS_PROMPT, json.dumps(papers, ensure_ascii=False))
    if result:
        return result
    html = ""
    for p in papers[:10]:
        kr_title = translate_ko(p["title"])
        kr_abs   = translate_ko(p["abstract"][:300]) if p["abstract"] else ""
        doi_link = f'<a href="https://doi.org/{p["doi"]}">DOI</a>' if p["doi"] else ""
        html += (
            f'<div style="background:#f8f9fa;border-left:4px solid #27ae60;'
            f'padding:12px 16px;margin:10px 0;">'
            f'<h4 style="margin:0 0 4px;color:#1a5276;">{p["title"]}</h4>'
            f'<p style="font-size:13px;color:#2c3e50;">🇰🇷 {kr_title}</p>'
            f'<p style="font-size:12px;color:#777;">👤 {p["authors"]}<br/>'
            f'🏛️ {p["affiliations"][:150]}<br/>📖 {p["journal"]} · '
            f'📅 {p["pub_date"]} {doi_link}</p>'
            f'<p style="font-size:13px;color:#333;">{p["abstract"][:300]}</p>'
            f'<p style="font-size:13px;color:#444;background:#eaf7ee;'
            f'padding:8px;border-radius:4px;">🇰🇷 {kr_abs}</p></div>'
        )
    return html


# ── 3. 이메일 조합 & 발송 ─────────────────────────────────────
def assemble_email(news_html: str, papers_html: str,
                   n_news: int, n_papers: int) -> str:
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html><html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;
  font-family:'Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"
  style="background:#f0f4f8;">
<tr><td align="center" style="padding:20px 10px;">
<table width="700" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:8px;overflow:hidden;
  box-shadow:0 2px 8px rgba(0,0,0,.1);">

  <tr><td style="background:linear-gradient(135deg,#1a5276,#2e86c1);
    padding:30px 40px;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;">
      🔊 초음파 산업 &amp; 인간공학 연구 다이제스트</h1>
    <p style="color:#aed6f1;margin:6px 0 0;font-size:13px;">
      전 세계 90개+ 초음파 회사 모니터링</p>
    <p style="color:#d4e6f1;margin:4px 0 0;font-size:12px;">{today}</p>
  </td></tr>

  <tr><td style="padding:16px 40px;background:#eaf2f8;">
    <table width="100%"><tr>
      <td width="50%" style="text-align:center;padding:8px;">
        <p style="margin:0;font-size:26px;color:#2e86c1;
          font-weight:bold;">{n_news}</p>
        <p style="margin:2px 0 0;font-size:12px;color:#555;">
          산업 뉴스</p></td>
      <td width="50%" style="text-align:center;padding:8px;">
        <p style="margin:0;font-size:26px;color:#27ae60;
          font-weight:bold;">{n_papers}</p>
        <p style="margin:2px 0 0;font-size:12px;color:#555;">
          연구 논문</p></td>
    </tr></table>
  </td></tr>

  <tr><td style="padding:20px 30px;">
    <h2 style="color:#1a5276;border-bottom:2px solid #2e86c1;
      padding-bottom:8px;">📰 초음파 산업 동향</h2>
    {news_html}
  </td></tr>

  <tr><td style="padding:0 40px;">
    <hr style="border:none;border-top:2px solid #eee;"/></td></tr>

  <tr><td style="padding:20px 30px;">
    <h2 style="color:#1a5276;border-bottom:2px solid #27ae60;
      padding-bottom:8px;">📄 인간공학 논문 동향</h2>
    {papers_html}
  </td></tr>

  <tr><td style="background:#2c3e50;padding:20px 40px;
    color:#bdc3c7;font-size:11px;line-height:1.6;">
    <p style="margin:0;">⚠️ AI 생성 요약입니다. 중요 결정은 원문을 확인하세요.</p>
    <p style="margin:4px 0 0;">🤖 Powered by GitHub Actions + Gemini API</p>
    <p style="margin:4px 0 0;">📡 Sources: Google News RSS (9 feeds) +
      AuntMinnie + MedTech Dive + FDA openFDA + PubMed + arXiv</p>
  </td></tr>

</table></td></tr></table></body></html>"""


def send_email(subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Ultrasound Digest <{GMAIL_ADDRESS}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText("HTML 지원 이메일 클라이언트에서 확인하세요.", "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [RECIPIENT_EMAIL], msg.as_string())
    print(f"✅ 이메일 발송 완료 → {RECIPIENT_EMAIL}")


# ── 메인 ──────────────────────────────────────────────────────
def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"🚀 뉴스레터 생성 시작: {today}")

    print("📡 초음파 뉴스 수집 중... (9개 피드 + 전문매체)")
    all_news = fetch_all_ultrasound_news() + fetch_fda_510k()

    print("📡 인간공학 논문 수집 중...")
    papers_raw  = fetch_pubmed_papers("ergonomics", 15)
    time.sleep(3)
    papers_raw += fetch_arxiv_papers("ergonomics", 8)
    papers_raw += fetch_semantic_scholar("ergonomics workplace", 10)

    seen, all_papers = set(), []
    for p in papers_raw:
        key = p["title"].lower()[:60]
        if key not in seen:
            seen.add(key); all_papers.append(p)

    print(f"📊 수집 완료: 뉴스 {len(all_news)}건, 논문 {len(all_papers)}편")

    print("🤖 AI 요약 및 번역 중...")
    news_html   = build_news_html(all_news)
    papers_html = build_papers_html(all_papers)

    html    = assemble_email(news_html, papers_html,
                             len(all_news), len(all_papers))
    subject = (f"🔊 초음파 & 인간공학 다이제스트 | {today} | "
               f"뉴스 {len(all_news)}건, 논문 {len(all_papers)}편")
    send_email(subject, html)
    print("✅ 완료!")


if __name__ == "__main__":
    main()
