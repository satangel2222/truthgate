#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""停车位闸 —— 收尾那条消息里把【当场能做的事】列进「还没解决 / 没做完 / 我接着做」,然后就停。

⛔ 病(Frank 2026-10-05,airbnb 项目,原话):
   「为何每次 superego/tg 没有这个 gate,每次说我还没解决,但是不会自动去做??!!!!
     立刻修正到真开火,保证引导成功作对的事,没用绕道机会,除非误拦」
   现场:我那轮收尾写「**还没解决** · …这次是我手工做的,还没写进系统 … 这一步我接着做。」然后结束了这一轮。
   那件事是可逆的、他早授权的、当场就能做的。

⛔ 为什么现有的闸全放行(2026-10-05 05:05 那次收尾,hook-stats 实录 12 道全 allow):
   promise-gate / commitment-execution-gate / idle-confess-gate / keep-going-gate / idle-ask-gate …
   前提全是「这一轮【零工具调用】却在说话」。我那轮干了很多活 ⇒ 每一道都放行。
   而且其中多数 9/26 起在只记账名单里(superego-observe.json),认出来也不拦。
   ⇒ 这道的前提正好相反:**不看这轮干没干活,只看收尾那条消息里有没有把能做的事停在那里。**
   前提相反,所以没塞进旧闸(塞进去会把旧闸的判据弄反)。

判据(只看本轮【最后一条】带文字的助手消息;中途的进度话不算 —— 中途说「我接着做」然后真做了是正常的):
  A. 自我承诺句:「这一步我接着做 / 我下一步去补 / 我稍后再接 / 接下来我会…」⇒ 一律拦。
     承诺要做 = 自己认了能做;说完就停 = 没做。这一类没有豁免理由(写了理由也拦:有理由就别承诺「接着做」)。
  B. 「还没解决 / 没做完 / 还剩 / 我还能自己做的」这类小标题下面的每一条:
     那一条里写明了【卡在哪一类】才放过 ——
       ①要他本人动手 / 点头(扫码、手机、拍板、花钱、不可逆、对外发)
       ②要等到某个时点或某个真事件(明天、几号出账单、下一次真掉线、没有样本)
     没写 ⇒ 当作「当场能做却停了车」⇒ 拦。
  ⇒ 被拦之后只有两条路:现在去做完;或在那一条里写明它卡在①还是②(那是事实陈述,写错了他一眼看得出)。
     把小标题删掉、把那几条藏起来不算路:那是静默丢信息(「压缩不等于删除」铁律),比停车更糟。

终止条件:同一轮最多连拦 MAX_BLOCKS 次(官方要求 Stop 闸必须有界),到顶放行并记 GAVEUP。
安全:fail-open;只读;留日志。自测:python parked-work-gate.py --self-test
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, strip_doc, trig, _text_of, _STOP_FEEDBACK_RE
except Exception:                                         # noqa: BLE001
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def strip_doc(t):
        return t or ""

    def trig(s, n=120):
        return str(s)[:n]

    def _text_of(c):
        return c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))

    _STOP_FEEDBACK_RE = re.compile(r"Stop hook (?:feedback|blocking error)", re.I)

NAME = "parked-work-gate"
MAX_BLOCKS = 3

_MARK = re.compile(r"[*#>`_~]+")
# B 类小标题:整行很短、就是这个意思(正文句子里顺带说「还没解决」不算标题)
HEAD_RE = re.compile(
    r"^(?:[0-9️⃣]+[.、 ]*)?(?:⚠️?|⛔|🔴|🟡)?\s*"
    r"(?:(?:还|仍|目前)?(?:没|未)(?:有)?(?:解决|做完|完成|做|修|接|测)(?:的)?(?:事|东西|部分)?"
    r"|还剩(?:什么|的|下的)?|遗留(?:问题)?|未完成|没做完的|还有什么没做完"
    r"|我还能自己做的|我知道但(?:故意)?没做的|下一步|后续(?:要做)?|待办|待做|TODO)"
    r"\s*[::]?\s*$", re.I)
BULLET_RE = re.compile(r"^\s*(?:[-*·•]|\d+[.、)])\s+(.*\S)\s*$")
NONE_RE = re.compile(r"^\s*(?:无|没有|none|n/?a)\s*[。.]?\s*$", re.I)
# A 类:自我承诺(第一人称 + 将来 + 动手动词)
SELF_RE = re.compile(
    r"我(?:会)?(?:接着|继续|稍后|之后|回头|随后|下一步|下一轮|下轮|马上|这就|待会|晚点)(?:再|就|去|会)?\s*"
    r"(?:做|去做|补|补上|写|接上|修|查|测|跑|弄|加|处理|搞)(?![了过完好])"
    r"|接下来我(?:会|去|再|要)|下一步(?:我)?(?:会|去|要)(?:做|补|写|接|修|测)"
    r"|我(?:会|将)(?:在)?(?:下一轮|下轮|之后|稍后|随后)")
