# -*- coding: utf-8 -*-
"""
one_common.py —— 公共环境准备（所有脚本 import 这个）

职责（按顺序）：
  1. 找 adb、选定目标设备（支持多实例：参数或环境变量 SERIAL 指定）
  2. 确保 root（重启模拟器后 adbd 会掉 root，这里自动重试 adb root + 重连）
  3. 确保 frida-server 在设备上运行（缺失自动按本机 frida 版本下载）
  4. 确保计费模块 module_521.apk 就位
  5. 确保 Play 商店进程在跑（★关键★：Play 商店不在场，BillingClient
     的 setup/queryProductDetails 永远不回调 —— 来自 11-18 版的教训）

刻意不做的事（VPN 友好）：
  —— 不调用 ultra0.ensure_network()：不清设备代理、不杀 Clash/VPN
  —— 不 force-stop Play 商店（结算服务由它提供，杀了就拉不起收银台）

依赖：
  —— ultra0_core.py（自包含核心，由 extract_core.py 从原 ultra0.py 抽取生成）
  —— 本机 pip 装 frida==16.x（17.x 在 MuMu Android12/x86_64 上 Java 桥坏）
"""
import os
import subprocess
import sys
import time

# 自包含核心（从原 ultra0.py 抽取，无外部依赖）——要更新抽取范围改 extract_core.py
import ultra0_core as ultra0  # noqa: E402

VENDING = "com.android.vending"                       # Play 商店
GOOGLE_ONE = "com.google.android.apps.subscriptions.red"


def setup(serial: str | None = None):
    """一键环境准备。serial 例：'127.0.0.1:16384'；None=自动选第一台。"""
    ultra0.ADB = ultra0.find_adb()
    ultra0.pick_device()
    # pick_device 永远选列表第一台；多实例时用显式传参或环境变量 SERIAL 覆盖
    # （注意：不读 sys.argv，调用方自己用 argparse 处理后再传进来）
    if serial is None:
        serial = os.environ.get("SERIAL")
    if serial:
        ultra0.SERIAL = serial
    print(f"TARGET_DEVICE = {ultra0.SERIAL}", flush=True)

    ensure_root_retry()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()
    # 注意：ensure_vending() 由各脚本自行调用（它可能触发重启恢复，由调用方决策）
    return ultra0.SERIAL


def _adb(*args, timeout=15):
    """裸 adb 调用（不走 ultra0.sh，用于 root/断线等特殊场景）。"""
    cmd = [ultra0.ADB, "-s", ultra0.SERIAL] + list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _reconnect():
    """adb root / 重启后 adbd 会掉线，重连一下。"""
    try:
        _adb("connect", ultra0.SERIAL, timeout=8)
    except Exception:
        pass


def ensure_root_retry():
    """确保设备 root。

    ultra0.ensure_root() 在『模拟器刚重启』后常失败：adb root 让 adbd 重启、
    连接瞬断，紧接着的校验命令超时。这里加重试 + 重连。
    """
    for attempt in range(3):
        try:
            uid = ultra0.sh("shell", "id", timeout=10)
            if "uid=0" in uid:
                ultra0.ok(f"root 已就绪（第 {attempt + 1} 次尝试）")
                return
        except Exception:
            pass
        # 尝试 adb root（adbd 重启会瞬断，稍等再重连）
        try:
            _adb("root", timeout=20)
        except Exception:
            pass
        time.sleep(3)
        _reconnect()
        time.sleep(2)
    # 最后走 ultra0 的完整逻辑（含 su 兜底和报错退出）
    ultra0.ensure_root()


def ensure_vending():
    """Play 商店保活（★收银台能否拉起的决定性条件★）。

    BillingClient 的结算服务寄宿在 Play 商店进程里；它不在场时
    onBillingSetupFinished 永远不回调，脚本就会卡在
    『未收到 launched 事件』。 —— 逻辑照抄 11-18 版 ensure_vending()
    """
    if ultra0.sh("shell", f"pidof {VENDING}"):
        ultra0.ok("Play 商店进程在跑")
        return True
    ultra0.warn("Play 商店没在跑，正在拉起…")
    try:
        ultra0.sh("shell", f"monkey -p {VENDING} -c android.intent.category.LAUNCHER 1", timeout=30)
    except Exception as e:
        ultra0.warn(f"monkey 拉起失败：{e}")
    for _ in range(20):
        time.sleep(1)
        if ultra0.sh("shell", f"pidof {VENDING}"):
            ultra0.ok("Play 商店已拉起")
            time.sleep(2)  # 给结算服务绑定时间
            return True
    ultra0.warn("Play 商店没起来 —— 若反复出现『failed to attach / start timeout』，"
                "说明 Play 商店假死，重启模拟器即可恢复：adb -s <serial> reboot")
    return False


def reboot_and_recover():
    """Play 商店假死时的自动恢复：重启设备 → 等 boot → 拉起 Play 商店。

    假死特征（logcat）：
      Process com.android.vending failed to attach
      Killing ... start timeout
    """
    ultra0.warn("重启模拟器恢复 Play 商店…")
    try:
        _adb("reboot", timeout=20)
    except Exception:
        pass
    # 等设备回来
    for _ in range(60):
        time.sleep(5)
        try:
            r = _adb("shell", "getprop sys.boot_completed", timeout=8)
            if r.stdout.decode(errors="ignore").strip() == "1":
                break
        except Exception:
            continue
    time.sleep(20)          # 等系统服务起来
    _reconnect()
    ensure_root_retry()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()
    time.sleep(5)
    return ensure_vending()
