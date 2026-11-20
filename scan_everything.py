# -*- coding: utf-8 -*-
"""
scan_everything.py —— 穷举账号所有 Google One SKU，生成带解释的清单文档

① 发现：从设备数据目录 grep SKU 字面量（root）
② 组合：容量 × 后缀 + play/ai 家族
③ 验证：scan_offers.js 查询每个 SKU 的 offer 与完整定价阶段（含币种/期数/标签）
④ 渲染：SKU-清单.md（写明每个试用/特价是什么、多久、之后多少）

用法：
  py scan_everything.py 127.0.0.1:16384
  py scan_everything.py --render-only
"""
import argparse
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import one_common

ultra0 = one_common.ultra0

HERE = Path(__file__).parent


def mask_serial(s):
    """脱敏设备序列号（写 JSON / 渲染文档用）：127.0.0.1:16384 → 127.0.0.1:****。"""
    s = str(s or "")
    if not s:
        return ""
    if ":" in s:                      # adb over TCP：保留 host，隐去端口
        return s.rpartition(":")[0] + ":****"
    return (s[:4] + "****") if len(s) > 4 else "****"


def json_path_for(tag):
    return HERE / (f"scan_result_{tag}.json" if tag else "scan_result_all.json")


JSON_PATH = HERE / "scan_result_all.json"
DOC_PATH = HERE / "SKU-清单.md"
CHUNK = 18

SIZES = ["30gb", "100gb", "200gb", "2tb", "5tb", "10tb", "20tb", "30tb", "helium"]
SUFFIXES = ["", ".annual", ".v2", ".ai", ".ai.annual", ".ai.subs_variant", ".subs_variant",
            ".1month_eft", ".3months_eft", ".6months_eft", ".12months_eft",
            ".3months_ip_85p.acq", ".3months_ip_75p.acq", ".3months_ip_83p.acq"]
PLAY_EXTRA = ["g1.play", "g1.play.ai", "g1.play.ai.pro", "g1.play.ai.plus", "g1.play.ai.ultra",
              "g1.play.pro", "g1.play.plus", "g1.play.home", "g1.play.health", "g1.play.helium",
              "g1.play.2tb", "g1.play.5tb", "g1.play.20tb", "g1.play.30tb"]
PLAY_MONTHS = [f"g1.play.{s}.{m}" for s in ("2tb", "5tb", "10tb", "20tb", "30tb")
               for m in ("1month", "3month", "6month", "12month")]
AI_EXTRA = ["g1.ai", "g1.ai.pro", "g1.ai.plus", "g1.ai.ultra",
            "g1.ai.pro.annual", "g1.ai.ultra.annual", "g1.ai.pro.subs_variant",
            "g1.ai.ultra.subs_variant", "g1.ai.plus.subs_variant"]
ADDONS = ["g1.youtube_premium_individual_add_on", "g1.youtube_premium_family_add_on",
          "g1.home_premium", "g1.health_premium", "g1.pro", "g1.plus", "g1.premium",
          "g1.ultra", "g1.ultra.20tb", "g1.ultra.30tb"]

PATTERN = r'g1\.[a-z0-9]{1,12}(\.[a-z0-9_-]{2,30}){0,4}'

# 容量 → 展示用名称
CAP = {"30gb": "30 GB", "100gb": "100 GB", "200gb": "200 GB", "2tb": "2 TB", "5tb": "5 TB",
       "10tb": "10 TB", "20tb": "20 TB", "30tb": "30 TB", "helium": "Helium"}


# ---------- 工具 ----------
def period_days(p):
    """把 ISO-8601 周期换算成天数（P1Y/P6M/P13W1D/P4W3D…）。"""
    m = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?", str(p or ""))
    if not m:
        return None
    y, mo, w, d = (int(x) if x else 0 for x in m.groups())
    return y * 365 + mo * 30 + w * 7 + d


def period_cn(p):
    """周期 → 中文时长（含天数）。"""
    d = period_days(p)
    if d is None:
        return str(p)
    if d >= 360 and d % 365 < 10:
        return f"{round(d / 365)} 年（{d} 天）"
    if d % 30 == 0:
        return f"{d // 30} 个月（{d} 天）"
    if d % 7 == 0:
        return f"{d // 7} 周（{d} 天）"
    return f"{d} 天"


