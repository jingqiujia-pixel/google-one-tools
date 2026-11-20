# -*- coding: utf-8 -*-
"""
launch_checkout.py —— 拉起任意 SKU 的 Play 收银台（只弹出，不自动订阅）

用法：
    py launch_checkout.py                      # 自动选第一台模拟器，SKU 见 launch_checkout.js
    py launch_checkout.py 127.0.0.1:16384      # 指定模拟器实例（多开时必须指定！）
    py launch_checkout.py --sku g1.30tb        # 临时换 SKU（不用改 js）
    py launch_checkout.py --sku g1.30tb 127.0.0.1:16384

流程：
    环境准备(one_common.setup) → 重启 Google One → frida 注入 →
    查询 SKU offer → 拉起收银台 → 等待结果

事件说明：
    setup    code=0  结算服务连接成功（没有此事件 = Play 商店没在跑）
    offer    查到的档位（micros 是百万分之一单位的价格，0=免费档）
    launched code=0  收银台已弹出（★可能消耗试用资格，谨慎反复拉★）
"""
import argparse
import json
import sys
import time
from pathlib import Path

import one_common
ultra0 = one_common.ultra0  # 自包含核心（见 ultra0_core.py）
HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser(description="拉起 Google One 任意 SKU 的 Play 收银台")
    ap.add_argument("serial", nargs="?", help="设备序列号，如 127.0.0.1:16384（多开时指定）")
    ap.add_argument("--sku", default=None, help="目标 SKU，如 g1.30tb；不填则用 launch_checkout.js 里的默认值")
    args = ap.parse_args()

    serial = one_common.setup(serial=args.serial)

    # Play 商店假死时自动重启恢复（可选，默认开；--no-reboot 关闭）
    if not one_common.ensure_vending():
        one_common.reboot_and_recover()

    import frida
    # 只重启 Google One（干净的 Activity 状态），绝不碰 Play 商店
    ultra0.sh("shell", f"am force-stop {one_common.GOOGLE_ONE}")
    time.sleep(2)
    pid = ultra0.launch_app()
    print("GOOGLE_ONE_PID =", pid, flush=True)
    if not pid:
        sys.exit("Google One 没起来（模拟器里手动开一次 Google One 再试）")

    dev = frida.get_device(ultra0.SERIAL, timeout=10)   # 按 serial 精确连，避免多开选错
    sess = dev.attach(pid)

    js = (HERE / "launch_checkout.js").read_text(encoding="utf-8")
    if args.sku:  # 命令行 --sku 覆盖 js 里的默认值
        import re
        js = re.sub(r'var TARGET_PRODUCT = "[^"]+";', f'var TARGET_PRODUCT = "{args.sku}";', js, count=1)

    launched = {"p": None}

    def on_msg(m, _d):
        p = m.get("payload") or {}
        ev = p.get("ev")
        if ev in ("setup", "products", "offer", "launched", "no_offer", "no_activity",
                  "no_activity_ui", "launch_err", "act_err", "purchase_cb", "disc"):
            print("EVENT:", json.dumps(p, ensure_ascii=False), flush=True)
        if ev == "launched":
            launched["p"] = p

    sc = sess.create_script(js)
    sc.on("message", on_msg)
    sc.load()

    for _ in range(15):           # 最多等 30 秒
        time.sleep(2)
        if launched["p"] is not None:
            break

    code = (launched["p"] or {}).get("code")
    if code == 0:
        print("\nRESULT: ✅ 收银台已成功拉起（launched code=0），请在模拟器上人工确认", flush=True)
    elif launched["p"] is not None:
        print(f"\nRESULT: ❌ 拉起失败 code={code} msg={(launched['p'] or {}).get('msg')}", flush=True)
    else:
        print("\nRESULT: ❌ 未收到 launched 事件"
              "\n  排查：① Play 商店是否在跑 ② 是否假死（failed to attach → 重启模拟器）"
              "\n        ③ 本机 frida 是否 16.x（17.x 在 MuMu 上 Java 桥坏）", flush=True)


if __name__ == "__main__":
    main()
