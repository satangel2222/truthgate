#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""网页对照闸(PreToolUse:Edit|Write|MultiEdit)—— 平台刚拒绝过你、你还没在真浏览器里亲眼看过那条流程,就不许改跟网页打交道的代码。

⛔ 病(Frank 2026-10-05,airbnb 项目,原话):
   「我怀疑你…就是没测试过浏览器用截图看整个流程导致的,只是底层用代码去猜,明明都点错了或者被拒了却不懂,
     又或者出现验证又不理,死死去做。所以你必须先登出后再登入,利用浏览器自动化去做一步一步看分析」
   「我说的用浏览器的那套方法来做测试,为何 truth gate 里不使有吗?还是没有?」
   现场:Booking 自动登录回 `"need": "sms"`、取电话接口回 `400 general_error`,我没打开真浏览器看一眼,
   直接改代码:先接一整套「短信码从 TG 收」,又加重试和退避,前后改了十几次、让平台给他手机发了 6 条短信。
   后来被逼着在真浏览器里一步步截图走了一遍,10 分钟看到两件页面上一眼可见的事
   (登录页有新旧两版、右下角有 Switch versions;取电话被拒是因为页面要求先验证身份)。

⛔ 为什么 reference-diff-guard 全放行(当天跑 32 次、32 次放行,不改它,另建这道):
   它只数「同一条工具调用连着失败 ≥3 次」—— 这次的失败在【产品输出】里(退出码 0、JSON 里写着 need=sms);
   它只在收尾看;收尾文字带「成功」就免拦。⇒ 前提都对不上。这道闸的前提正好相反:
   **不看我报不报成功,只看「平台拒绝过我」之后、我改网页相关代码之前,有没有真的看过页面。**

判据(三条同时成立才拦,只看事实不看措辞):
  1. 有拒绝证据:最近(3 小时内)Bash/PowerShell【运行输出】里出现平台拒绝的字样(need_login / SESSION_DEAD / "need":"sms" /
     mfa / captcha / 400·401·403·409·429 状态 / 短信码 / 掉登录 …)。localhost 自己服务的错不算。
     ⛔ 读代码 / 读文档 / 跑测试 / 查聊天档案 / 看 --help 的输出不算证据 —— 实测这天 scan 里 8 成「证据」是这类
        (sed 一段含 captcha 的代码、rg 搜 SESSION_DEAD)。判据贴着【平台真的回了什么】,不贴【屏幕上出现了这个词】。
  2. 这次要改的是代码文件(.py .js .ts .cjs .mjs .ps1 .sh),路径或写入内容里有网页交互的痕迹(http/cookie/login/fetch/token/…)。
     不拦文档、测试、故障注入、scratchpad / 临时目录里的探针脚本(它们正是拿去截图的)、TruthGate 自己的闸。
  3. 拒绝证据之后还没看过:要【既有】一次浏览器截图动作(命令里有 opencli/playwright/camoufox/… 且带 screenshot,
     或运行输出里有 Screenshot saved / 截图),【又有】在它之后(含同一步)Read 读了图片文件。只截不读不算;
     读的是拒绝证据之前的旧图不算 —— 图片文件还在的话,修改时间必须晚于拒绝证据。

出口只有一个:确实没有网页对照物(纯后端接口、对方没有任何网页界面)⇒ 同一轮回复里单独写一行
   `无网页对照物:<具体原因>`。原因为空、是占位符、或只是「不需要」之类 ⇒ 不算。

有界:同一段拒绝证据最多拦 MAX_BLOCKS=2 次(已拦次数直接从转录里数 —— 拦截提示会以 is_error 结果落进转录、带本闸名),
   第 3 次放行并记 DEGRADED。证据之后一旦「看过」,到下一段新证据出现前都不再拦(新证据 = 更晚的一条)。
fail-open:任何异常放行并记日志。自测:python web-walk-gate.py --selftest
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, _load_tail_raw, turn_start_index, _text_of
except Exception:                                         # noqa: BLE001
    def hook_log(name, msg, ctx=""):
        pass

    def _load_tail_raw(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def _text_of(c):
        return c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))

NAME = "web-walk-gate"
MAX_BLOCKS = 2
EVIDENCE_TTL = 3 * 3600          # 拒绝证据超过 3 小时就不再追着人(早已翻篇;逐 3 小时的窗也让转录尾部 4MB 够用)
SHELL = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")

