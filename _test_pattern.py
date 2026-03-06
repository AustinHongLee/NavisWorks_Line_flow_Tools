"""Quick pattern test — delete after use."""
import re

P = re.compile(r"(?i)^(?=.*\d)(?=.*-)[A-Z0-9][A-Z0-9\-\"'_]*[A-Z0-9]$")

tests = {
    "307-廢棄物回收場遮棚-建築": False,  # 中文 → 不是管線
    "C2418-崙尾一期建廠工程": False,     # 中文
    "廢棄物回收場遮棚": False,           # 純中文
    "FRMWORK": False,                     # 無數字無連字號
    "SUBSTRUCTURE": False,                # 結構
    "CW-22351-8-S1P1": True,             # 管線
    "CW-22206-6-S1P1": True,             # 管線
    "123-ABC-DEF": True,                  # 管線格式
    "307-ABC": True,                      # 短管線
    "": False,                            # 空
}

for val, expected in tests.items():
    result = bool(P.match(val)) if val else False
    ok = "✓" if result == expected else "✗ MISMATCH"
    print(f"  {ok}  {val:40s} → {result} (expect {expected})")
