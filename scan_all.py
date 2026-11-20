# -*- coding: utf-8 -*-
"""
scan_all.py —— 全量扫描当前账号所有 Google One SKU 的 offer（免费+付费）

用法：
    py scan_all.py                          # 自动选设备，扫内置 70 个候选 SKU
    py scan_all.py 127.0.0.1:16384          # 指定实例
    py scan_all.py --sku a --sku b          # 只扫指定的 SKU

输出：
    1) 免费档（micros==0）明细 + token
    2) 每个返回过的 SKU：offer 数 / 免费数 / 付费价格

说明：
    BillingClient 单次查询上限约 20 个 SKU，脚本自动按 18 个/批分批。
    只查询、不拉收银台，零风险。
"""
import argparse
import json
import threading
import time
from pathlib import Path

import one_common
ultra0 = one_common.ultra0  # 自包含核心（见 ultra0_core.py）
# 候选 SKU 池（存储档 / 年付 / AI 档 / play 促销族 / 折扣引导）
CANDIDATES = [
    # 存储基础档
    "g1.30gb", "g1.100gb", "g1.200gb", "g1.helium", "g1.2tb", "g1.5tb", "g1.10tb",
    "g1.20tb", "g1.30tb",
    # 年付变体
    "g1.100gb.annual", "g1.200gb.annual", "g1.2tb.annual", "g1.5tb.annual",
    # 1 个月免费试用后缀
    "g1.30gb.1month_eft", "g1.100gb.1month_eft", "g1.200gb.1month_eft",
    "g1.2tb.1month_eft", "g1.20tb.1month_eft", "g1.30tb.1month_eft",
    # 12 个月免费试用后缀
    "g1.2tb.12months_eft", "g1.20tb.12months_eft", "g1.30tb.12months_eft",
    # AI 档
    "g1.ai", "g1.ai.pro", "g1.ai.plus", "g1.ai.ultra",
    "g1.2tb.ai", "g1.2tb.ai.subs_variant", "g1.5tb.ai", "g1.20tb.ai", "g1.30tb.ai",
    "g1.5tb.ai.subs_variant", "g1.20tb.ai.subs_variant", "g1.30tb.ai.subs_variant",
    # play 促销族（带免费试用的都在这族）
    "g1.play", "g1.play.ai", "g1.play.2tb", "g1.play.5tb", "g1.play.20tb", "g1.play.30tb",
    "g1.play.ai.pro", "g1.play.ai.plus", "g1.play.ai.ultra",
    "g1.play.helium", "g1.play.pro", "g1.play.plus",
    "g1.play.20tb.12month", "g1.play.ai.pro.12month", "g1.play.30tb.12month", "g1.play.5tb.12month",
    # 折扣引导（introprice）
    "g1.2tb.3months_ip_85p.acq", "g1.5tb.3months_ip_75p.acq",
    "g1.100gb.3months_ip_83p.acq", "g1.200gb.3months_ip_83p.acq",
    "g1.30gb.3months_ip_83p.acq", "g1.helium.3months_ip_83p.acq",
    # 附加项
    "g1.youtube_premium_individual_add_on", "g1.youtube_premium_family_add_on",
    "g1.home_premium", "g1.health_premium", "g1.play.home", "g1.play.health",
    # 其它变体
    "g1.ultra", "g1.ultra.20tb", "g1.ultra.30tb", "g1.pro", "g1.plus", "g1.premium",
]

CHUNK = 18  # 单批查询上限（Play 限制约 20）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial", nargs="?", help="设备序列号")
    ap.add_argument("--sku", action="append", help="只扫指定 SKU（可多次）")
    args = ap.parse_args()

    skus = args.sku or CANDIDATES
    # 去重保序
    seen, uniq = set(), []
    for c in skus:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    skus = uniq
    print(f"共 {len(skus)} 个候选 SKU，按 {CHUNK} 个/批扫描", flush=True)

    one_common.setup(serial=args.serial)
    if not one_common.ensure_vending():
        one_common.reboot_and_recover()

    pid = ultra0.launch_app()
    print("GOOGLE_ONE_PID =", pid, flush=True)
    if not pid:
        raise SystemExit("Google One 没起来")

    import frida
    dev = frida.get_device(ultra0.SERIAL, timeout=10)
    sess = dev.attach(pid)

    all_offers = []

    def scan_chunk(part, idx):
        """扫一批：构造 PRODUCTS=[...] 的 list 脚本，收 offer 事件。"""
        js = ultra0.build_js("5x", True)  # 5x=单产品模板 + list_only，不改不点
        js = js.replace('var PRODUCTS=["g1.play.20tb"];', "var PRODUCTS=" + json.dumps(part) + ";", 1)
        got = []
        done = threading.Event()

        def on_msg(m, _d):
            p = m.get("payload") or {}
            ev = p.get("ev")
            if ev == "offer":
                got.append(p)
            elif ev in ("no_trial", "list_only", "query_err", "boot_err", "boot_fail"):
                done.set()

        sc = sess.create_script(js)
        sc.on("message", on_msg)
        sc.load()
        done.wait(timeout=12)
        time.sleep(0.3)
        try:
            sc.unload()
        except Exception:
            pass
        print(f"  批次{idx}: 查 {len(part)} 个 → 返回 offer {len(got)} 条", flush=True)
        return got

    for i in range(0, len(skus), CHUNK):
        all_offers.extend(scan_chunk(skus[i:i + CHUNK], i // CHUNK + 1))
        time.sleep(0.5)

    # ---- 汇总 ----
    def fmt(micros):
        try:
            m = int(micros)
            return "免费 $0" if m == 0 else f"${m / 1e6:.2f}"
        except Exception:
            return str(micros)

    print("\n" + "=" * 70 + "\n免费档（micros == 0）：\n" + "=" * 70, flush=True)
    dedup = {}
    for o in all_offers:
        if str(o.get("micros")) == "0":
            dedup[(o.get("product"), o.get("id"), o.get("token"))] = o
    if not dedup:
        print("  （没有发现任何 $0 免费档）", flush=True)
    for (prod, oid, tok), o in sorted(dedup.items(), key=lambda x: str(x[0][0])):
        print(f"  {prod:28s} offer={str(oid):20s} period={o.get('period')}", flush=True)
        print(f"      token={tok}", flush=True)

    print("\n" + "=" * 70 + "\n所有返回过的商品（含原价档）：\n" + "=" * 70, flush=True)
    prods = {}
    for o in all_offers:
        prods.setdefault(o.get("product"), []).append(o)
    for p in sorted(prods.keys(), key=str):
        lst = prods[p]
        f = sum(1 for x in lst if str(x.get("micros")) == "0")
        prices = sorted({fmt(x.get("micros")) for x in lst if int(x.get("micros", -1)) > 0})
        print(f"  {p:30s} offer={len(lst)} 免费={f} 付费={','.join(prices) if prices else '-'}", flush=True)

    out = Path(__file__).parent / "scan_result.json"
    out.write_text(json.dumps(all_offers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] 明细已写入 {out}", flush=True)


if __name__ == "__main__":
    main()
