import argparse
import os
from pathlib import Path

from sec_fetch import (
    get_submissions,
    list_recent_filings,
    download_complete_submission_text,
    load_state,
    save_state,
)
from evidence import build_evidence_pack
from deepseek_client import call_deepseek
from render import render_report, render_email


SYSTEM_PROMPT = """你是一名审计/合规风控分析师。请只输出 json（json object），不得输出任何额外文字、markdown 或代码块。

必须输出如下 JSON 结构（示例）：
{
  "items": {
    "Q1": {"answer": "是|否|不披露", "red_flag": true, "evidence": "来自证据摘录"},
    "Q2": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q3": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q4": {"answer": "是（异常且解释不足）|否（无异常或解释充分）|不披露", "red_flag": false, "evidence": "..."},
    "Q5": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q6": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q7": {"answer": "是（发生且依据不足）|否（没发生或依据充分）|不披露", "red_flag": false, "evidence": "..."},
    "Q8": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q9": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    "Q10":{"answer": "是|否|不披露", "red_flag": false, "evidence": "..."}
  },
  "score": 0,
  "light": "绿灯|黄灯|红灯"
}

规则：
- answer 必须贴近清单选项；证据不足就填“不披露”，并在 evidence 写明“证据不足”
- evidence 必须来自证据摘录内容或对“证据不足”的解释，不得编造
- red_flag 按你的清单红旗规则判定
- score=红旗题数；light: 0–1 绿灯，2–3 黄灯，≥4 红灯
"""


# 用于判断“是否财报类披露”的简单关键词（可自行扩充）
FINANCIAL_HINTS = [
    "unaudited",
    "condensed consolidated",
    "consolidated statements",
    "financial statements",
    "earnings release",
    "results for the",
    "quarter",
    "six months ended",
    "twelve months ended",
]


def looks_like_financial_filing(raw_submission_text: str) -> bool:
    t = raw_submission_text.lower()
    return any(k in t for k in FINANCIAL_HINTS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cik", required=True)
    p.add_argument("--forms", nargs="+", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--out", required=True)

    # ✅ 只分析“财报类披露”（默认开启，满足你“只分析最新财报”的要求）
    p.add_argument("--financial-only", action="store_true", default=True)
    p.add_argument("--no-financial-only", dest="financial_only", action="store_false")

    # 最多向前回看多少条“新披露”来找财报（防止 newest 是非财报 6-K 时永远卡住）
    p.add_argument("--lookback", type=int, default=8)

    args = p.parse_args()

    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise SystemExit("Missing SEC_USER_AGENT env (SEC requires declared User-Agent).")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(args.state)
    last_seen = (state.get("last_seen_accession") or "").strip()
    last_analyzed = (state.get("last_analyzed_accession") or "").strip()
    ignored = set(state.get("ignored_accessions") or [])

    subs = get_submissions(args.cik, user_agent=user_agent)
    filings = list_recent_filings(subs, forms=args.forms)

    if not filings:
        (out_dir / "email.md").write_text(
            "# AGRO 关联交易监控更新\n\n未抓到指定表格类型披露（forms 过滤后为空）。\n",
            encoding="utf-8",
        )
        return

    # filings 是“recent”列表，通常按时间倒序，但这里我们自己排序保证稳定
    filings_sorted = sorted(filings, key=lambda x: x.filing_date, reverse=True)

    # 只在“新披露区间”内找：遇到 last_seen 就停止（避免反复扫描历史）
    candidates = []
    for f in filings_sorted:
        if f.accession == last_seen:
            break
        if f.accession in ignored:
            continue
        candidates.append(f)
        if len(candidates) >= args.lookback:
            break

    if not candidates:
        (out_dir / "email.md").write_text(
            "# AGRO 关联交易监控更新\n\n本次运行未发现新的披露（与上次 last_seen_accession 相同）。\n",
            encoding="utf-8",
        )
        return

    chosen = None
    chosen_raw = None

    # 从最新开始往前找“财报类披露”
    for f in candidates:
        raw = download_complete_submission_text(args.cik, f.accession, user_agent=user_agent)

        if args.financial_only and (not looks_like_financial_filing(raw)):
            # 不是财报：加入 ignored，避免下次再下载同一个
            ignored.add(f.accession)
            continue

        chosen = f
        chosen_raw = raw
        break

    # 更新 last_seen：以“最新披露”的 accession 为准（即 candidates[0]）
    # 这样下一次不会再从头扫这批“新披露”
    state["last_seen_accession"] = candidates[0].accession
    state["ignored_accessions"] = list(ignored)[-500:]  # 控制大小

    if chosen is None:
        # 新披露里没找到财报
        (out_dir / "email.md").write_text(
            "# AGRO 关联交易监控更新\n\n检测到新的披露，但在回看区间内未识别到“财报类”披露（已自动忽略非财报 accession）。\n",
            encoding="utf-8",
        )
        save_state(args.state, state)
        return

    # 防止重复分析同一份财报
    if chosen.accession == last_analyzed:
        (out_dir / "email.md").write_text(
            "# AGRO 关联交易监控更新\n\n识别到财报类披露，但与上次分析 accession 相同，因此跳过重复分析。\n",
            encoding="utf-8",
        )
        save_state(args.state, state)
        return

    # 构造证据包（只提取关键词附近片段）
    pack = build_evidence_pack(chosen_raw)

    user_prompt = f"""请基于以下信息输出 10 问清单 JSON：

文件类型：{chosen.form}
日期：{chosen.filing_date}
accession：{chosen.accession}
关键词命中：{pack['keyword_hit']}
是否明确写“无关联交易”：{pack['explicit_none']}

证据摘录（仅供判断；若证据不足请用“不披露”并说明为什么）：
{pack['evidence_text']}
"""

    try:
        result = call_deepseek(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        # 写一个错误报告，方便你在仓库里直接看（不包含密钥）
        err_path = out_dir / "latest_error.md"
        err_path.write_text(
            f"# DeepSeek 分析失败\n\n- form: {chosen.form}\n- date: {chosen.filing_date}\n- accession: {chosen.accession}\n\n错误：{repr(e)}\n",
            encoding="utf-8",
        )
        raise

    meta = {
        "form": chosen.form,
        "filing_date": chosen.filing_date,
        "accession": chosen.accession,
        "keyword_hit": pack["keyword_hit"],
    }

    report_md = render_report(meta, result)
    (out_dir / "latest_report.md").write_text(report_md, encoding="utf-8")
    (out_dir / "email.md").write_text(render_email(meta, result), encoding="utf-8")

    # 更新 last_analyzed，保证不会重复分析
    state["last_analyzed_accession"] = chosen.accession
    save_state(args.state, state)


if __name__ == "__main__":
    main()
