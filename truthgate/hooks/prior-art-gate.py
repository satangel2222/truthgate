#!/usr/bin/env python3
"""prior-art-gate — PreToolUse hook

2026-07-27 真实翻车：零搜索写了 skills-origin.mjs(100+行)，
后来搜 GitHub 发现 xingkongliang/skills-manager ★3363 已在做同一件事。

判据：新建代码文件（≥40行）之前，必须有相关搜索。
  搜过且相关 → allow；没搜 / 搜过但无关 → deny
Fail-open：输入烂掉一律 allow。

⛔ 2026-10-04 分成两档（Frank「授权这里修复」，来历见 ~/.truthgate/six_universes.py「只看事实的三条」）：
  · 真拦（只看事实）：落点是工具目录（~/.claude/bin|skills|scripts、AG 的 scripts / skills…），
    而最近 3 轮没有查过本机以外的任何宇宙。本机 grep / 翻档案不算；web.py、gh search、网页抓取算。
    判据在 six_universes.tool_dest_verdict，和收尾的 search-breadth-gate 认的是同一份通道表。
  · 只记账：其余情况下的老判据（搜没搜过 + 搜的词和文件名像不像）。「像不像」靠词面 / 语义猜，
    9 月记账里误拦的都是它（搜了 15 次仍被说「主题不相关」），所以只写日志、不拦，输出里带 softDeny。
  同一个漏洞的另一半（先写在临时目录再复制进工具目录）由 shell-writes-code-gate 管。
"""
import json, re, sys, os
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.truthgate"))
try:
    import six_universes as _su
except Exception:            # 共用判据坏了 ⇒ 没有真拦那一档，整道闸退回只记账
    _su = None
HARD = {"on": False}         # 本次判决是不是「只看事实」那一档（main 用它决定真拦还是只记账）

SEARCH_TOOLS = {"WebSearch", "WebFetch", "mcp__weixin_reader__read_weixin_article"}
SEARCH_BASH_RE = re.compile(
    r"gh\s+search\s+repos|"
    r"gh\s+api\s+search|"
    r"gh\s+search\s+code|"
    r"grep\s+-\w*\s|"
    r"rg\s+-\w*\s|"
    r"find\s+",
    re.IGNORECASE,
)

MIN_LINES = 40
SAFE_DIRS = {
    "Temp", "temp", "tmp", ".claude-worktrees",
    "__pycache__", "node_modules", ".git",
    "test_", "tests/", "_test.", ".test.",
}
HOOKS_DIR = Path(__file__).parent
STOPWORDS = {
    "test","tests","tmp","temp","new","old","backup","probe","debug",
    "gen","util","helper","lib","src","dist","build","copy",
    "index","main","app","cli","api","core","base","common",
    "page","gpt","load","perf",
}


def _words(s):
    """取词面单元:ASCII 单词 + CJK 字 bigram。

    ⛔⛔ 2026-09-06 修的真 bug:原来只写 `re.findall(r"[a-z]+", ...)` —— **只抓 ASCII 字母**。
       而我的搜索词大部分是中文:「免费 embedding 向量模型」只剩下 `embedding`;
       纯中文的「反爬 绕检测」直接变成**空集** ⇒ q_words 为空 ⇒ 恒判无关 ⇒ **恒拦**。
       这不是"语义不够",是词面提取本身把中文整个丢了。
       CJK 按【字 bigram】取,和服务端 `RECALL_LEX_LAMBDA` 那套词面覆盖同一个思路。
    """
    s = (s or "").lower()
    w = set(re.findall(r"[a-z]+", s))
    cjk = re.findall(r"[一-鿿]+", s)
    for run in cjk:
        if len(run) == 1:
            w.add(run)
        else:
            w.update(run[i:i + 2] for i in range(len(run) - 1))
    return w


