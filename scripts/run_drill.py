#!/usr/bin/env python3
"""一键演练脚本：跑通 预警 → 译文核对 → 封路 → 转述 → 更正 → 问询 全流程。

在仓库根目录执行：

    python3 scripts/run_drill.py

所有数据均为虚构演练资料。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从仓库根目录直接运行脚本
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storm_nlp.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["--data", str(ROOT / "data" / "drill"), "demo"]))
