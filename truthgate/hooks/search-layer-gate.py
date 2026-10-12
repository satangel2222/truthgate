#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""search-layer-gate — PreToolUse:在我【搜索发出之前】拦,不是犯完错才提醒。

⛔ 来历(2026-08-14,Frank:「所以这个教训没让你免疫和进化做事吗?」):
   lessons.md 第 40 行两周前就钉死了铁律 ——
   「搜『有没有现成的』时,关键词必须至少覆盖三层:①产品名 ②能力名(中英各一遍) ③同源姊妹产品」
   今天照犯:Frank 说 dramalink,我只 `gh search "dramalink"`(仅第①层),而且只在 GitHub 一个宇宙里搜
   —— 它其实是**闭源商业平台**(上海君弈禾远,$59/月),GitHub 上永远搜不到。

⛔ 那条铁律为什么没起作用(实测,不是猜):
   ① 只存在于 lessons.md(3848 行),CLAUDE.md 明写"平时不占上下文";
   ② 133 个 hook 里没有一个检查"搜索覆盖了几层";
   ③ 语义召回按【Frank 的消息】检索 —— 他说 dramalink(话题),我需要的是"检索方法"(方法论),
      语义不相关 ⇒ 召回捞不到;
   ④ 最后是 `已查过闸` 在我发 WebFetch 时顶出来的 —— **在我犯完错之后**。
   ⇒ 抗体来晚了。所以本闸放在 PreToolUse。

⛔ 先查现成(2026-08-14):WebSearch「claude code hook 搜索关键词覆盖度」→ 只有 IP 管控/通用安全护栏,
   无此判据的现成实现 ⇒ **只能自建**。

⚠️ 设计纪律(来自 lessons.md:185 我自己的教训):
   「关键字/标记型防御**必带上下文豁免**」—— 否则我一在文档/代码里描述这道闸抓什么词就自触发。
   本闸的豁免:①查询里含能力词 ②本轮已做过能力层检索 ③查询是 URL/路径 ④明显在做打靶/测试。