# B 类放行:那一条自己写明了卡在哪一类
BLOCKER_RE = re.compile(
    r"要你|需要你|等你|请你|由你|你(?:来|去|本人|点头|拍板|说了?算|定|决定|扫|批|同意|一句话)|他本人|只有他|Frank\s*(?:本人|点头|拍板|决定|批)"
    r"|手机|扫码|扫一(?:次|下)|花(?:真)?钱|付费|不可逆|对外(?:发|公开|发布)|发给客人|公开内容"
    r"|明天|后天|下周|下个月|过几天|\d{1,2}\s*[/月]\s*\d{1,2}|[一二三四五六七八九十]+月"
    r"|才(?:知道|出|能|会|有|算)|等(?:到|它|账单|下一次|真|满)|出账单|下一次真|下次真|第一次真|真(?:掉线|触发|发生)(?:才|时)"
    r"|没有?(?:真)?样本|物理|够不到|没权限|故意(?:没|不)做")
QUOTED = re.compile("「[^」]*」|“[^”]*”|\"[^\"]*\"")
SENT = re.compile(r"(?<=[。!!??;;])")


def last_text(msgs):
    """本轮最后一条带文字的助手消息(已去掉代码块 / 引用 / 表格)。"""
    start = turn_start_index(msgs)
    for m in reversed(msgs[start + 1:] if start >= 0 else msgs):
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content") or []
        t = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
        if t.strip():
            return strip_doc(t)
    return ""


def parked(text):
    """回 [(类别, 那一条原文)]。A = 自我承诺;B = 没写卡点的未完成项。空 = 放行。"""
    out, seen = [], set()

    def add(kind, s):
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append((kind, s))
    in_sec = False
    for ln in text.split("\n"):
        bare = _MARK.sub("", ln).strip()
        promised = False
        for seg in SENT.split(QUOTED.sub(" ", bare)):      # 引号里的不算(在引用 / 纠正别人的话)
            if SELF_RE.search(seg):
                add("A", seg)
                promised = True
        if HEAD_RE.match(bare):
            in_sec = True
            continue
        b = BULLET_RE.match(ln)
        if in_sec and b:
            item = _MARK.sub("", b.group(1)).strip()
            if not promised and not NONE_RE.match(item) and not BLOCKER_RE.search(item):
                add("B", item)
            continue
        if in_sec and bare:                                # 小节结束:遇到非列表的正文
            in_sec = False
    return out


def blocks_so_far(msgs):
    rx = re.compile(r"^\[[^\n]*?[/\\]" + re.escape(NAME) + r"\.py\b[^\n]*?\]:", re.M)
    start = turn_start_index(msgs)
    n = 0
    for m in (msgs[start:] if start >= 0 else msgs):
        if m.get("type") == "user":
            t = _text_of((m.get("message") or {}).get("content"))
            if _STOP_FEEDBACK_RE.search(t):
                n += len(rx.findall(t))
    return n


def reason(items):
    a = [s for k, s in items if k == "A"]
    b = [s for k, s in items if k == "B"]
    r = ["⛔ 停车位闸:你收尾这条消息把能做的事停在那里就结束了(Frank 2026-10-05:「每次说还没解决,但是不会自动去做」)。"]
    if a:
        r.append("【你自己说了要做、却没做就停】")
        r += ["   · " + s[:120] for s in a[:6]]
        r.append("   ⇒ 现在就去做,做完再收尾。说了「我接着做」就没有别的出口。")
    if b:
        r.append("【列在「没解决 / 没做完」下面、却没写卡在哪】")
        r += ["   · " + s[:120] for s in b[:8]]
        r.append("   ⇒ 逐条:当场能做的现在做完;真做不了的,在那一条里写明卡在哪一类 ——")
        r.append("      ①要他本人动手 / 点头(扫码、手机、拍板、花钱、不可逆、对外发) ②要等到哪个时点或哪个真事件(写出日期 / 事件)。")
    r.append("⛔ 把小标题删掉、把这几条藏起来不算解决:那是静默丢信息,比停车更糟。")
    return "\n".join(r)


