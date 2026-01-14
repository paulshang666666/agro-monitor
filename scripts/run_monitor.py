import argparse
import os
from pathlib import Path
from sec_fetch import get_submissions, list_recent_filings, download_complete_submission_text, load_state, save_state
from evidence import build_evidence_pack
from deepseek_client import call_deepseek
from render import render_report, render_email

SYSTEM_PROMPT = """你是一名审计/合规风控分析师。请严格输出 json（json object），只输出 JSON，不要输出任何额外文字、markdown 或代码块。

必须输出如下 JSON 结构：
{
  "items": {
    "Q1": {"answer": "是|否|不披露", "red_flag": true, "evidence": "来自证据摘录"},
    "Q2": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."},
    ...
    "Q10": {"answer": "是|否|不披露", "red_flag": false, "evidence": "..."}
  },
  "score": 0,
  "light": "绿灯|黄灯|红灯"
}

规则：
- evidence 必须引用证据摘录或说明“证据不足”，不得编造
- score=红旗题数；light: 0–1绿，2–3黄，≥4红
"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cik", required=True)
    p.add_argument("--forms", nargs="+", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise SystemExit("Missing SEC_USER_AGENT env (SEC requires declared User-Agent).")

    state = load_state(args.state)
    last_acc = (state.get("last_accession") or "").strip()

    subs = get_submissions(args.cik, user_agent=user_agent)
    filings = list_recent_filings(subs, forms=args.forms)
    if not filings:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "email.md").write_text("# AGRO 关联交易监控更新\n\n未抓到指定表格类型。\n", encoding="utf-8")
        return

    # 只取“最新披露”
    newest = sorted(filings, key=lambda x: x.filing_date)[-1]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if newest.accession == last_acc:
        # 没有新披露：可选择发“无更新”邮件
        (out_dir / "email.md").write_text(
            "# AGRO 关联交易监控更新\n\n本次运行未发现新的 6-K/6-K/A/20-F（与上次 accession 相同）。\n",
            encoding="utf-8",
        )
        # 不改 latest_report.md
        return

    raw = download_complete_submission_text(args.cik, newest.accession, user_agent=user_agent)
    pack = build_evidence_pack(raw)

    user_prompt = f"""请基于以下信息输出 10 问清单 JSON：

文件类型：{newest.form}
日期：{newest.filing_date}
关键词命中：{pack['keyword_hit']}
是否明确写“无关联交易”：{pack['explicit_none']}

证据摘录（仅供判断，若证据不足请用“不披露”并说明为什么）：
{pack['evidence_text']}
"""

    result = call_deepseek(SYSTEM_PROMPT, user_prompt)

    meta = {
        "form": newest.form,
        "filing_date": newest.filing_date,
        "accession": newest.accession,
        "keyword_hit": pack["keyword_hit"],
    }

    report_md = render_report(meta, result)
    (out_dir / "latest_report.md").write_text(report_md, encoding="utf-8")
    (out_dir / "email.md").write_text(render_email(meta, result), encoding="utf-8")

    # 更新 state：保证下次不会重复分析旧文件
    state["last_accession"] = newest.accession
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    save_state(args.state, state)

if __name__ == "__main__":
    main()

