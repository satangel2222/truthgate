#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop gate·工具去重闸(2026-09-09 Frank 亲口要的)

⛔⛔ 与同目录 `tool-roster-gate.py` 的区别(功能回退闸问过两次,写清别再混):
    | | tool-roster-gate | 本闸 |
    |---|---|---|
    | 治什么 | 我给他【列表】时**漏掉** CLAUDE.md 现成表里的条目 | 我【引入新工具】后**两个都留**不去重 |
    | 判据 | 我写的表 vs CLAUDE.md 表求**集合差** | 引入 + 共存表述 + **无对比数字** |
    | 时机 | 我在列工具清单时 | 我装完/引入工具收尾时 |
    漏报 != 重复留,两者不能互相替代。**本闸是新增,tool-roster-gate.py 一行未动。**
  · 旧文件的 die_ok  —— 【有意不带】:它的 fail-open 辅助函数,本闸用顶层 try-except 等价实现。
  · 旧文件的 roster_from_claude_md —— 【有意不带】:那是读 CLAUDE.md 工具表做集合差用的,
    本闸不做集合差、只看本轮文本的结构特征,读那张表没有意义。

【治什么】Frank 原话:
  「两个路由用同一个工具不是多余的事？你脑袋不正常？加铁律,凡事重复的一样的工具,
   只能去重合并,验证那个最好最新的,只留一个。除非是 python 这些可以多个版本兼容的。」

【诞生现场(当天实录)】
  我装了 AutoCLI(它就是本机已有 opencli 的纯 Rust 重写版),然后在同一张路由表里
  写了【两行并列】+ 一句「⛔ 与 opencli **并存不替换**」。两个工具干同一件事却留两条路由。
  CLAUDE.md 的「先查现成」只管"造之前先找",【找到多个之后怎么办】那格当时是空的
  (本轮已补成「工具去重铁律」,CLAUDE.md 第 273 行)。

【为什么判据不能是枚举词】
  lessons 形状 2026-09-06-A / 2026-09-07-C:`not-mine-gate` 枚举「不是我(起|碰|改)的」,
  我写「不是我**的事**」就绕过。同理我这次写「并存不替换」,但同义说法还有
  「留作降级 / 两个都保留 / 各有各的用处 / 互补 / 各司其职 / fallback」…… 枚举追不上措辞。
  ⇒ **主判据必须是结构性的(做了什么动作、有没有证据),措辞只用来缩范围。**

【三条 AND,全中才拦】
  ① 本轮真的【引入了工具】—— pip/npm/cargo/winget/uv install、下载 release、写进路由表
  ② 出现【共存表述】—— 宽松语义簇(只缩范围)
  ③ 本轮【没有对比数字】—— 没有 "x 倍 / x 秒 vs / N 个 vs M 个" 这类实测对照
  ①③ 是硬信号,不靠措辞。

【豁免】同一软件多版本(python3.12/3.14、node、cuda)、同一个库装进多个解释器 —— Frank 明说不算重复。
fail-open:任何异常一律放行,绝不打扰。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, trig
except Exception:  # pragma: no cover
    def hook_log(*a, **k):
        pass

    def trig(s, n=120):
        return (s or "")[:n]


INTRODUCED = re.compile(
    r"pip\s+install|npm\s+i(nstall)?\b|cargo\s+install|winget\s+install|"
    r"uv\s+(tool\s+)?install|releases/latest/download|"
    r"(注册|加|写)(进|到).{0,14}(路由表|SKILL\.md|skill)",
    re.I,
)

COEXIST = re.compile(
    r"并存|共存|都(保?留|留着)|两个都|各有(各的)?(用处|长处|优势|场景)|"
    r"各司其职|留作(降级|备用|兜底|后备)|作为?(降级|备选|后备|兜底)|"
    r"不(替换|退役|删除)|保留.{0,8}(旧|原|另)(的)?(那个|工具|方案)?",
    re.I,
)

COMPARED = re.compile(
    r"快\s*[\d.]+\s*倍|慢\s*[\d.]+\s*倍|"
    r"[\d.]+\s*(s|秒|ms)\s*(vs|对比|比)\s*[\d.]+|"
    r"\d+\s*个?[^\n|]{0,8}(vs|对比|比)\s*\d+|"
    r"vs\s*[\d.]+\s*(s|秒|个|倍)",
    re.I,
)

MULTIVERSION = re.compile(
    r"py(thon)?\s*-?\s*3\.\d+[^\n]{0,60}py(thon)?\s*-?\s*3\.\d+|"
    r"(多|不同)(个)?版本(共存)?|版本共存|"
    r"node\s*\d+[^\n]{0,30}node\s*\d+|cuda\s*\d+",
    re.I,
)


def _extract_text(payload, raw):
    out = []
    for k in ("last_assistant_message", "assistant_message", "message", "transcript"):
        v = payload.get(k)
        if isinstance(v, str):
            out.append(v)
    return "\n".join(out) if out else raw


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    text = _extract_text(payload, raw)
    if not text.strip():
        return
    if not INTRODUCED.search(text):
        return
    m_co = COEXIST.search(text)
    if not m_co:
        return
    if COMPARED.search(text) or MULTIVERSION.search(text):
        return

    hook_log("tool-dedup-gate", "BLOCK", trig(m_co.group(0)))
    sys.stderr.write(
        "⛔ 工具去重闸:你这轮【引入了工具】并说了【两个都留着】"
        f"(命中「{m_co.group(0)}」),但整轮【没有一个对比数字】。\n"
        "⛔ Frank 2026-09-09 原话:「两个路由用同一个工具不是多余的事？你脑袋不正常？\n"
        "   凡事重复的一样的工具,只能去重合并,验证那个最好最新的,只留一个。」\n"
        "⛔ 诞生现场:我装了 AutoCLI(= 本机 opencli 的 Rust 重写版),\n"
        "   却在同一张路由表写了【两行并列】+「与 opencli 并存不替换」。\n"
        "⇒ 按 CLAUDE.md「工具去重铁律」三步办,做完再收尾:\n"
        "   ① **实测对比**:跑同一件事,量速度 / 数覆盖面(--help 数命令、数站点),\n"
        "      说得出【数字】才算比过 —— 没数字 = 没比过。\n"
        "   ② **合并成一条路由**:只准出现一条「这类活用什么」,\n"
        "      ⛔ 禁止两行并列 + 一句「并存 / 互补 / 留作降级」。\n"
        "   ③ **退役差的那个**;若差的有【独有能力】,写成\n"
        "      「默认 X；仅 A/B/C 这几种走 Y」的例外清单,不是并列两条。\n"
        "⛔ 唯一例外(他明说):**同一软件多版本**(python3.12/3.14、node、cuda)、\n"
        "   同一个库装进多个解释器 —— 那是版本不是竞品,本闸自动放行。\n"
        "(确实比过只是没写数字 ⇒ 把数字写出来即放行;\n"
        " 两者能力根本不重叠 ⇒ 一句话说清各自不可替代在哪。)\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # fail-open
        pass