def _sem_related(query, file_path, content="", thresh=0.33, timeout=6.0):
    """词面比不出来时,问语义:这次搜索和我要写的东西是不是同一个主题?

    ⛔ 为什么必须有它(2026-09-06 普查):接线在跑的 83 道闸里 **61 道是纯正则**,
       而正则判「主题相不相关」天生不行 —— 同一个主题我可以用完全不重叠的词:
         搜「反爬 绕检测」→ 写 `stealth_fetch.py`(零词重叠,词面必判无关)
         搜「free embedding API」→ 写 `向量召回.py`
       每补一个同义词,下次换一个说法立刻逃逸(同形状:promise-gate 5/5 全漏)。

    ⛔ 方向是【放行】(把词面误判的"无关"救回来)⇒ 判据必须保守:
       · 只在词面已判"无关"之后才问它,不改变任何已经放行的路径;
       · 服务挂/超时/异常 → False = 保持原判(拦),绝不因为语义层抽风而放宽。

    ⛔⛔ 阈值 0.33 是【量出来的,不是猜的】(2026-09-06,5 条该救 + 6 条该拦的对照):
       我第一版猜 0.42,而该救回的样本最高才 0.317 ⇒ **语义层等于完全没在工作**。
       更关键的是【拿什么去比】:
         只用文件名        → 该救最低 0.209 / 该拦最高 0.173,间隙 **0.036**(刀锋)
         文件名 + docstring → 该救最低 0.367 / 该拦最高 0.201,间隙 **0.166**(宽 4.6 倍)
       文件名才两三个词,几乎没有语义可比;而 `tool_input["content"]` 开头那段
       docstring 正是"这文件干嘛的",信息量高一个量级。
       ⇒ 通用判据:**语义比不开时,先问"我拿去比的东西信息量够吗",别急着调阈值。**
    """
    if not query:
        return False
    try:
        import urllib.request as _u
        base = "http://127.0.0.1:17911"
        try:
            sys.path.insert(0, str(Path.home() / ".claude"))
            from superego_port import BASE as base       # 端口的唯一出处
        except Exception:
            pass

        def emb(t):
            b = json.dumps({"text": t[:2000]}).encode("utf-8")
            r = _u.Request(base + "/embed", b, {"Content-Type": "application/json"})
            return json.loads(_u.urlopen(r, timeout=timeout).read())["embedding"]

        name = Path(file_path).stem.replace("-", " ").replace("_", " ")
        # 文件名 + 开头那段(docstring/注释)= "这文件干嘛的",信息量比光看文件名高一个量级
        target = (name + "。" + (content or "")[:800]).strip()
        v1, v2 = emb(query), emb(target)
        return sum(a * b for a, b in zip(v1, v2)) >= thresh   # 服务端已归一化
    except Exception:
        return False


def query_relevant(query, file_path):
    """query词 和 file 词是否相关。

    匹配条件：
    1. 精确匹配
    2. 复数/单数匹配（skills ~ skill）
    3. file词 包含 query词（搜"pageperf" → 写pageperf相关），而非反过来
    4. ⛔ 2026-09-06 新增：以上词面全不中时，问语义（见 _sem_related）
    """
    if not query:
        return False
    q_words = _words(query)
    f_words = _words(Path(file_path).stem)
    if not f_words or not q_words:
        return False
    MIN_SUBSTR = 4  # 子串匹配最短长度

    def _sg(w):
        return w[:-1] if w.endswith("s") and len(w) > 2 else w

    for qw in q_words:
        for fw in f_words:
            sq, sf = _sg(qw), _sg(fw)
            # 精确或单数化相等
            if qw == fw or sq == sf:
                return True
            # file词 包含 query词（单向，且 query词 >= 4 字符防止短词误匹配）
            if len(qw) >= MIN_SUBSTR and len(fw) >= MIN_SUBSTR and qw in fw:
                return True
    return False


def read_transcript(path):
    out = []
    try:
        for l in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if l.strip():
                try:
                    out.append(json.loads(l))
                except Exception:      # 最后一行可能正写到一半：丢这一行，别把整份读成空
                    pass
    except Exception:
        return []
    return out


