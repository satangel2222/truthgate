# -*- coding: utf-8 -*-
"""六宇宙：「找现成 / 下领域级结论」的共用判据（两端同一份，2026-10-02）。

三层（Frank 2026-10-02「全都要」）：
  1. 提问时提醒：问题像「有没有 X / 哪个最好 / 找工具 / 选型 / 替代方案」⇒ 注入六宇宙清单（只注入不拦）。
  2. 深挖层：问题是「深挖 Reddit / 找客户 / 找推广版块 / 谁在找 X」⇒ 提醒有 Reddit Radar（只提醒，不跑）。
  3. 收尾真拦：说出领域级断言（没有现成 / 最强是 / 只能自建 / 换什么都一样…）⇒ 数本轮覆盖了几个【宇宙】，
     不是几种【工具】。gh search + 话题页 + gh api 是同一个宇宙（GitHub），以前能凑成 3 种工具过关。

用的地方：hooks/search-breadth-gate.py（Claude 收尾）、hooks/superego-recall-inject.py（Claude 提问时）、
ag_superego_bridge.py（AG 收尾 check_search_breadth_violation、AG 提问时 handle_pre）。改判据只改这里。

自检：py -3 six_universes.py
"""
import json
import re

# ───────────────────────── 宇宙 ─────────────────────────
# ③④（商业产品 / 大厂官方）用的是同一把工具（网页搜索），从动作记录分不开 ⇒ 合成一个。
U_LOCAL, U_GH, U_WEB, U_PKG, U_LIST, U_VOICE = "local", "github", "web", "pkg", "list", "voice"
U_NAME = {
    U_LOCAL: "①本机已有", U_GH: "②GitHub", U_WEB: "③④商业产品/大厂(网页)",
    U_PKG: "⑤包索引/模型站", U_LIST: "⑥人工清单/文献", U_VOICE: "口碑(真人社区)",
}
U_HOW = {
    U_LOCAL: "py -3.12 ~/.claude/skills/agent-cockpit/scripts/skill_index.py --json --grep <词>"
             "（项目级 */.claude/skills 也扫；他的知识库 brainq.py、聊天档案 chat-archive 也算本机）",
    U_GH: 'gh search repos <词>（翻页）＋ 话题页 gh api "search/repositories?q=topic:<词>"',
    U_WEB: 'py -3 ~/.claude/web.py search "<能力> 平台 推荐 价格"（中英各一遍；大厂按「<大厂> <能力>」搜）',
    U_PKG: "pypi / npm / crates，或 huggingface.co/api/models?search=<词>、ModelScope",
    U_LIST: "awesome-<词> 清单、知乎/掘金盘点文、arXiv",
    U_VOICE: 'last30days "<词>"（最近 30 天真人在用什么）；要深挖 Reddit 用 Reddit Radar（花钱，先说）',
}
CHANNEL_UNIVERSE = {
    "skill-index": U_LOCAL, "his-kb": U_LOCAL, "archive": U_LOCAL,
    "gh-search": U_GH, "gh-topic": U_GH, "gh-api": U_GH,
    "web": U_WEB, "web-fetch": U_WEB, "anysearch": U_WEB,
    "pkg-index": U_PKG, "hf-hub": U_PKG, "cn-model-hub": U_PKG,
    "curated-list": U_LIST, "paper": U_LIST,
    "last30days": U_VOICE, "en-forum": U_VOICE, "cn-forum": U_VOICE,
    "video-community": U_VOICE, "social": U_VOICE, "reddit-radar": U_VOICE,
}
MIN_UNIVERSES = 3   # REQUIREMENTS 第 2 条 3 档：先内部记录，再外部调研 ⇒ ①本机 + 至少两个外部宇宙


def universes(channels):
    return {CHANNEL_UNIVERSE[c] for c in channels if c in CHANNEL_UNIVERSE}


# ───────────────────────── 通道识别（工具调用 → 通道）─────────────────────────
TOOL_CHANNELS = {"WebSearch": "web", "WebFetch": "web", "search_web": "web", "read_url_content": "web"}
BLOB_CHANNELS = [
    (re.compile(r"\bgh(?:\.exe)?[\"']?\s+search\b", re.I), "gh-search"),
    (re.compile(r"topic:|search/repositories\?q=topic", re.I), "gh-topic"),
    (re.compile(r"\bgh\s+api\s+.*search/repositories", re.I), "gh-api"),
    (re.compile(r"curl\s+.*api\.github", re.I), "gh-api"),
    (re.compile(r"pypi\.org|registry\.npmjs|crates\.io|pkg\.go\.dev", re.I), "pkg-index"),
    (re.compile(r"huggingface\.co/api|hf\.co/api|\bhf\s+(search|list)", re.I), "hf-hub"),
    (re.compile(r"last30days|/last30days\.py", re.I), "last30days"),
    (re.compile(r"reddit[-_]radar", re.I), "reddit-radar"),
    (re.compile(r"brainq\.py|vault_semantic\.py|openclaw_query_router", re.I), "his-kb"),
    (re.compile(r"skill_index\.py", re.I), "skill-index"),
    (re.compile(r"easy_anysearch|anysearch/search\.py", re.I), "anysearch"),
    (re.compile(r"r\.jina\.ai|firecrawl|web\.py\s+(?:search|get)", re.I), "web-fetch"),
    (re.compile(r"reddit\.com|news\.ycombinator|stackoverflow\.com|lobste\.rs"
                r"|dev\.to|medium\.com|producthunt\.com|indiehackers\.com", re.I), "en-forum"),
    (re.compile(r"zhihu\.com|v2ex|juejin|tieba|csdn|segmentfault|bilibili"
                r"|xiaohongshu|weixin|sogou\.com/weixin|36kr|sspai|gitee\.com"
                r"|douban\.com|oschina", re.I), "cn-forum"),
    (re.compile(r"youtube\.com|youtu\.be|yt-dlp .*search|/watch\?v=", re.I), "video-community"),
    (re.compile(r"modelscope|阿里云百炼|openi\.pcl|wisemodel", re.I), "cn-model-hub"),
    (re.compile(r"awesome-|awesome_|topic:awesome", re.I), "curated-list"),
    (re.compile(r"arxiv\.org|semanticscholar|scholar\.google", re.I), "paper"),
    (re.compile(r"x-tweet-fetcher|twitter\.com|x\.com/search", re.I), "social"),
    (re.compile(r"chat-archive|q-frank\.js|q\.js\b|ag_archive\.py", re.I), "archive"),
]
# 扫本机 skill 目录：列 / 搜 / Glob / Grep 到 ~/.claude/skills 或 plugins 才算（Read 某一个 skill 文件不算在找）
LOCAL_SCAN = re.compile(r"(?:\bls|\bfind|\bgrep|\brg|Get-ChildItem|\bdir)\b[^|;&]{0,200}\.claude[\\/]+(?:skills|plugins)", re.I)
LOCAL_SCAN_TOOLS = {"Glob", "Grep", "find_by_name", "grep_search", "list_dir"}
SKILLS_DIR = re.compile(r"\.claude[\\/]+(?:skills|plugins)", re.I)


# 写 / 读文件的工具参数里出现 gh search、reddit.com 不代表查过（外审 10-02：改闸文件本身就能凑够宇宙）
NON_SEARCH_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "TodoWrite",
                    "write_to_file", "replace_file_content", "multi_replace_file_content", "view_file"}


def channels_of(name, blob):
    """一次工具调用 → 它算哪些检索通道。name 是工具名，blob 是参数原文（JSON 字符串即可）。"""
    out = set()
    if name in NON_SEARCH_TOOLS:
        return out
    if name in TOOL_CHANNELS:
        out.add(TOOL_CHANNELS[name])
    if re.search(r"reddit[-_]radar", name or "", re.I):
        out.add("reddit-radar")
    for pat, tag in BLOB_CHANNELS:
        if pat.search(blob):
            out.add(tag)
    if LOCAL_SCAN.search(blob) or (name in LOCAL_SCAN_TOOLS and SKILLS_DIR.search(blob)):
        out.add("skill-index")
    return out