def check(msgs):
    """回 (decision, items)。decision: 'allow' / 'block' / 'gaveup'。"""
    text = last_text(msgs)
    if not text:
        return "allow", []
    items = parked(text)
    if not items:
        return "allow", []
    if blocks_so_far(msgs) >= MAX_BLOCKS:
        return "gaveup", items
    return "block", items


def self_test():
    ok = bad = 0

    def T(c, name):
        nonlocal ok, bad
        if c:
            ok += 1
        else:
            bad += 1
            print("  ✗", name)
    real = ("连上了。\n\n**还没解决**\n- TNG 登录只管大约一天,过期要重扫。「一直续着能不能撑过一天」我没测。\n"
            "- 「断了就自动把二维码推到你 TG」这次是我手工做的,还没写进系统。下次断连时系统只会发文字提醒,不带二维码。这一步我接着做。")
    r = parked(strip_doc(real))
    T(any(k == "A" and "接着做" in s for k, s in r), "真现场(10/05):「这一步我接着做」然后停 ⇒ 拦")
    T(any(k == "B" and "没测" in s for k, s in r), "真现场:「我没测」没写卡在哪 ⇒ 拦")
    T(parked("## 还没做完\n- 十月账单 10/16 前后才出,收款那步等它出来才第一次真触发。\n- TNG 钱包要你手机扫一次。") == [], "每条都写了卡点(等日期 / 要他扫码)⇒ 放行")
    T(parked("**我还能自己做的**\n- 无\n\n**卡着等你一句话的**\n- 要不要放全局:要你点头。") == [], "写「无」+ 要他点头 ⇒ 放行")
    T(parked("做完了,回归 155/155。") == [], "没有未完成项 ⇒ 放行")
    T(parked("他原话:「每次说我还没解决,但是不会自动去做」。这道闸已经装好。") == [], "引用他的话里有「还没解决」⇒ 不算")
    T(parked("旧文案写的是「这一步我接着做」,已经删掉。") == [], "引号里的承诺句(在纠正旧说法)⇒ 不算")
    T(len(parked("**没解决的**\n- 文档没更新。\n- 另一个脚本没接。")) == 2, "两条都没写卡点 ⇒ 两条都列出来")
    two = parked("**没解决的**\n- 文档没更新。\n\n下面是别的内容\n- 这条不在小节里。")
    T(len(two) == 1 and two[0][1] == "文档没更新。", "小节在非列表正文处结束")
    T(parked("修好了。剩下的我下一步去补。")[0][0] == "A", "「我下一步去补」⇒ 拦")
    T(parked("我接着把文档也改了,现在三处一致。") == [] and parked("然后我继续跑了三次,都成。") == [], "已经做完的叙述(接着…改了 / 继续跑了)⇒ 不算")

    def mk(final, feedback=0):
        ms = [{"type": "user", "message": {"content": "修它"}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "中途:这一步我接着做"}, {"type": "tool_use", "name": "Bash", "input": {}}]}}]
        for _ in range(feedback):
            ms.append({"type": "user", "message": {"content": 'Stop hook feedback:\n[python "$HOME/.claude/hooks/parked-work-gate.py"]: ⛔ 停车位闸'}})
        ms.append({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
        return ms
    T(check(mk("全做完了。"))[0] == "allow", "中途说过「接着做」、收尾没停车 ⇒ 放行(只看最后一条)")
    T(check(mk(real))[0] == "block", "收尾停车 ⇒ 拦(这轮干过活也拦 —— 跟旧闸前提相反)")
    T(check(mk(real, feedback=MAX_BLOCKS - 1))[0] == "block" and check(mk(real, feedback=MAX_BLOCKS))[0] == "gaveup", "连拦到顶才放行(有界)")
    T("接着做" in reason(r) and "①" in reason(r), "拦的那段话点出是哪几条、给出两条出路")
    print("parked-work-gate self-test %d/%d %s" % (ok, ok + bad, "OK" if not bad else "FAIL"))
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
        msgs = load_transcript_tail(data.get("transcript_path")) or []
        d, items = check(msgs)
        if d == "allow":
            return 0
        if d == "gaveup":
            hook_log(NAME, "GAVEUP(连拦 %d 次到顶) " % MAX_BLOCKS + trig(items[0][1], 60))
            return 0
        hook_log(NAME, "BLOCK(%s) " % "+".join(sorted({k for k, _ in items})) + trig(items[0][1], 60))
        print(json.dumps({"decision": "block", "reason": reason(items)}, ensure_ascii=False))
        return 0
    except Exception:                                     # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(main())
