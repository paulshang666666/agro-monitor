import json
import os
import time
from typing import Dict, Any
import requests

DEEPSEEK_BASE = "https://api.deepseek.com"
ENDPOINT = "/chat/completions"  # DeepSeek 文档示例 :contentReference[oaicite:9]{index=9}

def call_deepseek(prompt_system: str, prompt_user: str, timeout: int = 60) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in env")

    model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()

    url = DEEPSEEK_BASE + ENDPOINT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.2,
        "max_tokens": 1600,
        "stream": False,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    # 简单重试（网络/429）
    last_err = None
    for i in range(3):
        try:
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 + i * 2)
                continue
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content", "").strip()
            return json.loads(content)  # 我们要求模型输出严格 JSON
        except Exception as e:
            last_err = e
            time.sleep(2 + i * 2)

    raise RuntimeError(f"DeepSeek call failed: {last_err}")