def channels_from_ag(tool_calls):
    out = set()
    for tc in tool_calls or []:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        args = fn.get("args", {}) or fn.get("arguments", {})
        blob = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        out |= channels_of(name, blob)
    return out


# ───────────────────────── 只看事实的几条（2026-10-04）─────────────────────────
# 来历：tempchat 会话里排查 Antigravity「开了窗口但人看不见」。我拆了它的安装目录、自己找到根因、写了个工具
# 放进 ~/.gemini/antigravity/scripts，全程零联网；Frank 提醒后一搜，GitHub 上 8 个项目早有同一个做法。
# 当时四道「先查现成」的闸一道没响：prior-art-gate 对临时目录免检（我先写在临时目录再复制过去）、
# 把本机 grep 当成「搜过」、却不认识 web.py；search-breadth-gate 只在说出领域级断言时才数宇宙。
# 下面几条都不看措辞：落点是哪、读了哪个目录、工具目录里多了什么文件、有没有联网。
# 同日外审（独立实例，12 条）后重写过一遍：严格通道、只看命令 / 路径字段、动词要在路径前面、收尾按文件系统兜底。
import os
import time

EXTERNAL_US = {U_GH, U_WEB, U_PKG, U_LIST, U_VOICE}
SHELL_TOOLS = {"Bash", "PowerShell", "run_command"}
_PATH_KEYS = ("file_path", "path", "notebook_path", "AbsolutePath", "SearchPath", "DirectoryPath", "SearchDirectory")
# 「真的去取了」的动词：域名只是出现在 grep / echo / pip -i 里不算联网检索
FETCH_VERB = re.compile(
    r"\b(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod|yt-dlp|scrapling|opencli|browser-act|x-tweet-fetcher)\b"
    r"|web\.py\s+(?:search|get)|r\.jina\.ai|firecrawl|\bgh(?:\.exe)?[\"']?\s+(?:api|search)\b", re.I)
# 这些通道是靠「参数里出现了某个域名 / 字样」认的 ⇒ 严格模式下要配上取数动词才算
DOMAIN_TAGS = {"pkg-index", "en-forum", "cn-forum", "video-community", "cn-model-hub", "curated-list",
               "paper", "social", "gh-topic", "hf-hub"}


def _args_text(name, blob):
    """只取「真正执行 / 真正指向」的那部分参数：命令行工具取命令本身（不含 description），读类工具取路径字段。"""
    try:
        d = json.loads(blob) if isinstance(blob, str) else blob
    except Exception:
        return blob or ""
    if not isinstance(d, dict):
        return blob or ""
    if name in SHELL_TOOLS:
        return str(d.get("command") or d.get("CommandLine") or "")
    if name in LOCAL_SCAN_TOOLS or name in ("Read", "view_file"):
        return " ".join(str(d[k]) for k in _PATH_KEYS if d.get(k))
    return blob if isinstance(blob, str) else json.dumps(d, ensure_ascii=False)


def strict_channels_of(name, blob):
    """和 channels_of 同一张表，但不让本机动作冒充联网：
    Grep / Glob 这类本机工具只可能是①；命令行里靠域名认的通道要同时有取数动词。"""
    if name in NON_SEARCH_TOOLS:
        return set()
    text = _args_text(name, blob)
    if name in LOCAL_SCAN_TOOLS:
        return {"skill-index"} if SKILLS_DIR.search(text) else set()
    out = set()
    if name in TOOL_CHANNELS:
        out.add(TOOL_CHANNELS[name])
    if re.search(r"reddit[-_]radar", name or "", re.I):
        out.add("reddit-radar")
    shell = name in SHELL_TOOLS
    fetch = bool(FETCH_VERB.search(text)) if shell else True
    for pat, tag in BLOB_CHANNELS:
        if pat.search(text) and (fetch or tag not in DOMAIN_TAGS):
            out.add(tag)
    if LOCAL_SCAN.search(text):
        out.add("skill-index")
    return out


def external_universes(channels):
    """本机以外的宇宙。本机 grep / 翻档案只算①，不能单独当成「查过现成」。"""
    return universes(channels) & EXTERNAL_US


# 「以后反复用的工具」落的地方：往这里新建脚本 = 在造工具，不是项目里的一次性胶水
TOOL_DEST = re.compile(
    r"(?:^~|[\\/])[\\/]*\.claude[\\/]+(?:bin|skills|scripts)[\\/]"
    r"|(?:^~|[\\/])[\\/]*\.claude[\\/]+[^\\/]+\.(?:py|js|mjs|cjs|ps1|sh)$"            # web.py 这类直接放在 ~/.claude 根下的
    r"|(?:^~|[\\/])[\\/]*\.gemini[\\/]+(?:antigravity[\\/]+scripts|config[\\/]+skills)[\\/]"
    r"|(?:^~|[\\/])[\\/]*\.(?:codex|agents)[\\/]+skills[\\/]", re.I)
# 临时落点：先写在这里再复制到工具目录，等于新建工具（PreToolUse:Write 看不见复制）
TEMP_SRC = re.compile(r"[\\/](?:Temp|tmp|scratchpad)[\\/]|\$env:TE?MP\b|%TE?MP%", re.I)
CODE_SUFFIX = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".ps1", ".bat", ".cmd", ".rb", ".go", ".rs")
MIN_TOOL_LINES = 40


def is_tool_dest(path):
    return bool(TOOL_DEST.search(str(path or "")))


# 考卷 c090 / c097（2026-10-04 第一版兜底误拦的两题）照出来的两类「不是在造新工具」：
#   · 往【已经存在的技能】里加一个脚本（给 runninghub 技能加 runninghub-apply-local.sh）—— 是在扩自己的技能；
#   · 这一轮有安装动作（git clone / npx skills add / pip install / 解压）—— 文件是别人做好的，装它本身就是在用现成的。
# 都看文件系统 / 动作事实，不看措辞。这两类退回 prior-art-gate 的只记账那一档。
_SKILL_DIR = re.compile(r"^(.*?[\\/]\.(?:claude|gemini[\\/]+config|codex|agents)[\\/]+skills[\\/]+[^\\/]+)[\\/]", re.I)
INSTALL_VERB = re.compile(
    r"\bgit\s+clone\b|\bgh\s+repo\s+clone\b|\bskills\s+add\b|\bplugin\s+(?:install|add)\b"
    r"|\bExpand-Archive\b|\bunzip\b|\btar\s+-?\w*x", re.I)       # pip / npm 装的是依赖包，不算把别人的工具装进来


def extends_existing_skill(path, since=None):
    """这个文件是不是落在一个【早就有的】技能目录里。since 给了就看技能目录的创建时间是否早于它（收尾用），
    不给就看目录现在在不在（调用前用：文件还没写，目录在 = 技能早就有）。"""
    m = _SKILL_DIR.match(local_path(path))
    if not m or not os.path.isdir(m.group(1)):
        return False
    try:
        return since is None or os.stat(m.group(1)).st_ctime < since
    except OSError:
        return False


