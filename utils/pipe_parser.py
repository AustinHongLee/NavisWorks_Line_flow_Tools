from __future__ import annotations

"""管線編號解析模組。

依照 JSON 設定檔中的 pipe_code_pattern，
將整串管線編號 (PipeCode) 拆解成有語意的欄位。

設定檔格式 (pipeline_config.json 範例)：

{
  "pipe_code_pattern": {
    "separators": ["-"],
    "segments": [
      {"index": 0, "role": "system"},
      {"index": 1, "role": "line_no"},
      {"index": 2, "role": "size"},
      {"index": 3, "role": "class"},
      {"index": 4, "role": "insulation"}
    ]
  }
}

role 可用：
- system, line_no, size, class, insulation, material
- ignore (忽略此段)
- custom_1, custom_2 ... (暫不特別處理，只原樣回傳)

"""

import json
from pathlib import Path
from typing import Dict, Any


DEFAULT_CONFIG_FILENAME = "pipeline_config.json"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_pipe_pattern(config_path: str | Path | None = None) -> Dict[str, Any]:
    """從 JSON 檔讀取 pipe_code_pattern 設定並回傳 dict。

    若檔案不存在或沒有設定，回傳空 dict，
    呼叫端應自行處理「尚未設定 pattern」的情況。
    """

    if config_path is None:
        config_path = DEFAULT_CONFIG_FILENAME

    cfg_path = Path(config_path)
    data = _load_json(cfg_path)
    pattern = data.get("pipe_code_pattern") or {}
    # 基本結構檢查
    seps = pattern.get("separators") or []
    segs = pattern.get("segments") or []
    if not seps or not isinstance(seps, list) or not isinstance(segs, list):
        return {}
    return pattern


def parse_pipe_code(pipe_code: str, pattern: Dict[str, Any]) -> Dict[str, Any]:
    """依照 pattern['separators'] 和 pattern['segments'] 拆解管線編號。

    - pipe_code: 例如 'BFW-12001-6"-C1S1-HC2'
    - pattern:   由 load_pipe_pattern() 讀出的設定

    回傳：
        {
          "raw": "BFW-12001-6\"-C1S1-HC2",
          "system": "BFW",
          "line_no": "12001",
          "size": "6\"",
          "class": "C1S1",
          "insulation": "HC2",
          ...
        }

    若 pattern 無效或 pipe_code 為空，僅回傳 {"raw": pipe_code}。
    """

    result: Dict[str, Any] = {"raw": pipe_code or ""}
    if not pipe_code:
        return result
    if not pattern:
        return result

    seps = pattern.get("separators") or []
    segments_def = pattern.get("segments") or []
    if not seps or not segments_def:
        return result

    # 目前僅支援第一個分隔符，預留擴充空間
    sep = str(seps[0]) if seps else "-"
    parts = str(pipe_code).split(sep)

    for seg in segments_def:
        try:
            idx = int(seg.get("index"))
        except Exception:
            continue
        role = (seg.get("role") or "").strip()
        if not role or role == "ignore":
            continue
        if not (0 <= idx < len(parts)):
            continue
        value = parts[idx].strip()
        if not value:
            continue
        # 直接以 role 當 key，例如 system, line_no, size...
        result[role] = value

    return result
