# -*- coding: utf-8 -*-
"""从原版 ultra0.py 抽取本工具包需要的部分，生成自包含 ultra0_core.py。"""
import os
from pathlib import Path

# 原版脚本位置：默认 <用户目录>/Downloads/google-ultra-main/ultra0.py，
# 也可用环境变量 ULTRA0_SRC 覆盖（避免把本机路径写死进仓库）。
SRC = Path(os.environ.get(
    "ULTRA0_SRC",
    Path.home() / "Downloads" / "google-ultra-main" / "ultra0.py",
))
DST = Path(__file__).resolve().parent / "ultra0_core.py"

lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)


def seg(a, b):
    """1-based 闭区间取片段"""
    return "".join(lines[a - 1:b])


HEADER = '''# -*- coding: utf-8 -*-
"""
ultra0_core.py —— 自 google-ultra-main/ultra0.py 抽取的核心运行时（自包含，无外部依赖）

包含：adb 探测/选设备、root、frida-server 管理（含自动下载）、计费模块推送、
Google One 启动、BillingClient 注入模板（FRIDA_JS）、计费模块二进制（MODULE_B64）。
由 extract_core.py 生成，请勿手改；要改逻辑改 extract_core.py 的抽取范围。
"""
import base64
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

'''

# 找到尾部 if __name__ 块并截断（只保留 FRIDA_JS + MODULE_B64）
tail_start = next(i for i, l in enumerate(lines, 1) if l.startswith('if __name__'))
FRIDA_AND_MODULE = "".join(lines[759:tail_start - 1]).rstrip() + "\n"

parts = [
    HEADER,
    "# ---------- 常量（原 52-74 行）----------\n",
    seg(53, 74),
    "\n# ---------- 全局（原 91-92 行）----------\n",
    seg(91, 92),
    "\n# ---------- adb 探测（原 78-88 行）----------\n",
    seg(78, 88),
    "\n# ---------- 基础工具：sh / 打印（原 95-117 行）----------\n",
    seg(95, 117),
    "\n# ---------- 设备选择 / root / frida-server / 计费模块（原 120-218 行）----------\n",
    seg(120, 218),
    "\n# ---------- Google One 启动（原 462-467 行）----------\n",
    seg(462, 467),
    "\n# ---------- BillingClient 注入模板（原 470-488 行）----------\n",
    seg(470, 488),
    "\n# ---------- 内嵌资源：FRIDA_JS + MODULE_B64（原 760 行至尾部）----------\n",
    FRIDA_AND_MODULE,
]

DST.write_text("".join(parts), encoding="utf-8")
print("written:", DST, DST.stat().st_size, "bytes")
