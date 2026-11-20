# -*- coding: utf-8 -*-
"""
render_multi.py —— 合并多地区扫描结果：同一 SKU 一行，各地区金额并列

读取 scan_result_{gb,us,hk,tr,in}.json
输出 SKU-清单.md
"""
import json
import time
from pathlib import Path

import scan_everything as se

HERE = Path(__file__).parent
DOC = HERE / "SKU-清单.md"

REGIONS = [("GB", "scan_result_gb.json"), ("US", "scan_result_us.json"),
           ("HK", "scan_result_hk.json"), ("TR", "scan_result_tr.json"),
           ("IN", "scan_result_in.json")]


def load():
    out = {}
    for tag, fn in REGIONS:
        p = HERE / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        out[tag] = d
    return out


def split(offers):
    """返回 (trials, intros, base)：
       trials/intros: {(sku, oid): row}；base: {sku: row}"""
    trials, intros, base = {}, {}, {}
    for o in offers:
        ph = o.get("phases") or []
        if not ph:
            continue
        oid = "" if o.get("id") in (None, "null", "None") else str(o.get("id"))
        sku = o.get("product")
        title = o.get("title", "")
        row = {"sku": sku, "title": title, "oid": oid, "ph": ph}
        if len(ph) > 1 and ph[0].get("free"):
            trials[(sku, oid)] = row
        elif oid and len(ph) > 1:
            intros[(sku, oid)] = row
        else:
            base.setdefault(sku, row)
    return trials, intros, base


def short_name(title):
    """Google AI Pro (5 TB) (Google One) → Google AI Pro 5TB"""
    t = (title or "").replace("(Google One)", "").strip()
    t = t.replace("(Google One)", "")
    t = t.replace("(", "").replace(")", "")
    return " ".join(t.split())


def cell_price(row, idx=0):
    if not row:
        return "-"
    ph = row["ph"][idx] if len(row["ph"]) > idx else row["ph"][0]
    return se.money(ph.get("micros"), ph.get("cur")) or "-"


def main():
    data = load()
    parsed = {tag: split(d["offers"]) for tag, d in data.items()}
    heads = " | ".join(t for t, _ in REGIONS)
    div = "---|" * len(REGIONS)

    L = ["# Google One / AI 订阅 SKU 清单（多地区金额对照）", ""]

    # 概要
    L += ["| 地区 | 设备 | 扫描时间 | 上架 SKU | 免费档 |", "|---|---|---|---|---|"]
    for tag, d in data.items():
        tr, it, base = parsed[tag]
        L.append(f"| {tag} | `{se.mask_serial(d.get('serial',''))}` | {d.get('at','')} | "
                 f"{len(set(base) | {k[0] for k in tr} | {k[0] for k in it})} | {len(tr)} |")

    # 1. 免费试用（合并同 SKU）
    L += ["", "## 1. 免费试用档", "",
          f"> 单元格 = 试用结束后的续费价（每月），`-` = 该地区不提供此试用。", "",
          f"| SKU | 名称 | offerId | 试用时长 | {heads} |", f"|---|---|---|---|{div}"]
    keys = sorted({k for tag in parsed for k in parsed[tag][0]})
    for key in keys:
        rows = {tag: parsed[tag][0].get(key) for tag in parsed}
        sample = next(r for r in rows.values() if r)
        dur = se.period_cn(sample["ph"][0].get("period"))
        cells = " | ".join(cell_price(rows[tag], 1) for tag, _ in REGIONS)
        L.append(f"| `{key[0]}` | {short_name(sample['title'])} | `{key[1]}` | {dur} | {cells} |")

    # 2. 首期特价（合并同 SKU）
    L += ["", "## 2. 首期特价档（introprice）", "",
          f"> 单元格 = 特价/期（共 N 期）→ 之后恢复价。", "",
          f"| SKU | 名称 | offerId | 期数 | {heads} |", f"|---|---|---|---|{div}"]
    keys = sorted({k for tag in parsed for k in parsed[tag][1]})
    for key in keys:
        rows = {tag: parsed[tag][1].get(key) for tag in parsed}
        sample = next(r for r in rows.values() if r)
        cyc = sample["ph"][0].get("cycles")
        cells = []
        for tag, _ in REGIONS:
            r = rows[tag]
            if not r:
                cells.append("-")
            else:
                first = se.money(r["ph"][0].get("micros"), r["ph"][0].get("cur"))
                nxt = se.money(r["ph"][1].get("micros"), r["ph"][1].get("cur")) if len(r["ph"]) > 1 else "-"
                cells.append(f"{first} → {nxt}")
        L.append(f"| `{key[0]}` | {short_name(sample['title'])} | `{key[1]}` | {cyc} 期 | " + " | ".join(cells) + " |")

    # 3. 正价（合并同 SKU）
    L += ["", "## 3. 正价订阅档", "",
          f"| SKU | 名称 | 周期 | {heads} |", f"|---|---|---|{div}"]
    skus = sorted({s for tag in parsed for s in parsed[tag][2]})
    for sku in skus:
        rows = {tag: parsed[tag][2].get(sku) for tag in parsed}
        sample = next(r for r in rows.values() if r)
        period = sample["ph"][0].get("period", "")
        cells = " | ".join(cell_price(rows[tag]) for tag, _ in REGIONS)
        L.append(f"| `{sku}` | {short_name(sample['title'])} | {period} | {cells} |")

    # 术语 / 规则
    L += ["", "## 4. 说明", "",
          "- **免费试用**：0 元阶段结束前取消不收费；否则按单元格价格按月续费。",
          "- **首期特价**：前 N 期享特价，之后自动恢复原价。",
          "- 同一档一般只有一次试用机会，`launchBillingFlow` 拉起即可能消耗资格；"
          "免费档是否真可用以收银台显示为准。",
          "- 术语：`eft`=免费试用、`subs_variant`=订阅变体、`_ip_85p.acq`=85% off 拉新档、"
          "`g1.play.*`=Play 促销族；标签 `genai`=含 AI、`helium`=Helium 套餐线。",
          "- 周期：`P1M`=1 月、`P4W3D`=31 天、`P3M`=3 月、`P13W1D`=92 天、`P6M`=6 月、"
          "`P26W2D`=184 天、`P1Y`=12 月。",
          f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M')}", ""]

    DOC.write_text("\n".join(L), encoding="utf-8")
    print(f"已写入 {DOC}（{len(L)} 行）")


if __name__ == "__main__":
    main()
