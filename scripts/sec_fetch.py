import json
import time
from dataclasses import dataclass
from typing import Dict, Any, List
import requests

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVES_TXT_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{acc}.txt"

@dataclass
class Filing:
    form: str
    filing_date: str
    accession: str
    primary_document: str

def _headers(user_agent: str, host: str) -> Dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": host,
    }

def get_submissions(cik: str, user_agent: str) -> Dict[str, Any]:
    cik10 = str(int(cik)).zfill(10)
    url = SUBMISSIONS_URL.format(cik10=cik10)
    r = requests.get(url, headers=_headers(user_agent, "data.sec.gov"), timeout=30)
    r.raise_for_status()
    return r.json()

def list_recent_filings(submissions: Dict[str, Any], forms: List[str]) -> List[Filing]:
    recent = submissions.get("filings", {}).get("recent", {})
    out: List[Filing] = []
    for i, form in enumerate(recent.get("form", [])):
        if form in forms:
            out.append(
                Filing(
                    form=form,
                    filing_date=recent["filingDate"][i],
                    accession=recent["accessionNumber"][i],
                    primary_document=recent["primaryDocument"][i],
                )
            )
    return out

def download_complete_submission_text(cik: str, accession: str, user_agent: str) -> str:
    cik_int = str(int(cik))
    acc_nodash = accession.replace("-", "")
    url = ARCHIVES_TXT_URL.format(cik_int=cik_int, acc_nodash=acc_nodash, acc=accession)

    r = requests.get(url, headers=_headers(user_agent, "www.sec.gov"), timeout=60)
    r.raise_for_status()

    # SEC 公平访问：<=10 req/s，这里保守 sleep :contentReference[oaicite:8]{index=8}
    time.sleep(0.4)
    return r.text

def load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_accession": ""}

def save_state(path: str, state: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
