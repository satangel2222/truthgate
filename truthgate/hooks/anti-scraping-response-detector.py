#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostToolUse detector: anti-bot + empty-shell + timeout detection.

Records pending routes. Does NOT bypass CAPTCHA, touch browsers, or invoke skills.
"""
# ⛔ 2026-09-10 接进账本(Frank:「为何 superego 没拦你还是没开火?」):本闸此前从没 import guard_common,
#   于是它每次开火 hook-stats.jsonl 里都是 0 条 ⇒ 记分板看不见它、nudge-escalation-gate 也数不到它
#   (同日扫出 10 道同病,ui-edit-guard 一天响 8 次账本 0 条)。guard_common 一 import 就自动观测 stdout、
#   退出时按内容判 nudge/block/allow,本闸逻辑一字不改。自包含写法:不依赖本文件已有的 import。
try:
    import os as _gc_os, sys as _gc_sys
    _gc_sys.path.insert(0, _gc_os.path.dirname(_gc_os.path.abspath(__file__)))
    import guard_common  # noqa: F401  接线即记账;失败不影响本闸(fail-open)
except Exception:
    pass

import json, os, re, sys, time

STATE = os.environ.get(
    "ANTI_SCRAPING_STATE",
    os.path.expanduser("~/.claude/hooks/.anti-scraping-pending.json"),
)
MARKERS = re.compile(
    r"bot detected|captcha|recaptcha|turnstile|just a moment|cf-chl-|cloudflare|"
    r"access denied|forbidden|too many requests|rate limit|http\s*429|http\s*403",
    re.I,
)
SHELL_MARKERS = re.compile(
    r"loading\.\.\.|加载中|请稍候|"
    r"(?:has not|hasn't|not)\s+fully\s+loaded|"
    r"(?:enable|turn on)\s+(?:javascript|js)|requires?\s+javascript|"
    r"you need to enable|noscript|"
    r"<div id=[\"']root[\"']></div>|<div id=[\"']app[\"']></div>",
    re.I,
)
SHELL_MAX_CHARS = 1500

# 2026-09-01: timeout 检测
# 逻辑回退在 fetch.py 里已固化;这道闸只管注入提示,确保我知道有那条链
# ⛔ 2026-09-15 误伤根治(本会话弹 133 次):旧 pat 匹配裸词 "timeout",而我命令里天天用
#    `timeout 60 node ...`(shell 的 timeout 工具)⇒ 每条这种命令都被当成"抓取超时"。且这提示
#    只跟 fetch.py 的抓取回退链有关,根本不该挂在跟抓网页无关的命令上。
#    修法:①只认【真超时错误】的措辞,不认裸 "timeout"/"exceeded";②必须同时有 fetch/抓取上下文;
#    ③超时措辞只在【工具输出】里找,不在【命令文本】里找(coreutil `timeout 60` 出现在命令里)。
TIMEOUT_PAT = re.compile(
    r"timed\s*out|timeout\s*(?:error|exceeded|of\s*\d)|ETIMEDOUT|TimeoutError|"
    r"navigation\s+timeout|read\s+timed\s+out|抓取超时|请求超时|连接超时|响应超时", re.I)
# fetch.py 抓取回退链才相关的信号(引擎名 / fetch.py / 抓取 skill)
FETCH_CONTEXT = re.compile(r"fetch\.py|camoufox|cloakbrowser|scrapling|crawl4ai|playwright|"
                           r"anti-scraping|browser-routing|\bgrab\(|firecrawl|r\.jina\.ai", re.I)
# SUPEREGO_LOG_DIR = 测试隔离目录(与 guard_common 同口径);2026-09-16 前测试会直接重置这份生产状态
_CHAIN_STATE = os.path.join(os.environ.get("SUPEREGO_LOG_DIR") or os.path.expanduser("~/.claude/hooks"),
                            ".fetch-chain-state.json")

def _chain_read():
    try:
        with open(_CHAIN_STATE) as f:
            return json.load(f)
    except Exception:
        return {"engines_tried": []}

def _chain_write(s):
    os.makedirs(os.path.dirname(_CHAIN_STATE), exist_ok=True)
    with open(_CHAIN_STATE, "w") as f:
        json.dump(s, f)

def looks_like_empty_shell(raw):
    if len(raw) > SHELL_MAX_CHARS:
        return None
    m = SHELL_MARKERS.search(raw)
    return m.group(0) if m else None

# 只有【会抓网页】的工具的结果才该被这道探测器看 —— 反爬/超时/空壳都是抓取产物的特征。
# ⛔ 2026-09-15:不加这个限定,写一个【内容里含"抓取超时"/"fetch.py"的文件】(比如这条教训本身)
#   都会让 Write 的 tool_input 触发提示。Read/Write/Edit/Grep 从不抓网页,一律跳过。
FETCH_TOOLS = {"Bash", "WebFetch"}


def _split_cmd_out(raw):
    """把 PostToolUse 的 stdin 拆成 (工具名, 命令文本, 工具输出)。解析失败就整块都当输出。
    关键:coreutil `timeout 60` 出现在【命令】里,真超时错误出现在【输出】里 ⇒ 必须分开。"""
    try:
        d = json.loads(raw)
    except Exception:
        return "", "", raw
    tool = d.get("tool_name") or ""
    ti = d.get("tool_input") or {}
    cmd = ti.get("command") if isinstance(ti, dict) else ""
    cmd = cmd or (json.dumps(ti, ensure_ascii=False) if ti else "")
    resp = d.get("tool_response")
    out = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False) if resp is not None else ""
    return tool, cmd, out or raw


def main():
    raw = sys.stdin.read()
    tool, cmd, out = _split_cmd_out(raw)
    # 解析出了工具名、但不是抓网页的工具 ⇒ 跳过(解析失败时 tool="" 放行,保守不漏真抓取)。
    if tool and tool not in FETCH_TOOLS:
        return

    # 1. timeout 检测 —— 只在【输出】里找真超时错误,且必须有 fetch.py 抓取上下文,
    #    否则我命令里的 `timeout 60 ...`(shell 工具)会被误当成"抓取超时"(2026-09-15 弹 133 次的根因)。
    if TIMEOUT_PAT.search(out) and FETCH_CONTEXT.search(cmd + "\n" + out):
        st = _chain_read()
        tried = st.get("engines_tried", [])
        if len(tried) < 2:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "检测到 timeout,已尝试的引擎: %s (共 %d 个)。"
                    "fetch.py 里自动回退链: Camoufox -> CloakBrowser -> worker Playwright。"
                    "如果还没试过 CloakBrowser,下一轮抓同一 URL 时会自动切换;"
                    "要强制指定引擎可用 force='cloak' 或 force='worker' 参数。"
                ) % (tried, len(tried))
            }}, ensure_ascii=False))

    # 2. anti-bot 标记 —— 反爬响应在【抓取输出】里,不在我的命令文本里(命令里提 cloudflare/429 不算)
    match = MARKERS.search(out)
    if match:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump({
                "created_at": int(time.time()),
                "marker": match.group(0),
                "reason": "network response matched anti-bot markers",
            }, f, ensure_ascii=False)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "检测到反爬响应(%s)。"
                "下一次网络抓取前必须先 invoke anti-scraping skill grab(),"
                "按 ~/.claude/browser-routing.md 选 CloakBrowser 或 scrapling。"
            ) % match.group(0)
        }}, ensure_ascii=False))
        return

    # 3. 空壳页检测 —— 空壳是【抓取输出】的特征,不看命令
    shell = looks_like_empty_shell(out)
    if shell:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                "抓到空壳页(命中 %r,内容不足 %d 字符) —— HTTP 200 但内容要 JS 才出来。"
                "=> 用 `py -3` + scrapling(必须 py -3,py -3.12 里没装);"
                "登录墙站按 browser-routing.md 走 CloakBrowser。"
            ) % (shell, SHELL_MAX_CHARS)
        }}, ensure_ascii=False))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
