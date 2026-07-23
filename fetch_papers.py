# -*- coding: utf-8 -*-
"""
Veterinary Journal List — 논문 수집기
- PubMed에서 '소동물' 논문을 수집 → 분야 분류 → (선택) 한국어 요약 → papers.json 저장
- 매일 GitHub Actions가 이 파일을 실행합니다.

★ '🔧' 표시가 있는 부분이 '내가 나중에 고치는 곳' 입니다. 번호는 조건서와 같습니다.
"""

import urllib.request
import urllib.parse
import json
import time
import os
import re
from datetime import datetime, timedelta

# =====================================================================
#  ⚙️ 설정 (🔧 = 자유롭게 고쳐도 되는 곳)
# =====================================================================

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# 🔧(7) 수집 기간: 최근 며칠 논문을 볼지
LOOKBACK_DAYS = 60

# 🔧 결과 상한: 최신순으로 최대 몇 편까지 가져올지 (너무 많으면 요약 비용↑)
MAX_RESULTS = 100

# 🔧(4) 소동물 한정 키워드 — 제목/초록에 이 중 하나라도 있어야 수집
SMALL_ANIMAL_TERMS = ["dogs", "dog", "cats", "cat", "feline", "canine", "small animal"]

# 🔧(5) 저널 제외 목록: 여기에 저널 약어(소문자 일부)를 넣으면 그 저널은 빠집니다.
#      처음엔 비어 있음. 결과를 보고 원치 않는 저널을 한 줄씩 추가하세요.
#      예)  "plos one",  "sci rep",  "front vet sci"
JOURNAL_EXCLUDE = [
]

# 🔧(6) '이 저널만 보기'로 바꾸고 싶을 때: 아래에 저널을 넣고 USE_WHITELIST = True
JOURNAL_WHITELIST = []
USE_WHITELIST = False

# 🔧(8) 분야 우선순위 = 아래 딕셔너리의 '순서'.  위에서부터 먼저 확정됩니다.
#      한 논문은 한 분야로만 분류됩니다(위에서 처음 걸리는 분야).
# 🔧(9~13) 분야별 키워드 — 제목/초록에 있으면 그 분야
CATEGORY_KEYWORDS = {
    # 🔧(10) 신경외과  (목록 중 아무거나 걸리면 신경외과)
    "neurosurgery": ["neurosurgery", "neuro", "spinal", "brain", "vestibular",
                     "disc", "cerebell", "myelopathy", "hemilaminectomy", "intervertebral"],
    # 🔧(9) 정형외과
    "orthopedics":  ["surgery", "surgical", "fracture", "orthopedic", "repair",
                     "resection", "arthro", "arthroscopy", "arthroscopic",
                     "osteotomy", "luxation", "cruciate", "tplo", "patellar"],
    # 🔧(11) 영상
    "imaging":      ["radiograph", "radiographic", "radiography", "mri",
                     "magnetic resonance", "ct", "computed tomography", "ultrasound",
                     "ultrasonographic", "ultrasonography", "imaging", "echocardiographic"],
    # 🔧(13) 내과
    "internal":     ["renal", "kidney", "hepatic", "liver", "endocrine", "diabetes",
                     "pancreatitis", "gastrointestinal", "gastro", "enteropathy",
                     "azotemia", "hypothyroid", "hyperadrenocorticism", "immune-mediated",
                     "proteinuria"],
    # 🔧(12) 종양
    "oncology":     ["tumor", "tumour", "cancer", "carcinoma", "sarcoma", "osteosarcoma",
                     "lymphoma", "mast cell", "melanoma", "adenoma", "neoplasia",
                     "neoplastic", "oncology", "oncologic", "malignant", "metastasis",
                     "metastatic"],
}

# 화면에 보여줄 한글 이름 (index.html 에도 같은 값이 있음)
CATEGORY_LABELS = {
    "neurosurgery": "신경외과", "orthopedics": "정형외과", "imaging": "영상",
    "internal": "내과", "oncology": "종양", "other": "기타",
}

# 🔧(14) '단어 전체 일치'로만 인정할 짧은 토큰 (부분일치 오분류 방지)
#      예: disc 가 'discussion' 에 걸리지 않도록. (2~3글자는 자동으로 단어일치 처리)
WHOLE_WORD_TOKENS = {"disc"}

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


# =====================================================================
#  🔧(15) 요약 스타일 — 여기(프롬프트)만 고치면 요약 문체가 바뀝니다.
#      한글 + 영어 전문용어 병기 방식.
# =====================================================================
def summarize_ko(title, abstract):
    if not ANTHROPIC_API_KEY or not abstract:   # 🔧(16) 키 없으면 요약 생략(목록은 정상)
        return ""
    prompt = (
        "다음 수의학 논문을 한국어로 2~3문장으로 요약해줘.\n"
        "규칙: 의학·해부·수술 전문용어는 영어 원어를 그대로 쓰고, 필요하면 괄호로 한글 뜻을 덧붙여라.\n"
        '예) "osteophyte 제거함", "cranial cruciate ligament(전십자인대) 파열".\n'
        "전문 수의사가 읽는다고 가정하고 임상적으로 중요한 내용 위주로 써라.\n\n"
        f"제목: {title}\n\n초록: {abstract}"
    )
    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 320,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"  요약 오류: {e}")
        return ""