"""
import json
import re
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "search-layer-gate.log"

# 能力词(第②层的标志) —— 中英各一批。查询里出现任一 ⇒ 说明已经在按能力搜,放行
# ⛔ 2026-08-14 打靶发现的漏词:原表只有动词类(生成/转换/制作),漏了【领域能力名词】——
#    「小说转短剧剧本 工具」这种一眼就是能力层的查询竟然识别不出来,靶3 误伤。
#    补:小说/剧本/短剧/漫剧/视频/图片/语音…这类"要什么能力"的名词。
CAP_WORDS = re.compile(
    r"(生成|转换|转成|制作|创作|写作|改编|拆解|分镜|剪辑|合成|识别|转录|翻译|抓取|部署|流水线|全流程"
    # ⛔ 别加 工具|平台|方案 这类【泛用后缀】——加了以后「dramalink 工具」就会被当成能力层放行,
    #    而它明明还是只搜产品名。只收真正表达"要什么能力"的名词。(2026-08-14 当场抓到,已拿掉)
    r"|小说|网文|剧本|编剧|短剧|漫剧|漫画|视频|图片|配音|语音|字幕|成片"
    # ⛔ 英文能力词必须带词边界 \b —— 否则子串会命中产品名本身。
    #    2026-08-14 实测:我加了 `drama`,而 `dramalink` 里就含 drama ⇒
    #    **这道专为 dramalink 建的闸,恰恰放行了 dramalink**。三个靶同时红,就是这一个原因。
    r"|\b(generate|generation|convert|pipeline|workflow|agent|studio|editor|render"
    r"|automat\w*|extract|transcri\w*|translat\w*|scrape|deploy|framework"
    r"|novel|script|screenplay|drama|comic|video|audio|subtitle|storyboard)\b"
    r"|to[\s_-]?video|to[\s_-]?script)", re.I)

# 上下文豁免:这些出现在查询里 ⇒ 不是"找现成",别拦
EXEMPT_Q = re.compile(r"^(https?://|/|[A-Za-z]:\\)|测试|打靶|回归|靶子|self[\s_-]?test", re.I)

SEARCH_TOOLS = {"WebSearch"}
BASH_SEARCH = re.compile(r"\bgh\s+search\s+repos?\b|\bgh\s+api\s+.*search/repositories", re.I)


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def looks_like_bare_product_name(q):
    """像不像【只用产品名】在搜:短、没有能力词、分词数<=2。"""
    q = (q or "").strip().strip('"').strip("'")
    if not q or len(q) > 30:
        return False
    if CAP_WORDS.search(q) or EXEMPT_Q.search(q):
        return False
    core = re.sub(r"(github|开源|官网|是什么|怎么样|下载|安装|repo)", " ", q, flags=re.I)
    toks = [t for t in re.split(r"[\s,，、_/+\-]+", core) if t]
    return len(toks) <= 2


def extract_query(tool, inp):
    if tool == "WebSearch":
        return inp.get("query") or ""
    cmd = inp.get("command") or ""
    m = re.search(r'gh\s+search\s+repos?\s+(?:"([^"]+)"|\'([^\']+)\'|([^\s\-]\S*))', cmd)
    if m:
        return m.group(1) or m.group(2) or m.group(3) or ""
    m = re.search(r'[?&]q=([^&"\'\s]+)', cmd)
    return m.group(1) if m else ""


def turn_already_searched_capability(tp):
    """本轮是否已经发过【带能力词】的检索 —— 有就说明我在补层了,放行。"""
    if not tp or not Path(tp).exists():
        return True                      # 拿不到证据就放行,绝不挡路
    try:
        sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        st = turn_start_index(msgs)
        for m in (msgs[st:] if st >= 0 else msgs):
            if m.get("type") != "assistant":
                continue
            for c in ((m.get("message") or {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                    if CAP_WORDS.search(blob):
                        return True
        return False
    except Exception:
        return True


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    if tool not in SEARCH_TOOLS:
        if tool != "Bash" or not BASH_SEARCH.search(inp.get("command") or ""):
            return 0

    q = extract_query(tool, inp)
    if not looks_like_bare_product_name(q):
        _log("pass(not bare name): %s" % (q or "")[:40])
        return 0
    if turn_already_searched_capability(data.get("transcript_path")):
        _log("pass(capability layer covered): %s" % q[:40])
        return 0

    _log("DENY bare-name search: %s" % q[:40])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "⛔ 检索分层闸:你只用【产品名】「%s」在搜 —— 这是 lessons.md 第 40 行两周前钉死的坑。\n"
                "铁律原文:关键词必须至少覆盖三层 ①产品名 ②**能力名(中英各一遍)** ③**同源姊妹产品**。\n"
                "  · 实录1(豆包):只搜产品名,同公司同后端的剪映/CapCut/飞书妙记全被扫在外面。\n"
                "  · 实录2(dramalink,今天):只搜产品名+只在 GitHub 搜 ⇒ 零命中;\n"
                "    实际是**闭源商业平台**(上海君弈禾远,$59/月无限 tokens),GitHub 上永远搜不到。\n"
                "⛔ 今天新补的第四层:**它可能根本不在 GitHub**。「选型=选开源」是我自己加的前提,\n"
                "  Frank 从没这么要求 —— 这领域最强的一批(阿里万镜一刻/字节火山剧创/百度Hogee/\n"
                "  360纳米漫剧/Seko)全是闭源商业产品。\n"
                "现在补:再发一次【能力名】查询(如「小说转短剧剧本」/「novel to screenplay」/「短剧全流程」),\n"
                "并先判断这东西属于哪个宇宙(开源仓库/商业产品/App/小程序),再下结论。"
            ) % q[:24]
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
