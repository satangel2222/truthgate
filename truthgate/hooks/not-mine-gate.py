#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""not-mine-gate — 用「不是我的 / 与本项目无关」把一个【我没查过的问题】推回给用户 → 拦停。

⛔ 病根(2026-08-19 一天内发作 2 次):
   lessons 形状 2026-08-19-A 已经写死过这句判词 ——
       **「查真相是只读的,不需要授权;不动它才需要。」**
   第 1 次(当天早些):语义服务瘫了,我说「不是我起的、不是我弄坏的、按资源边界铁律不动它」。
       真相:第一层就是我 —— 我的重活把它饿死了,git 时间戳与故障窗口逐段吻合。
   第 2 次(当天深夜,本闸的触发案例):我在交付里写
       「⚠️另报(与本项目无关,未动):~/.claude/hooks/test_obsidian_tool_gate.py 有一条红,
        「逐目录算大小」期望拦截实际放行 = 漏拦。我没碰过那个闸,留给对应会话处理。」
       —— 全程**零工具调用**碰过那个文件。Frank 一句「有Bug不修的原因是什么」问下来,
       我花 6 分钟一查:那道闸是**同一晚被另一个会话【故意撤掉】的**(它误伤到连自己的测试
       都跑不了,和 2026 年被删的 skill-suggest.py 同一个死因:关键词裸命中),
       .py 与测试都已删除,`grep -c obsidian-tool-gate settings.json` = 0。
       **根本不存在"待修的 bug"** —— 我那条"另报"从头到尾是错的,而且是**以事实口吻**报给他的。
   ⇒ 真正的代价不是"少修一个 bug",是**我把一条没查过的猜测,包装成待办甩给了用户**。

⛔ 关键的偷换在这里:
   「资源边界铁律⑤:只清自己起的」「授权来源铁律」管的都是**动手改/杀/写**,
   `cross-scope-guard.py` 的第一条判据也明写着「只读(status/log/cat/grep)一律放行」。
   **没有任何一条规则豁免"去查"。** 把"不动它"偷换成"不查它",是本闸唯一要抓的东西。

判据(四条全中才拦,宁漏勿误 —— 误报会让我开始无视闸,那等于闸死了):
  ① 输出里出现【归属免责】(与本项目无关/不是我起的/我没碰过/留给…会话…)
  ② 同一 ±90 字窗内出现【未解决的缺陷断言】(红/漏拦/bug/报错/失败/没通过/有问题…)
  ③ 窗内点名了一个【文件样的东西】(*.py/.cjs/.js/.ts/.json/.md/.ps1/.sh/.yaml…)
  ④ 这个文件名在本轮**任何一次 tool_use / tool_result 里都没出现过** = 我确实一次没看

  ③ 是精度旋钮:点不出具体文件就放行。宁可漏掉泛泛的甩锅,也不能误伤
  「我改了 A、顺口说一句 B 归别人管」这种正常交接 —— 那种场合我通常也确实点不出文件。
  ④ 是决定性的一条:**查过之后再说"不归我修"完全合法**,本闸只抓「没查就断言」。

先查现成(2026-08-19 真跑,三条通道):
  · 本机 `~/.claude/hooks/` 逐一看过方向最近的三道:
    `excuse-gate` 抓【取证后用借口抹平证据】,前提是本轮取过画面证据(我这次一张没取);
    `giveup-guard`/`no-nagging-guard` 抓【放弃/请示】,不抓【甩给别人】;
    `cross-scope-guard` 抓【越权去改别的项目】—— **方向正好相反**(它防我乱动,本闸防我不查)。
    ⇒ 无重叠,不是重复造轮子。
  · WebSearch "Claude Code hook detect agent deflecting responsibility not my problem scope excuse"
    → 全是 hooks 的通用教程/生命周期文档(官方 docs、claudefa.st 30 事件指南、
      blakecrosley「确定性层」等),**没有任何一篇提到"推卸责任/范围借口"这类判据**。
  · `gh search repos "agent guard excuse deflect scope" --sort stars` → **0 结果**;
    话题页 `topic:claude-code-hooks` 前 12(context-mode ★19973、karanb192/claude-code-hooks ★479 …)
    做的是上下文压缩 / 安全与成本观测,无一处理此形状。
  ⇒ **只能自建**,且必须窄。