# =====================================================================
#  분류 로직 (건드릴 필요 없음 — 키워드는 위 CATEGORY_KEYWORDS 에서 조정)
# =====================================================================
def match_kw(text, kw):
    kw = kw.lower()
    if len(kw) <= 3 or kw in WHOLE_WORD_TOKENS:      # 짧은 약어 → 단어 전체 일치
        return re.search(r"\b" + re.escape(kw) + r"\b", text) is not None
    return kw in text                                 # 그 외 → 부분 포함


def categorize(title, abstract):
    text = (title + " " + (abstract or "")).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():        # 위에서부터 첫 매칭
        if any(match_kw(text, k) for k in kws):
            return cat
    return "other"


def journal_ok(source):
    s = (source or "").lower()
    if USE_WHITELIST:
        return any(w.lower() in s for w in JOURNAL_WHITELIST)
    return not any(x.lower() in s for x in JOURNAL_EXCLUDE)


# =====================================================================
#  수집
# =====================================================================
def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def load_previous_summaries():
    """이미 요약된 논문은 다시 요약하지 않도록 캐시로 재사용 (API 비용 절약)."""
    cache = {}
    if os.path.exists("papers.json"):
        try:
            prev = json.load(open("papers.json", encoding="utf-8"))
            for p in prev.get("papers", []):
                if p.get("summary_ko"):
                    cache[p["id"]] = p["summary_ko"]
        except Exception:
            pass
    return cache


def get_papers():
    date_from = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y/%m/%d")
    date_to = datetime.now().strftime("%Y/%m/%d")
    sa = " OR ".join(f'"{t}"[tiab]' for t in SMALL_ANIMAL_TERMS)
    term = urllib.parse.quote(
        f'({sa}) AND ("{date_from}"[PDAT] : "{date_to}"[PDAT])'
    )
    search = fetch_json(
        f"{BASE}esearch.fcgi?db=pubmed&term={term}&retmax={MAX_RESULTS}&sort=date&retmode=json"
    )
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    time.sleep(0.4)

    # 초록(XML)
    fetch_url = f"{BASE}efetch.fcgi?db=pubmed&id={','.join(ids)}&retmode=xml&rettype=abstract"
    req = urllib.request.Request(fetch_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        xml = r.read().decode()

    abstracts = {}
    for block in re.findall(r"<PubmedArticle>(.*?)</PubmedArticle>", xml, re.DOTALL):
        pmid_m = re.search(r"<PMID[^>]*>(\d+)</PMID>", block)
        abs_m = re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", block, re.DOTALL)
        if pmid_m and abs_m:
            abstracts[pmid_m.group(1)] = " ".join(re.sub(r"<[^>]+>", "", a) for a in abs_m)

    # 메타데이터(JSON)
    summary = fetch_json(f"{BASE}esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json")
    result = summary.get("result", {})

    cache = load_previous_summaries()
    papers = []
    for pid in ids:
        item = result.get(pid)
        if not item:
            continue
        source = item.get("source", "")            # 저널 약어 (예: J Vet Intern Med)
        if not journal_ok(source):                 # 🔧(5)/(6) 저널 필터
            continue
        abstract = abstracts.get(pid, "")
        title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        category = categorize(title, abstract)

        summary_ko = cache.get(pid)
        if summary_ko is None:
            print(f"    요약: {title[:42]}...")
            summary_ko = summarize_ko(title, abstract)
            time.sleep(0.25)

        papers.append({
            "id": pid,
            "title": title,
            "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:5]),
            "journal": source,
            "date": item.get("pubdate", ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "abstract": abstract[:500] if abstract else "",
            "category": category,
            "summary_ko": summary_ko,
        })
    return papers


def main():
    print("Fetching small-animal papers from PubMed...")
    try:
        papers = get_papers()
    except Exception as e:
        print(f"수집 오류: {e}")
        papers = []

    papers.sort(key=lambda x: x.get("date", ""), reverse=True)

    # 분야별 편수 집계(참고 출력)
    counts = {}
    for p in papers:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print("분야별:", {CATEGORY_LABELS.get(k, k): v for k, v in counts.items()})

    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(papers),
        "categories": CATEGORY_LABELS,     # 화면에서 한글 이름 표시에 사용
        "papers": papers,
    }
    with open("papers.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"완료! 총 {len(papers)}편 저장 → papers.json")


if __name__ == "__main__":
    main()
