#!/usr/bin/env python3
"""
초음파 산업 & 인간공학 연구 뉴스레터
- 전 세계 90개+ 초음파 회사 모니터링
- 회사별 그룹핑 + 자연스러운 한국어 번역
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

# ── RSS 쿼리 9개 ───────────────────────────────────────────────
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
    ("AuntMinnie",            "http://cdn.auntminnie.com/rss/rss.aspx"),
    ("MedTech Dive",          "https://www.medtechdive.com/feeds/news/"),
    ("MassDevice",            "https://www.massdevice.com/feed/"),
    ("Medical Device Network","https://www.medicaldevice-network.com/feed/"),
]

# ── 회사 분류 맵 ───────────────────────────────────────────────
COMPANY_MAP = {
    "GE HealthCare":        ["ge healthcare", "gehc", "intelerad", "bk medical", "caption health"],
    "Philips":              ["philips"],
    "Siemens Healthineers": ["siemens healthineers"],
    "Samsung Medison":      ["samsung medison", "samsung hme"],
    "Canon Medical":        ["canon medical"],
    "FUJIFILM / Sonosite":  ["fujifilm", "sonosite", "visualsonics"],
    "Mindray":              ["mindray"],
    "Esaote":               ["esaote"],
    "Butterfly Network":    ["butterfly network", "bfly"],
    "Exo Imaging":          ["exo imaging", "exo iris"],
    "Clarius":              ["clarius mobile", "clarius"],
    "EchoNous":             ["echonous", "kosmos ultrasound"],
    "Alpinion":             ["alpinion"],
    "Healcerion":           ["healcerion", "sonon"],
    "SonoScape":            ["sonoscape"],
    "CHISON":               ["chison"],
    "Wisonic":              ["wisonic"],
    "AI 초음파 솔루션":      ["ultromics", "ultrasight", "dia imaging",
                             "icardio", "brightheart", "thinksono",
                             "smartalpha", "nerveblox", "ligence", "diagnoly"],
    "FDA 인허가":            ["fda 510", "510(k)", "ce mark", "de novo",
                             "fda approval", "fda clearance"],
}

def get_company(item: dict) -> str:
    text = (item["title"] + " " + item.get("snippet","") + " " + item.get("source","")).lower()
    for company, keywords in COMPANY_MAP.items():
        if any(kw in text for kw in keywords):
            return company
    return "기타 초음파 동향"

# ── 1. 데이터 수집 ─────────────────────────────────────────────
def fetch_google_news_rss(query: str, label: str, max_items: int = 15) -> list:
    url = (f"https://news.google.com/rss/search?"
           f"q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en")
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

def fetch_all_ultrasound_news() -> list:
    all_items, seen = [], set()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    for label, query in RSS_QUERIES.items():
        items = fetch_google_news_rss(query, label, 15)
        for item in items:
            key = item["title"].lower()[:80]
            if key not in seen:
                seen.add(key)
                all_items.append(item)
        time.sleep(1)
    for name, url in SPECIALIST_RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:20]:
                pub = e.get("published_parsed")
                if pub:
                    pub_dt = datetime.datetime(*pub[:6], tzinfo=datetime.timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title   = e.get("title", "")
                snippet = e.get("summary", "")[:300]
                if "ultrasound" not in (title + snippet).lower():
                    continue
                if not is_medical_news(title, snippet):
                    continue
                key = title.lower()[:80]
                if key not in seen:
                    seen.add(key)
                    all_items.append({
                        "title":    title,
                        "snippet":  snippet,
                        "url":      e.get("link", ""),
                        "date":     e.get("published", ""),
                        "source":   f"STAR {name}",
                        "category": "전문매체",
                    })
        except Exception as ex:
            print(f"  {name} RSS 오류: {ex}")
    print(f"  뉴스 총 {len(all_items)}건 수집")
    return all_items

def fetch_fda_510k() -> list:
    today    = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    url = (f"https://api.fda.gov/device/510k.json?"
           f"search=openfda.device_name:ultrasound"
           f"+AND+decision_date:[{week_ago:%Y%m%d}+TO+{today:%Y%m%d}]&limit=10")
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            items = []
            for rec in r.json().get("results", []):
                items.append({
                    "title":    f"FDA 510(k) Cleared: {rec.get('device_name','N/A')}",
                    "snippet":  f"Applicant: {rec.get('applicant','N/A')} | K-number: {rec.get('k_number','N/A')}",
                    "url":      f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={rec.get('k_number','')}",
                    "date":     rec.get("decision_date", ""),
                    "source":   "FDA openFDA",
                    "category": "FDA 인허가",
                })
            print(f"  FDA 510k {len(items)}건")
            return items
    except Exception as e:
        print(f"  FDA 오류: {e}")
    return []

def fetch_pubmed_papers(query="ergonomics", max_results=15) -> list:
    params = {"db":"pubmed","term":query,"datetype":"edat","reldate":2,
              "retmax":max_results,"retmode":"json","sort":"date"}
    if PUBMED_API_KEY: params["api_key"] = PUBMED_API_KEY
    r = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                     params=params, timeout=30)
    ids = r.json().get("esearchresult",{}).get("idlist",[])
    if not ids: print("  PubMed 논문 없음"); return []
    time.sleep(0.5)
    params2 = {"db":"pubmed","id":",".join(ids),"rettype":"xml","retmode":"xml"}
    if PUBMED_API_KEY: params2["api_key"] = PUBMED_API_KEY
    r2 = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                      params=params2, timeout=30)
    root = ET.fromstring(r2.content)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find(".//MedlineCitation")
        art = medline.find(".//Article") if medline is not None else None
        if art is None: continue
        title    = art.findtext(".//ArticleTitle","")
        abstract = " ".join([a.text or "" for a in art.findall(".//AbstractText")])[:500]
        authors  = [f"{a.findtext('ForeName','')} {a.findtext('LastName','')}".strip()
                    for a in art.findall(".//Author")[:6] if a.findtext("LastName")]
        affil_el = art.find(".//AffiliationInfo/Affiliation")
        affil    = affil_el.text[:200] if affil_el is not None and affil_el.text else ""
        journal  = art.findtext(".//Journal/Title","")
        pmid     = medline.findtext(".//PMID","")
        doi_el   = art.find(".//ELocationID[@EIdType='doi']")
        doi      = doi_el.text if doi_el is not None else ""
        pub      = art.find(".//Journal/JournalIssue/PubDate")
        pub_date = " ".join(filter(None,[pub.findtext("Year",""),pub.findtext("Month","")])) if pub else ""
        papers.append({"title":title,"authors":", ".join(authors),"affiliations":affil,
                       "abstract":abstract,"doi":doi,"journal":journal,"pub_date":pub_date,
                       "link":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    print(f"  PubMed 논문 {len(papers)}편")
    return papers

def fetch_arxiv_papers(query="ergonomics", max_results=8) -> list:
    r = requests.get("http://export.arxiv.org/api/query",
                     params={"search_query":f"all:{query}","start":0,
                             "max_results":max_results,"sortBy":"submittedDate",
                             "sortOrder":"descending"}, timeout=30)
    ns = {"atom":"http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.content)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
    papers = []
    for entry in root.findall("atom:entry", ns):
        pub = entry.findtext("atom:published","",ns)
        try:
            if datetime.datetime.fromisoformat(pub.replace("Z","+00:00")) < cutoff: continue
        except: pass
        authors = [a.findtext("atom:name","",ns) for a in entry.findall("atom:author",ns)]
        papers.append({
            "title":   entry.findtext("atom:title","",ns).strip().replace("\n"," "),
            "authors": ", ".join(authors[:6]), "affiliations":"",
            "abstract":entry.findtext("atom:summary","",ns).strip()[:500],
            "doi":"","journal":"arXiv preprint","pub_date":pub[:10],
            "link":    entry.findtext("atom:id","",ns)
        })
    print(f"  arXiv 논문 {len(papers)}편")
    return papers

def fetch_semantic_scholar(query="ergonomics workplace", max_results=10) -> list:
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=3)
    try:
        r = requests.get("https://api.semanticscholar.org/graph/v1/paper/search",
                         params={"query":query,
                                 "fields":"title,authors,abstract,publicationDate,journal,externalIds",
                                 "limit":max_results,
                                 "publicationDateOrYear":f"{yesterday}:{today}"},
                         timeout=30)
        if r.status_code != 200: return []
        papers = []
        for p in r.json().get("data",[]):
            doi = (p.get("externalIds") or {}).get("DOI","")
            papers.append({
                "title":    p.get("title",""),
                "authors":  ", ".join([a.get("name","") for a in (p.get("authors") or [])[:6]]),
                "affiliations":"","abstract":(p.get("abstract") or "")[:500],
                "doi":doi,"journal":(p.get("journal") or {}).get("name",""),
                "pub_date": p.get("publicationDate",""),
                "link":     f"https://doi.org/{doi}" if doi else ""
            })
        print(f"  Semantic Scholar 논문 {len(papers)}편")
        return papers
    except Exception as e:
        print(f"  Semantic Scholar 오류: {e}"); return []

# ── 2. Gemini 호출 ─────────────────────────────────────────────
def call_gemini(prompt: str, data_json: str) -> str:
    if not GEMINI_API_KEY: return ""
    time.sleep(8)
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}")
    payload = {
        "contents":[{"parts":[{"text": prompt.replace("{{DATA_JSON}}", data_json)}]}],
        "generationConfig":{"temperature":0.3,"maxOutputTokens":8000}
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=120)
            if r.status_code == 200:
                candidates = r.json().get("candidates",[])
                if candidates:
                    return (candidates[0]["content"]["parts"][0]["text"]
                            .replace("```html","").replace("```","").strip())
            elif r.status_code == 429:
                wait = (attempt + 1) * 20
                print(f"  Gemini 429 — {wait}초 대기...")
                time.sleep(wait)
            else:
                print(f"  Gemini 오류: {r.status_code}"); return ""
        except Exception as e:
            print(f"  Gemini 예외: {e}"); return ""
    print("  Gemini 실패 → fallback 사용")
    return ""

def translate_ko(text: str) -> str:
    if not text: return ""
    try:
        return GoogleTranslator(source="auto", target="ko").translate(text[:4500])
    except: return text

# ── 3. 뉴스 HTML — 회사별 그룹핑 ──────────────────────────────
NEWS_PROMPT = """당신은 초음파 의료기기 산업 전문 애널리스트입니다.
아래 뉴스를 회사별로 그룹핑하여 HTML 뉴스레터를 만드세요.