# ── 关 2:改的是什么 ────────────────────────────────────────────────────────────
CODE_EXT = re.compile(r"\.(?:py|js|ts|cjs|mjs|ps1|sh)$", re.I)
EXEMPT_PATH = re.compile(
    r"[\\/]scratchpad[\\/]|[\\/]tmp[\\/]|[\\/]temp[\\/]|AppData[\\/]Local[\\/]Temp"          # 探针脚本 / 临时目录
    r"|[\\/]\.(?:truthgate|claude)[\\/](?:hooks|semantic|exam)[\\/]"                          # 闸自己(内容全是 token/http 这类词)
    r"|(?:^|[\\/])(?:tests?|__tests__|faults?)[\\/]|(?:^|[\\/])(?:test_|fault_)[^\\/]*$"      # 测试 / 故障注入
    r"|[._-](?:test|spec)\.\w+$|selftest", re.I)
WEB_RE = re.compile(
    r"https?://|cookie|log[_-]?in\b|sign[_-]?in|fetch|httpx|requests|aiohttp|urllib|axios|playwright|camoufox|cloakbrowser"
    r"|puppeteer|selenium|opencli|selector|csrf|xsrf|token|session|headers|referer|retry|backoff|\botp\b|\bsms\b|\bmfa\b"
    r"|captcha|\.goto\(|\.fill\(|\.click\(", re.I)

# ── 关 1:什么算平台的拒绝证据 ───────────────────────────────────────────────────
_HTTP_BAD = r"(?:400|401|403|409|429)"
EV_RE = re.compile(
    r"\\?\"need\\?\"\s*:\s*\\?\"(?:sms|otp|mfa|2fa|captcha|login|verify|verification)\\?\""
    r"|\bneed_login\b|\bSESSION_DEAD\b|\bapi_reject\b|\bgeneral_error\b|\bmfa\b|captcha|verification code"
    r"|sign[ -]?in failed|unauthori[sz]ed|\bchallenge\b"
    r"|HTTP/\d(?:\.\d)?\s+" + _HTTP_BAD + r"\b"
    r"|\bstatus(?:[_ ]?code)?[\"']?\s*[:=]\s*" + _HTTP_BAD + r"\b"
    r"|\b" + _HTTP_BAD + r"\s+(?:Bad Request|Unauthorized|Forbidden|Conflict|Too Many Requests)\b"
    r"|(?:Client Error|HTTPError)\W{0,6}" + _HTTP_BAD + r"\b"
    r"|短信码|验证码|被拒|掉登录", re.I)
LOCAL_LINE = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]", re.I)
CJK = re.compile(r"[\u4e00-\u9fff]")
JSON_KEY = re.compile(r"\\?\"\w+\\?\"\s*:")
SRC_LINE = re.compile(r"^\s*(?:(?:[^\s:]{1,80}:)?\d{1,5}[:|\t]\s|#|//|/\*|\*\s|<!--"
                      r"|(?:def|class|function|async|const|let|var|return|import|from|if|elif|else|for|while|try|except|raise|await)\b.*[({;=]"
                      r"|[A-Za-z_][\w.]*\(.*\)[;,]?\s*$)")        # 整行只是一个函数调用 `_die("SESSION_DEAD")` = 源码(跑脚本 && sed 混在一条命令里时分不出来)

# 这些命令的输出【不是平台回的话】:读代码/文档、跑测试、查聊天档案、看 --help
READ = frozenset(("sed awk rg grep egrep fgrep cat head tail nl less more wc ls dir find type get-content gc select-string sls "
                  "cut sort uniq tr tee jq stat file diff cmp fd get-childitem gci test-path get-item").split())
NEUTRAL = frozenset("cd set-location set echo printf date sleep true pwd export write-host start-sleep [ [[ test".split())
GIT_READ = frozenset("log diff show grep blame status stash branch ls-files rev-parse config remote".split())
TESTRUN = re.compile(r"(?<![A-Za-z])test_\w+|\w*selftest\w*|\w+_test\b|\.test\.|\.spec\.|pytest|unittest|--self-?test"
                     r"|npm\s+(?:run\s+)?test|node\s+--test|fault[-_]\w+|[\\/]faults?[\\/]", re.I)
ARCHIVE = re.compile(r"chat-archive|(?:^|[\s\\/\"'])q(?:-\w+)?\.js|brainq|ag_archive|vault_log|obsidian|web\.py\s+search|easy_anysearch"
                     r"|[\\/]\.(?:truthgate|claude)\b|hook-stats", re.I)
HELP = re.compile(r"(?:^|\s)(?:--help|-h|--version)(?:\s|$)")
DATA_PATH = re.compile(r"\.(?:log|jsonl|ndjson|out|err|har)\b|[\\/]logs?[\\/]", re.I)   # 读日志/数据 = 读产品输出,不排除

