#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ghost-browser-gate.py: 幽灵浏览器与假前台视窗全局硬阻断闸。
遵循教训 2026-09-18-AA 与 2026-09-19-AG 核心铁律：
【严禁以隔离 Profile 后台 Chrome 偷换宿主前台浏览器，杜绝无主幽灵进程欺诈】

拦截场景：
1. 试图通过命令行运行包含 --user-data-dir=...temp... / tmp 的孤立 Chrome/Edge 进程；
2. 回复中宣称「已在浏览器中打开/已拉起/已登录/窗口已在屏幕呈现」，但本轮命令使用了孤儿调试端口（如 9222 独立实例），
   或者未通过宿主浏览器工具链（OpenCLI / open-browser.cmd）与桌面真实视窗核验。
"""
import os
import sys
import re
import json
from pathlib import Path

# 违规幽灵浏览器启动特征（在临时/隔离目录偷偷拉起私有实例，无主窗口，沉入底层）
GHOST_BROWSER_SPAWN = re.compile(
    r'(?:chrome|msedge)(?:\.exe)?\s+.*--user-data-dir=.*(?:temp|tmp|chrome_dev|isolated)',
    re.I
)

# 违规直接裸占用无登录态的孤儿调试端口
ORPHAN_CDP_SPAWN = re.compile(
    r'(?:chrome|msedge)(?:\.exe)?\s+.*--remote-debugging-port=9222\b',
    re.I
)

# 宣称前台已打开/就绪断言
BROWSER_FOREGROUND_CLAIM = re.compile(
    r"(?:已(?:在|为您)?(?:打开|拉起|弹出|登入|登录)|已经在|窗口已|视窗已).*(?:浏览器|chrome|edge|后台大盘|管理后台)|"
    r"(?:浏览器|chrome|edge|窗口|视窗).*(?:已在屏幕|正最大化|已置顶|呈现在屏幕|正处于前台)",
    re.I
)

QUOTING_HISTORIC = re.compile(r"(实录|当年|上一轮|过去式|教训|lessons|形状 20\d\d|举例|比如说明|复盘|拦截|门禁|禁止|严禁|误报)")

def extract_commands(blob):
    """从输入载荷中精准提取真实执行的命令行列表，剥离 view_file、tool_result、thinking 等纯文本噪音。"""
    cmds = []
    if "{" in blob and any(k in blob for k in ("tool_calls", "CommandLine", "GENERIC", "step_index")):
        for line in blob.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(k in line for k in ('"TOOL_RESULT"', '"GENERIC"', '"thinking"')):
                continue
            if any(k in line for k in ('"name":"view_file"', '"name": "view_file"', '"name":"read_url_content"', '"name":"grep_search"', '"name":"write_to_file"', '"name":"replace_file_content"')):
                continue
            m_cmd = re.search(r'"(?:CommandLine|command)":\s*"((?:[^"\\]|\\.)*)"', line)
            if m_cmd:
                try:
                    cmd_val = json.loads(f'"{m_cmd.group(1)}"')
                except Exception:
                    cmd_val = m_cmd.group(1)
                cmds.append(cmd_val)
    else:
        cmds.append(blob)
    return cmds

def check_text(text, blob=""):
    """供 ag_superego_bridge 与 dynamic claude gates 调用的标准接口。"""
    cmds = extract_commands(blob)

    # 1. 检查命令行中是否试图启动隔离沙箱的幽灵浏览器
    for cmd in cmds:
        # 排除自检测试脚本与门禁自身代码
        if "ghost_browser_gate" in cmd or "ghost-browser-gate" in cmd:
            continue
        if re.search(r'py(?:thon)?(?:\.exe)?\s+(?:-\d+\s+)?-c\b', cmd) and "GHOST_BROWSER" in cmd:
            continue

        if GHOST_BROWSER_SPAWN.search(cmd):
            return (
                "[Superego 拦截 - ghost-browser-gate] 严禁使用隔离 Temp 目录拉起私有幽灵 Chrome/Edge 进程！\n"
                "铁律 2026-09-19-AG 规定：\n"
                "1. 在后台使用 --user-data-dir=Temp... 启动的浏览器无前台交互主窗口，会导致用户物理屏幕完全扑空！\n"
                "2. 打开网页必须使用系统宿主入口（open-browser.cmd 或 Start-Process https://...）；\n"
                "3. 浏览器自动化与网页操控必须使用 OpenCLI (opencli browser ...) 接入用户当前正在使用的宿主 Chrome！"
            )

        if ORPHAN_CDP_SPAWN.search(cmd) and "--user-data-dir" in cmd:
            return (
                "[Superego 拦截 - ghost-browser-gate] 检测到试图在后台拉起 9222 孤儿调试端口的临时浏览器！\n"
                "铁律 2026-09-19-AG 规定：严禁私自拉起无主调试进程，必须接入宿主真实浏览器！"
            )

    # 2. 如果文本中做出了前台视窗交付断言，且涉及历史案卷或讨论时豁免
    if text and not QUOTING_HISTORIC.search(text):
        if BROWSER_FOREGROUND_CLAIM.search(text):
            has_ghost_cmd = any(GHOST_BROWSER_SPAWN.search(c) for c in cmds)
            if has_ghost_cmd:
                return (
                    "[Superego 拦截 - ghost-browser-gate] 严禁将后台隔离沙箱中的幽灵浏览器宣称为「已在前台打开/呈现」！\n"
                    "请使用 OpenCLI 或 open-browser.cmd 接入宿主真实浏览器，并通过物理桌面全屏截屏核验置顶状态！"
                )

    return None

if __name__ == '__main__':
    # 单元自检
    test_cases = [
        ('chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\Temp\\profile', True),
        ('msedge.exe --user-data-dir="C:/Users/<username>\\AppData\\Local\\Temp\\edge_tmp"', True),
        ('opencli browser work tab new https://zimagen.art', False),
        ('open-browser.cmd "https://zimagen.art"', False),
        ('Start-Process "https://zimagen.art"', False),
        ('py -3 test_script.py', False),
    ]
    all_passed = True
    for cmd, should_block in test_cases:
        res = check_text("", cmd)
        is_blocked = (res is not None)
        if is_blocked != should_block:
            print(f"❌ 自检失败: '{cmd}' -> 期望阻断: {should_block}, 实际结果: {is_blocked}")
            all_passed = False
    if all_passed:
        print("✅ [ghost-browser-gate] 单元自检 100% 通过！")
        sys.exit(0)
    else:
        sys.exit(1)