규칙:
1. 회사별로 묶어서 출력 (뉴스 건수 많은 순)
2. TV/오디오/가전/순수 주가 분석 기사는 완전 제외
3. 각 기사: 영어 요약 2문장 + 자연스러운 한국어 번역

회사 헤더:
<div style="margin:20px 0 8px;padding:10px 16px;background:#1a5276;border-radius:6px;">
  <h3 style="color:#fff;margin:0;font-size:16px;">COMPANY_NAME (N건)</h3>
</div>

기사 카드:
<div style="background:#f8f9fa;border-left:4px solid #2e86c1;padding:12px 16px;margin:4px 0 4px 16px;">
  <span style="font-size:11px;font-weight:bold;color:#2e86c1;">CATEGORY</span>
  <h4 style="margin:4px 0;font-size:14px;"><a href="URL" style="color:#1a5276;text-decoration:none;">TITLE</a></h4>
  <p style="font-size:11px;color:#777;margin:2px 0;">DATE · SOURCE</p>
  <p style="font-size:13px;color:#333;line-height:1.6;">ENGLISH_SUMMARY</p>
  <p style="font-size:13px;color:#444;background:#eef6fb;padding:8px;border-radius:4px;line-height:1.6;">KOREAN_SUMMARY</p>
</div>

카테고리: 신제품/기술, 인허가 승인, 인수/합병/파트너십, 시장/경영, 임상/연구
HTML만 출력하세요.
{{DATA_JSON}}"""

PAPERS_PROMPT = """당신은 인간공학 분야 전문 연구자입니다.
아래 논문들을 분석하여 HTML 뉴스레터를 만드세요.

