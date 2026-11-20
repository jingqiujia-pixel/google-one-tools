# -*- coding: utf-8 -*-
"""
probe_env.py —— 环境诊断：frida 连通性 + Java 桥 + Play 商店状态

用途：拉不起来/查不到 offer 时，先用这个定位是哪一环坏了。

用法：
    py probe_env.py                       # 自动选设备
    py probe_env.py 127.0.0.1:16384       # 指定实例

判读：
    frida 版本        必须 16.x（17.x 在 MuMu Android12/x86_64 上 Java 桥坏）
    hasJava=false     Java 桥不可用 → 检查 frida 版本匹配
    vmOk=true         注入与 Java.perform 正常
    vending 进程      必须存在，否则 BillingClient 永远不回调
"""
import argparse
import json

import one_common
ultra0 = one_common.ultra0  # 自包含核心（见 ultra0_core.py）
PROBE_JS = r"""
rpc.exports.probe = function () {
  var out = { hasJava: (typeof Java !== 'undefined'), avail: null, version: null,
              vmOk: false, err: null };
  if (typeof Java !== 'undefined') {
    try {
      out.avail = Java.available;
      Java.perform(function () { out.vmOk = true; });
    } catch (e) { out.err = String(e); }
  }
  return out;
};
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial", nargs="?", help="设备序列号")
    args = ap.parse_args()

    import frida
    print(f"本机 frida 版本 = {frida.__version__}"
          + ("   ✅ 16.x 正常" if frida.__version__.startswith("16") else "   ❌ 不是 16.x！MuMu 上需 pip install frida==16.7.19")
          , flush=True)

    one_common.setup(serial=args.serial)

    vending = ultra0.sh("shell", "pidof com.android.vending")
    print(f"Play 商店进程 = {vending or '不存在'}"
          + ("   ❌ 不在场，BillingClient 不会回调（跑 ensure_vending / 重启模拟器）" if not vending else "   ✅")
          , flush=True)

    pid = ultra0.launch_app()
    print("GOOGLE_ONE_PID =", pid, flush=True)
    if not pid:
        raise SystemExit("Google One 起不来")

    dev = frida.get_device(ultra0.SERIAL, timeout=10)
    sess = dev.attach(pid)
    sc = sess.create_script(PROBE_JS)
    sc.load()
    r = sc.exports_sync.probe()
    print("Java 桥探测:", json.dumps(r, ensure_ascii=False), flush=True)
    if r.get("vmOk"):
        print("✅ 注入链路正常，可以跑拉起/扫描脚本", flush=True)
    else:
        print("❌ Java 桥不可用 —— 十有八九是 frida 版本问题（17.x 换 16.x，"
              "并删除设备上 /data/local/tmp/frida-server 让脚本重新下载匹配版本）", flush=True)


if __name__ == "__main__":
    main()