def local_path(p):
    """把命令里各种写法的路径换成这台机器上 Python 打得开的样子（~、$HOME、%USERPROFILE%、/c/…、/tmp/）。"""
    p = str(p or "").strip().strip("\"'")
    home = os.path.expanduser("~")
    p = re.sub(r"^(?:~|\$\{?HOME\}?|\$env:USERPROFILE|%USERPROFILE%)(?=[\\/]|$)", lambda m: home, p, flags=re.I)
    p = re.sub(r"^/([a-zA-Z])/", lambda m: m.group(1).upper() + ":/", p)
    if re.match(r"^/tmp(?:/|$)", p):
        import tempfile
        p = tempfile.gettempdir() + p[4:]
    p = re.sub(r"^(?:\$env:TE?MP|%TE?MP%)(?=[\\/]|$)", lambda m: os.environ.get("TEMP", ""), p, flags=re.I)
    return os.path.normpath(p)


# 别人软件的安装目录（排除开发工具链 / SDK：它们的路径天天出现在命令里，读它们的头文件也不是在拆谁）
_SEP = r"[\\/]+(?![\\/])"
_DEV = (r"Git[\\/]|GitHub CLI|nodejs|PowerShell|dotnet|Python|WindowsApps|Microsoft VS Code|NVIDIA|Common Files"
        r"|Java|Windows Kits|Microsoft SDKs|Microsoft Visual Studio|Docker|7-Zip")
_INSTALL_SRC = (
    r"(?:AppData" + _SEP + r"Local|\$env:LOCALAPPDATA)" + _SEP + r"Programs" + _SEP + r"(?!" + _DEV + r")[\w.-]+"
    r"|(?:Program Files(?: \(x86\))?|\$env:ProgramFiles(?:\(x86\))?|PROGRA~[12])" + _SEP + r"(?!" + _DEV + r")[\w.-]+")
INSTALL_DIR = re.compile(_INSTALL_SRC, re.I)
# 在命令里「翻内容」的动词。只认搜内容 / 拆二进制的；cat / ls 不认（看一眼配置文件不算拆，认了会天天误拦）
_VERB_SRC = r"\b(?:grep|rg|strings|findstr|Select-String|sls|objdump|dumpbin|asar\s+(?:extract|list|e|l))\b"
INSPECT_VERB = re.compile(_VERB_SRC, re.I)
# 动词在前、路径在后、中间不跨管道：`chrome.exe --version | findstr x` 是启动程序再过滤输出，不是翻它的目录
_VERB_THEN_DIR = re.compile(_VERB_SRC + r"[^|;&\n]*?(" + _INSTALL_SRC + r")", re.I)
_CD_DIR = re.compile(r"(?:^|[;&|\n])\s*(?:cd|pushd|Set-Location|Push-Location|sl)\s+[\"']?[^;&|\n]*?(" + _INSTALL_SRC + r")", re.I)
PROBE_READ_TOOLS = {"Read", "Grep", "Glob", "view_file", "grep_search", "find_by_name", "list_dir"}
MIN_EXTERNAL_FOR_PROBE = 2   # Frank 2026-10-04「双向核实」：官方 + 社区这样两个互相独立的外部来源


def probe_of(name, blob):
    """这次工具调用是不是在翻别人软件的安装目录。是 ⇒ 返回命中的那段路径，否则 None。
    已知量不到的（外审登记）：先 cd 进去、下一条命令才 grep；用脚本 / 逆向工具（ghidra 等）读；AppData\\Local\\<应用>（不在 Programs 下）。"""
    text = _args_text(name, blob)
    if name in PROBE_READ_TOOLS:
        m = INSTALL_DIR.search(text)
        return m.group(0)[:60] if m else None
    if name in SHELL_TOOLS:
        m = _VERB_THEN_DIR.search(text)
        if m:
            return m.group(1)[:60]
        m = _CD_DIR.search(text)
        if m and INSPECT_VERB.search(text[m.end():]):
            return m.group(1)[:60]
    return None


