#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""excuse-gate — 取证之后,用一句没验过的借口把【与结论冲突的观察】抹平 → 拦停。

这是 `visual-proof-gate` 的**串联第二道**:
    第一道管「我有没有去看」   ——  它成功了。
    这一道管「我看完有没有被证据改变主意」—— 它是第一道的盲区。

⛔ 2026-08-13 实录(osidian-openclaw,Frank 原话「你室友侦查还是假查,为何我这里一直看都只有x?」):
   眼见为实闸拦住我,逼我去截 CDP 9226 的画面。**闸完全生效**:我真截了图、真 Read 了,
   看到的是两个空的 `x.com/robots.txt` —— 与我正要说的「Twitter 主页抓了 287 条、通道正常」
   **直接冲突**。我当场写下「20:31 刚重启完,还没导航」,然后继续报告一切正常。
   **那句解释我一次都没验证过。** 51 分钟后 Frank 甩来截图:还是 robots.txt。
   真相是源码里 `TW_HOME_PARK_URL = 'https://x.com/robots.txt'` —— 刻意设计的"停车位"
   (x.com/home 是活 SPA,丢了 CF 脚本会无限转圈饿死浏览器;robots.txt 同源无 JS 还能读 cookie)。
   ⇒ **结论蒙对了,机制全错,过程完全是坏的** —— 同样的做法下次必然蒙错。
   后续才叫侦查:写了个蹲守脚本等日志出现 "Cold start ready" 的瞬间立刻截图,
   拿到活动页确实在 x.com/home、登录态 @satangel8、推荐流有真实推文和互动数。
   **上一轮那句借口叫假查;蹲守那一下才叫真查。**

   ⇒ **强制取证的闸,管得住「有没有去看」,管不住「看完之后怎么解释」。**
     闸把证据递到我手上,我用一句嘴替把它消化掉,闸就此失效 —— 日志上还显示我"合规"了。

先查现成(2026-08-13 真跑,三轮,非编造):
  · WebSearch "claude code hook detect agent rationalization confirmation bias explaining away evidence"
    → anthropics/claude-code#29849(QC agent 迭代中系统性确认偏误)、mcpmarket "Confirmation Bias
      Mitigation" **skill**、若干 hook 科普。都是**引导性框架/讨论**,非结构性拦截。
  · WebSearch "LLM agent excuse detection guard hook explain away anomaly unverified excuse"
    → MindGuard(arxiv 2508.20412)、XG-Guard(arxiv 2512.18733)等**学术多智能体安全框架**,
      以及通用 guardrail 最佳实践;有一篇 Claude Code hook 文章恰好讨论 excuse 检测的
      召回/精度困境 —— 是经验讨论,不是可复用实现。
  · gh search repos "claude code hooks guard" --sort stars
    → toolbeltross/rh-claude-framework ★1、soyukke/ccguard ★0、
      noelfortman/claude-code-hooks-guardrail-integrity ★0、monokuroailink-lab/HAPPYWEEK7 ★0
  · gh search repos "excuse detection agent guard" --sort stars → **0 结果**
  ⇒ **结论:只能自建**(无可复用/可改造的现成实现)。

判据(两条同时成立才拦,尽量少误伤):
  ① 本轮【确实取过画面/文件证据】(与第一道相反:那条是没取才拦)
  ② 输出里出现【时序/揣测式借口】,且其邻近 ±80 字跟着【健康或无害化断言】