# ── 关 3:看过没有 ──────────────────────────────────────────────────────────────
IMG_EXT = re.compile(r"\.(?:png|jpe?g|webp)$", re.I)
BROWSER_RE = re.compile(r"opencli|playwright|camoufox|chromium|puppeteer|cloakbrowser|selenium|patchright|browser-act|scrapling", re.I)
SHOT_RE = re.compile(r"screenshot", re.I)
SHOT_OUT = re.compile(r"Screenshot saved|截图", re.I)

# ── 出口 ───────────────────────────────────────────────────────────────────────
EXEMPT_RE = re.compile(r"无网页对照物\s*[::]\s*(.+)")
WEAK_REASON = re.compile(r"^(?:不需要|无需|不用|不必|没必要|没有|无|没|略|其他|其它|不适用|同上|见上|n/?a|none)[\w ,，。]{0,6}$", re.I)   # 「不需要」「没有网页对照」这类只有一句话的


def _segments(cmd):
    """按 ; && || | 换行切命令,引号里的不切(rg -n "a|b" 不能被劈开)。"""
    out, cur, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur.append(ch)
        elif ch in ";\n|" or cmd[i:i + 2] == "&&":
            out.append("".join(cur))
            cur = []
            if cmd[i:i + 2] in ("&&", "||"):
                i += 1
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _verb(seg):
    seg = re.sub(r"^(?:[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\S*)\s+)+", "", seg)      # 前缀的 VAR=值
    if re.match(r"^[A-Za-z_]\w*=", seg):
        return "set"                                                                  # 纯赋值段
    tok = re.split(r"\s+", seg, maxsplit=1)[0].strip("\"'")
    return re.sub(r"\.exe$", "", os.path.basename(tok.replace("\\", "/")).lower())


def _reader_only(cmd):
    """整条命令只是在读文件 / 搜文件(至少有一个读类动词,其余都是 cd/echo 这类不产出的)。"""
    seen = False
    for s in _segments(cmd):
        s = re.sub(r"^(?:do|then|else|elif|if|while|until|!|\{|\()\s+", "", s)             # for … do rg …; done 里的 rg 照样是读
        v = _verb(s)
        if v in NEUTRAL or v in ("for", "done", "fi", "esac", "}", ")"):
            continue
        if v == "git":
            m = re.match(r"git\s+(?:-C\s+\S+\s+)?([\w-]+)", s)
            if m and m.group(1) in GIT_READ:
                seen = True
                continue
            return False
        if v in READ:
            seen = True
            continue
        return False
    return seen


def not_remote(cmd):
    """这条命令的输出不可能是「远端平台回的话」。"""
    return bool(HELP.search(cmd) or TESTRUN.search(cmd) or ARCHIVE.search(cmd)
                or (_reader_only(cmd) and not DATA_PATH.search(cmd)))


def evidence_in(text):
    """输出里第一处【平台真回了拒绝】的字样,回 (摘要, 命中的整行);没有回 ("", "")。
    命中词只是「屏幕上出现了这个词」的几种情形都不算 —— 2026-10-05 回放 27 次拦里 7 次是这几类(逐条看过命中行):
      localhost 自己服务的错;带行号的代码清单(`81:  _die("SESSION_DEAD")`)和代码 / 注释行;
      词长在文件名里(challenge.js、auto-mfa-1.png);整行中文说明文字(笔记里写「被拒」「SESSION_DEAD」)。"""
    for m in EV_RE.finditer(text):
        a = text.rfind("\n", 0, m.start()) + 1
        b = text.find("\n", m.end())
        line, ms = text[a:len(text) if b < 0 else b], m.start() - a
        if LOCAL_LINE.search(line) or SRC_LINE.match(line) or (len(CJK.findall(line)) >= 14 and not JSON_KEY.search(line)):
            continue
        ta = max(line.rfind(c, 0, ms) for c in " \t\"'(,") + 1
        tb = min([i for i in (line.find(c, ms) for c in " \t\"')(,") if i >= 0] or [len(line)])
        tok = line[ta:tb]
        if "://" not in tok and re.search(r"\.[A-Za-z]{2,4}$", tok):          # 文件名里的词;URL 里的不算文件名
            continue
        s = max(0, m.start() - 50)
        return " ".join(text[s:m.end() + 60].split()), line.strip()[:200]
    return "", ""


def _epoch(ts):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:                                     # noqa: BLE001
        return None


