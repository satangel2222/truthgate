#!/usr/bin/env python3
"""Stop hook: 【让 Frank 做选择,却没给评比】= 违规。

2026-07-28 Frank 亲口钉死:「1 vs 2,深度评比哪个更好,区别是什么,适合什么场景?
**每当有多种选择都要给我自动回答这种**」——他要的是【不用问就有】,不是每次追问一遍。

为什么必须是可执行闸,而不是 CLAUDE.md 里再加一行:
  CLAUDE.md 第 128 行本来就写着「方案决策 — 对比排序,不只给一个方案」,
  而我当天照样甩出「两条路:1.用快照 2.改成 off」就收尾 —— 纯文字规则 = 纸老虎(形状P)。

权威依据:Nielsen Norman Group《Compensatory vs Noncompensatory Decisions》——
  逐属性并排展示才支持"补偿式决策",用户能看清"多花一点换来什么";
  只列选项不列维度 = 逼人做无信息的盲选。

先查现成(2026-07-28,两轮六组词):gh search 六组全部零命中,WebSearch 只有 hook 教程与
  决策科学论文,无现成工具 ⇒ 只能自建。采纳了查到的省事做法:官方 Stop hook 直接给
  `last_assistant_message`,不必 parse transcript(代价见下方 ⚠️ 边界)。

━━ ⛔ v2 判据(v1 被外部 critic 用 33 条独立样本打回:18 条判错)━━
v1 的根因错误:**把"裸编号 1. 2."当成选项**。而「我改了两处:1…2…」是我输出里最高频的形状,
  于是 7/8 条日常交付文被误伤;我又加「步骤/流程」排除当创可贴 —— 那反而成了后门:
  长文前半有正当步骤清单,就给整条消息买了免检(和 no-nagging 修过的 EXEMPT 全文短路同形状)。
v2 改成**两个信号都要命中**:
  ① 有并列选项的形态 ② 且有【让他选】的信号(你选/哪个/挑一个/二选一/which…)
  真选择题必然带 ②,而改动清单/步骤/findings 列表不会带 ⇒ 误伤自然消失,
  伪装成"步骤:"也躲不掉(排除分支已整段删除,不再需要)。

与 no-nagging-guard 的分工:no-nagging 管【该不该问】(可逆技术活别问);本闸管【问得合不合格】。
与记忆 frank-default-answer-is-C-not-either-or:那条说"先找第三条路";本闸是它的下一道。

⚠️ 已知边界(诚实标注,别当没有):
  · `last_assistant_message` 只含【最后一条】助手消息(已从 cli 构造点核实:Jc(d.message.content))。
    我在最后一次工具调用【之前】写的选项,这道闸看不到。no-nagging 走 transcript 能看全轮 ——
    这是"少 30 行解析代码"换来的真实代价,不是纯收益。
  · 只认中文/英文常见句式;刻意换生僻说法仍可绕过。闸是减少复发,不是绝对防线。
安全:fail-open;只读;per-turn 只拦一次且【每轮复位】(照 no-nagging:stop_hook_active=False 即新轮)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:                                   # ⛔ 逐个 import 带兜底:打包成一条时只要少一个名字,
    from guard_common import hook_log   #    完好的其它函数会被一起降级成哑巴(critic 抓到过)
except Exception:
    def hook_log(*a, **k):
        pass
try:
    from guard_common import trig
except Exception:
    def trig(x, n=120):
        return "trig=?"
try:
    from guard_common import strip_doc
except Exception:
    def strip_doc(t):
        return t
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return False
import sys, json, re

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "multi-option"
W = r".{0,1200}?"      # 选项间距窗口。v1 只有 400,而"每个方案配一段说明"的长报告
                       # (最需要评比表的那种)动辄相隔 500+ 字 → critic 实测 440 字就漏拦。

# ① 并列选项的形态 —— 有 CHOICE 兜底,这里可以放宽到 bullet/全角/英文
OPTION_PATS = [
    r"方案\s*[1１一]" + W + r"方案\s*[2２二]",
    r"选项\s*[1１一AＡ]" + W + r"选项\s*[2２二BＢ]",
    r"①" + W + r"②",
    r"(?:^|\n)\s*[-*•]\s*\*{0,2}\S" + W + r"(?:^|\n)\s*[-*•]\s*\*{0,2}\S",   # bullet(最常见)
    r"(?:^|\n)\s*[1１][.、)]" + W + r"(?:^|\n)\s*[2２][.、)]",                  # 编号(含全角)
    r"(?:两|三|四)\s*(?:条路|种(?:方案|做法|选择|路子)|个选择|个方案|个办法)",
    r"要么" + W + r"要么",
    r"\bOption\s*A\b" + W + r"\bOption\s*B\b",
]

# ② 【让他选】的信号 —— 真选择题必有;改动清单/步骤/findings 不会有。
#    这一条是 v2 的核心:它把"列举"和"让他选"区分开,替代了 v1 那个成为后门的步骤排除。
CHOICE = re.compile(                                 # ⛔ 必须 re.I:漏了它,"Which one" 大写就溜过去
    r"你(?:选|定|挑|来定|说了算|倾向|想要哪)|哪(?:个|条|种)(?:更|好|合适|适合|快|划算)?|"
    r"挑一个|二选一|选哪|要不要(?:改|换|用)|你的意见|你决定|看你|随你|"
    r"which\s+(?:one|is|do)|pick\s+one|your\s+call|up\s+to\s+you",
    re.I,
)

# ③ 评比要素 = 【我给出了判断】的痕迹。
# ⛔ 这里只能放"我在给答案"的措辞,绝不能放疑问句式。
#    v2 初版放了 `(?:哪个|该)(?:更好|选哪|怎么选)` → 与 CHOICE 语义重叠且方向相反:
#    「① 本地 ② 云端,哪个更好?」里那句"哪个更好"同时被认成【他在问】和【我在答】,
#    判据自己把自己放行,实测漏拦(回归 C3 抓到)。删掉,不留这种双关词。
CMP_TABLE = re.compile(r"\|[^\n]*\|[^\n]*\n\s*\|?\s*:?-{2,}")
CMP_WORDS = [
    r"适合(?:场景|谁|你|哪|什么|的人|的情况)",
    r"(?:区别|差别|不同)(?:是|在|:|：)",
    r"我(?:推荐|建议|选|的推荐)",
    r"(?:优|缺)点",
    r"什么时候(?:用|选)",
]

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`\n]+`")
_QUOTE = re.compile(r"^\s*>.*$", re.M)


def cmp_source(text):
    """给【评比判定】专用的源:剥掉代码块/行内代码/引用块,但【保留 markdown 表格行】。

    ⛔ 为什么不能直接用 strip_doc:它把表格行整个扔掉(guard_common.py:149
       `if s.startswith("|") or ln.count("|") >= 2: continue`)⇒ 我认真给了对比表反而被拦,
       正好惩罚正确行为(回归测试当场抓到)。
    ⛔ 也不能直接用原文:critic 实测,代码块里恰好有 `|---|`、注释里有"我推荐"、
       引用用户原话"哪个更好",都会被当成我给过评比 ⇒ 漏拦。
    正解是单独造一个源,让触发与豁免的剥法方向一致。"""
    t = _INLINE.sub(" ", _FENCE.sub(" ", text))
    return _QUOTE.sub("", t)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)                                  # fail-open

    try:
        # ⛔ 每轮复位(照抄 no-nagging-guard:244-247,v1 抄漏了这 4 行 —— critic 实测后果:
        #    拦过一次后同 session 整整 15 分钟全聋,「本轮」退化成「最近15分钟」)。
        if not data.get("stop_hook_active"):
            self_blocked_this_turn(NAME, turn_start=True)
        if self_blocked_this_turn(NAME):
            sys.exit(0)

        text = data.get("last_assistant_message") or ""
        # 门槛只挡极短噪音。v1 设 60,而 critic 实测「两条路:1.快照 2.改off,你选哪个?」只有 43 字 ——
        # 越短的甩锅式二选一越懒、越该拦,门槛反而把最该拦的放走了。
        if not isinstance(text, str) or len(text) < 25:
            sys.exit(0)

        body = strip_doc(text)                       # 找【选项】用剥净版
        hit = next((p for p in OPTION_PATS if re.search(p, body, re.S | re.M)), None)
        if not hit:
            sys.exit(0)
        if not CHOICE.search(body):                  # ② 没有"让他选"的信号 = 只是在列举,放行
            hook_log(NAME, "allow: options but no choice-signal", trig(hit))
            sys.exit(0)

        src = cmp_source(text)                       # 找【评比】用保留表格版
        if CMP_TABLE.search(src) or any(re.search(w, src) for w in CMP_WORDS):
            hook_log(NAME, "allow: choice with comparison", trig(hit))
            sys.exit(0)

        # 标记写不进去时 guard_common 返回 True = 这道闸已无循环上限,宁可这轮放行也不裸奔重拦
        if self_blocked_this_turn(NAME, mark=True):
            hook_log(NAME, "allow: mark unwritable, skip to avoid loop", "")
            sys.exit(0)
        hook_log(NAME, "block: choice without comparison", trig(hit))
        print(
            "⛔ 多选必评比闸:你这轮让 Frank【做选择】,却【没有评比】——他 2026-07-28 亲口钉死:"
            "「每当有多种选择都要给我自动回答:哪个更好、区别是什么、适合什么场景」,"
            "不该等他追问一次你才补。\n"
            "现在补上再收尾,三样缺一不可:\n"
            "  ① **区别**:一张对比表,逐维度列(成本/速度/风险/要不要他动手/可逆性…),"
            "数字必须是这轮真跑出来的;测不了的写「没测」,别含糊。\n"
            "  ② **适合场景**:每个选项配一句「什么情况下选它」,用他能感知的话"
            "(等多久/卡不卡/花不花钱/会不会误删)。\n"
            "  ③ **我的推荐**:直接给结论 + 一句理由,别把选择题原样丢回给零编程的他。\n"
            "⛔ 别忘了前一道:记忆 frank-default-answer-is-C-not-either-or —— "
            "先想「有没有第三条路能全都要」,有就别让他选。\n"
            "⛔ 别靠改措辞躲闸(把「你选哪个」删掉就放行)—— 那是绕过,不是交付。要么给评比,"
            "要么自己拍板直接干(授权即执行铁律:能 revert 的别问)。",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception:
        sys.exit(0)                                  # fail-open:闸自己坏了绝不挡路


if __name__ == "__main__":
    main()