def money(micros, cur=""):
    try:
        m = int(micros) / 1e6
    except Exception:
        return ""
    s = f"{m:,.2f}"
    return f"{s} {cur}" if cur else s


def cap_of(sku, title=""):
    """容量：优先取收银台名称里的容量（更准），否则按 SKU 名推断。"""
    m = re.search(r"\((\d+(?:\.\d+)?\s*(?:GB|TB))\)", title or "")
    if m:
        return m.group(1).replace(" ", "")
    body = sku[3:] if sku.startswith("g1.") else sku
    for k in CAP:
        if body == k or body.startswith(k + "."):
            return CAP[k]
    return ""


def describe(sku, oid, phases):
    """给一条 offer 生成人话解释。"""
    if not phases:
        return ""
    first = phases[0]
    typ = "trial" if len(phases) > 1 and first.get("free") else ("free" if first.get("free") else "paid")
    if typ == "trial":
        nxt = phases[1] if len(phases) > 1 else {}
        return (f"**免费试用**：前 {period_cn(first.get('period'))} 收 0 元，"
                f"之后按 {money(nxt.get('micros'), nxt.get('cur'))}/期 自动续费（取消须在试用结束前）")
    if typ == "free":
        return "**整段免费**（无后续扣费阶段）"
    # 折扣引导价
    if oid and oid.lower() != "null" and len(phases) > 1:
        cycles = first.get("cycles") or 0
        nxt = phases[1]
        return (f"**首期特价**：前 {cycles or '?'} 期每期 {money(first.get('micros'), first.get('cur'))}，"
                f"之后恢复 {money(nxt.get('micros'), nxt.get('cur'))}/期")
    return "正常订阅（无折扣/试用）"


# ---------- 发现 / 扫描 ----------
def discover_from_device():
    found = set()
    for path in ("/data/data/com.google.android.apps.subscriptions.red",
                 "/data/data/com.android.vending/databases"):
        cmd = [ultra0.ADB, "-s", ultra0.SERIAL, "shell",
               f"su -c \"grep -a -r -o -E '{PATTERN}' {path} | sed 's/.*://' | sort -u\""]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=120)
            for line in r.stdout.decode("utf-8", "ignore").splitlines():
                line = line.strip()
                if re.fullmatch(PATTERN, line):
                    found.add(line)
        except Exception as e:
            print(f"  发现失败 {path}: {e}", flush=True)
    return found


def build_candidates(discovered):
    gen = set(discovered)
    for s in SIZES:
        for suf in SUFFIXES:
            gen.add(f"g1.{s}{suf}")
    gen.update(PLAY_EXTRA)
    gen.update(PLAY_MONTHS)
    gen.update(AI_EXTRA)
    gen.update(ADDONS)
    return sorted(gen)