def check(tool_name, tool_input, messages):
    if tool_name != "Write":
        return "allow", ""

    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    if not file_path:
        return "allow", ""

    p = Path(file_path)

    # hook 自身修改 → allow
    # ⛔⛔ 2026-09-05 修【相对路径把豁免撑破】(Frank 授权彻查 superego 时挖出):
    #   原写法 `Path(file_path).resolve()` 对**相对路径**是拿【当前工作目录】补全的。
    #   于是同一个 `lib/dbpool.py`:在别处跑 → deny(正确);而【从 hooks/ 目录跑】→
    #   被补成 ~/.claude/hooks/lib/dbpool.py → 落进 HOOKS_DIR 豁免 → **无条件放行**。
    #   实测:test_prior_art_falseblock.py 就在 hooks/ 下跑,4 次调用全部拿到 63 字节的
    #   `{"permissionDecision":"allow"}`,两条「该拦」的对抗样本长期假红,而闸本身没错 ——
    #   **错的是「豁免判定依赖调用者当时站在哪个目录」**。
    #   ⛔ 可迁移:任何拿路径做【安全豁免】的判据,只认【绝对路径】;相对路径一律不给豁免
    #   (放行方向的判据必须最保守 —— 判错就是开洞)。
    try:
        _fp = Path(file_path)
        if _fp.is_absolute() and HOOKS_DIR in _fp.resolve().parents and ".py" in file_path:
            return "allow", ""
    except Exception:
        pass

    # 豁免目录
    try:
        rel = p.relative_to(Path.home())
    except Exception:
        rel = p
    if any(s in str(rel).split(os.sep) for s in SAFE_DIRS):
        return "allow", ""

    # 非脚本文件 → allow（SKILL.md 在 skills/ 下除外）
    suffix = p.suffix.lower()
    is_skill_md = (
        suffix == ".md" and ".claude" + os.sep + "skills" in str(rel)
    )
    if suffix not in {".py",".js",".mjs",".cjs",".sh",".ps1",".bat",".cmd",".ts",".tsx",".jsx",".go",".rs",".rb"} and not is_skill_md:
        return "allow", ""

    # 行数不足 → allow
    lines = [l for l in content.splitlines() if l.strip()]
    if len(lines) < MIN_LINES:
        return "allow", ""

    # 2026-10-04 工具落点：只看事实，不看「像不像」
    if _su is not None and _su.is_tool_dest(file_path) and not os.path.exists(_su.local_path(file_path)):
        why = _su.tool_dest_verdict(file_path, messages)
        if why:
            HARD["on"] = True
            return "deny", why + (
                "\n（2026-07-27 同一个形状：零搜索写了 skills-origin.mjs，"
                "GitHub 上 xingkongliang/skills-manager ★3363 早在做同一件事。）")

    # 收集搜索动作
    # ⛔⛔ 2026-09-05 接上共享的轮次边界(Frank 授权彻查 superego 时补):
    #   原来遍历【整份 transcript】,于是**上一轮、甚至几天前的搜索也算成"我这轮查过了"** ——
    #   一次搜索能给后面无数次新建文件发通行证,这道闸就等于只在会话第一次生效。
    #   `turn_start_index` 是 6 道闸共用的那一份(本轮起点 = 最后一条真人消息),
    #   别再各写各的:它们原本各写一遍、且全都漏了"通知"这一类消息。
    #   ⛔ 收紧方向的改动,不会造成误伤放宽;拿不到共享函数时退回原行为(fail-open 不改语义)。
    try:
        import sys as _sys
        _sys.path.insert(0, str(HOOKS_DIR))
        from guard_common import turn_start_index
        _start = turn_start_index(messages)
        if _start >= 0:
            messages = messages[_start:]
    except Exception:
        pass
    searches = []
    for m in messages:
        if m.get("type") != "assistant":
            continue
        msg = m.get("message", {})
        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, str):
            content_blocks = [{"type": "text", "text": content_blocks}]
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input") or {}
            cmd = str(inp)

            if name in SEARCH_TOOLS:
                q = inp.get("query", "") or inp.get("url", "") or ""
                searches.append(("web", q))
            elif name in ("Bash", "PowerShell") and _su is not None and _su.external_universes(
                    _su.channels_of(name, json.dumps(inp, ensure_ascii=False))):
                searches.append(("web", str(inp.get("command", ""))))   # web.py search / r.jina.ai / gh search…
            elif name == "Bash" and SEARCH_BASH_RE.search(cmd):
                searches.append(("bash", cmd))
            elif name == "Grep":
                q = inp.get("pattern", "") or inp.get("path", "") or ""
                searches.append(("grep", q))
            elif name == "Glob":
                q = inp.get("pattern", "") or ""
                searches.append(("glob", q))

    if not searches:
        reason = (
            "你要新建代码文件但本轮没有任何搜索动作。\n"
            "2026-07-27 真实教训：零搜索写了 skills-origin.mjs(100+行)，\n"
            "后来一搜 GitHub 发现 xingkongliang/skills-manager 已在做同一件事。\n"
            "正确做法：先 WebSearch 或 gh search repos 确认没有现成的再写。"
        )
        return "deny", reason

    # 搜过但主题无关
    has_relevant = any(
        (stype == "web" and query_relevant(q, file_path)) or
        (stype in ("bash", "grep") and query_relevant(q, file_path))
        for stype, q in searches
    )
    # ⛔ 词面全判"无关"时,再问一次语义 —— 治「搜的和写的是同一主题、但用词零重叠」。
    #   只在这个分支问(已放行的路径一律不碰);最多问 3 次,别把 PreToolUse 拖慢。
    #   语义层不可用 → _sem_related 恒 False → 行为与接线前完全一致。
    if not has_relevant:
        has_relevant = any(_sem_related(q, file_path, content)
                           for _, q in searches[:3] if q)
    if not has_relevant:
        searched_queries = [q for _, q in searches if q][:3]
        reason = (
            f"你搜过 {len(searches)} 次，但搜索词「{searched_queries[0] if searched_queries else '?'}」"
            f"与文件名「{p.name}」主题不相关。\n"
            "2026-07-27 真实教训：搜 h264 却写 skills-origin.mjs，\n"
            "同一晚 GitHub 就有 skills-manager。\n"
            "搜索词必须和要写的东西同主题。"
        )
        return "deny", reason

    return "allow", ""