fail-open:任何异常一律放行,绝不因本闸自身出错卡住交付。
"""
import json
import re
import sys

# ① 本轮取过证据的指纹。2026-09-08:这里原本就写着"与 visual-proof-gate 的 VISUAL 同源"
#   却各抄了一份 ⇒ 补一个新取证工具只补一边,两道串联的闸会分裂。已统一到 guard_common。
try:
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from guard_common import SHARED_VISUAL_EVIDENCE as TOOK_EVIDENCE
except Exception:
    # 应急最小版:guard_common 挂了才走这里。**故意不与主判据保持一致**——
    # 抄一份完整副本正是本次要根治的病;这里只保证闸不崩。
    TOOK_EVIDENCE = re.compile(r"screenshot|\.png\b|webapp-testing|browser-act", re.I)

# ② 时序/揣测式借口 —— 共同功能:把刚看到的异常说成"暂时的/无所谓的"
EXCUSE = re.compile(
    r"刚(重启|启动|起来|开|跑|改|完|结束)[^。;;\n]{0,14}(还没|没来得及|尚未|所以)"
    r"|还没(导航|加载|跑到|轮到|开始|来得及|刷新)"
    r"|应该是[^。;;\n]{0,20}(所以|因此|吧|的)"
    r"|(可能|估计|大概|多半)[^。;;\n]{0,20}(所以|因此|吧|导致|造成)"
    r"|(暂时|一时)(性的|的)?[^。;;\n]{0,10}(现象|状态|情况)",
    re.I)

# ③ 无害化断言 —— 借口的落点
BENIGN = re.compile(
    r"正常|健康|没问题|不影响|无所谓|不是(故障|问题|坏)|属正常|可以忽略|不用管|没坏|(?<![a-zA-Z])OK(?![a-zA-Z])|✅",
    re.I)

# ④ 豁免:复盘/引用语境 —— 我在【认错时复述那句错话】,不是在【现行犯用它消化异常】。
#
# ⛔ 2026-08-13 本闸上线当轮就误报了一次(新造的工具第一次跑就带 bug,skill 早写过):
#    我在向 Frank 认错、原样引用自己上一轮那句「刚重启还没导航」,闸把引用当成了犯案。
#    ⇒ 判据补一条:命中窗口附近若有【认错/引用标记】,说明这句借口是被审判的对象,不是通行证。
# ⛔ 豁免词必须精准 —— docguard 第一版豁免词写了个"月"就成了摆设。
#    这里只认【明确指向过去的自我审查】,不认任何泛化的转折词。
QUOTING = re.compile(
    r"我(上一轮|上轮|之前|刚才)(说|写|给|报|判|以为|那句)"
    r"|上一轮那(句|个|套)"
    r"|(是|都是)编的|恰好蒙对|蒙对了|机制全错|过程是坏的"
    r"|实录|复盘|归形状|形状\s*\d{4}-\d{2}-\d{2}"
    r"|打脸|错在(哪|这)|认错"
    r"|触发处|回归(测试|用例)|测试用例|期望(拦|放行)",
    re.I)


def _load_turn(tp):
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
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            text.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                text.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                blob.append(str(c.get("name", "")) + " " +
                            json.dumps(c.get("input") or {}, ensure_ascii=False))
    return "\n".join(text), "\n".join(blob)


def find_violation(text, blob=""):
    """返回触发窗或 ''。抽成函数是为了能用【这次真实的错误数据】做回归。

    行为(2026-08-13 经外部异模型审查校正过措辞,原断言写得太绝对):
      · 触发前提是本轮取过**画面/文件类证据**(不止截图:browser-act / webapp-testing /
        desktop-window-shot / 读过 .png 都算),且 blob 与 text 两处都查。
      · **逐个** EXCUSE 匹配判定,不是整段一刀切:只要存在**任意一个**借口
        「80 字内有 BENIGN」且「200 字内无 QUOTING」,立即返回并拦停。
        ⇒ 一段话里既复盘旧错、又给当下找新借口时,**新借口仍会被拦** —— 这是想要的(见测试 #12)。

    ⚠️ 已知边界(老实登记,不假装解决):QUOTING 的 200 字窗**偏宽**,
       一个真正的现行借口若恰好落在某个复盘词(实录/复盘/我上一轮…)附近 200 字内,会被放过。
       故意选宽而非窄:**误报会让我开始忽略这道闸(等于闸死了),漏报只是少拦一次**。
       docguard 的血泪是豁免词太糙(一个"月"字放过全部);这里豁免词只认
       【明确指向过去的自我审查】,不认任何泛化转折词,已用测试 #10/#11/#12 钉住三个方向。
    """
    if not (TOOK_EVIDENCE.search(blob) or TOOK_EVIDENCE.search(text)):
        return ""          # 没取过证据 → 归 visual-proof-gate 管,不是本闸的活
    for m in EXCUSE.finditer(text):
        near = text[max(0, m.start() - 80):min(len(text), m.end() + 80)]
        if not BENIGN.search(near):
            continue
        # 复盘/引用语境用更宽的窗(认错标记常在句子外围),命中即豁免
        wide = text[max(0, m.start() - 200):min(len(text), m.end() + 200)]
        if QUOTING.search(wide):
            continue
        return near
    return ""


def main():
    data = json.loads(sys.stdin.read())
    if data.get("stop_hook_active"):
        sys.exit(0)
    tp = data.get("transcript_path")
    if not tp:
        sys.exit(0)
    text, blob = _load_turn(tp)
    hit = find_violation(text, blob)
    if not hit:
        sys.exit(0)
    print(
        "⛔ 借口闸(眼见为实闸的第二道):你本轮【确实取过证据】,但紧接着用一句"
        "【没验证过的借口】把一个与结论冲突的观察抹平了,然后继续原来的结论。\n"
        f"触发处:…{hit.strip()[:160]}…\n"
        "⛔ 2026-08-13 实录:截图看到 CDP 9226 里只有两个空的 x.com/robots.txt —— 与"
        "「Twitter 主页抓了287条、通道正常」直接冲突。我写「刚重启完还没导航」就放过去了,"
        "那句话一次没验过。51 分钟后 Frank 截图打脸;真相是源码里刻意设计的『停车位』,机制完全不同。"
        "⇒ 结论蒙对、机制全错、过程是坏的。\n"
        "现在二选一,不许第三种:\n"
        "  ① **去验那句借口** —— 它本身是一条待验证的新命题,不是通行证。"
        "读源码 / 查配置 / 看日志 / 蹲一次现场,拿到机制再下结论。\n"
        "  ② **如实写「我看到 X,与预期不符,原因未知」** —— "
        "「我不知道为什么」是合格的交付;「我猜是因为刚…」不是。\n"
        "自检:从取证到这个结论之间,我有没有做过任何一次针对『为什么会这样』的查询?"
        "没有 = 我在用嘴解释画面。",
        file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)   # fail-open
