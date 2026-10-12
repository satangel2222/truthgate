#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse gate: 浏览器自动化前必须读 browser-routing.md。
违反: deny + 打印路由表摘要。不需要 Frank 授权的纯诊断读取不触发。"""
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

import json, os, re, sys

RAW = sys.stdin.read()
try:
    DATA = json.loads(RAW)
except:
    sys.exit(0)  # 解析失败就放行

TOOL = DATA.get("tool_name", "")
CMD = str(DATA.get("tool_input", {}).get("command", "")).lower()

if TOOL not in ("Bash", "PowerShell"):
    sys.exit(0)

BRUTAL_KEYWORDS = [
    "playwright", "puppeteer", "selenium", "webdriver", "camoufox", "cloakbrowser",
    "chromium.launch", "chrome.launch", "firefox.launch",
    "opencli", "web-access", "browser-act", "connectovercdp",
    "fetch.*grab", "fetch.grab", "curl.*douyin", "wget.*douyin",
    "yt-dlp.*douyin", "douyin.*download",
]

# ⛔ 2026-09-06 补【本闸的致命盲区】(Frank:「为何你遇到反爬网站,不会自动用反爬 skill?」)
#   本闸原来只看【命令字符串】。而我把 playwright 调用写进 .py 文件里,
#   命令行只剩 `py -3 shot.py` ⇒ **本闸从头到尾是瞎的**。
#   实录:那一轮我用 playwright 抓 Reddit 抓了三次(headless + 非 headless),本闸一次没响,
#   然后我向 Frank 宣布「这是真边界」——而 scrapling/CloakBrowser 一直装着没碰。
#   ⇒ 通用教训:**判据盯"命令长什么样"的闸,只要把动作挪进脚本文件就自动失效。**
#   修法:命令里跑到的本地脚本,把它的正文也纳入匹配(限大小、失败静默,绝不因此挂掉)。
RAW_CMD = str(DATA.get("tool_input", {}).get("command", ""))

# ⛔ 2026-10-03 读正文这一段重写,两个方向都错过:
#   误拦:原来命令里【提到】的任何脚本文件名都读正文、正文里有 playwright 这个词就算
#     ⇒ `sed -n … guard_common.py`、`python ag_superego_bridge.py status` 全被拦(考题 c061~c065、c080、c081)。
#     讲浏览器的文件 ≠ 开浏览器的文件:正文里只是引用 / 举例这些词(词表、判据、测试靶子)的脚本不算。
#   漏拦:10-02 tempchat `cd <草稿目录> && py -3 lx.py`(里面 from playwright …,拿去登 Google 被拒)——
#     脚本路径相对的是命令里 cd 去的目录,原来按会话目录去找 ⇒ 正文一个字都没进匹配。
#   现在:只读【解释器真在跑】的脚本(和交付自检同一份 RUN_SCRIPT);只认【导入了浏览器驱动库】;相对路径也按 cd 的目录找。
# ponytail: 只认导入语句。脚本里用 subprocess 起 opencli / npx playwright、或 importlib 动态导入的,这里不管;
#   真漏过一次再加(到目前真漏的两次 09-06、10-02 都是 from playwright import)。
_DRIVES = re.compile(
    r"^\s*(?:from|import)\s+(?:playwright|patchright|selenium|seleniumbase|pyppeteer|cloakbrowser|camoufox|scrapling"
    r"|undetected_chromedriver|nodriver|DrissionPage|botasaurus)\b"
    r"|^\s*(?:const|let|var|import)\b[^\n]*['\"](?:playwright|playwright-core|patchright|rebrowser-playwright"
    r"|puppeteer|puppeteer-core|puppeteer-extra|selenium-webdriver)(?:/[^'\"]*)?['\"]", re.M | re.I)
try:
    sys.path.insert(0, os.path.expanduser("~/.truthgate"))
    from evidence_table import RUN_SCRIPT
except Exception:
    RUN_SCRIPT = None                     # 导入失败 ⇒ 这一轮只看命令行(fail-open,同本闸其余部分)


def _win(p):
    """~ 展开;git-bash 的 /c/Users/… 换成 c:/Users/…(Windows 的 Python 只认后一种)。"""
    return re.sub(r"^/([a-zA-Z])/", r"\1:/", os.path.expanduser(p))


def _runs_browser_script(raw, cwd):
    if not RUN_SCRIPT:
        return False
    bases = [cwd] + [a or b or c for a, b, c in
                     re.findall(r"""(?:^|[;&|(]\s*)cd\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))""", raw)]
    for g in RUN_SCRIPT.findall(raw):
        p = _win(next((t for t in g if t), ""))
        if not re.search(r"\.(?:py|js|mjs|cjs|ts)$", p, re.I):
            continue
        for f in {os.path.join(_win(b), p) for b in bases if b} | {p}:
            try:
                if os.path.isfile(f) and os.path.getsize(f) < 512_000:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        if _DRIVES.search(fh.read()):
                            return True
            except Exception:
                pass
    return False


IS_BROWSER_AUTO = (any(re.search(k, CMD) for k in BRUTAL_KEYWORDS)
                   or _runs_browser_script(RAW_CMD, str(DATA.get("cwd") or "")))

DIAG_ONLY = any(re.search(p, CMD) for p in [
    r"curl.*\/json(?:/version)?\s*$",
    r"netstat.*\d{4}",
    r"Get-Process.*chrome",
    r"Get-NetTCPConnection.*\d{4}",
    r"tasklist.*chrome",
    r"#\s*browser-routing-ok",
    r"yt-dlp\s+",
])
IS_REGISTRATION = ("_register" in CMD) or ("settings" in CMD and "python" in CMD)

if not IS_BROWSER_AUTO or DIAG_ONLY or IS_REGISTRATION:
    sys.exit(0)

ROUTING_FILE = os.path.expanduser("~/.claude/browser-routing.md")
# 2026-10-03:标记按对话记。原来全机共用一份 ⇒ 任何一个对话读过一次,所有对话从此都放行(直到路由表下次被改):
#   tempchat 10-02 晚读过之后,这道闸对全机每个对话都不拦了 —— 「恢复拦截」等于没恢复。
READ_FLAG = os.path.expanduser("~/.claude/hooks/.browser-routing-read-%s.json"
                               % re.sub(r"[^\w-]", "", str(DATA.get("session_id") or ""))[:16])

recently_read = False
try:
    routing_mtime = os.path.getmtime(ROUTING_FILE)
    if os.path.exists(READ_FLAG):
        last_read = os.path.getmtime(READ_FLAG)
        recently_read = (last_read >= routing_mtime)
except:
    pass

# ⛔ 2026-09-05 死锁修复(Frank 当场撞上):判据原本【只】看 mtime,而 READ_FLAG 的
#   唯一写入点在下面的 `if recently_read:` 分支里 ⇒ 一旦 browser-routing.md 因为任何原因
#   变新(当天实录:我批量替换写死的旧用户名路径,顺手动到了这个文档的时间戳),
#   flag 就永远追不上 ⇒ **我真的 Read 了两次,闸照样拦,而且再也解不开**。
#   这不是"没读",是尺子锁死。⇒ 补一条【事实判据】:直接翻本轮 transcript,
#   看有没有真的用 Read 工具读过 browser-routing.md。读过 = 放行(并让下面把 flag 写新)。
#   mtime 那条保留作快路径;两条是 OR,只放宽"认得出我读过",不放宽"没读也过"。
if not recently_read:
    try:
        tp = DATA.get("transcript_path") or ""
        if tp and os.path.exists(tp):
            with open(tp, "r", encoding="utf-8", errors="replace") as _f:
                _lines = _f.readlines()[-400:]      # 只看尾部,别把整份 transcript 读进来
            for _ln in reversed(_lines):
                if "browser-routing" not in _ln:
                    continue
                try:
                    _m = json.loads(_ln)
                except Exception:
                    continue
                if _m.get("type") != "assistant":
                    continue
                for _c in (_m.get("message") or {}).get("content") or []:
                    if (isinstance(_c, dict) and _c.get("type") == "tool_use"
                            and str(_c.get("name")) in ("Read", "NotebookRead")
                            and "browser-routing" in str((_c.get("input") or {}).get("file_path", ""))):
                        recently_read = True
                        break
                if recently_read:
                    break
    except Exception:
        pass      # fail-safe:翻不动 transcript 就维持原判(保持拦),绝不因解析失败放水

if recently_read:
    try:
        os.makedirs(os.path.dirname(READ_FLAG), exist_ok=True)
        open(READ_FLAG, "w").close()
    except:
        pass
    sys.exit(0)

# Deny: 没读过 browser-routing.md
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "\n\n======== browser-routing gate ========\n"
            "本闸触发 = 上一轮没有读过 browser-routing.md\n"
            "\n"
            "=== 场景 -> 工具 ===\n"
            "CF墙/抖音/高风险: CloakBrowser > Camoufox > worker Playwright\n"
            "已登录站(XHS/X/微博): opencli/web-access\n"
            "反爬硬页: browser-act stealth\n"
            "本地页/性能: webapp-testing\n"
            "\n"
            "=== 端口红线 ===\n"
            "9226 = claude-code知识库专用 - 禁止征用\n"
            "9555 = bananaflow专用 - 禁止征用\n"
            "9222 = 空标签页 - 无登录态\n"
            "14406 = Frank日常Chrome - 禁止征用\n"
            "\n"
            "=== 登录态 ===\n"
            "已登录Douyin浏览器: 目前没有(实测2026-09-01)\n"
            "正确做法: 油猴转TG(跑在他浏览器里,天然登录态)\n"
            "===================================\n"
            "\n"
            "=> 先 Read ~/.claude/browser-routing.md 再执行这条命令。\n"
        ),
    }
}))
