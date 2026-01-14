import json
import os
import re
import time
from typing import Dict, Any, Optional
import requests

DEEPSEEK_BASE = "https://api.deepseek.com"
ENDPOINT = "/chat/completions"  # 官方文档示例路径 :contentReference[oaicite:2]{index=2}

def _safe_json_loads(s: str) -> Dict[str, Any]:
    s = (s or "").strip()
    # 1) 直接解析
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2) 去掉 ```json ... ``` 包裹
    s2 = re.sub(r"^```json\s*|\s*```$", "", s, flags=re.IGNORECASE).strip()
    try:
        return json.loads(s2)
    except Exception:
        pass

    # 3) 截取第一个 { 到最后一个 }（应对前后夹杂解释文本）
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        return json.loads(s[i:j+1])

    raise json.JSONDecodeError("No JSON object found in model output", s, 0)

def call_deepseek(prompt_system: str, prompt_user: str, timeout: int = 90) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in env")

    model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()

    url = DEEPSEEK_BASE + ENDPOINT
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    # ✅ 开启 JSON 模式（保证输出为合法 JSON 字符串）
    # 文档要求 response_format={"type":"json_object"} 且 prompt 要明确要求 JSON :contentReference[oaicite:3]{index=3}
    base_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.2,
        "max_tokens": 2200,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    last_err: Optional[Exception] = None

    for attempt in range(1, 4):
        try:
            r = requests.post(url, headers=headers, json=base_payload, timeout=timeout)

            # 非 2xx：把状态码和响应体前 400 字打印出来（不包含密钥）
            if r.status_code >= 400:
                preview = (r.text or "")[:400]
                raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {preview}")

            data = r.json()
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()

            # 文档提示 JSON 模式下可能返回空 content：遇到空就重试 :contentReference[oaicite:4]{index=4}
            if not content:
                raise ValueError("DeepSeek returned empty content (JSON mode). Retry.")

            return _safe_json_loads(content)

        except Exception as e:
            last_err = e
            # 指数退避
            time.sleep(1.5 * attempt)

            # 第 2/3 次重试：增强提示，降低“空白输出/夹杂解释”的概率
            base_payload["messages"][0]["content"] = (
                prompt_system
                + "\n\nIMPORTANT: Output MUST be a non-empty JSON object ONLY. No markdown. No code fences. No extra text."
            )

    raise RuntimeError(f"DeepSeek call failed: {last_err}")