def _tool_uses(msgs):
    for m in msgs or []:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content") or []
        for b in c if isinstance(c, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b.get("name") or "", json.dumps(b.get("input") or {}, ensure_ascii=False)


def channels_in(msgs, strict=False):
    """Claude 会话记录里的一段消息 → 检索通道集合。strict=True 用严格通道（本机动作不冒充联网）。"""
    out = set()
    for name, blob in _tool_uses(msgs):
        out |= strict_channels_of(name, blob) if strict else channels_of(name, blob)
    return out


def probes_in(msgs):
    return [p for p in (probe_of(n, b) for n, b in _tool_uses(msgs)) if p]


def actions_text(msgs):
    """这段消息里所有工具调用「真正执行 / 指向」的文本（归属用：工具目录里多出来的文件是不是我这轮弄的）。"""
    return "\n".join(_args_text(n, b) for n, b in _tool_uses(msgs))


def probes_from_ag(tool_calls):
    out = []
    for tc in tool_calls or []:
        fn = tc.get("function", {}) if "function" in tc else tc
        args = fn.get("args", {}) or fn.get("arguments", {})
        p = probe_of(fn.get("name", ""), args if isinstance(args, str) else json.dumps(args, ensure_ascii=False))
        if p:
            out.append(p)
    return out


def strict_channels_from_ag(tool_calls):
    out = set()
    for tc in tool_calls or []:
        fn = tc.get("function", {}) if "function" in tc else tc
        args = fn.get("args", {}) or fn.get("arguments", {})
        out |= strict_channels_of(fn.get("name", ""), args if isinstance(args, str) else json.dumps(args, ensure_ascii=False))
    return out


def _is_user(m):
    try:
        from guard_common import is_real_user_msg
        return is_real_user_msg(m)
    except Exception:
        c = (m.get("message") or {}).get("content")
        return m.get("type") == "user" and (isinstance(c, str) or any(
            isinstance(b, dict) and b.get("type") == "text" for b in c or []))


def recent_turns(msgs, n=3):
    """最近 n 轮（本轮 + 前 n-1 轮）的消息。调研常在上一轮做完、这一轮才动手，只数本轮会逼着重搜一遍。"""
    msgs = msgs or []
    users = [i for i, m in enumerate(msgs) if _is_user(m)]
    return msgs[users[-n]:] if len(users) >= n else msgs


def _how(us_missing):
    return "\n".join("  · %s：%s" % (U_NAME[u], U_HOW[u]) for u in (U_WEB, U_GH, U_VOICE) if u in us_missing)


def tool_dest_verdict(path, msgs):
    """往工具目录新建脚本前：最近 3 轮有没有查过本机以外的宇宙。没有 ⇒ 返回拦截理由，否则 None。
    读不到会话记录（空 / 没有一条真人消息）⇒ None：判不了就放行，不能因为记录读不出来把人卡死。"""
    if not is_tool_dest(path):
        return None
    msgs = msgs or []
    if not any(_is_user(m) for m in msgs):
        return None
    if extends_existing_skill(path):
        return None
    recent = recent_turns(msgs)
    ch = channels_in(recent, strict=True)
    if external_universes(ch) or INSTALL_VERB.search(actions_text(recent)):
        return None
    us = universes(ch)
    return (
        "⛔ 先查现成（工具落点）：你要往工具目录放一个新脚本（…%s），但最近 3 轮没有查过本机以外的任何地方"
        "（已覆盖：%s）。本机 grep / 翻档案只算①，不算查过现成。\n"
        "2026-10-04 实录：排查 Antigravity 开窗口看不见，自己拆程序、自己写工具，全程没上网；"
        "一搜 GitHub 上 8 个项目早有同一个做法（指定桌面启动 + 写进规则文件）。\n"
        "先查至少一个外部宇宙再建：\n%s") % (
            str(path)[-60:], "、".join(U_NAME[u] for u in U_NAME if u in us) or "一个都没有", _how(EXTERNAL_US))


def probe_verdict(channels, probes, need=MIN_EXTERNAL_FOR_PROBE):
    """翻过别人软件的安装目录，却没有 need 个外部宇宙的检索 ⇒ (日志标签, 拦截理由)，否则 None。channels 传严格通道。"""
    if not probes:
        return None
    ext = external_universes(channels)
    if len(ext) >= need:
        return None
    return ("BLOCK third-party-probe ext=%s probes=%s" % (sorted(ext), probes[:2]), (
        "⛔ 检索广度闸·拆别人的软件：这一轮你翻过别人软件的安装目录（%s），但最近 3 轮本机以外只查了 %d 个宇宙"
        "（要 ≥%d：官方文档 / 问题单 + 社区，各算一个）。已覆盖的外部宇宙：%s。\n"
        "别人的软件为什么这样表现，官方和社区通常早有答案；自己拆出来的结论也要拿它们对一遍再交。\n"
        "2026-10-04 实录：拆 Antigravity 找到「命令跑在隐藏桌面」，没上网就写了修复工具；Frank 提醒后搜一次，"
        "8 个项目的现成做法都在。\n%s\n"
        "确实不需要查（比如他只是让你找某个配置文件在哪）：回复里写一行「误报：search-breadth-gate — <理由>」，这条每轮只拦一次。"
    ) % ("、".join(probes[:2]), len(ext), need,
         "、".join(U_NAME[u] for u in U_NAME if u in ext) or "一个都没有", _how(EXTERNAL_US - ext)))


# 收尾按文件系统兜底：不管是 Write、cp、robocopy、cat >、还是脚本写的，工具目录里这一轮多出了新脚本就算
TOOL_ROOTS = (("~/.claude", 0), ("~/.claude/bin", 2), ("~/.claude/scripts", 2), ("~/.claude/skills", 4),
              ("~/.gemini/antigravity/scripts", 2), ("~/.gemini/config/skills", 4))
_PRUNE = {"node_modules", ".git", "__pycache__", "tmp", "temp", "tests", ".venv", "venv", "dist", "build"}


def new_tool_files(since_epoch, mention_text, budget=1.5, roots=TOOL_ROOTS, until=None):
    """工具目录里【创建时间】晚于本轮开始、而且文件名在本轮动作里出现过的新脚本（≥40 行）。
    until = 这一轮收尾的时间：比它还晚才建的文件不是这一轮的事（考卷 c097：回放 9/30 16:04 那一轮时，
    把 16:23 才装进来的同名文件算了进去）。实时跑的时候它就是「现在」，传不传都一样。
    只认创建时间：改已有的文件不算。要文件名在本轮动作里出现：别的会话同时在这些目录里建文件，不能算到我头上。
    超过 budget 秒就收手（有多少算多少），不让收尾被扫目录拖住。"""
    out, t0 = [], time.time()
    for root, depth in roots:
        base = os.path.expanduser(root)
        base_depth = base.rstrip("\\/").count(os.sep)
        for d, dirs, files in os.walk(base):
            if time.time() - t0 > budget:
                return out
            if d.count(os.sep) - base_depth >= depth:
                dirs[:] = []
            else:
                dirs[:] = [x for x in dirs if x.lower() not in _PRUNE]
            for f in files:
                if not (f.lower().endswith(CODE_SUFFIX) or f == "SKILL.md") or f not in mention_text:
                    continue
                p = os.path.join(d, f)
                try:
                    ct = os.stat(p).st_ctime
                    if ct < since_epoch or (until is not None and ct > until) or extends_existing_skill(p, since_epoch):
                        continue
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        if sum(1 for ln in fh if ln.strip()) < MIN_TOOL_LINES:
                            continue
                except OSError:
                    continue
                out.append(p)
    return out


def new_tool_verdict(files, channels, actions=""):
    """这一轮工具目录里多了新脚本，而最近 3 轮没查过本机以外 ⇒ (日志标签, 拦截理由)。channels 传严格通道，
    actions 传最近 3 轮的动作文本（里面有安装动作 ⇒ 文件是装来的，不拦）。"""
    if not files or external_universes(channels) or INSTALL_VERB.search(actions or ""):
        return None
    return ("BLOCK new-tool-no-search files=%s" % [os.path.basename(f) for f in files[:3]], (
        "⛔ 检索广度闸·新工具没查现成：这一轮工具目录里多了新脚本（%s），而最近 3 轮没有查过本机以外的任何地方。\n"
        "不管它是怎么放进去的（写、复制、脚本生成），建工具之前都要先看别人有没有现成的。现在补查；"
        "查到现成的更好就换掉它，查完确实没有再交付：\n%s\n"
        "这条每轮只拦一次。") % ("、".join(os.path.basename(f) for f in files[:3]), _how(EXTERNAL_US)))


# ───────────────────────── 领域级断言（收尾第 3 层）─────────────────────────
# 词表来历见 hooks/search-breadth-gate.py 开头。2026-10-02 按 9/16~10/01 的 31 次真实记账逐条看过后收窄
# （要开真拦，误拦会被 misfire_rate 一周自动降级）：
#   · 「(全部|都…)(失败|不行|没用|无效)」整类删掉：10 次误报全是「测试两次都失败」「这道拦截都抓不到」
#     「每一次都失败」这类讲自己的代码 / 测试结果的句子，0 次是领域断言。
#     「全部/统统/一律/无一 + 拿不到/下不了…」留下，但不再认单字「都」（「对 5 张单都拿不到号码」是查过的事实）。
#     2026-09-09 的真靶子（「换什么工具都一样…全部拿不到」）仍由下面两条认出。
#   · 「任何/所有/市面上…都一样」要求中间是工具类名词：「换到任何机器都一样」（某个文件 404）不算。
#   · 「给不了 / 拿不出」要求主语是来源（GitHub/开源/社区/市面上/全网）：「D-11-21 在 10/7 给不了」是订房事实。
#   · 「没有现成」前面不能是「有」：「有没有现成可以直接用的」是在问，不是在答。
#   · 「最强…是」中间不许跨「；;」：「你要最强；代价是…」不是选型断言。
#   · 单独的「当前最强」删掉：「先找现成的、选当前最强的」是复述规矩；「当前最强的是 X」仍由「最强…是」认。
#   留出集（9/01~9/15 共 2597 轮收尾，没参与调词表）又照出一批，同日再收：
#   · 「零命中 / 零成果 / 零收获」删掉：7 次全是本地 grep 的结果（「在配置里零命中」「三个 .env 都搜过，零命中」）。
#   · 「没有现成」后面要跟工具类名词：「没有现成 token」「没有现成的真实场景」「没有现成安装包」不算。
#   · 「换什么 X 都一样」X 要是工具类名词：「换什么 shell 都一样」是在讲 Bash 工具层，不是找工具。
#   · 工具类名词去掉「项目」：「你所有项目都一样」。
#   · 「列举…都没有」要求列举的是网站 / 平台：「HKCU/HKLM 注册表、代理设置里都没有」是本机检查。
#   · 「没有更好的」「一个都拿不到」排除问句复述（「有没有更好的？」）和定语（「CLI 一个都拿不到的功能」）。
#   外审（独立实例，同日）又抓出几处，修掉：
#   · 「无现成 / 找不到现成」也要跟工具类名词（「找不到现成的配置文件」）；「只能自建」要么跟工具名词、要么就在句尾
#     （「只能自建一个缓存目录」不算）；「没有更好的」要跟工具名词（「没有更好的办法，只能这样」不算）。
#   · 工具类名词去掉「服务」「办法」「路子」：「所有服务都一样要重启」「首选就是重启服务」。
#   · 反驳句「不是没有现成的工具」、问句「任何方案都不行吗？」不算。
_TOOLISH = r"(?:工具|方案|站|网站|平台|产品|软件|库|下载器|插件|模型|开源|轮子|实现|skill|app|API)"
_NOT_Q = r"(?![^，。！\n]{0,4}[吗？?])"
#   · 「最 SOTA」和「最强」一样要跟「是」：「5 个最 SOTA 的 OCR 全部部署完成」在调研后的 4 轮总结里反复出现。
#   · 「GitHub 上没有」后面要跟工具类名词：「仓库在 GitHub 上没有部署记录」。
#   · 名词搜索不跨引号（_GAP）：「说『最强/没有现成』时数的是工具」是在提词表本身。
_GAP = r"[^，。！？\n」』\"”]{0,8}"
_SITES = (r"(?:全站|全网|网站|平台|社区|市场|模型库|商店|GitHub|HuggingFace|Hugging Face|civitai|ModelScope"
          r"|PyPI|npm|Reddit|知乎|RunningHub|liblib)")
CLAIM_SRC = (
    r"(?<!有)(?<!不是)没有现成的?" + _GAP + _TOOLISH + r"|(?:无|找不到)现成的?" + _GAP + _TOOLISH
    + r"|(?:GitHub 上?|开源(?:界|里)?)没有" + _GAP + _TOOLISH + r"|只能自建(?:" + _GAP + _TOOLISH + r"|(?=[，。！；\n]|$))"
    r"|都是玩具|全是玩具|没人做过|无人做过"
    r"|(?:最强|最 ?SOTA)的?(?:[^，。！？、；;」』\"”\n是]{0,6})?(?:是|就是)|头部就是|首选就是"
    r"|(?:GitHub|开源|社区|市面上|网上|全网|官方)" + _GAP + r"(?:给不了|拿不出)|(?<!有)没有更好的" + _GAP + r"(?:" + _TOOLISH + r"|选择|选项|替代)" + _NOT_Q +
    r"|(?:全部|一个都|统统|一律|无一)(?:拿不到|下不了|取不到|抓不到)(?!的)"
    # 2026-10-02 补：考卷 c048「civitai、HuggingFace、RunningHub 全站…里都没有」（当晚被工具自己找到）、
    #   9/30「免费档里没有一家能 1:1 原样跑」—— 列举了好几个网站再说「都没有」，或「没有一家」
    r"|(?:没有|无)一家(?:能|可以|支持|有)|一家都没有"
    r"|、(?=[^，。！？\n]{0,40}" + _SITES + r")[^，。！？\n]{2,40}(?:里|上|中)都(?:没有|找不到|搜不到)"
    r"|换(?:什么|哪个|任何)\s*" + _TOOLISH + r"[^，。！？\n]{0,6}都(?:一样|不行|没用|拿不到|无效)" + _NOT_Q +
    r"|(?:任何|所有|市面上|一整类|这一类|这类)" + _GAP + _TOOLISH + r"[^，。！？\n]{0,6}(?:都|也)"
    r"(?:一样|不行|没用|拿不到|做不到|无效|撞)" + _NOT_Q)
DOMAIN_CLAIM = re.compile("(" + CLAIM_SRC + ")", re.I)
# 复述历史 / 立规矩（结构性标记，别堆「复盘」这类通用词 —— 一段真断言开头写「复盘一下」就能穿过去）
PAST_CTX = re.compile(
    r"(上一轮|(?<!动手)(?<!开工)(?<!下结论)之前|昨天|历史上|曾经|原话|引述|复述|教训|lessons|形状 ?20"
    r"|这类结论|这种结论|下次(要|再|该)下?|以后(要|再|该)下?|反向指纹)")
# 引号里的模板占位符：「最强是 X」—— 在举例，不是断言（与主判据同一份词表）
# 引号里可以并列引好几个词：「最强是 X / 没有现成的」（10-02 oldgame 原句），所以前后各放宽到 16 字
PLACEHOLDER = re.compile(r"[「『\"“][^」』\"”]{0,16}(?:" + CLAIM_SRC + r")[^」』\"”]{0,16}[」』\"”]", re.I)
METRIC_AFTER = re.compile(r"\s*(率|比例|占比|百分比|[:：]?\s*\d+(\.\d+)?\s*%)")
# 选型类断言（中英社区常给出不同第一名 ⇒ 要中英都有）
SELECT_CLAIM = re.compile(
    r"(?<!有)没有现成的?|无现成|找不到现成|GitHub 上?没有|开源(?:界|里)?没有|只能自建"
    r"|没人做过|无人做过|零命中|都是玩具|全是玩具"
    r"|最强的?(?:[^，。！？、；;\n是]{0,6})?(?:是|就是)|最 ?SOTA"
    r"|头部就是|首选就是|没有更好的", re.I)
# 会过期的选型对象（模型 / 版本）⇒ 要时间证据
SELECTION = re.compile(
    r"(embedding|模型|model)\b|"
    r"(最新|新版|旧版|过时|迭代|发布|更新)[^\n]{0,10}(模型|版本|工具)|"
    r"(轻量|更省|不降级)[^\n]{0,12}(模型|选择|方案)")
FRESHNESS = re.compile(
    r"(202[5-9]-\d{2}|最近\s*30\s*天|lastModified|last30days|"
    r"本月|上月|今年|\d+\s*天前|\d+\s*个?月前|刚发布|新发)", re.I)
# 选型判决：编号方案 ≥2 + 推荐
PLAN_CLAIM_OPTS = re.compile(r"方案\s*[0-9一二三四五六七八九十A-Fa-f]|\b[Pp]lan\s*[0-9A-Fa-f]")
PLAN_CLAIM_VERB = re.compile(r"推荐|建议|首选|先做|我选|该做|优先做|最划算|最合适|最省")
# 2026-10-02 留出集（8/15~8/31）：漫剧项目里「方案 B 千魂残影态逼格最高」「方案 3 久保带人画风」这种创作选择
#   也被当成选型判决 ⇒ 方案里得提到外部世界的东西（钱 / 平台 / 模型 / 工具…）才算要上网查的选型
PLAN_EXTERNAL = re.compile(r"美元|\$|美金|月费|价格|定价|免费额度|付费|订阅|套餐|服务商|SaaS|平台|开源|GitHub"
                           r"|API|工具|插件|软件|主机|云端|云主机", re.I)   # 不放「模型」「云」：「Diffusion 模型的联想能力」「流云长发」
PEOPLE_CH = {"last30days", "en-forum", "cn-forum", "video-community", "social", "reddit-radar"}
DOCS_CH = {"web", "web-fetch", "anysearch", "gh-search", "gh-topic", "gh-api", "pkg-index",
           "curated-list", "hf-hub", "cn-model-hub", "paper", "his-kb", "archive", "skill-index"}
CN_CH = {"cn-forum", "cn-model-hub", "his-kb", "archive"}
EN_CH = {"en-forum", "gh-search", "gh-topic", "gh-api", "pkg-index", "hf-hub", "paper", "curated-list",
         "last30days", "reddit-radar"}


def _missing_lines(us):
    return "\n".join("  · %s：%s" % (U_NAME[u], U_HOW[u]) for u in U_NAME if u not in us)


def judge(tail, channels, sizes=None, probes=None, strict=None):
    """收尾判决。tail = 本轮最后一段回复（取尾 1500 字），channels = 本轮检索通道，
    sizes = 这些检索各自回来的结果大小（拿不到就传 None），probes = 翻过的别人软件安装目录（probes_in / probes_from_ag），
    strict = 严格通道（channels_in(…, strict=True)；不传就用 channels）。返回 None（放）或 (日志标签, 拦截理由)。"""
    pv = probe_verdict(channels if strict is None else strict, probes)     # 只看事实，不看 tail 里说了什么
    if pv:
        return pv
    us = universes(channels)
    got = "、".join(U_NAME[u] for u in U_NAME if u in us) or "一个都没有"

    # 选型判决：编号方案 ≥2 + 推荐 ⇒ 3 个宇宙 + 真人社区 + 一手资料 + 时间证据
    # 2026-10-11: 排除房东/民宿运营报价语境(房费/分成/清洁费/payout等非IT技术选型)
    BIZ_PRICE_CTX = re.compile(r"房东|客人|房源|退房|入住|清洁费|分成|民宿|payout|special offer|inquiry|租金|每晚|晚数", re.I)
    if len(set(PLAN_CLAIM_OPTS.findall(tail))) >= 2 and PLAN_CLAIM_VERB.search(tail) and PLAN_EXTERNAL.search(tail) and not BIZ_PRICE_CTX.search(tail):
        lacks = []
        if len(us) < MIN_UNIVERSES:
            lacks.append("只覆盖 %d 个宇宙（要 ≥%d）" % (len(us), MIN_UNIVERSES))
        if not channels & PEOPLE_CH:
            lacks.append("没有任何真人社区源")
        if not channels & DOCS_CH:
            lacks.append("没有任何一手资料源")
        if not FRESHNESS.search(tail):
            lacks.append("整段没有时间证据")
        if lacks:
            return ("BLOCK plan-claim lacks=%s universes=%s" % (lacks, sorted(us)), (
                "⛔ 检索广度闸·选型判决：你在给几个方案下推荐，但本轮检索不够：%s（已覆盖：%s）。\n"
                "Frank 2026-09-16：「我怀疑你没用深度搜索双向核实你的答案，而是用你自己的知识库给的」。\n"
                "缺的宇宙：\n%s") % ("；".join(lacks), got, _missing_lines(us)))

    # 每处命中都看：第一处是复述历史 / 引号举例被豁免，后面的真断言照样要查（外审 10-02）
    hit = None
    for m in DOMAIN_CLAIM.finditer(tail):
        s = tail[max(0, m.start() - 80): m.end() + 80]
        if not (METRIC_AFTER.match(tail[m.end(): m.end() + 14]) or PAST_CTX.search(s) or PLACEHOLDER.search(s)):
            hit, seg = m, s
            break
    if not hit:
        return None
    claim = hit.group(0)[:20]
    # 通道都有，但每条都几乎空 ⇒ 是管道坏了，不是领域是空的（2026-09-08：十组关键词全回 0，话题页实有 69,275 个）
    if sizes and max(sizes) < 200:
        return ("BLOCK all-empty-results claim=%s n=%d max=%d" % (claim, len(sizes), max(sizes)), (
            "⛔ 检索广度闸·空管道：你用了 %d 条检索命令，每一条都几乎没返回东西（最大一条 %d 字符），就要下「%s」这个结论。\n"
            "先给查询管道跑一次阳性对照：换一个一定有结果的词。它也回 0 ⇒ 管道坏了，先修工具；它有结果 ⇒ 你的「找不到」才作数。"
        ) % (len(sizes), max(sizes), claim))
    lacks = []
    if U_LOCAL not in us:
        lacks.append("没查①本机已有（先看家里：他机器上常常早就装着）")
    if len(us) < MIN_UNIVERSES:
        lacks.append("只覆盖 %d 个宇宙（要 ≥%d）" % (len(us), MIN_UNIVERSES))
    if lacks:
        return ("BLOCK universes claim=%s universes=%s channels=%s" % (claim, sorted(us), sorted(channels)), (
            "⛔ 检索广度闸（六宇宙）：你说了「%s」这类领域级断言，但%s。本轮已覆盖：%s。\n"
            "同一个宇宙里换工具、换关键词不算（gh search + 话题页 + gh api 都是 GitHub 一个宇宙）。\n"
            "2026-08-14 实录：只搜 GitHub 就写「GitHub 给不了强货」；补上话题页、网页搜索后，同一领域从 308 个变成 7446 个，"
            "而最该先看的他本机早就装着 9 个同类 skill。\n"
            "补下面缺的宇宙再下结论：\n%s") % (claim, "；".join(lacks), got, _missing_lines(us)))
    if SELECTION.search(seg) and not FRESHNESS.search(tail):
        return ("BLOCK no-freshness claim=%s universes=%s" % (claim, sorted(us)), (
            "⛔ 检索广度闸·时效性：宇宙够了（%s），但整轮没有任何时间证据（发布日期 / 最后更新 / 最近 30 天）。\n"
            "Frank 2026-09-06：「如果这些是几年前的，这些东西还有必要去研究？」⇒ 每个候选标日期，再跑一次 last30days。"
        ) % got)
    has_cn, has_en = bool(channels & CN_CH), bool(channels & EN_CH)
    if SELECT_CLAIM.search(seg) and has_cn != has_en:
        miss = "中文" if has_en else "英文"
        return ("BLOCK single-language channels=%s" % sorted(channels), (
            "⛔ 检索广度闸·语言覆盖：宇宙够了（%s），但全是%s源、一个%s源都没有。铁律是「中英各一遍」——"
            "同一个能力，中英社区常给出完全不同的第一名。补一遍%s源：%s"
        ) % (got, "英文" if has_en else "中文", miss, miss,
             "知乎 / V2EX / 掘金 / 贴吧 / B站 / 小红书 / ModelScope，加他的知识库 brainq" if has_en else
             "GitHub(gh search + 话题页) / Reddit / HN / HuggingFace / awesome 清单"))
    return None


# ───────────────────────── 提问时提醒（第 1、2 层）─────────────────────────
# 窄触发（Frank：别天天硬塞、影响 coding）：要么问「有没有 / 哪个最好 + 工具类名词」，要么直说选型 / 替代 / 找工具。
# 不放单字「库」：「误伤记录有没有自动入库」（9/18 真实提问）；不放「项目」「API」：「有没有项目记忆」「有没有 API 文档」（外审）
_ASK_NOUN = r"(?:工具(?!函数|类|方法)|方案|开源库|软件|插件|skill|app|平台|模型|替代|现成|开源|服务|产品|网站|框架|轮子)"
FIND_ASK = re.compile(
    r"有没有[^，。？?！!\n]{0,16}" + _ASK_NOUN +
    r"|(?:哪个|哪家|哪款|什么" + _ASK_NOUN + r")[^，。？?\n]{0,4}(?:最好|最强|更好|更强|好用|靠谱|推荐)"
    r"|找(?:个|一下|下|一些|几个)?(?:现成的?|开源的?|免费的?)?(?:工具(?!函数|类|方法)|方案|替代|轮子|插件|skill)"
    r"|选型|替代方案|替代品|平替|有更好的|更强的(?:工具|方案|模型)|最 ?SOTA"
    r"|\b(?:alternatives?\s+to|best\s+(?:tool|library|way)\s+(?:to|for)|is\s+there\s+(?:a|an|any)\s+(?:tool|library|app))\b",
    re.I)
RADAR_ASK = re.compile(
    r"深挖\s*reddit|reddit[^\n]{0,8}深挖|reddit\s*radar|找(?:潜在)?(?:客户|买家|用户)|谁在找"
    r"|推广(?:版块|渠道|的?地方)|(?:在|去)哪(?:里|儿)?(?:推广|打广告|发帖)|哪(?:些|个)\s*(?:subreddit|版块)"
    r"|\bfind\s+(?:customers|leads|prospects)\b|\bwho(?:'s|\s+is)\s+looking\s+for\b", re.I)

FIND_NOTE = (
    "[六宇宙·找现成] 这句像在找工具 / 选型。下结论前按宇宙查，同一宇宙换工具、换关键词不算第二个：\n"
    + "\n".join("%s %s" % (U_NAME[u], U_HOW[u]) for u in U_NAME) +
    "\n收尾说「最强 / 没有现成 / 只能自建 / 换什么都一样」时，search-breadth-gate 数的是本轮覆盖了几个宇宙"
    "（要 ≥%d 个且含①），不够就拦。完整做法见 skill six-universes。" % MIN_UNIVERSES)
RADAR_NOTE = (
    "[深挖 Reddit] 这句是在找人 / 找推广的地方。本机装了 Reddit Radar（MCP，用户级）：\n"
    "  · 找人 / 找该回的帖子：mcp__reddit-radar__radar_scan → radar_prospects（作者、帖子链接、发帖天数、subreddit 分布；找人加 max_age_days=45）\n"
    "  · 看大家在聊什么痛点：同一次扫描 → radar_results（按主题聚类）\n"
    "  · 代价：每次约 $0.15（花的是他的钥匙）、会弹出 Chrome、1000 条约 3 分钟 ⇒ 跑之前跟 Frank 说一声费用。\n"
    "  · 只要最近 30 天口碑、不要找人 ⇒ 先用免费的 last30days。")


def prompt_notes(prompt):
    """提问时要注入的提醒（可能 0~2 段）。"""
    p = prompt or ""
    out = []
    if RADAR_ASK.search(p):
        out.append(RADAR_NOTE)
    if FIND_ASK.search(p):
        out.append(FIND_NOTE)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    bad = []
    def ok(name, cond):
        print(("✓ " if cond else "✗ ") + name)
        cond or bad.append(name)
    GH = {"gh-search", "gh-topic", "gh-api"}
    ok("GitHub 三件套只算 1 个宇宙", universes(GH) == {U_GH})
    ok("GitHub 三件套 + 断言 ⇒ 拦", judge("这个方向 GitHub 上没有现成的方案。", GH) is not None)
    ok("本机 + GitHub + 网页 + 中文社区 ⇒ 放", judge("这个方向没有现成的方案。", GH | {"skill-index", "web", "cn-forum"}) is None)
    ok("本机 + GitHub + 网页但只有英文 ⇒ 拦（中英各一遍）", judge("这个方向没有现成的方案。", GH | {"skill-index", "web"}) is not None)
    ok("三个外部宇宙但没查本机 ⇒ 拦", judge("这个方向没有现成的方案。", GH | {"web", "last30days"}) is not None)
    ok("「有没有现成」是在问 ⇒ 不算断言", DOMAIN_CLAIM.search("国风卡通渲染在网页上有没有现成可以直接用的") is None)
    ok("「测试两次都失败」不算断言", DOMAIN_CLAIM.search("对 AI 模型两次都失败。") is None)
    ok("「给不了」订房事实不算", DOMAIN_CLAIM.search("D-11-21 在 10/7–10/10 给不了") is None)
    ok("「GitHub 给不了强货」算", DOMAIN_CLAIM.search("这三环 GitHub 给不了强货") is not None)
    ok("「换什么工具都一样」算", DOMAIN_CLAIM.search("所以我换什么工具都一样") is not None)
    ok("「你要最强；代价是」不算", DOMAIN_CLAIM.search("你要最强；代价是显卡占用更高") is None)
    ok("Glob 扫 skills 算本机", "skill-index" in channels_of("Glob", json.dumps({"pattern": "*", "path": "C:/Users/<username>\\.claude\\skills"})))
    ok("Read 一个 skill 文件不算本机", "skill-index" not in channels_of("Read", json.dumps({"file_path": "C:/Users/<username>\\.claude\\skills\\x\\SKILL.md"})))
    ok("Reddit Radar MCP 算口碑", universes(channels_of("mcp__reddit-radar__radar_scan", "{}")) == {U_VOICE})
    ok("提问「有没有更好的下载工具」⇒ 提醒", prompt_notes("有没有更好的抖音下载工具？"))
    ok("提问「哪个模型最强」⇒ 提醒", prompt_notes("现在生视频哪个模型最强"))
    ok("提问「有没有报错」⇒ 不提醒", not prompt_notes("刚才跑完有没有报错？"))
    ok("提问「改一下这个函数」⇒ 不提醒", not prompt_notes("把 judge 函数改一下，加个参数"))
    ok("提问「找客户」⇒ Radar 提醒", any("Reddit Radar" in n for n in prompt_notes("帮我在 Reddit 找客户，谁在找 Airbnb 管理工具")))
    # 外审 10-02 给的误拦 / 漏拦句子
    # 「首选就是重启服务」仍会命中：「首选就是 <名字>」从字面分不开，4440 轮真实留出集里它 0 次误拦，留着
    for s in ("找不到现成的配置文件", "这里只能自建一个缓存目录", "没有更好的办法，只能这样",
              "不是没有现成的工具，是你没找", "所有服务都一样要重启", "任何方案都不行吗？"):
        ok("不算断言：" + s, not any(not PAST_CTX.search(s) for _ in DOMAIN_CLAIM.finditer(s)))
    ok("算断言：这三环只能自建。", DOMAIN_CLAIM.search("这三环只能自建。") is not None)
    ok("第一处是复述、后面真断言仍拦",
       judge("上一轮我说过最强的是 A。\n" + "x" * 200 + "\n查完了，这个方向没有现成的工具。", set()) is not None)
    ok("「动手之前」不算复述", judge("动手之前我看了一下，没有现成的工具。", set()) is not None)
    ok("Edit 参数里写 gh search 不算检索", not channels_of("Edit", json.dumps({"new_string": "gh search repos x reddit.com"})))
    for s in ("有没有 API 文档", "有没有项目记忆", "帮我找一下工具函数在哪"):
        ok("提问不提醒：" + s, not prompt_notes(s))
    ok("「谁需要重启服务」不出 Radar", not any("深挖" in n for n in prompt_notes("谁需要重启服务")))
    # 2026-10-04 只看事实的几条（含外审 12 条里的对抗样本）
    AGS = "C:/Users/<username>\\.gemini\\antigravity\\scripts\\__probe_not_exist__.py"
    U = {"type": "user", "message": {"content": "修一下"}}
    def T(name, inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}
    def B(cmd):
        return T("Bash", {"command": cmd})
    ok("AG 脚本目录算工具落点", is_tool_dest(AGS))
    ok("~/.claude/bin、skills、根下的 web.py 算工具落点", is_tool_dest("~/.claude/bin/x.py") and is_tool_dest("/c/Users/<username>/.claude/skills/a/s.py") and is_tool_dest("C:/Users/<username>\\.claude\\web.py"))
    ok("项目里的脚本、~/.claude 下的记忆文件不算工具落点", not is_tool_dest("D:\\airbnb ai manager\\scripts\\x.py") and not is_tool_dest("C:/Users/<username>\\.claude\\projects\\p\\memory\\a.md"))
    ok("工具落点 + 零检索 ⇒ 拦", tool_dest_verdict(AGS, [U]) is not None)
    ok("工具落点 + 只在本机 grep ⇒ 拦", tool_dest_verdict(AGS, [U, T("Grep", {"pattern": "desktop"})]) is not None)
    ok("工具落点 + 只翻聊天档案 ⇒ 拦", tool_dest_verdict(AGS, [U, B("node D:/chat-archive/q.js x")]) is not None)
    ok("工具落点 + web.py 搜过 ⇒ 放", tool_dest_verdict(AGS, [U, B('py -3 ~/.claude/web.py search "exebox"')]) is None)
    ok("工具落点 + 上一轮 gh search ⇒ 放", tool_dest_verdict(AGS, [U, B("gh search code exebox"), U]) is None)
    ok("工具落点 + gh.exe 带路径带引号的写法 ⇒ 放", tool_dest_verdict(AGS, [U, B('"C:\\Program Files\\GitHub CLI\\gh.exe" search repos x')]) is None)
    ok("工具落点 + 四轮前搜的 ⇒ 拦", tool_dest_verdict(AGS, [U, T("WebSearch", {"query": "x"}), U, U, U]) is not None)
    ok("读不到会话记录 ⇒ 放（判不了不卡人）", tool_dest_verdict(AGS, []) is None and tool_dest_verdict(AGS, None) is None)
    for fake in (T("Grep", {"pattern": "weixin"}), T("Grep", {"pattern": "topic:"}), B("grep -rn reddit.com ."),
                 B("node D:/chat-archive/q.js v2ex"), B("echo medium.com"), B("pip install foo -i https://pypi.org/simple"),
                 T("Glob", {"pattern": "**/awesome-*"}), T("Bash", {"command": "ls", "description": "search reddit.com with curl"})):
        ok("本机动作不冒充联网 ⇒ 拦：" + json.dumps(fake["message"]["content"][0]["input"], ensure_ascii=False)[:50],
           tool_dest_verdict(AGS, [U, fake]) is not None)
    ok("curl 真去取 reddit ⇒ 放", tool_dest_verdict(AGS, [U, B('curl -s "https://www.reddit.com/r/x/search.json?q=y"')]) is None)
    AGDIR = "/c/Users/<username>/AppData/Local/Programs/antigravity/resources/bin"
    def PB(cmd):
        return probe_of("Bash", json.dumps({"command": cmd}))
    def PP(cmd):
        return probe_of("PowerShell", json.dumps({"command": cmd}))
    ok("cd 到安装目录再 grep ⇒ 算拆", PB('cd "%s" && grep -rl -a exebox .' % AGDIR))
    ok("grep 直接指向安装目录 ⇒ 算拆", PB('grep -rl exebox "C:/Users/<username>\\AppData\\Local\\Programs\\antigravity"'))
    ok("$env:LOCALAPPDATA 写法 ⇒ 算拆", PP('Select-String -Path "$env:LOCALAPPDATA\\Programs\\antigravity\\resources\\x.js" -Pattern exebox'))
    ok("Read 安装目录里的文件 ⇒ 算拆", probe_of("Read", json.dumps({"file_path": "C:\\Program Files\\Obsidian\\resources\\app.asar"})))
    for cmd in ('& "C:/Users/<username>\\AppData\\Local\\Programs\\Obsidian\\Obsidian.com" help',
                '& "C:/Users/<username>\\AppData\\Local\\Programs\\Obsidian\\Obsidian.com" help | Select-String cli',
                '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --version | findstr 1',
                '"C:\\Program Files\\GitHub CLI\\gh.exe" search repos x | grep star',
                '"C:/Users/<username>\\AppData\\Local\\Programs\\Ollama\\ollama.exe" list | findstr qwen',
                '"C:/Users/<username>\\AppData\\Local\\Programs\\Microsoft VS Code\\bin\\code" --list-extensions | grep py',
                '"C:\\Program Files\\Git\\bin\\bash.exe" -c "grep -n x a.py"',
                'C:/Users/<username>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe x.py | grep y'):
        ok("启动程序 / 开发工具链 + 过滤输出 ⇒ 不算拆：" + cmd[:44], not PP(cmd))
    ok("动词只在 description 里 ⇒ 不算拆", not probe_of("Bash", json.dumps({"command": 'ls "C:\\Program Files\\Obsidian"', "description": "grep it"})))
    ok("Read JDK / Windows Kits 头文件 ⇒ 不算拆", not probe_of("Read", json.dumps({"file_path": "C:\\Program Files\\Java\\jdk-21\\include\\jni.h"}))
       and not probe_of("Read", json.dumps({"file_path": "C:\\Program Files (x86)\\Windows Kits\\10\\Include\\x.h"})))
    ok("在自己仓库里 Grep 一个写着 Program Files 的字符串 ⇒ 不算拆", not probe_of("Grep", json.dumps({"pattern": "Program Files\\\\Foo", "path": "D:\\proj"})))
    ok("Read 自己项目里的 app.asar ⇒ 不算拆", not probe_of("Read", json.dumps({"file_path": "D:\\proj\\dist\\win-unpacked\\resources\\app.asar"})))
    ok("拆了 + 零外部 ⇒ 拦", probe_verdict(set(), ["Programs/antigravity"]) is not None)
    ok("拆了 + 只有一个外部宇宙 ⇒ 拦", probe_verdict({"web-fetch", "archive"}, ["Programs/antigravity"]) is not None)
    ok("拆了 + 网页 + GitHub ⇒ 放", probe_verdict({"web-fetch", "gh-search"}, ["Programs/antigravity"]) is None)
    ok("没拆 ⇒ 不管", probe_verdict(set(), []) is None)
    ok("judge 带 probes：拆了零外部 ⇒ 拦（不看措辞）", judge("查完了，根因在这。", set(), None, ["Programs/antigravity"]) is not None)
    ok("judge 不带 probes ⇒ 行为不变", judge("查完了，根因在这。", set()) is None)
    ok("judge 用严格通道：两条本机 grep 凑不出两个外部宇宙", judge("根因在这。", {"cn-forum", "gh-topic"}, None, ["Programs/x"], set()) is not None)
    # 考卷 c090 / c097：扩已有技能、安装别人的技能，都不是造新工具
    RH = os.path.expanduser("~/.claude/skills/runninghub")
    if os.path.isdir(RH):
        ok("往已有技能里加脚本 + 零检索 ⇒ 不拦", tool_dest_verdict(os.path.join(RH, "scripts", "__new_helper__.sh"), [U]) is None)
    ok("全新的技能目录 + 零检索 ⇒ 拦", tool_dest_verdict(os.path.expanduser("~/.claude/skills/__nope_not_exist__/scripts/a.py"), [U]) is not None)
    ok("这几轮有 git clone ⇒ 不拦（装别人的）", tool_dest_verdict(os.path.expanduser("~/.claude/skills/__nope_not_exist__/scripts/a.py"),
                                                    [U, B("git clone https://github.com/x/watch ~/.claude/skills/watch")]) is None)
    ok("AG 脚本目录是平的：新文件就是新工具", tool_dest_verdict(AGS, [U]) is not None)
    import tempfile
    tr = tempfile.mkdtemp(prefix="su_tools_")
    new_py = os.path.join(tr, "show_on_desktop.py")
    with open(new_py, "w", encoding="utf-8") as fh:
        fh.write("\n".join("x%d = 1" % i for i in range(60)))
    with open(os.path.join(tr, "tiny.py"), "w", encoding="utf-8") as fh:
        fh.write("x = 1\n")
    roots = ((tr, 2),)
    ok("收尾兜底：本轮多出的 60 行脚本、动作里提到过 ⇒ 认出", new_tool_files(time.time() - 60, "robocopy src dst show_on_desktop.py tiny.py", roots=roots) == [new_py])
    ok("收尾兜底：动作里没提到这个文件名（别的会话建的）⇒ 不认", not new_tool_files(time.time() - 60, "ls", roots=roots))
    ok("收尾兜底：创建时间早于本轮 ⇒ 不认", not new_tool_files(time.time() + 60, "show_on_desktop.py", roots=roots))
    ok("收尾兜底：这一轮收尾之后才建的 ⇒ 不认", not new_tool_files(time.time() - 600, "show_on_desktop.py", roots=roots, until=time.time() - 300))
    ok("收尾兜底：有新工具 + 零外部 ⇒ 拦；查过 ⇒ 放", new_tool_verdict([new_py], set()) is not None and new_tool_verdict([new_py], {"web-fetch"}) is None)
    ok("收尾兜底：这几轮有安装动作 ⇒ 放", new_tool_verdict([new_py], set(), "npx skills add x/watch") is None)
    ok("路径换算：/c/…、%USERPROFILE%、~ 都指到同一个地方", local_path("/c/Users/x/a.py") == os.path.normpath("C:/Users/x/a.py")
       and local_path("%USERPROFILE%\\a.py") == local_path("~/a.py") == local_path("$env:UserProfile\\a.py"))
    print("全过" if not bad else "失败 %d 项" % len(bad))
    sys.exit(1 if bad else 0)