def main():
    data = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    messages = data.get("messages", [])  # PreToolUse 直接传 messages

    # transcript_path → 仅当 messages 为空时读文件
    tp = data.get("transcript_path")
    if tp and not messages:
        messages = read_transcript(tp)

    decision, reason = check(tool_name, tool_input, messages)

    if decision == "deny" and not HARD["on"]:
        # 只记账那一档：写日志，放行；softDeny 给测试 / 考卷看它本来的结论
        try:
            sys.path.insert(0, str(HOOKS_DIR))
            from guard_common import hook_log
            hook_log("prior-art-gate", "WOULDBLOCK(soft)", re.sub(r"\s+", " ", reason)[:140])
        except Exception:
            pass
        print(json.dumps({"permissionDecision": "allow", "permissionDecisionReason": "",
                          "softDeny": reason}, ensure_ascii=False))
        sys.exit(0)

    if decision == "deny":
        sys.stderr.write(reason)
        print(
            json.dumps(
                {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                        "additionalContext": reason,
                    },
                },
                ensure_ascii=False,
            )
        )
        # ⛔ 2026-10-04 外审：原来只在 JSON 顶层写 permissionDecision、退出码 0 —— Claude Code 不认这个写法。
        #   近 60 份会话里这道闸判过 5 次 deny，5 次 Write 都是 File created successfully：它从来没真拦住过。
        #   退出码 2 + stderr 是所有版本都认的拦法（shell-writes-code-gate 一直这么写）。
        sys.exit(2)
    else:
        print(
            json.dumps(
                {
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "",
                },
                ensure_ascii=False,
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
