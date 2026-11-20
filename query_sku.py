# -*- coding: utf-8 -*-
"""
query_sku.py —— 查询指定的几个 SKU 的全部 offer（免费+付费，含 token）

用法：
    py query_sku.py g1.30tb g1.20tb                 # 自动选设备
    py query_sku.py 127.0.0.1:16384 g1.30tb         # 指定实例

只查询、不拉收银台，零风险。
"""
import argparse
import json
import threading
import time

import one_common
ultra0 = one_common.ultra0  # 自包含核心（见 ultra0_core.py）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial", nargs="?", help="设备序列号（可选，放第一个参数）")
    ap.add_argument("skus", nargs="+", help="要查的 SKU，如 g1.30tb g1.20tb")
    args = ap.parse_args()

    # 第一个参数长得不像 SKU（不含点/不以 g1 开头）就当 serial
    serial = None
    skus = list(args.skus)
    if args.serial and ("." not in args.serial):
        serial = args.serial
    elif args.serial:
        skus.insert(0, args.serial)

    one_common.setup(serial=serial)
    if not one_common.ensure_vending():
        one_common.reboot_and_recover()

    pid = ultra0.launch_app()
    print("GOOGLE_ONE_PID =", pid, flush=True)
    if not pid:
        raise SystemExit("Google One 没起来")

    import frida
    dev = frida.get_device(ultra0.SERIAL, timeout=10)
    sess = dev.attach(pid)

    js = ultra0.build_js("5x", True)
    js = js.replace('var PRODUCTS=["g1.play.20tb"];', "var PRODUCTS=" + json.dumps(skus) + ";", 1)

    offers = []
    done = threading.Event()

    def on_msg(m, _d):
        p = m.get("payload") or {}
        ev = p.get("ev")
        if ev == "offer":
            offers.append(p)
            micros = str(p.get("micros"))
            price = "免费 $0" if micros == "0" else f"${int(micros) / 1e6:.2f}/期"
            print(f"  [{p.get('product')}] offer={p.get('id')} period={p.get('period')} → {price}", flush=True)
            if micros == "0":
                print(f"        token={p.get('token')}", flush=True)
        elif ev in ("no_trial", "list_only", "query_err", "boot_err", "boot_fail", "pd"):
            if ev != "pd":
                done.set()

    sc = sess.create_script(js)
    sc.on("message", on_msg)
    sc.load()
    done.wait(timeout=25)
    time.sleep(1)

    print(f"\n=== {', '.join(skus)} ===", flush=True)
    if not offers:
        print("  （没有任何 offer 返回 —— SKU 在该账号地区不存在）", flush=True)


if __name__ == "__main__":
    main()
