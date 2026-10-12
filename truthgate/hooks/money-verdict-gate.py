#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""money-verdict-gate — 拦【用单一数据源，就对"做什么能赚钱"下判决】。

⛔ 来历(2026-08-22, Frank:「凡是变现优先…所有宇宙加我雷达交叉,凡是涉及这个最重要的
   事情需要交叉验证那个才是真相答案,因为前面一但错了,一步错步步错,后面做得再好也
   变现不了,浪费时间和成本」):
   我刚接上 trendsmcp(YouTube 搜索热度),拿【一个 API 的一个指标】就写出
   「系统流=红海别进 / multisub=真蓝海该抢」,画成表交付。
   而搜索热度高 != 有人付费看 != RPM 高 != 我们进得去。
   中间隔着:观众是谁、广告主投不投、头部吃掉多少、我们有没有入场券。
   ⇒ **赛道判决是变现链的最上游。它错了,后面小说/分镜/出片做得再好也是零。**

⛔ 先查现成(2026-08-22 扫六宇宙,判定【只能自建】):
   · ②GitHub:`gh search repos "cross-validation data source guard llm agent"` 零命中;
     `--sort stars "decision gate multi source evidence agent"` 无同类;
     话题页 `topic:llm-guardrails` 前 20(★2598~10)**全是安全向**
     (deepteam/agentic_security/last_layer = prompt injection、越狱、红队)。
   · ①本机 hooks:`search-breadth-gate` 管【检索通道数】(找工具时用了几种搜法),
     `authority-source-gate` 管【引用权威源】,都不管【下判决时用了几个独立数据源】。
   · ③闭源/市场:mcpmarket 有 `financial-data-cross-validation` skill,但它是
     **财报数字跨源核对**(SEC EDGAR/Gurufocus 同一个数对不对得上),
     不是"下商业判决前必须取几个盲区不重叠的源" —— 形状不同,不可复用。
   · ④⑤⑥ 大厂/包索引/清单:业界(AWS/Strands)只给通用架构模式
     (Executor→Validator→Critic),是建议不是可挂的 hook。
   ⇒ 自建薄壳,零依赖,照本机 search-breadth-gate 同协议(exit 2 + stderr)。

⛔ 与 search-breadth-gate 的分工:
   那道管【找工具时用了几种检索通道】(gh-search / 话题页 / WebSearch…)。
   本道管【下商业判决时用了几个互相独立的数据源】(自有雷达 / 搜索趋势 / 社区民意 /
   平台官方规则 / 竞品实拍…)。前者防"查了一种就说没有",后者防"一个指标就定生死"。

⛔ 为什么必须是【机器拦】而不是【写进铁律】:
   "变现优先"和"要交叉验证"在 CLAUDE.md 里已经写了,我今天照样只用一个源就下判决 ——
   因为那个数据看起来很合理(带百分比、带箭头、带周期),我根本不觉得需要第二个源。
   警告在"我没意识到需要它"的时刻进不去,只有结构性拦停有效。

判据(三条同时成立才拦,宁漏勿误杀):
  ① 本轮说出了【赛道/变现级判决】:红海/蓝海/该进/别进/值得做/换赛道/推荐做…
  ② 本轮实际调用过的【独立数据源】<= 1 种
  ③ 不在过去式/引述/立规矩语境