def analyse(msgs):
    """一遍扫完转录,回 {ev: 最晚一条拒绝证据, shots: 截图动作的下标, views: [(下标, 路径)], denials: 本闸拦过的下标}。"""
    uses, st = {}, {"ev": None, "shots": [], "views": [], "denials": []}
    for i, m in enumerate(msgs):
        c = (m.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for x in c:
            if not isinstance(x, dict):
                continue
            k, t = x.get("type"), m.get("type")
            if t == "assistant" and k == "tool_use":
                nm, inp = str(x.get("name") or ""), x.get("input") or {}
                uses[x.get("id")] = (nm, inp)
                cmd = str(inp.get("command") or "")
                if nm == "Read" and IMG_EXT.search(str(inp.get("file_path") or "")):
                    st["views"].append((i, str(inp.get("file_path"))))
                elif nm in SHELL and BROWSER_RE.search(cmd) and SHOT_RE.search(cmd) and not HELP.search(cmd) and not _reader_only(cmd):
                    st["shots"].append(i)
                elif nm.startswith("mcp__") and SHOT_RE.search(nm + json.dumps(inp, ensure_ascii=False)):
                    st["shots"].append(i)                  # 浏览器类 MCP 的截图:图直接回到我眼前 = 截 + 看一步完成
                    st["views"].append((i, ""))
            elif t == "user" and k == "tool_result":
                s = x.get("content")
                s = s if isinstance(s, str) else _text_of(s)
                if x.get("is_error") and NAME in s:
                    st["denials"].append(i)
                    continue
                if re.match(r"\s*(?:Pre|Post)ToolUse", s):
                    continue
                nm, inp = uses.get(x.get("tool_use_id"), ("", {}))
                cmd = str(inp.get("command") or "")
                if nm not in SHELL or not_remote(cmd):
                    continue
                if SHOT_OUT.search(s):
                    st["shots"].append(i)
                hit, line = evidence_in(s)
                if hit:
                    st["ev"] = {"i": i, "id": x.get("tool_use_id") or str(i), "ts": _epoch(m.get("timestamp")), "snip": hit,
                                "cmd": " ".join(cmd.split())[:80], "line": line, "cmdfull": cmd[:700]}
    return st


def _fresh(path, ev_ts):
    """这张图是不是拒绝证据【之后】才生成/改过。文件找不到(已删 / 别的机器)就只按顺序判。"""
    if not path or ev_ts is None:
        return True
    try:
        return os.path.getmtime(path) >= ev_ts - 2
    except OSError:
        return True


def viewed(st):
    ev = st["ev"]
    shots = [s for s in st["shots"] if s > ev["i"]]
    if not shots:
        return False
    s0 = min(shots)
    return any(i >= s0 and _fresh(p, ev["ts"]) for i, p in st["views"])


def exempt_reason(msgs):
    """同一轮(自最后一条真人消息起)的助手文字里,有没有一行「无网页对照物:<具体原因>」。"""
    start = turn_start_index(msgs)
    for m in msgs[start + 1:] if start >= 0 else msgs:
        c = (m.get("message") or {}).get("content")
        if m.get("type") != "assistant" or not isinstance(c, list):
            continue
        for x in c:
            if not (isinstance(x, dict) and x.get("type") == "text"):
                continue
            for mm in EXEMPT_RE.finditer(x.get("text") or ""):
                r = mm.group(1).strip(" *`_>「」\"'。.!!")
                if len(r) >= 6 and not WEAK_REASON.match(r) and "具体原因" not in r:
                    return r
    return ""


def written(tool, inp):
    if tool == "Write":
        return str(inp.get("content") or "")
    if tool == "Edit":
        return str(inp.get("new_string") or "")
    return "\n".join(str(e.get("new_string") or "") for e in (inp.get("edits") or []) if isinstance(e, dict))


def decide(tool, inp, get_msgs, now=None, extra_blocks=0):
    """回 (verdict, info)。verdict: allow / block / exempt / degraded。
    get_msgs 是个函数:前两关(改的是什么)过不了就不去读转录。extra_blocks 给回放用(转录里没有真被拦过的痕迹)。"""
    if tool not in EDIT_TOOLS:
        return "allow", {}
    path = str(inp.get("file_path") or "")
    if not CODE_EXT.search(path) or EXEMPT_PATH.search(path):
        return "allow", {}
    if not WEB_RE.search(path + "\n" + written(tool, inp)):
        return "allow", {}
    msgs = get_msgs() or []
    st = analyse(msgs)
    ev = st["ev"]
    if not ev or (now is not None and ev["ts"] is not None and now - ev["ts"] > EVIDENCE_TTL):
        return "allow", {}
    if viewed(st):
        return "allow", {}
    info = {"path": path, "ev": ev}
    why = exempt_reason(msgs)
    if why:
        return "exempt", dict(info, why=why)
    n = sum(1 for d in st["denials"] if d > ev["i"]) + extra_blocks
    if n >= MAX_BLOCKS:
        return "degraded", dict(info, n=n)
    return "block", dict(info, n=n + 1)


def reason(info):
    ev = info["ev"]
    return "\n".join([
        "⛔ 网页对照闸(web-walk-gate):平台刚拒绝过你,你还没在真浏览器里亲眼看过那条流程,就要去改跟网页打交道的代码 —— 先别改。",
        "   刚才的拒绝:%s    (来自命令:%s)" % (ev["snip"][:110], ev["cmd"]),
        "   要改的文件:%s(第 %d/%d 次拦)" % (info["path"], info["n"], MAX_BLOCKS),
        "按这四步走:",
        "① 在真浏览器里把这条流程从头走一遍(涉及登录 / 验证的,先登出、再从头登入),每一步截图,并且自己用 Read 把那张图看一遍。",
        "   本机现成:opencli(复用 Frank 已登录的 Chrome:自己起一个会话,用完 close,不动别人的标签)——",
        "     opencli browser <自己起的名字> open <网址> ;  ... screenshot <文件.png> ;  ... close      选工具先读 ~/.claude/browser-routing.md",
        "   ⛔ 别碰 CDP 9226 / 9555(那是别的自动化专用的浏览器)。",
        "② 看页面上有没有代码里没处理的东西:别的入口 / 新旧版本切换 / 要先验证身份的提示 / 报错浮层。",
        "③ 把浏览器真发出去的那条请求录下来(... network),跟项目里发的那条逐项比:地址、请求头、cookie、参数。",
        "④ 看完再改代码,并在回复里写清:页面上看到了什么、跟代码原来的假设差在哪。",
        "(由来:2026-10-05 Booking 回 need=sms、取电话回 400,没打开浏览器看一眼就连改十几次、让平台给他手机发了 6 条短信;真浏览器走一遍 10 分钟,两件事在页面上一眼可见。)",
        "唯一出口:这件事确实没有网页对照物(纯后端接口、对方没有任何网页界面)⇒ 在回复里单独写一行  无网页对照物:<具体原因>  再重试。原因写「不需要」之类不放行。",
    ])


def self_test():
    ok = bad = 0

    def T(c, name):
        nonlocal ok, bad
        if c:
            ok += 1
        else:
            bad += 1
            print("  ✗", name)

    def U(t="继续"):
        return {"type": "user", "message": {"content": t}}

    def AT(t):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}

    def USE(i, name, inp):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}

    def RES(i, t, err=False):
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": t, "is_error": err}]}}

    EVO = '{"ok": false, "need": "sms", "url": "https://auth.booking.com/u/mfa-sms-challenge?state=x"}'

    def ran(i="e1", cmd="py -3.12 scripts/bk_cli.py probe", out=EVO):
        return [USE(i, "Bash", {"command": cmd}), RES(i, out)]

    def shot(i="s1", cmd='opencli browser bk open "https://x" && opencli browser bk screenshot /tmp/a.png'):
        return [USE(i, "Bash", {"command": cmd}), RES(i, "ok")]

    def read(p="D:/p/shots/a.png"):
        return [USE("r" + p[-6:], "Read", {"file_path": p}), RES("r" + p[-6:], "(image)")]

    EDIT = ("Edit", {"file_path": "D:/proj/scripts/booking_login.py", "new_string": "r = requests.post(url, headers=h, cookies=ck)\nif sms: retry()"})

    def V(msgs, edit=EDIT, **kw):
        return decide(edit[0], edit[1], lambda: msgs, **kw)[0]
    base = [U("修登录")]
    T(V(base + ran()) == "block", "有 need=sms 证据、没截图没读图、改 booking_login.py ⇒ 拦")
    T(V(base + ran() + shot()) == "block", "只截图、没 Read 图 ⇒ 仍拦")
    T(V(base + ran() + read() + shot()) == "block", "先读了张旧图、之后才截图(没再读)⇒ 仍拦")
    T(V(base + read() + ran() + shot()) == "block", "证据【之前】读的旧图 ⇒ 仍拦")
    T(V(base + shot() + read() + ran()) == "block", "截图和读图都发生在拒绝证据【之前】⇒ 仍拦")
    T(V(base + ran() + shot() + read()) == "allow", "证据之后:截图 + Read 图 ⇒ 放行")
    T(V(base + ran() + shot() + read() + ran("e2")) == "block", "看过之后又来一段新拒绝证据 ⇒ 再拦")
    T(V(base + ran() + shot() + read() + ran("e2") + shot("s2") + read("D:/p/shots/b.png")) == "allow", "新证据之后又看过 ⇒ 放行")
    T(V(base + ran(out='{"error":"HTTP 500"} GET http://127.0.0.1:8890/api -> status: 401')) == "allow", "localhost 自己服务的 401 ⇒ 不算证据,放行")
    T(V(base + ran(out="all good")) == "allow", "没有任何拒绝证据 ⇒ 放行")
    # 下面几条的输出样本刻意【不会被行级规则放过】(没有行号 / 不是注释 / 不是整行中文)——只有命令级的排除能放过它,
    # 这样把命令级排除删掉时测试才会红(故障注入实测:原先的样本被行级规则抢先放过,删了命令级排除测试照样绿 = 测不到)
    T(V(base + ran(cmd="sed -n 100,140p scripts/booking_login.py", out="返回 SESSION_DEAD 就重登")) == "allow", "证据只出现在【读代码】的输出里 ⇒ 不算,放行")
    T(V(base + ran(cmd='rg -o "need_login|captcha" scripts/', out="need_login")) == "allow", "rg 搜代码命中 ⇒ 不算证据")
    T(V(base + ran(cmd='for f in a.py b.py; do echo "== $f"; head -25 scripts/$f | rg -v "^import"; done 2>&1 | head -50',
                   out="== a.py\nneed_login\n== b.py")) == "allow", "for 循环里读文档/代码 ⇒ 仍认成纯读,不算证据")
    # 命中词只是屏幕上出现的词、不是平台回的话:各一条
    for nm, out in (("文件名里的词(challenge.js)", "813729 字节  challenge.js   路径 0"), ("文件名里的词(auto-mfa-1.png)", "18:15:29 35752 auto-mfa-1.png"),
                    ("带行号的代码清单", '81:        _die("SESSION_DEAD")'), ("代码注释行", "# ⛔ 这里不再自己重登,原来会话一死就走验证码路"),
                    ("整行只是一个函数调用", '        _die("SESSION_DEAD")'),
                    ("整行中文说明文字", "几分钟内 Booking 把整个登录会话踢了(20:36 同步还正常、20:41 那轮卡在 Booking;探活 SESSION_DEAD,首页跳登录页),")):
        T(V(base + ran(cmd="py -3.12 scratch.py && sed -n 1,9p x.py", out=out)) == "allow", "混合命令里的「" + nm + "」⇒ 不算证据")
    for nm, out in (("JSON 里的 SESSION_DEAD", '{"__err": "SESSION_DEAD"}'), ("转义后的 need=sms", '{"lastErr":"{\\"ok\\": false, \\"need\\": \\"sms\\"}"}'),
                    ("JSON 里的 status 400", '  "withCsrf": {\n   "status": 400,\n   "body": "x"'), ("URL 里的 mfa-sms-challenge", "https://auth.booking.com/u/mfa-sms-challenge?state=abc"),
                    ("JSON 里带中文的错误文本", '{"ok": false, "err": "Booking 要手机短信验证码 —— 等了 330 秒没收到你回的码(这次的码作废)"}')):
        T(V(base + ran(out=out)) == "block", "真输出「" + nm + "」⇒ 仍算证据")
    T(V(base + ran(cmd="py -3.12 scripts/test_bk_phones.py", out="✅ 14/14 不带就 5/5 张回 400 general_error")) == "allow", "跑测试输出里的字样 ⇒ 不算证据")
    T(V(base + ran(cmd="node q-window.js 2026-10-01 booking", out="他说:验证码被拒了")) == "allow", "查聊天档案的输出 ⇒ 不算证据")
    T(V(base + ran(cmd="opencli browser x get --help", out="Options:\n  --retry   retry on unauthorized responses")) == "allow", "--help 输出 ⇒ 不算证据")
    T(V(base + ran(cmd='tail -5 "$TEMP/bk_live.log"', out='{"need": "sms"}')) == "block", "读【日志】= 读产品输出,仍算证据 ⇒ 拦")
    for p in ("D:/p/README.md", "D:/p/notes.txt", "D:/p/cfg.json"):
        T(V(base + ran(), edit=("Write", {"file_path": p, "content": "requests cookie 掉登录"})) == "allow", "改文档/配置 %s ⇒ 放行" % p[-10:])
    T(V(base + ran(), edit=("Write", {"file_path": r"C:\Users\x\AppData\Local\Temp\claude\p\s\scratchpad\probe.py", "content": "import requests"})) == "allow",
      "scratchpad 里的探针脚本 ⇒ 放行")
    T(V(base + ran(), edit=("Edit", {"file_path": "D:/p/scripts/test_bk_heal.js", "new_string": "fetch(url)"})) == "allow", "测试文件 ⇒ 放行")
    T(V(base + ran(), edit=("Edit", {"file_path": "D:/p/scripts/faults/fault_x.py", "new_string": "requests.get(u)"})) == "allow", "故障注入文件 ⇒ 放行")
    T(V(base + ran(), edit=("Edit", {"file_path": "D:/p/lib/math.js", "new_string": "return a + b"})) == "allow", "改的东西跟网页无关 ⇒ 放行")
    T(V(base + ran(), edit=("Edit", {"file_path": "/home/u/.truthgate/hooks/x-gate.py", "new_string": "token session http://"})) == "allow", "TruthGate 自己的闸 ⇒ 放行")
    T(V(base + ran(), edit=("MultiEdit", {"file_path": "D:/p/a.js", "edits": [{"new_string": "x"}, {"new_string": "await fetch(url, {headers})"}]})) == "block", "MultiEdit 里有网页痕迹 ⇒ 拦")
    T(V(base + ran(), edit=("Bash", {"command": "echo requests"})) == "allow", "不是 Edit/Write ⇒ 放行")
    T(V(base + ran() + [AT("无网页对照物:纯后端的内部定时任务接口,对方没有任何网页界面")]) == "exempt", "写了「无网页对照物:具体原因」⇒ 放行")
    T(V(base + ran() + [AT("无网页对照物:不需要")]) == "block", "原因只是「不需要」⇒ 仍拦")
    T(V(base + ran() + [AT("无网页对照物:<具体原因>")]) == "block", "原因是占位符 ⇒ 仍拦")
    # 长度已够 6 字、只有弱原因 / 占位符规则能拒的两条(只靠「不到 6 字」拒的样本测不到这两条规则 —— 故障注入实测抓出)
    T(V(base + ran() + [AT("无网页对照物:不需要看网页对照物")]) == "block", "「不需要……」一句话原因(够 6 字)⇒ 仍拦")
    T(V(base + ran() + [AT("无网页对照物:<填具体原因>")]) == "block", "占位符加了字(够 6 字)⇒ 仍拦")
    T(V(base + ran() + [AT("无网页对照物:后端接口")]) == "block", "原因只有 4 个字、说不出具体是什么 ⇒ 仍拦")
    T(V(base + ran() + [AT("无网页对照物:不需要,因为这是纯后端的内部定时任务,对方没有网页")]) == "exempt", "「不需要」后面真给了原因 ⇒ 放行")
    T(V(base + ran() + [AT("无网页对照物:")]) == "block", "原因为空 ⇒ 仍拦")
    T(V([U("上一轮"), AT("无网页对照物:纯后端的内部定时任务接口,对方没有任何网页界面"), U("新一轮")] + ran()) == "block", "上一轮写的出口不算 ⇒ 仍拦")
    d1, d2 = RES("d1", "PreToolUse:Edit hook error: [python web-walk-gate.py]: ⛔ 网页对照闸", True), RES("d2", "PreToolUse:Edit hook error: [python web-walk-gate.py]: ⛔", True)
    T(V(base + ran() + [d1]) == "block", "已拦 1 次 ⇒ 还拦")
    r2 = decide(EDIT[0], EDIT[1], lambda: base + ran() + [d1])
    T(r2[1].get("n") == 2, "已拦 1 次 ⇒ 这是第 2 次")
    T(V(base + ran() + [d1, d2]) == "degraded", "拦满 2 次 ⇒ 第 3 次放行(DEGRADED)")
    T(V(base + [d1, d2] + ran("e3")) == "block", "旧证据的拦截次数不带到新证据上 ⇒ 新一段重新数")
    T(V(base + ran(), extra_blocks=2) == "degraded", "回放用的 extra_blocks 也受上限约束")
    T(V(base + ran(out='HTTP/1.1 403 Forbidden')) == "block", "HTTP 403 状态行 ⇒ 算证据")
    T(V(base + ran(out='Traceback ... requests.exceptions.HTTPError: 429 Client Error: Too Many Requests')) == "block", "429 ⇒ 算证据")
    T(V(base + ran(out='版本号 v1.403 / 订单 4001 / 价格 4090')) == "allow", "数字里碰巧带 403/401 ⇒ 不算证据")
    # 图片新旧:截图靠【运行输出里的「截图」】认,Read 的是旧文件 ⇒ 不算;新文件 ⇒ 算
    import tempfile
    d = tempfile.mkdtemp()
    old, new = os.path.join(d, "old.png"), os.path.join(d, "new.png")
    for f in (old, new):
        open(f, "wb").write(b"x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))
    e_ts = ran()
    e_ts[1]["timestamp"] = ts
    out_shot = [USE("s9", "Bash", {"command": "py scripts/login.py"}), RES("s9", "截图 old.png")]
    T(V(base + e_ts + out_shot + read(old)) == "block", "输出里有「截图」但 Read 的是证据之前就存在的旧文件 ⇒ 仍拦")
    T(V(base + e_ts + out_shot + read(new)) == "allow", "输出里有「截图」且 Read 的是证据之后生成的新文件 ⇒ 放行")
    mcp = [USE("m1", "mcp__browser__take_screenshot", {}), RES("m1", "(image)")]
    T(V(base + ran() + mcp) == "allow", "浏览器类 MCP 的截图(图直接回来)⇒ 放行")
    old_ev = ran()
    old_ev[1]["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5 * 3600))
    T(V(base + old_ev, now=time.time()) == "allow", "拒绝证据已过 3 小时 ⇒ 不再追")
    T(V(base + ran(cmd="cat scripts/x.py && curl -s https://api.example.com/login", out="HTTP/2 401 Unauthorized")) == "block", "读 + 真发请求混在一条命令里 ⇒ 不算纯读,证据成立")
    T(_reader_only('rg -n "a|b" scripts/ | head') is True, "引号里的 | 不把 rg 命令劈开,整条仍认成纯读")
    # 端到端:真 stdin + 真转录文件,fail-open 与退出码
    import subprocess
    import tempfile as tf
    tp = os.path.join(tf.mkdtemp(), "t.jsonl")
    with open(tp, "w", encoding="utf-8") as f:
        for m in base + ran():
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    payload = json.dumps({"tool_name": EDIT[0], "tool_input": EDIT[1], "transcript_path": tp, "session_id": "s"})

    def run(inp, **env):
        r = subprocess.run([sys.executable, os.path.abspath(__file__)], input=inp, capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, SUPEREGO_LOG_DIR=tf.mkdtemp(), PYTHONIOENCODING="utf-8", **env))
        return r
    r = run(payload)
    T(r.returncode == 2 and '"permissionDecision": "deny"' in r.stdout and "web-walk-gate" in r.stderr, "端到端:真 stdin 进、拦截 JSON + 退出码 2")
    T(run("not json").returncode == 0 and run("").returncode == 0, "垃圾输入 ⇒ fail-open 放行")
    T(run(json.dumps({"tool_name": "Edit", "tool_input": EDIT[1], "transcript_path": "Z:/nope.jsonl"})).returncode == 0, "转录读不到 ⇒ fail-open 放行")
    T(run(json.dumps({"tool_name": "Edit", "tool_input": "不是字典", "transcript_path": tp})).returncode == 0, "内部抛异常(tool_input 不是字典)⇒ fail-open 放行")
    T("第 1/2 次拦" in reason({"path": "p", "n": 1, "ev": {"snip": "s", "cmd": "c"}}) and "opencli" in reason({"path": "p", "n": 1, "ev": {"snip": "s", "cmd": "c"}})
      and "9226" in reason({"path": "p", "n": 1, "ev": {"snip": "s", "cmd": "c"}}) and "无网页对照物" in reason({"path": "p", "n": 1, "ev": {"snip": "s", "cmd": "c"}}),
      "拦截提示点出四步、opencli、9226/9555 红线和唯一出口")
    print("web-walk-gate self-test %d/%d %s" % (ok, ok + bad, "OK" if not bad else "FAIL"))
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv or "--selftest" in sys.argv:
        return self_test()
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:                                     # noqa: BLE001
        return 0
    try:
        tool, inp = data.get("tool_name"), data.get("tool_input") or {}
        tp = data.get("transcript_path")
        verdict, info = decide(tool, inp, lambda: _load_tail_raw(tp) if tp else [], now=time.time())
        if verdict == "allow":
            return 0
        ctx = "文件=%s | 证据=%s" % (os.path.basename(info["path"]), info["ev"]["snip"])
        if verdict == "exempt":
            hook_log(NAME, "EXEMPT(无网页对照物:%s)" % info["why"][:60], ctx)
            return 0
        if verdict == "degraded":
            hook_log(NAME, "DEGRADED(同一段证据已拦 %d 次到顶,这次放行)" % info["n"], ctx)
            return 0
        hook_log(NAME, "BLOCK(第 %d/%d 次)" % (info["n"], MAX_BLOCKS), ctx)
        why = reason(info)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}, ensure_ascii=False))
        sys.stderr.write(why + "\n")
        return 2
    except Exception as e:                                # noqa: BLE001
        try:
            hook_log(NAME, "ERROR(fail-open) %s" % type(e).__name__, str(e)[:100])
        except Exception:                                 # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:                                     # noqa: BLE001
        pass
    sys.exit(main())
