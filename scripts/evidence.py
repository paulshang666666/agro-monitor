import re
from typing import List, Dict
from bs4 import BeautifulSoup

KEYWORDS = [
    "tether",
    "related party",
    "related-party",
    "related parties",
    "affiliate",
    "affiliated",
    "关联方",
    "关联交易",
    "关联方交易",
    "due from related parties",
    "due to related parties",
]

def html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "lxml")
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text

def extract_snippets(text: str, window: int = 320, max_snippets: int = 30) -> Dict[str, List[str]]:
    tl = text.lower()
    hits: Dict[str, List[str]] = {}
    for kw in KEYWORDS:
        pos = 0
        while True:
            idx = tl.find(kw, pos)
            if idx == -1:
                break
            start = max(0, idx - window)
            end = min(len(text), idx + window)
            snippet = text[start:end].replace("\n", " ").strip()
            hits.setdefault(kw, []).append(snippet[:900])
            pos = idx + len(kw)
            if sum(len(v) for v in hits.values()) >= max_snippets:
                return hits
    return hits

def build_evidence_pack(raw_submission_text: str) -> Dict:
    text = html_to_text(raw_submission_text)
    snippets = extract_snippets(text)
    keyword_hit = any(len(v) > 0 for v in snippets.values())
    explicit_none = ("no related party" in text.lower()) or ("no material related party" in text.lower())
    # 控制发送给模型的长度
    flat = []
    for kw, arr in snippets.items():
        for s in arr[:4]:
            flat.append(f"[{kw}] {s}")
    evidence_text = "\n\n".join(flat)[:12000]
    return {
        "keyword_hit": keyword_hit,
        "explicit_none": explicit_none,
        "evidence_text": evidence_text,
    }

