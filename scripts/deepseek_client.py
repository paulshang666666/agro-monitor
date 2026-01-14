import json
import os
import re
import time
from typing import Dict, Any, Optional
import requests

DEEPSEEK_BASE = "https://api.deepseek.com"
ENDPOINTS = ["/chat/completions", "/v1/chat/completions"]  # 兼容两种路径

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

    raise json.JSONDecodeError("No JSON object found", s, 0)

def _post_once(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if r.status_code == 404:
        raise FileNotFoundError("404")
    if r.status_code >= 400:
        raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {(r.text or '')[:400]}")
    return r.json()

def call_deepseek(prompt_system: str, prompt_user: str, timeout: int = 120) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in env")

    # 你可以在 secrets 里设 deepseek-reasoner；这里也会自动降级
    primary_model = (os.getenv("DEEPSEEK_MODEL") or "deepseek-reasoner").strip()
    fallback_model = "deepseek-chat"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def build_payload(model: str) -> Dict[str, Any]:
        # reasoner 有些参数“不会生效/不支持”，尽量保持简单 :contentReference[oaicite:2]{index=2}