번역 핵심 규칙:
- 한국어는 전문 연구자가 쓴 것처럼 자연스럽게 작성
- 기계 번역 스타일 금지 (예: "~의 효과" 대신 "~이 미치는 영향")
- 문장 끝: ~했습니다, ~나타났습니다, ~시사합니다
- 숫자/저자명/기관명은 영어 유지

논문 카드 형식:
<div style="background:#f8f9fa;border-left:4px solid #27ae60;padding:14px 16px;margin:12px 0;">
  <p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">TOPIC</p>
  <h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">ENGLISH_TITLE</h4>
  <p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">KOREAN_TITLE</p>
  <p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">AUTHORS<br/>AFFILIATION<br/>JOURNAL · DATE · DOI_LINK</p>
  <p style="font-size:13px;color:#333;line-height:1.7;"><strong>Summary:</strong> ENGLISH_SUMMARY_3_4_SENTENCES</p>
  <p style="font-size:13px;color:#444;background:#eaf7ee;padding:10px;border-radius:4px;line-height:1.8;"><strong>요약:</strong> KOREAN_SUMMARY</p>
</div>

주제 분류: 근골격계질환 / 임상 인간공학 / 작업환경 개선 / 생체역학 / 역학통계 / AI기술 / 초음파 인간공학 / 기타
HTML만 출력하세요.
{{DATA_JSON}}"""


def build_news_html(items: list) -> str:
    if not items:
        return "<p>오늘 관련 뉴스가 없습니다.</p>"

    # Gemini 시도 (25개씩 청크)
    if GEMINI_API_KEY:
        all_html = ""
        for i in range(0, min(len(items), 75), 25):
            chunk = items[i:i+25]
            result = call_gemini(NEWS_PROMPT, json.dumps(chunk, ensure_ascii=False))
            if result:
                all_html += result
        if all_html:
            return all_html

    # ── Fallback: 회사별 그룹핑 ──────────────────────────────
    grouped = {}
    for item in items:
        company = get_company(item)
        grouped.setdefault(company, []).append(item)

    sorted_cos = sorted(
        [(k, v) for k, v in grouped.items() if k != "기타 초음파 동향"],
        key=lambda x: len(x[1]), reverse=True
    )
    if "기타 초음파 동향" in grouped:
        sorted_cos.append(("기타 초음파 동향", grouped["기타 초음파 동향"]))

    html = ""
    for company, co_items in sorted_cos:
        # 회사 헤더 (파란 배경)
        html += (
            f'<div style="margin:20px 0 8px;padding:10px 16px;'
            f'background:#1a5276;border-radius:6px;">'
            f'<h3 style="color:#fff;margin:0;font-size:16px;">'
            f'{company} ({len(co_items)}건)</h3></div>'
        )
        for item in co_items[:6]:
            title = item["title"]
            if " - " in title:
                title = title.rsplit(" - ", 1)[0]
            kr = translate_ko(title)
            html += (
                f'<div style="background:#f8f9fa;border-left:4px solid #2e86c1;'
                f'padding:12px 16px;margin:4px 0 4px 16px;">'
                f'<h4 style="margin:0 0 4px;font-size:14px;">'
                f'<a href="{item["url"]}" style="color:#1a5276;text-decoration:none;">'
                f'{title}</a></h4>'
                f'<p style="font-size:11px;color:#777;margin:2px 0;">'
                f'{item["date"][:16]} · {item["source"]}</p>'
                f'<p style="font-size:13px;color:#444;background:#eef6fb;'
                f'padding:6px 8px;border-radius:4px;margin:4px 0 0;">'
                f'{kr}</p></div>'
            )
    return html


def build_papers_html(papers: list) -> str:
    if not papers:
        return "<p>오늘 새 논문이 없습니다.</p>"

    # Gemini 시도
    if GEMINI_API_KEY:
        result = call_gemini(PAPERS_PROMPT, json.dumps(papers, ensure_ascii=False))
        if result:
            return result

    # ── Fallback: 주제 분류 + 자연스러운 번역 ─────────────────
    TOPIC_MAP = {
        "초음파 인간공학":  ["ultrasound","sonographer","transducer","scanning"],
        "근골격계질환":     ["musculoskeletal","carpal tunnel","shoulder","wrist","tendon","repetitive"],
        "임상 인간공학":    ["surgeon","physician","nurse","clinician","radiation","echocardiographer"],
        "작업환경 개선":    ["workstation","workplace","posture","pointing device","mouse","sitting","standing"],
        "생체역학":         ["biomechanics","muscle activity","emg","force","kinematics"],
        "역학·통계":        ["epidemiology","prevalence","survey","cohort","cross-sectional","retrospective"],
        "AI·기술":          ["machine learning","deep learning","algorithm"],
    }

    def get_topic(paper):
        text = (paper["title"] + " " + paper["abstract"]).lower()
        for topic, kws in TOPIC_MAP.items():
            if any(kw in text for kw in kws):
                return topic
        return "기타 의학연구"

    html = ""
    for p in papers[:10]:
        topic    = get_topic(p)
        kr_title = translate_ko(p["title"])
        kr_abs   = translate_ko(p["abstract"][:400]) if p["abstract"] else ""
        doi_link = (f' · <a href="https://doi.org/{p["doi"]}" style="color:#2e86c1;">원문 보기</a>'
                    if p["doi"] else "")
        html += (
            f'<div style="background:#f8f9fa;border-left:4px solid #27ae60;'
            f'padding:14px 16px;margin:12px 0;">'
            f'<p style="font-size:11px;color:#27ae60;font-weight:bold;margin:0 0 4px;">'
            f'[{topic}]</p>'
            f'<h4 style="margin:0 0 4px;font-size:15px;color:#1a5276;">{p["title"]}</h4>'
            f'<p style="font-size:14px;color:#2c3e50;margin:2px 0 8px;">{kr_title}</p>'
            f'<p style="font-size:12px;color:#777;margin:4px 0 8px;line-height:1.8;">'
            f'{p["authors"]}<br/>'
            f'{p["affiliations"][:150] if p["affiliations"] else "소속 정보 없음"}<br/>'
            f'{p["journal"]} · {p["pub_date"]}{doi_link}</p>'
            f'<p style="font-size:13px;color:#333;line-height:1.7;margin:0 0 6px;">'
            f'<strong>Abstract:</strong> {p["abstract"][:350]}...</p>'
            f'<p style="font-size:13px;color:#444;background:#eaf7ee;'
            f'padding:10px;border-radius:4px;line-height:1.8;">'
            f'<strong>요약:</strong> {kr_abs}</p></div>'
        )
    return html


# ── 4. 이메일 조합 & 발송 ──────────────────────────────────────
def assemble_email(news_html, papers_html, n_news, n_papers):
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    return f"""<!DOCTYPE html><html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4f8;font-family:'Malgun Gothic',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f4f8;">
<tr><td align="center" style="padding:20px 10px;">
<table width="700" cellpadding="0" cellspacing="0"
  style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1);">
  <tr><td style="background:linear-gradient(135deg,#1a5276,#2e86c1);padding:30px 40px;text-align:center;">
    <h1 style="color:#fff;margin:0;font-size:22px;">초음파 산업 &amp; 인간공학 연구 다이제스트</h1>
    <p style="color:#aed6f1;margin:6px 0 0;font-size:13px;">전 세계 90개+ 초음파 회사 모니터링</p>
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
    <p style="margin:0;">AI 생성 요약입니다. 중요 결정은 원문을 확인하세요.</p>
    <p style="margin:4px 0 0;">Powered by GitHub Actions + Gemini API</p>
    <p style="margin:4px 0 0;">Sources: Google News RSS (9 feeds) + AuntMinnie + MedTech Dive + FDA openFDA + PubMed + arXiv</p>
  </td></tr>
</table></td></tr></table></body></html>"""


def send_email(subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Ultrasound Digest <{GMAIL_ADDRESS}>"
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText("HTML 이메일 클라이언트에서 확인하세요.", "plain"))
    msg.attach(MIMEText(html, "html"))
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
    papers_raw  = fetch_pubmed_papers("ergonomics", 15)
    time.sleep(3)
    papers_raw += fetch_arxiv_papers("ergonomics", 8)
    papers_raw += fetch_semantic_scholar("ergonomics workplace", 10)

    seen, all_papers = set(), []
    for p in papers_raw:
        key = p["title"].lower()[:60]
        if key not in seen:
            seen.add(key); all_papers.append(p)

    print(f"수집 완료: 뉴스 {len(all_news)}건, 논문 {len(all_papers)}편")
    print("HTML 생성 중...")

    news_html   = build_news_html(all_news)
    papers_html = build_papers_html(all_papers)

    html    = assemble_email(news_html, papers_html, len(all_news), len(all_papers))
    subject = (f"초음파 & 인간공학 다이제스트 | {today} | "
               f"뉴스 {len(all_news)}건, 논문 {len(all_papers)}편")
    send_email(subject, html)
    print("완료!")


if __name__ == "__main__":
    main()
