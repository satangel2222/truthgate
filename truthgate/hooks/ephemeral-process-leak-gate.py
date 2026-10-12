#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ephemeral-process-leak-gate.py: 临时服务与脱缰浏览器源头阻断闸。
遵循教训 2026-09-15-L 核心铁律：
【源头禁止脱缰唤起，杜绝后台无主僵尸进程】
拦截场景：
1. 试图通过 start microsoft-edge: / start chrome / start "" http 脱缰拉起系统浏览器；
2. 试图在后台裸跑未加超时自毁的 python -m http.server。
"""
import os, sys, re, json
from pathlib import Path

# 违规外部浏览器唤起特征
BROWSER_SPAWN_PATTERNS = [
    re.compile(r'\bstart\s+microsoft-edge:', re.I),
    re.compile(r'\bstart\s+["\']?["\']?\s+microsoft-edge:', re.I),
    re.compile(r'\bstart\s+msedge(?:\.exe)?', re.I),
    re.compile(r'\bstart\s+chrome(?:\.exe)?', re.I),
    re.compile(r'start-process\s+["\']?msedge', re.I),
    re.compile(r'start-process\s+["\']?chrome', re.I),
]

# 违规裸跑 HTTP 服务特征
NAKED_HTTP_SERVER = re.compile(
    r'(?:^|[\;&\|\n]|\bcmd(?:\.exe)?\s+/c\s+|\bpowershell(?:\.exe)?\s+(?:-Command\s+)?)\s*(?:py(?:thon)?(?:\.exe)?(?:\s+-\d+)?)\s+-m\s+http\.server(?!\s+--timeout)',
    re.I
)

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
    # 消除正文复盘/解释讨论中的引用假阳性（如在反引号或讨论句中提到该命令）
    clean_text = re.sub(r'`[^`]*`', '', text)
    clean_text = re.sub(r'["\'][^"\']*["\']', '', clean_text)
    clean_text = re.sub(r'(?:拦截|复盘|案卷|修复|假阳性|误报|提到|排查|讨论).*', '', clean_text)

    cmds = extract_commands(blob)
    for cmd in cmds:
        for pat in BROWSER_SPAWN_PATTERNS:
            # 如果带有受控调试端口（--remote-debugging-port），属于受控自动化测试，不属于无主脱缰唤起
            if pat.search(cmd) and "--remote-debugging-port" not in cmd:
                return (
                    "[Superego 拦截 - ephemeral-process-leak-gate] 检测到试图通过 start/start-process 脱缰唤起系统浏览器！\n"
                    "铁律 2026-09-15-L 规定：\n"
                    "1. 严禁通过系统协议脱离进程树唤起 Edge/Chrome，防止窗口关闭后后台渲染进程继续死循环渲染吃满 CPU，并保障前台打字零打扰！\n"
                    "2. 成果展示必须使用 Playwright 无头模式截图并嵌入对话出示证据，或交付本地 HTML 文件链接供用户自主点击打开！"
                )

        if NAKED_HTTP_SERVER.search(cmd):
            # 排除内联执行脚本（如 python -c "..." / py -3 -c "..."）中作为字符串引用的情况
            if re.search(r'py(?:thon)?(?:\.exe)?\s+(?:-\d+\s+)?-c\b', cmd):
                continue
            return (
                "[Superego 拦截 - ephemeral-process-leak-gate] 检测到试图裸跑无生命周期托管的 python -m http.server！\n"
                "铁律 2026-09-15-L 规定：\n"
                "1. 严禁在后台启动无超时自毁机制的临时 HTTP 服务，防止会话结束后沦为挂机孤儿进程；\n"
                "2. 临时服务必须使用带自动销毁超时的受控脚本，或在任务交付前主动完成 Teardown 资源释放！"
            )

    return None

if __name__ == '__main__':
    # 单元自检
    test_cases = [
        ('cmd.exe /c start microsoft-edge:http://localhost:8989/test.html', True),
        ('start msedge.exe http://127.0.0.1:3000', True),
        ('python -m http.server 8989', True),
        ('py -3 -m http.server 8989', True),
        ('playwright codegen http://localhost:3000', False),
        ('py -3 test_script.py', False),
        ('python -c "for line in blob: if \'http.server\' in line: pass"', False),
    ]
    all_passed = True
    for cmd, should_block in test_cases:
        res = check_text("", cmd)
        is_blocked = (res is not None)
        if is_blocked != should_block:
            print(f"❌ 自检失败: '{cmd}' -> 期望阻断: {should_block}, 实际结果: {is_blocked}")
            all_passed = False
    if all_passed:
        print("✅ [ephemeral-process-leak-gate] 单元自检 100% 通过！")
        sys.exit(0)
    else:
        sys.exit(1)