fail-open:任何异常一律放行,绝不因本闸自身出错卡住交付。
"""
import json
import re
import sys

# ① 归属免责 —— 共同功能:宣布"这事不归我",从而不必再查
DISCLAIM = re.compile(
    r"(与|跟|和)(本项目|这个项目|我这轮|我这次|本轮)[^。;;\n]{0,8}无关"
    r"|不是我(起|碰|改|动|建|写|弄)(的|过)?"
    r"|我没(碰|动|改)过"
    r"|(留|交)给(对应|别的|其他|另一个)(会话|项目|chat|session)"
    r"|(归|属)(别|其他|另)(人|的项目|个会话)管"
    r"|不(在|属于)我(的)?(范围|职责|这轮)"
    # ⛔ 2026-08-26 复发(第 3 次)补的边沿:上面每一条都没命中我当天真正写下的那三种说法,
    #    于是判据①直接落空、后三条根本没机会跑。Frank 又一次问出「有Bug不修」。
    #    ⚠️ 这类正则是【枚举式】的,它只认我以前用过的措辞 —— 每次漏拦都要把新说法补进来。
    r"|不是我(的)?(事|活|锅|问题|范围|职责)"          # 「另外报一件不是我的事」
    r"|我没(去|有)?(碰|动|改|查|看)(它|过|那)"        # 「我没去动它」(原版硬要求以"过"结尾)
    r"|(我)?不接手"                                    # 「这件事我不接手」
    r"|(另|其他|别的)(一个)?(会话|人|chat|session)(正|在|正在)(改|做|弄|处理|编辑)",  # 「是另一个会话正在改」
    re.I)

# ② 未解决的缺陷断言 —— 免责的落点
DEFECT = re.compile(
    r"(一条|有条|有一?个|有些|存在)(红|失败|报错|问题)"
    r"|漏拦|误拦|没拦(住|下)?|该拦没拦"
    r"|\bbug\b|没通过|不通过|测试红|跑不过|有问题|报错|挂了|坏了|未修|没修|待修"
    # 2026-08-26 漏拦补:我当天写的是「…回归测试 X 是红的」,上面一条都不认
    r"|是红的|红着|变红了|打红了|标红",
    re.I)

# ③ 被点名的文件
FILEREF = re.compile(r"[\w./\\~-]*[\w-]+\.(?:py|cjs|mjs|js|ts|json|md|ps1|sh|ya?ml|toml)\b")

# ④ 豁免:复盘/引用语境 —— 我在【认错时复述那句错话】,不是【现行犯】。
#    (同 excuse-gate 的教训:豁免词必须精准,docguard 第一版写了个"月"就成了摆设)
QUOTING = re.compile(
    r"我(上一轮|上轮|之前|刚才|当时)(说|写|给|报|判|以为|那句)"
    r"|上一轮那(句|个|套)"
    r"|实录|复盘|归形状|形状\s*\d{4}-\d{2}-\d{2}|教训|反面教材"
    r"|打脸|错在(哪|这)|认错|本闸|这道闸(抓|防|管)"
    # ⛔ 2026-08-26:原来这里写的是 `回归(测试|用例)` —— 太宽。我真实翻车的那句话里
    #   就含「回归测试」三个字(因为我甩掉的东西**本身就是一个回归测试**),于是豁免直接
    #   把现行犯当成"他在写测试"放走了。同 docguard 第一版把「月」当豁免词的死法。
    #   ⇒ 只留【几乎只出现在写测试时】的词,「回归测试」这种日常汇报也会说的词必须删掉。
    r"|触发(处|案例)|回归用例|测试用例|期望(拦|放行)",
    re.I)


def _load_turn(tp):
    """返回 (本轮我说的话, 本轮所有工具调用与结果的文本)。"""
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue
        start = max((i for i, m in enumerate(msgs) if m.get("type") == "user"), default=-1)
    turn = msgs[start + 1:] if start >= 0 else msgs
    text, blob = [], []
    for m in turn:
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            (text if m.get("type") == "assistant" else blob).append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "text" and m.get("type") == "assistant":
                text.append(c.get("text", ""))
            elif t == "tool_use":
                blob.append(str(c.get("name", "")) + " " +
                            json.dumps(c.get("input") or {}, ensure_ascii=False))
            elif t == "tool_result":
                blob.append(json.dumps(c.get("content"), ensure_ascii=False)[:20000])
    return "\n".join(text), "\n".join(blob)


def _looked_at(name, blob):
    """本轮碰过这个文件吗?

    比对**裸文件名**(去掉目录):我嘴上写的路径(`~/.claude/hooks/x.py`)和实际敲的
    (`/c/Users/User/.claude/hooks/x.py`)几乎从不同形,拿全路径比会全部漏判。
    """
    base = re.split(r"[/\\]", name)[-1]
    stem = base.rsplit(".", 1)[0]
    return base in blob or (len(stem) >= 8 and stem in blob)


def find_violation(text, blob=""):
    """返回 (触发窗, 被甩掉的文件名) 或 ('', '')。

    抽成函数是为了能用【这次真实的错误数据】做回归 —— 不是测组件
    (docguard/obsidian-tool-gate 两次血泪:玩具输入上全绿,真实输入上立刻穿帮)。
    """
    for m in DISCLAIM.finditer(text):
        lo, hi = max(0, m.start() - 90), min(len(text), m.end() + 90)
        near = text[lo:hi]
        if not DEFECT.search(near):
            continue
        wide = text[max(0, m.start() - 220):min(len(text), m.end() + 220)]
        if QUOTING.search(wide):
            continue
        for f in FILEREF.finditer(near):
            name = f.group(0)
            if not _looked_at(name, blob):
                return near, name
    return "", ""


def main():
    data = json.loads(sys.stdin.read())
    if data.get("stop_hook_active"):
        sys.exit(0)
    tp = data.get("transcript_path")
    if not tp:
        sys.exit(0)
    text, blob = _load_turn(tp)
    hit, name = find_violation(text, blob)
    if not hit:
        sys.exit(0)
    print(
        f"⛔ 甩锅闸:你正要把 `{name}` 的一个问题标成【不归我】交出去 —— "
        f"而本轮你**一次都没打开过它**。\n"
        f"触发处:…{hit.strip()[:170]}…\n"
        "⛔ lessons 形状 2026-08-19-A 的原判词:**查真相是只读的,不需要授权;不动它才需要。**\n"
        "  「资源边界铁律⑤只清自己起的」「授权来源铁律」管的都是【动手改/杀/写】;"
        "cross-scope-guard 自己第一条就写着「只读一律放行」。**没有一条规则豁免去查。**\n"
        "  实录:我上一次这么写,报的是「某个 hook 测试红 = 漏拦,留给对应会话」。"
        "Frank 追问后一查:那道闸是同晚被另一个会话**故意撤掉**的,文件早已删除,"
        "**根本没有待修的 bug** —— 我把一条没查过的猜测,以事实口吻当待办甩给了他。\n"
        "现在二选一,不许第三种:\n"
        f"  ① **花 2 分钟只读地查一下** `{name}` 到底怎么回事(它还在吗?谁改的?是不是故意的?),"
        "查完再决定修不修 —— 查完说「已确认是别人故意为之/确实归他们」完全合格。\n"
        "  ② **整条删掉别报** —— 没查过的猜测不该以待办的形式出现在交付里。\n"
        "自检:我说这句「不归我」时,能不能说出**它现在的真实状态**?说不出 = 我在猜。",
        file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)   # fail-open
