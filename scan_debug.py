# -*- coding: utf-8 -*-
"""scan_debug.py —— 打印一次查询的全部事件，用于排查「全 0 返回」"""
import argparse
import json
import sys
import time
from pathlib import Path

import one_common

ultra0 = one_common.ultra0
HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial")
    ap.add_argument("--sku", action="append", default=["g1.2tb"])
    a = ap.parse_args()

    one_common.setup(serial=a.serial)
    print("vending pid:", ultra0.sh("shell", "pidof com.android.vending") or "(无)")
    print("Google One pid:", ultra0.sh("shell", "pidof com.google.android.apps.subscriptions.red") or "(无)")

    pid = ultra0.launch_app()
    print("launch_app pid =", pid, flush=True)
    if not pid:
        raise SystemExit("Google One 没起来")

    import frida
    dev = frida.get_device(ultra0.SERIAL, timeout=10)
    sess = dev.attach(pid)
    js = (HERE / "scan_offers.js").read_text(encoding="utf-8")
    js = js.replace("var PRODUCTS = [];", "var PRODUCTS = " + json.dumps(a.sku) + ";", 1)

    def on_msg(m, _d):
        print("EVENT:", json.dumps(m.get("payload") or m, ensure_ascii=False)[:600], flush=True)

    sc = sess.create_script(js)
    sc.on("message", on_msg)
    sc.load()
    time.sleep(12)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
