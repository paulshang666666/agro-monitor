from datetime import datetime
from typing import Dict, Any, List

def traffic_light(score: int) -> str:
    if score <= 1:
        return "绿灯"
    if score <= 3:
        return "黄灯"
    return "红灯"

def render_report(meta: Dict[str, Any], result: Dict[str, Any]) -> str:
    score = int(result.get("score", 0))
    light = result.get("light") or traffic_light(score)

    lines: List[str] = []
    lines.append("# AGRO 关联交易监控（最新披露）")
    lines.append("")
    lines.append(f"- 文件类型：**{meta['form']}**")
    lines.append(f"- 日期：**{meta['filing_date']}**")
    lines.append(f"- accession：`{meta['accession']}`")
    lines.append(f"- 关键词命中：**{'是' if meta['keyword_hit'] else '否'}**")
    lines.append(f"- 红旗计分：**{score}** → 交通灯：**{light}**")
    lines.append("")
    lines.append("## 10 问输出")
    lines.append("")
    lines.append("| 题号 | 结论 | 红旗 | 证据/理由（摘录） |")
    lines.append("|---|---|---|---|")
    for i in range(1, 11):
        q = f"Q{i}"
        item = result.get("items", {}).get(q, {})
        ans = item.get("answer", "")
        red = "✅" if item.get("red_flag") else ""
        ev = (item.get("evidence", "") or "").replace("|", " ")
        if len(ev) > 200:
            ev = ev[:200] + "…"
        lines.append(f"| {q} | {ans} | {red} | {ev} |")

    lines.append("")
    lines.append(f"_生成时间（UTC）：{datetime.utcnow().isoformat(timespec='seconds')}Z_")
    return "\n".join(lines)

def render_email(meta: Dict[str, Any], result: Dict[str, Any]) -> str:
    score = int(result.get("score", 0))
    light = result.get("light") or traffic_light(score)

    red_qs = []
    for i in range(1, 11):
        q = f"Q{i}"
        item = result.get("items", {}).get(q, {})
        if item.get("red_flag"):
            red_qs.append(f"- **{q}**：{item.get('answer','')}")

    red_text = "\n".join(red_qs) if red_qs else "- 无红旗"

    return f"""# AGRO 关联交易监控更新（最新披露）

- 文件：**{meta['form']}** / **{meta['filing_date']}**
- 关键词命中：**{'是' if meta['keyword_hit'] else '否'}**
- 红旗计分：**{score}** → **{light}**

## 红旗清单
{red_text}

附件：`latest_report.md`
"""

