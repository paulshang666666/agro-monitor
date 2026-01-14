import json
import os
import re
import time
from typing import Dict, Any, Optional
import requests

DEEPSEEK_BASE = "https://api.deepseek.com"
ENDPOINT = "/chat/completions"  # DeepSeek 文档：POST /chat/completions :contentReference[oaicite:3]{index=3}

def _safe_json_loads(s: str) -> Dict[str, Any]:
    s = (s or "").strip()

    # 1) 直接解析
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) 去掉 ```json ``` 包裹
    s2 = re.sub(r"^```json\s*|\s*```$", "", s, flags=re.IGNORECASE).strip()
    try:
        return json.loads(s2)
    except Exception:
        pass

    # 3) 截取第一个 { 到最后一个 }
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        return json.loads(s[i:j+1])

    raise json.JSONDecodeError("No JSON object found in model output", s, 0)

def call_deepseek(prompt_system: str, prompt_user: str, timeout: int = 90) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in env")

    model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-reasoner").strip()

    url = DEEPSEEK_BASE + ENDPOINT
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.2,
        "max_tokens": 2200,
        "stream": False,
        # ✅ JSON 模式：保证 message.content 是“合法 JSON 字符串”
        # 文档提醒：必须在 prompt 明确要求输出 JSON，否则可能输出空白字符 :contentReference[oaicite:4]{index=4}
        "response_format": {"type": "json_object"},
    }

    last_err: Optional[Exception] = None

    for attempt in range(1, 6):  # 多重试几次，DeepSeek 文档明确说“有概率空 content” :contentReference[oaicite:5]{index=5}
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)

            if r.status_code >= 400:
                preview = (r.text or "")[:400]
                raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {preview}")

            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"DeepSeek response missing choices: {(r.text or '')[:400]}")

            choice0 = choices[0]
            finish = choice0.get("finish_reason")
            msg = choice0.get("message") or {}

            content = (msg.get("content") or "").strip()

            # 打印关键信息（不含敏感信息），方便你在 Actions 里定位
            print(f"[DeepSeek] attempt={attempt} finish_reason={finish} content_len={len(content)}")

            # content 空：按文档提示，确实可能发生 → 重试 :contentReference[oaicite:6]{index=6}
            if not content:
                raise ValueError("DeepSeek returned empty content (JSON mode). Retry.")

            return _safe_json_loads(content)

        except Exception as e:
            last_err = e
            # 逐步强化 system prompt，降低“空白/跑偏”概率
            payload["messages"][0]["content"] = (
                prompt_system
                + "\n\nIMPORTANT: Output MUST be a NON-EMPTY JSON object ONLY. No markdown. No code fences. No extra text."
            )
            time.sleep(1.5 * attempt)

    raise RuntimeError(f"DeepSeek call failed: {last_err}")