"""
import json
import re
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "money-verdict-gate.log"

# ① 赛道/变现级判决 —— 这类话直接决定后面几周的工作方向,举证责任最高
MONEY_VERDICT = re.compile(
    r"(红海|蓝海|别进|该进|不要进|值得做|不值得做|换赛道|保持赛道"
    r"|这个赛道(能|不能|可以|不可以)"
    r"|(推荐|建议)(做|选|走|上)"
    r"|最(赚钱|值钱|有钱途)|钱在|变现最|能不能变现"
    r"|RPM 最|收益最|回本)", re.I)

# ③ 过去式/引述/立规矩:复述历史、写判据 —— 不是"我现在下判决"
PAST_CTX = re.compile(
    r"(上一轮|之前|昨天|历史上|曾经|原话|引述|复述|教训|lessons|形状 ?20"
    r"|这类结论|这种结论|下次(要|再|该)|以后(要|再|该)|已冻结|你.{0,4}拍板)")

# ③b 模板占位符:「X 是红海」这种举例
PLACEHOLDER = re.compile(r"[「『\"“]([^」』\"”]{0,12})(红海|蓝海|该进|别进)[^」』\"”]{0,6}[」』\"”]")

# 独立数据源识别 —— 关键:它们的盲区互不重叠
TOOL_SOURCES = {"WebSearch": "web-search", "WebFetch": "web-fetch"}
BASH_SOURCES = [
    # 自有雷达(供给侧:同行拍了什么)
    (re.compile(r"radar/(pick2?|topic_scout|form_deep|form_compare|analyze)\.py", re.I), "own-radar"),
    (re.compile(r"radar\.db", re.I), "own-radar"),
    # 搜索趋势(需求侧:观众在搜什么)
    (re.compile(r"trendsmcp|google.?trends|youtube-trends", re.I), "search-trend"),
    # 社区民意(真人在说什么)
    (re.compile(r"last30days", re.I), "community"),
    # 平台官方(规则/门槛/分成)
    (re.compile(r"support\.google\.com|youtube\.com/howyoutubeworks|blog\.youtube", re.I),
     "platform-official"),
    # 自有知识库
    (re.compile(r"brainq\.py|openclaw_query_router|vault_scan", re.I), "own-vault"),
    # 竞品实拍(扒别人的成品)
    (re.compile(r"yt-dlp|storyboard", re.I), "competitor-teardown"),
    # 跨项目档案(他说过什么)
    (re.compile(r"chat-archive|q-frank\.js|q-digest\.js", re.I), "archive"),
]


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def collect(turn):
    """从本轮消息里抽出:我说的话 + 我实际调用过的独立数据源。"""
    said, sources = [], set()
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            said.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                name = c.get("name") or ""
                if name in TOOL_SOURCES:
                    sources.add(TOOL_SOURCES[name])
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                for pat, tag in BASH_SOURCES:
                    if pat.search(blob):
                        sources.add(tag)
    return said, sources


def judge(said, sources):
    """返回 (should_block, hit_or_reason)。抽出来是为了能被测试直接打靶。"""
    tail = "\n".join(said)[-1500:]
    hit = MONEY_VERDICT.search(tail)
    if not hit:
        return False, "no money verdict"
    if PAST_CTX.search(tail) or PLACEHOLDER.search(tail):
        return False, "past/quote ctx"
    if len(sources) >= 2:
        return False, "sources=%d" % len(sources)
    return True, hit.group(0)


REASON = (
    "⛔ 变现判决闸:你这轮下了【赛道/变现级判决】(命中 %r),"
    "但本轮只用了 %d 个数据源%s。\n"
    "⛔ 2026-08-22 实录:我拿 trendsmcp 一个 API 的搜索热度,就写出"
    "「系统流=红海别进 / multisub=真蓝海该抢」画成表交付 —— "
    "而搜索热度高 != 有人付费看 != RPM 高 != 我们进得去。\n"
    "⛔ Frank 原话:「凡是变现优先…一步错步步错,后面做得再好也变现不了,浪费时间和成本」。\n"
    "⇒ **赛道判决是变现链最上游,它错了后面全废。** 至少再取一个【盲区不重叠】的源再说:\n"
    "   · own-radar(自有雷达=同行拍了什么) · search-trend(观众在搜什么)\n"
    "   · community(last30days=真人在说什么) · platform-official(规则/门槛/分成)\n"
    "   · own-vault(他自己的知识库) · competitor-teardown(扒竞品成品) · archive(他说过什么)\n"
    "⇒ 而且必须回答:**这个热度怎么变成钱?**(谁看→谁投广告→RPM 多少→我们吃得到几成)\n"
    "⇒ 若这轮只是复述已有结论,改成过去式/引述措辞即可放行。\n"
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        _log("skip(no transcript)")
        return 0

    sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
    except Exception:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
        except Exception:
            return 0
        turn = msgs[-40:]

    said, sources = collect(turn)
    block, info = judge(said, sources)
    if not block:
        _log("pass(%s)" % info)
        return 0

    _log("BLOCK(verdict=%r sources=%s)" % (info, sorted(sources)))
    sys.stderr.write(REASON % (
        info, len(sources),
        ("(%s)" % ",".join(sorted(sources))) if sources else ""))
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # fail-open:绝不因为这道闸挡住正常交付