def scan_skus(skus):
    pid = ultra0.launch_app()
    print("GOOGLE_ONE_PID =", pid, flush=True)
    if not pid:
        raise SystemExit("Google One 没起来")

    import frida
    dev = frida.get_device(ultra0.SERIAL, timeout=10)
    sess = dev.attach(pid)
    template = (HERE / "scan_offers.js").read_text(encoding="utf-8")
    offers = []

    def scan_chunk(part, idx):
        js = template.replace("var PRODUCTS = [];",
                              "var PRODUCTS = " + json.dumps(part) + ";", 1)
        got, done = [], threading.Event()

        def on_msg(m, _d):
            p = m.get("payload") or {}
            ev = p.get("ev")
            if ev == "offer":
                got.append(p)
            elif ev in ("done", "query_err", "setup") and (ev != "setup" or p.get("code")):
                if ev != "setup":
                    done.set()

        sc = sess.create_script(js)
        sc.on("message", on_msg)
        sc.load()
        done.wait(timeout=15)
        time.sleep(0.3)
        try:
            sc.unload()
        except Exception:
            pass
        print(f"   批{idx}: {len(part)} 个 → {len(got)} 条", flush=True)
        return got

    for i in range(0, len(skus), CHUNK):
        offers.extend(scan_chunk(skus[i:i + CHUNK], i // CHUNK + 1))
        time.sleep(0.4)
    return offers


# ---------- 渲染 ----------
def render_doc(offers, candidates_count, serial, scanned_at):
    trials, intros, paid = {}, {}, {}
    for o in offers:
        prod, oid = o.get("product"), o.get("id")
        phases = o.get("phases") or []
        if not phases:
            continue
        oid_s = "" if oid in (None, "null", "None") else str(oid)
        first = phases[0]
        is_trial = len(phases) > 1 and first.get("free")
        is_intro = bool(oid_s) and not first.get("free") and len(phases) > 1
        key = (prod, oid_s)
        row = {
            "sku": prod, "title": o.get("title", ""), "oid": oid_s,
            "cap": cap_of(prod, o.get("title", "")), "tags": o.get("tags", ""), "phases": phases,
        }
        if is_trial:
            trials[key] = row
        elif is_intro:
            intros[key] = row
        else:
            paid.setdefault(prod, []).append(row)

    listed = {p for p, _ in trials} | {p for p, _ in intros} | set(paid)

    L = ["# Google One / AI 订阅 SKU 清单", "",
         f"> 设备 `{serial}`，扫描时间 {scanned_at}；探测 {candidates_count} 个候选，"
         f"命中上架 {len(listed)} 个 SKU。价格均为账号 Play 地区本地货币（见各单元格币种）。", ""]

    # ---- 1. 免费试用 ----
    L += ["## 1. 免费试用档", "",
          "> 「试用时长」= 0 元阶段的实际周期；「试用结束后」= 到期自动续费的价格（未取消则扣费）。",
          "",
          "| SKU | 收银台名称 | 容量 | offerId | 标签 | 试用时长 | 试用结束后 |",
          "|---|---|---|---|---|---|---|"]
    for (prod, oid), r in sorted(trials.items()):
        ph = r["phases"]
        nxt = ph[1] if len(ph) > 1 else {}
        L.append(f"| `{prod}` | {r['title'] or '-'} | {r['cap'] or '-'} | `{oid}` | "
                 f"{r['tags'] or '-'} | {period_cn(ph[0].get('period'))} | "
                 f"{money(nxt.get('micros'), nxt.get('cur'))}/期 |")

    # ---- 2. 特价（首期折扣）----
    L += ["", "## 2. 首期特价档（introprice）", "",
          "> 「特价」= 前 N 期每期价格；「之后恢复」= 折扣期结束后的正常月费。",
          "",
          "| SKU | 收银台名称 | 容量 | offerId | 特价 | 特价期数 | 之后恢复 |",
          "|---|---|---|---|---|---|---|"]
    for (prod, oid), r in sorted(intros.items()):
        ph = r["phases"]
        nxt = ph[1] if len(ph) > 1 else {}
        L.append(f"| `{prod}` | {r['title'] or '-'} | {r['cap'] or '-'} | `{oid}` | "
                 f"{money(ph[0].get('micros'), ph[0].get('cur'))}/期 | {ph[0].get('cycles')} 期 | "
                 f"{money(nxt.get('micros'), nxt.get('cur'))}/期 |")

    # ---- 3. 正价 ----
    L += ["", "## 3. 正价订阅档", "", "| SKU | 收银台名称 | 容量 | 周期 | 价格 |",
          "|---|---|---|---|---|"]
    for prod in sorted(paid):
        for r in paid[prod]:
            ph = r["phases"][0]
            L.append(f"| `{prod}` | {r['title'] or '-'} | {r['cap'] or '-'} | "
                     f"{ph.get('period')} | {money(ph.get('micros'), ph.get('cur'))} |")

    # ---- 4. 术语与有效期说明 ----
    L += ["", "## 4. 术语解释", "",
          "| 片段 | 含义 |", "|---|---|",
          "| `eft` / `freetrial` | 免费试用（free trial）。`12months-eft`=12 个月，`eft-3mo`=3 个月 |",
          "| `subs_variant` | 订阅变体 SKU，试用/促销通常挂在这类 SKU 上 |",
          "| `.1month_eft` / `.3months_eft` / `.6months_eft` / `.12months_eft` | 按试用时长单独上架的 SKU |",
          "| `_ip_85p.acq` | intro price 85% off 的拉新（acquisition）档：前几期打折，之后恢复原价 |",
          "| `_ip_75p` / `_ip_83p` | 同上，折扣比例分别为 75% / 83% off |",
          "| `g1.play.*` | Play 促销族，免费试用大多在这族 SKU 上 |",
          "| `youtube_premium_*` / `home_premium` / `health_premium` | 附加订阅（非存储容量档） |",
          "",
          "### offer 标签（tags）",
          "",
          "| 标签 | 含义 |",
          "|---|---|",
          "| `eft` | 免费试用 offer |",
          "| `promotional` | 促销类 offer（试用/首期特价都是） |",
          "| `play` | Play 渠道促销组 |",
          "| `genai` | 含 Gemini 等 AI 功能的新版套餐 |",
          "| `helium` | Helium 套餐线（小容量 AI Plus） |",
          "| `intro-pricing` | 首期折扣价（intro price） |",
          "",
          "## 5. 周期换算与有效期", "",
          "| 周期字段 | 天数 | 中文 |",
          "|---|---|---|",
          "| `P1M` | 30 | 1 个月 |",
          "| `P4W3D` | 31 | 约 1 个月（4 周 3 天） |",
          "| `P3M` | 90 | 3 个月 |",
          "| `P13W1D` | 92 | 3 个月（13 周 1 天） |",
          "| `P6M` | 180 | 6 个月 |",
          "| `P26W2D` | 184 | 6 个月（26 周 2 天） |",
          "| `P1Y` | 365 | 12 个月（1 年） |",
          "",
          "## 6. 规则与注意", "",
          "- 试用期 0 扣费，**试用结束前取消即不收费**，否则按「试用结束后」价格自动续费，按月扣。",
          "- 首期特价按「特价期数」计费（如 3 期=3 个月），结束后自动回到原价。",
          "- 资格前提：账号**无现存同类订阅**、已绑定有效支付方式；同一档一般**只有一次机会**，"
          "`launchBillingFlow` 一拉起就可能消耗资格。",
          "- 免费档 token 为设备级（不同账号扫出可能完全相同），是否真可用以收银台显示为准。",
          "- 免费试用叠加实测：Pro 5TB 的 12+6+6 可叠到 24 个月；第 4 个 6 个月档拉起后变原价，不再叠加。",
          ""]

    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial", nargs="?")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--tag", default="", help="地区标签，如 us/hk/gb，用于命名 JSON")
    ap.add_argument("--json-only", action="store_true", help="只扫描并存原始 JSON，不渲染文档")
    args = ap.parse_args()

    if args.render_only:
        d = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        offers = d["offers"] if isinstance(d, dict) else d
        cand = d.get("candidates", 0) if isinstance(d, dict) else 0
        ser = d.get("serial", "") if isinstance(d, dict) else ""
        at = d.get("at", "") if isinstance(d, dict) else ""
        DOC_PATH.write_text(render_doc(offers, cand, ser, at), encoding="utf-8")
        print(f"已重写 {DOC_PATH}（{len(offers)} 条 offer）", flush=True)
        return

    one_common.setup(serial=args.serial)
    if not one_common.ensure_vending():
        one_common.reboot_and_recover()

    print("① 发现设备 SKU …", flush=True)
    discovered = discover_from_device()
    print(f"   {len(discovered)} 个", flush=True)

    print("② 生成候选 …", flush=True)
    skus = build_candidates(discovered)
    print(f"   合计 {len(skus)} 个", flush=True)

    print("③ 验证 …", flush=True)
    offers = scan_skus(skus)
    if not offers:
        raise SystemExit("全部无返回 —— 结算异常，未覆盖原清单")

    at = time.strftime("%Y-%m-%d %H:%M")
    jpath = json_path_for(args.tag)
    jpath.write_text(json.dumps(
        {"serial": mask_serial(ultra0.SERIAL), "tag": args.tag, "candidates": len(skus),
         "at": at, "offers": offers},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始 JSON 已写入 {jpath}（{len(offers)} 条 offer）", flush=True)
    if args.json_only:
        return
    DOC_PATH.write_text(render_doc(offers, len(skus), mask_serial(ultra0.SERIAL), at), encoding="utf-8")
    print(f"\n完成：{len(offers)} 条 offer，已写入 {DOC_PATH}", flush=True)


if __name__ == "__main__":
    main()
