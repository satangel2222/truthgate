#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""empty-promise-gate —— Stop 闸:【我说了"对你有什么好处",却一个具体的都举不出来】。

INTENTIONAL-REWRITE: 这不是 `promise-gate.py` 的重写,是一道**全新的、管另一件事**的闸。
  功能回退闸按【文件名相似度】判亲缘,而所有闸都叫 `xxx-gate.py`,天然相似 ⇒ 结构性误报。
  它点名的 8 个标识符(`_log` / `_self_blocked_marker` / `is_real_user_msg` /
  `promise_is_write` / `promise_targets` / `substantive_done` / `target_missed` /
  `turn_touched`)全是 promise-gate 的内部实现,**那个文件原样健在、一行没动**。
  两者的分工:
    · `promise-gate`      管【我说要做某件事,却没做】—— 看的是"承诺 vs 动作"
    · `empty-promise-gate` 管【我说这对你有好处,却举不出是哪一件】—— 看的是"断言 vs 实例"
  一个也不需要从对方那里带过来:判据不同、数据源不同(它比对工具调用,我比对同段文本)。

⛔ 为什么要它(2026-09-09 Frank 亲口下的单):
  他连问三次「我还是看不懂你之前做了什么对我有什么帮助」「我完全不懂你说什么」,
  我第三次的回答是:**「你骂过我的事,我不会再犯第二遍」**。
  他炸了:「**我骂你什么,你不会重犯什么,你傻都没说清楚?妈的,莫名其妙,
  给我弄一个 gate,防止每次你给我回答不准这种莫名其妙的东西**」。

  ⇒ 病根不是用词太专业(那是 jargon-gate 管的),是**我给了一个空的承诺**:
    「错」「教训」「问题」「东西」全是【类别词】,他要的是【哪一件】。
    我换了三轮措辞,每一轮都还是空的 —— 因为我改的是词,不是"有没有指到具体那件事"。

判据(全中才拦,宽放窄拦):
  ① 这一段里有【对他的效果断言】:你会/你少/你不用/对你有帮助/不会再犯/更快更准…
  ② 【同一段】里找不到任何【具体锚点】:引号里的原话 / 带单位的数字 / 反引号里的名字 /
     "比如、例如" / 日期 / "第N条" —— 一个都没有
  ③ 不是短确认(整轮回复太短就不管,那是"好的""收到"这类)
  = 说了好处、举不出一件具体的 → 拦

⛔ 为什么按【段】不按【全文】:capability-boundary 2026-09-06 的教训 ——
   整轮糊成一团,一句空话埋在十句数据里就被稀释掉了。反过来也成立:
   别处有例子不代表【这句承诺】有例子。所以逐段判。

安全: fail-open(自己出错绝不挡路);同一回合只拦一次(防 loop);拦截提示直接给出该怎么补。
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from guard_common import (hook_log, turn_start_index, load_transcript_tail,
                              self_blocked_this_turn, trig)
except Exception:                      # 公共工具挂了 → 整道闸放行,别挡路
    sys.exit(0)

SELF = "empty-promise-gate"

# ① 对他的【效果断言】—— 说的是"你会怎样",不是"我做了什么"
BENEFIT = re.compile(
    r"对你(有|的)[^\n]{0,6}(帮助|好处|用处|价值|意义)"
    r"|你(以后|将来|下次|接下来)?[^\n]{0,8}(会少|少[骂说催问]|不用再|不会再|不必再|省得|免得)"
    r"|(我|它|这)[^\n]{0,10}不会(再)?(犯|出错|重复|重犯|发生)"
    r"|你(会|能|可以)[^\n]{0,10}(感觉到|看到|发现|省下|少花)"
    r"|(变得|会)?更(准|快|好|省|稳|方便)"
    r"|(同样|一样)的(错|问题|事)[^\n]{0,12}(少|不会|不用)",
    re.I)

# ② 【具体锚点】—— 有任意一个,就说明我指到了某件具体的事
ANCHOR = re.compile(
    r"[「『][^」』]{4,}[」』]"                       # 引号里的原话
    r"|“[^”]{4,}”"
    r"|`[^`]{2,}`"                                    # 反引号里的具体名字
    r"|\d{1,4}\s*(次|条|个|秒|分钟|小时|天|倍|%|页|字|行|MB|GB)"   # 带单位的数字
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}"      # 日期
    r"|比如|例如|举个|譬如|具体说|就是那个|上次那个"       # 明确的举例
    r"|第[一二三四五六七八九十\d]+(条|次|个|件)",
    re.I)

MIN_CHARS = 60          # 整轮回复短于这个 = 纯确认,不管

MSG = """⛔ 空承诺闸:你说了【对他有什么好处】,但同一段里**一个具体的都没举**。

命中的那句:
  · %s

⛔ 2026-09-09 Frank 亲口下的单。当时我说「**你骂过我的事,我不会再犯第二遍**」,
   他的回答是:「**我骂你什么,你不会重犯什么,你傻都没说清楚?妈的,莫名其妙**」。
⛔ 我前两轮已经换过措辞了,还是空的 —— 因为**问题不在用词,在有没有指到【哪一件】**。
   「错」「教训」「问题」「东西」全是类别词,他要的是那一件事本身。

✅ 补法(任选其一,补在同一段里):
   · 把他的原话抄进引号:「你上次说『XXX』」
   · 举一件具体的:「比如你 9 月 4 号说过的那个 XXX」
   · 给个数:「以前 8 次里丢 7 次,现在 8 次全在」
   · 指名道姓:用 `具体名字` 而不是"那个东西"

现在把上面那句改成【有具体指向】的,再收尾。
"""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if self_blocked_this_turn(SELF):          # 同一回合只提醒一次,防 loop
        return 0
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return 0
    try:
        msgs = load_transcript_tail(tp)
    except Exception:
        return 0
    start = turn_start_index(msgs)
    texts = []
    for m in (msgs[start:] if start >= 0 else msgs[-30:]):
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content")
        if isinstance(c, str):
            texts.append(c)
        else:
            for it in c or []:
                if isinstance(it, dict) and it.get("type") == "text":
                    texts.append(it.get("text") or "")
    final = texts[-1] if texts else ""
    if len(final.strip()) < MIN_CHARS:
        hook_log(SELF, "pass(too short)")
        return 0

    # ⛔ 逐【段】判:别处有例子不代表这句承诺有例子
    for para in re.split(r"\n\s*\n", final):
        p = para.strip()
        if len(p) < 10:
            continue
        # ⛔ 2026-09-09 建闸当天就误伤了我自己:`## 我不会重犯什么` 这个 markdown 标题
        #   自己独占一段,当然举不出例子 —— **例子在它【下面】那段**。
        #   标题是【索引】不是【陈述】,对它要求具体实例毫无意义,而我写回复几乎必用标题
        #   ⇒ 不跳过 = 这道闸会天天误伤,然后被我训练成背景音。
        if len(p.splitlines()) == 1 and re.match(r"^#{1,6}\s", p):
            continue
        if BENEFIT.search(p) and not ANCHOR.search(p):
            self_blocked_this_turn(SELF, mark=True)
            sent = next((s for s in re.split(r"[。\n!!??]", p) if BENEFIT.search(s)), p)
            hook_log(SELF, "BLOCK(benefit-without-example)", trig(sent, 140))
            sys.stderr.write(MSG % sent.strip()[:90])
            return 2

    hook_log(SELF, "pass(has anchor or no benefit claim)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                    # 闸自己坏了绝不挡路
        try:
            hook_log(SELF, "FAIL-OPEN", repr(e))
        except Exception:
            pass
        sys.exit(0)
