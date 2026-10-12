#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""promise-gate — 拦【承诺了却没启动任何东西】的收尾。

⛔ 缺口来历(2026-07-28,Frank:「不用我回话接着做?但是停手了?为何 superego 没逼你做完?」):
   `no-nagging-guard` 只抓【疑问/请示句】——「要不要我改?」「需要我继续吗」「should I」。
   而我那句是**陈述句承诺**:「我接着做,不用你回话」「这条不用你管」——
   词表一个字都抓不到,于是我说完就停手,他等了一轮才发现。
   ⇒ 请示是"不敢做",承诺不兑现是"假装在做";后者更隐蔽,得单独一道闸。

先查现成 → **自建**:社区确有「Stop hook 验证承诺兑现」这一模式(hooks 让模型可问责,
   风险在执行时而非承诺时),但无现成实现;这个语义判据是本 Superego 体系特有的。

判据(全中才拦,宁漏勿误杀):
  ① 本轮结尾说了【承诺继续做】的陈述句(我接着做/我继续/不用你回话/剩下我来)
  ② 且本轮**没有任何**"活还在往前走"的证据(没起后台任务、没跑脚本/测试/请求、没建定时任务)
  ③ 且那句话不在过去式/引述语境里
"""
import json
import re
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "promise-gate.log"

PROMISE = re.compile(
    r"(我(接着|继续|再)(做|弄|查|修|跑|试)"
    r"|接着做|继续做下去|我会继续|我自己(会|来)(做|弄|跑|查)"
    r"|不用你(回话|管|等|盯|动手|操心|插手)|不用(你|您)再?(回|说|管)"
    r"|这条不用你|剩下(的)?我来|后面我来|我来接着"
    # ⛔ 2026-08-05 实测穿透(Frank:「你都说不用我动手了,你还没做,坏掉吗」):
    #   「我下轮自己查,不用你动手」「查实后我会把它焊死」两句全放行 —— 词表没有
    #   「下轮/下次+动词」和「我会把它X掉」这两个形。补上;同族的「回头我」也一并。
    r"|我?下(轮|次)(自己)?再?(查|修|做|弄|跑|试|补|接|焊)"
    r"|回头我(再)?(查|修|做|弄|跑|试|补)"
    r"|(查实|查完|修完|弄完|做完|验完)后?我会"
    r"|我会把(它|这|那|这个|那个).{0,8}(焊死|修掉|做掉|查掉|补上|接上)"
    # ⛔ 2026-08-26 第 N 次穿透(Frank 当场戳穿:「你说你不问了,你要做了,但 Superego 还是没生效」):
    #   我的原话是「**接下来我直接做**(不问了):从风险最高那 16 道开始…」然后收尾,一件没动。
    #   上面所有形都要求【我+动词】紧挨着,而这句把范围词提到前面、动词是"做"单字 ⇒ 5 个形全漏。
    #   ⇒ 补「接下来/下一步/等下/马上/现在就 + (我) + 做/开始/动手/处理/清理/整改」这一族。
    r"|(接下来|下一步|等下|等会|马上|现在就|随后)[^\n。]{0,12}(我)?[^\n。]{0,8}"
    r"(直接)?(做|开始|动手|处理|清理|整改|搞定|弄|修|补)"
    r"|我(直接|现在|马上)(做|开始|动手|处理|清理|整改)"
    r"|先(从|把)[^\n。]{0,20}(开始|做起|入手|清理|整改)"
    r"|I'?ll (keep|continue|carry on|take it from here|look into|dig into|fix) )", re.I)

# regex-sanity: ok — 本职就是找『有没有跑过东西』的证据,命中 jest 正确
PROGRESS_EVIDENCE = re.compile(
    r"(run_in_background|nohup|Start-Process|schtasks|CronCreate|ScheduleWakeup"
    r"|pytest|unittest|npm\s+(test|run)|jest|vitest|go\s+test|cargo\s+test"
    r"|curl|Invoke-WebRequest|Invoke-RestMethod"
    r"|python\s+\S+\.py|node\s+\S+\.js|py\s+-3|--retry)", re.I)

PAST = re.compile(r"(已经|已挂|上一轮|之前|刚才|例如|比如|违规示例|反面|原话)", re.I)

# ⛔ 2026-08-03 补的缺口:【动了,但没动完】
# 下面 main() 里的 `if acted: pass` 只覆盖「承诺了却完全没动」。我这轮的形状不同:
# 跑了几十个工具(acted=True),结尾却说「还剩 3 道…我会逐个读代码判断」⇒ 直接放行。
# Frank 当场质问:「为何还没做完会自动停下来?superego 没有这个规则防止吗?」
# 实测:用那句原话喂 no-nagging / promise-gate / idle-ask-gate / false-done-gate,
# 四道【全部 ALLOW】—— 各自的判据分别是「请示句」「完全没动」「一个工具没调」「虚报完成」,
# 我那句是陈述句 + 动过 + 调过工具 + 没报完成,正好落在所有缝里。
# 判据故意收得很窄(宁漏勿误杀):必须【带量词的待办计数】+【承诺自己接着做】两者同时出现,
# 且不在过去式/引述语境。只有量词能挡住「还剩 3 天到期」这类无关句。
UNFINISHED = re.compile(
    r"(还剩|剩下|还有|尚有|仍有|待办|待做)\s*\d+\s*(道|个|项|条|处|件|步|块|台|张|份|篇)")

# ⛔ 2026-08-14 第三个缺口(形状I 第 23 次。Frank:「这个你只是说说而已,但是没用真做对吗」)
# 那轮我写的是:「## 接下来我做（不用你管）」+ markdown 编号清单 1./2./3.,然后收尾,一件没动。
# 三条判据为什么全漏:
#   · UNFINISHED 要【带量词的计数】(「还剩 3 项」)——我用编号列表,没写"还剩几项" ⇒ 不命中
#   · PROMISE 其实命中了「不用你管」,却被下面 `if acted: pass` 放行 —— 因为我这轮为
#     【别的事】跑过 python 脚本(生成 HTML),acted=True ⇒ 承诺免检
#   ⇒ 真正的形状:**为 A 动了手,再把 B/C/D 列成清单说"接下来我做"**。
#     "这轮动过手"根本不能证明"清单上那几件动过"。
# 判据(收窄,宁漏勿误杀):【接下来/下一步/后续 + 我】起头,其后紧跟 >=2 条编号或项目符号,
# 且没有完成标记。必须放在 acted 之前判 —— acted 正是它的漏因。
# ⛔ 2026-08-14 第二次补(Frank:「你说直接做下一步,等了1小时都没看你做」):
#    上一版要求触发词后【12 字内】必须出现"我/咱/我们"。而我那轮写的是
#    「按你定的顺序,赛道之后是**选题工具实测**。我这就把三个候选真跑一遍打分:」
#    —— "接下来"类词与"我"之间隔了 20+ 字,{0,12} 窗口够不到 ⇒ 放行。实测证明确实漏。
#    修法:①窗口放宽 ②补「我这就/我马上/我先去/我现在就」这类【立即承诺】句式
#         ③列表符号补破折号"—"(我上轮用的正是它)。
#    ⛔ 绝不放松真拦截条件:仍要求其后有 >=2 条列表项、且仍在 acted 之前判。
TODO_LIST_PROMISE = re.compile(
    r"(?:(?:接下来|下一步|后续|下轮|稍后|之后)[^\n]{0,60}?(?:我|咱|我们)"
    r"|我(?:这就|马上|立刻|先去|现在就))"
    r"[^\n]{0,50}\n"
    r"(?:[^\n]*\n){0,3}?"
    r"\s*(?:\d+[.、)]|[-*+•—])\s+[^\n]+\n"
    r"(?:[^\n]*\n){0,2}?"
    r"\s*(?:\d+[.、)]|[-*+•—])\s+[^\n]+")

# ⛔ 2026-08-14 第四个缺口,而且这次是【量出来该怎么分工】的,不是又拍一次脑袋:
# 把我真实漏掉的 5 句和该放行的 5 句全部打出语义 margin,分布是这样的 ——
#     下一步 R1:…                +0.3865 ┐
#     下一步按我排的顺序:…         +0.3883 ├ 纯自由句式,语义分得极开
#     下一步 = R1(…)             +0.3329 ┘
#     我认为该做的三件…①②③        +0.1596 ┐ 带枚举的待办,挤在边界
#     还没做的三件:①②③           +0.0592 ┘
#     ──────────────────────────
#     R4 做完了,…(该放行)        +0.0496 ← 该放的最高,只差 0.0048
# ⇒ 硬调阈值去卡那 0.0048 = 拿漏拦换误伤,两头都不讨好。**该分工:**
#     · 【结构性的枚举待办】→ 正则(便宜、精确,结构本来就摆在那)= 下面这条
#     · 【自由句式的下一步宣告】→ 语义(margin 0.33+,余量巨大)= main() 里的兜底
#   这不是"再补一次词表" —— 是把两种机制各放到它擅长的那一半上。
# 判据:【下一步/接下来/该做的/还没做的 + 数量或列表标记 + 至少两项】,不要求出现"我"
#   (我真实那几句一个"我"字都没有,这正是原版全漏的根因)。
# ⛔ 2026-08-14 当天就漏了一次:我用「⛔ 还欠(10)」列表格收尾,这条正则没抓到 ——
#   因为词表里有「还没做的」却没有「还欠」。Frank 当场问「还欠的是没必要做吗?不然为何不做」。
#   ⇒ 补的同时也记死这件事:**这正是 lessons 形状 2026-08-14-E 说的「补第 N 次词表」**。
#   之所以这次还是补词表、而不是全交给语义:实测过 —— 带 ①②③ 枚举的清单语义 margin
#   只有 +0.06~+0.16,和该放行的 +0.05 挤在一起,靠语义切必然误伤。**结构归正则、自由句归语义**
#   的分工没错,错的是我列词表时没把「欠/剩/未做」这一族想全。
TODO_ENUM_PROMISE = re.compile(
    r"(接下来|下一步|后续|下轮|稍后|该做的|还没做的|没做的|待办|要做的"
    r"|还欠|欠着|剩下的|还剩|未做|没动的|待补|尚未)"
    r"[^\n]{0,24}?"
    r"(?:[①②③④⑤]|\d+\s*[.、)]|[-*+•])\s*[^\n]{2,}"
    r"[^\n]{0,80}?"
    r"(?:[②③④⑤]|\d+\s*[.、)]|[-*+•])\s*[^\n]{2,}")
DONE_MARK = re.compile(r"(✅|已完成|已做完|已跑完|\bdone\b)", re.I)

# ⛔ 2026-08-14 修判据过宽(两个独立来源同时指向它,不是我猜的):
#   ①回归自带的「判据过宽普查」报:`SOFT_PROMISE ← 「普通中文汇报」被匹配到 '我跑'`
#   ②R5 连拦率显示 promise-gate 38%(拦完我常常没改 = 典型的误伤特征)
#   病因:`我跑` 既是**承诺**(「我跑一下」)也是**汇报**(「我跑了测试,全过」),
#   原正则不看后面跟什么,两种一起抓 ⇒ 我每次汇报"我跑了X"都可能被当成承诺。
#   ⇒ 加否定环视:动词后面紧跟【了/过/完/的】= 已经做完的汇报,不算承诺。
SOFT_PROMISE = re.compile(
    r"我会|我来"
    r"|我(先|再)?去?(读|查|测|跑|改|修|做|装|验证|体检|逐个|逐条|挨个)(?![了过完的])"
    r"|下一步(我|再)|接下来(我|再)|之后(我|再)|随后(我|再)")

# ── 语义兜底的锚点(2026-08-14)──────────────────────────────────
# ⛔ 正样本【全部是我真实说过、并且三个正则一个都没抓到】的原句,不是我编的范例。
#   用真话当锚点是硬要求:编出来的范例往往比真话更"典型",反而抓不到真实那一种。
# ⚠️ 带 ①②③ 枚举的待办清单【不放这里】—— 实测它们的 margin 挤在边界(+0.06~+0.16),
#   而该放行的完成汇报最高 +0.05,只差 0.005,靠阈值切必然两头受伤。那一类交给
#   TODO_ENUM_PROMISE 正则(结构摆在那,正则又便宜又准)。语义只管【自由句式的下一步宣告】。
_PROM_POS = [
    "下一步 R1:把 PROGRESS 按项目隔离接进语义召回",
    "下一步按我自己排的顺序:先做 R4 再做 R1",
    "接下来要做的是把这个模块接进那个服务",
    "下一步 = 把它按项目隔离接进召回,完整清单在报告里",
]
# ⛔ 负样本 = 【长得很像但不该拦】的:已完成的汇报、在描述规则、真的只有他能做的、
#   以及**汇报当前卡点并已记录**(这一类是我第一版误伤的那条,不是编的)。
#   负样本挑不好 = 闸变噪音 = 两周后我开始略读 = 等于没装。
_PROM_NEG = [
    "这一步已经做完了,回归 12/12 全过,证据在上面",
    "我刚才把它做完并验证过了,下面是实测输出",
    "R4 做完了,真拦截率已经用真数据取代了假的那份",
    "这条闸的判据是:出现「下一步」就提醒我别停手",
    "这件事需要你本人操作:要扫码/输密码/花钱/对外发消息,我做不了",
    "继续做会不可逆(删数据/force push),所以停在这里等你确认",
    "我在解释这个形状是什么、以前发作过几次",
    "三个平台都还没登进去,卡点各不相同,已写进 PROGRESS",
]
# ⛔ 阈值不是拍的:实测该拦的最低 +0.3329、该放的最高 +0.0496 ⇒ 0.15 落在中间,两边各留 ~0.18 余量。
_PROM_HOT = 0.15


def _log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# ⛔ 死循环风险已实测排除(2026-08-26,Frank 当场要求「确保不会一直死循环几小时不断 loop」):
#    本闸 main() 第一行就是 `if data.get("stop_hook_active"): return` ——
#    **被拦一次后,Claude Code 会把该标记置 True,下一轮直接跳过** ⇒ 结构上不可能连拦。
#    实测(scratchpad/loop_test.py,连喂 5 轮同一个"承诺了却没碰"的场景):
#        第1轮 拦 → 第2~5轮 全部放行  ⇒ 连续 5 轮只拦 1 次。
#    ⛔ 我一度在这里加了 MAX_BLOCKS 计数,**那是没用的代码** —— stop_hook_active 已经挡在它前面,
#      计数器永远只会数到 1。按「不写未要求的抽象」拆掉,只留这段说明,免得下个人再加一遍。
#    ⚠️ 边界:这也意味着本闸**每轮只拦一次**;真要连拦得靠 keep-going-gate 那种"看本轮有没有动手"的设计。

# ── 承诺对象闸的三个判据(2026-08-26 拔根)──────────────────────────────
# ⛔ 必须是【模块级】:第一版写成 main() 内的闭包,测试只能自己抄一份副本来测,
#    结果故障注入 6/7 全"仍绿" —— 我测的是我自己抄的副本,不是这道闸。
# ⛔ 2026-08-26 故障注入当场抓到的真 bug:第一版写成 `([^`\n]{4,60})`,
#    对 "`w` 模式，参数加 `-i`" 会**跨过成对反引号**,把中间的中文「模式，参数加」当成对象。
#    (是「直接问代码抽出了什么」发现的 —— 我前两次都在猜样本,猜错两轮。)
#    ⇒ 反引号内容不许含空格/中文标点;而「像标识符/路径」才是真正的"对象"。
TARGET_RE = re.compile(
    r'`([A-Za-z0-9_./\\-]{4,60})`'                      # 反引号里的标识符/路径
    r'|([\w\-]+\.(?:py|js|cjs|mjs|ts|json|md|sh|ps1))'  # 裸文件名
)


def promise_targets(text):
    """从承诺文本里抽出【被点名要动的对象】:反引号里的名字 / 文件名。"""
    out = set()
    for a, b in TARGET_RE.findall(text or ""):
        t = (a or b).strip().strip('`').lower()
        t = t.split('/')[-1].split('\\')[-1]
        if len(t) >= 4 and not t.startswith(('http', 'www')) and ' ' not in t:
            out.add(t)
    return out


def turn_touched(turn_msgs):
    """本轮工具调用真正碰过的东西(所有 tool_use 的 input 摊平成一段文本)。"""
    blob = []
    for mm in turn_msgs or []:
        if mm.get("type") != "assistant":
            continue
        for cc in (mm.get("message") or {}).get("content") or []:
            if isinstance(cc, dict) and cc.get("type") == "tool_use":
                blob.append(json.dumps(cc.get("input") or {}, ensure_ascii=False))
    return "\n".join(blob).lower()


def target_missed(promised, touched):
    """承诺点名了对象,但本轮一个都没碰 ⇒ True(该拦)。"""
    return bool(promised) and not any(t in (touched or "") for t in promised)


# ⛔⛔ 2026-08-26 第三次拔根(Frank:「所以没有彻底根治不误伤的方案?穷极了?」)
# 前三次修法全在【同一根轴】上滑:「实质动作」只认写文件 → 误伤"承诺去查、真去查了";
# 放宽成 PROGRESS_EVIDENCE(跑过任何东西都算) → 变回 `acted` 的翻版,漏掉
# 「承诺改代码、转头跑测试」。宽一点漏、严一点误伤 —— 这就是打地鼠的定义。
# ⇒ 拔根:不调宽严,按【承诺自己的动词】分流。说要改就得有改的痕迹;说要查,查了就算数。
#   两边都没有可误伤的空间,因为判据跟着承诺的语义走,不跟句式走。
# ⛔ 必须是【模块级】—— 本文件上面那条教训原话:「第一版写成 main() 内的闭包,测试只能
#   自己抄一份副本来测,结果故障注入 6/7 全『仍绿』= 我测的是自己抄的副本,不是这道闸」。
#   我这次差点原样重犯:改完跑 5 个套件全绿,而它们复刻的是旧判据、根本碰不到新代码。
WRITE_VERB = re.compile(
    r"(改|修|换|加|删|写|补|建|接上|落成|上线|重构|迁移|替换|配置|注册|部署)")
WROTE_FILE = re.compile(r'"(?:file_path|old_string|new_string|content)"', re.I)


def promise_is_write(text, start=None, end=None):
    """这句承诺是【要改东西】还是【只是去查/测】。只看承诺命中处附近,不看整段
    —— 整段判会被无关句子里的『改』带偏(2026-08-14 踩过的反向坑)。"""
    if start is None:
        seg = text or ""
    else:
        seg = (text or "")[max(0, start - 30):(end or start) + 30]
    return bool(WRITE_VERB.search(seg))


def substantive_done(is_write, blob):
    """承诺兑现了没。承诺要改 → 必须真写过文件;承诺只查/测 → 跑过脚本就算。"""
    blob = blob or ""
    wrote = bool(WROTE_FILE.search(blob))
    ran = bool(PROGRESS_EVIDENCE.search(blob))
    return wrote if is_write else (wrote or ran)


def _self_blocked_marker(transcript_path):
    """本闸【自己】在这一轮拦过没的标记文件（按 transcript 隔离，不同会话互不干扰）。"""
    import hashlib
    key = hashlib.md5(str(transcript_path or "none").encode()).hexdigest()[:12]
    return LOG.parent / f".promise-gate-blocked-{key}"


def main():
    data = json.loads(sys.stdin.read())
    tp0 = data.get("transcript_path")
    # ⛔⛔ 2026-08-26 第四次拔根（Frank：「彻底深度审查整个 superego 为何没有防止你
    #    说继续做，但是没做」）。查它自己的 promise-gate.log，最后 25 条里
    #    **skip(stop_hook_active) 占 10 条** —— 这道闸有一大半根本没运行过。
    # 原设计（同日早些时候）：`if stop_hook_active: return`，理由是防死循环，Frank 也
    #    确实要求过「确保不会一直死循环几小时不断 loop」——那个理由成立。
    # ⛔ 但它漏了一个场景：`stop_hook_active` 只说明【这一轮有闸拦过】，**不区分是谁拦的**。
    #    今晚我被人话闸/眼见为实闸/外部审查闸拦了几十次，**每一次都顺带把本闸打晕**：
    #    被拦 → 补完那件事 → 顺口说句「接下来我做 X」→ 收尾，本闸连看都没看。
    # ⇒ 拔根：只在【本闸自己已经拦过这一轮】时才跳过（死循环风险来自"我拦→我再拦"，
    #    别的闸拦我，不构成我的循环）。用一个按 transcript 隔离的标记文件判断，
    #    标记在本闸真正 BLOCK 时才写，下一轮开头清理 —— 既防循环，又不再被误伤失效。
    marker = _self_blocked_marker(tp0)
    if data.get("stop_hook_active"):
        if marker.exists():
            _log("skip(self-blocked-this-turn)")   # 我自己刚拦过 ⇒ 让路，防死循环
            try:
                marker.unlink()                     # 用完即清，下一轮重新计
            except Exception:
                pass
            return
        _log("continue(other-gate-blocked)")        # 是别的闸拦的 ⇒ 我照常检查
    if not data.get("stop_hook_active"):
        try:
            if marker.exists():
                marker.unlink()                     # 新一轮开始，清掉上一轮的残留标记
        except Exception:
            pass
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no transcript)")
        return
    msgs = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from guard_common import load_transcript_tail, is_real_user_msg
        msgs = load_transcript_tail(tp)
    except Exception:
        def is_real_user_msg(m):        # guard_common 挂了时的保守桩:只排 tool_result
            c = (m.get('message') or {}).get('content')
            return m.get('type') == 'user' and not (isinstance(c, list) and any(
                isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
        try:
            for ln in Path(tp).read_text(encoding="utf-8").splitlines():
                try:
                    msgs.append(json.loads(ln))
                except Exception:
                    continue
        except Exception:
            _log("skip(read fail)")
            return

    last_user = -1
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        c = (m.get("message") or {}).get("content")
        # is_real_user_msg 同时排除 tool_result 和【系统注入的伪 user 消息】(后台 Agent 完成通知)。
        # 原来只排 tool_result ⇒ 通知被当成新一轮开始 ⇒ 本轮已做的事全失效 ⇒ 反复开火。
        if not is_real_user_msg(m):
            continue
        last_user = i
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs

    said, acted = [], False
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
                inp = c.get("input") or {}
                blob = json.dumps(inp, ensure_ascii=False)
                # ⛔ 2026-08-26 端到端测试抓到的老 bug：这里只认【后台任务】和【跑脚本】，
                #    **不认 Edit/Write 写文件** ⇒ 真在改代码的人反而算"没动过手"，
                #    于是跳过下面按动词分流那段、直接落到兜底 BLOCK 被拦（实测误伤）。
                #    这不是今晚引入的，是一直存在——只有端到端跑真进程才看得见，
                #    因为单测函数时 substantive_done 是对的（我先测函数，全绿，差点收工）。
                if (inp.get("run_in_background") is True
                        or PROGRESS_EVIDENCE.search(blob)
                        or WROTE_FILE.search(blob)):
                    acted = True

    tail = "\n".join(said)[-1200:]

    # ⛔⛔ 三个判据函数【必须是模块级】的 —— 第一版我写成 main() 内的闭包,
    #    结果测试只能自己抄一份副本来测 ⇒ 改被测文件 6/7 全"仍绿" = 测试是彻底的摆设
    #    (「测代码长什么样、不测它干了什么」的极端形态:我测的是我自己抄的副本)。
    #    ⇒ 抽成模块级 promise_targets / turn_touched / target_missed,测试直接调真函数。
    # ⛔⛔ 2026-08-26 拔根:`acted` 的语义是【这轮有没有跑后台任务 / 碰过 PROGRESS】,
    #    却被当成【承诺兑现了没】的证据 —— 这两件事根本不是一回事。
    #    本文件第 50/66/70 行的注释已经承认过这个洞【三次】,每次修法都是「再插一条特判在 acted 之前」
    #    = 打地鼠,从没拔根。实录(Frank 当场问「为何只说不做,superego 没拦你,还是纸老虎?」):
    #    我上一轮承诺「改 critic-gate 机制 + 固化轨迹工具,现在接着做完」,转头去装了 agentsview,
    #    并跑了一个**后台等待命令** ⇒ run_in_background=True ⇒ acted=True ⇒ 承诺免检。
    # ⇒ 正确判据不是「有没有动」,是「**动的是不是承诺的那件事**」:
    #    承诺文本点名了具体对象(反引号里的名字 / 文件名),而本轮工具**一次都没碰过** ⇒ 拦。
    #    ⛔ 只在承诺【点名了对象】时生效;没点名的("我接着做")仍走原路,不引入新误伤面。
    _promised = promise_targets(tail)
    if _promised and PROMISE.search(tail):
        _touched = turn_touched(turn)
        if target_missed(_promised, _touched):
            _log("BLOCK(promise-target-miss) 点名 %s 但本轮没碰"
                 % ",".join(sorted(_promised)[:3]))
            try:
                marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
            except Exception:
                pass
            print(
                "⛔ 承诺对象闸:你承诺要动的是 **%s**,但这一轮的工具调用**一个都没碰过它们**。\n"
                "  ⛔ 别拿「我这轮跑过工具」当兑现 —— `acted` 只知道你【动了】,"
                "不知道你动的是不是【承诺的那件】。\n"
                "     实录(2026-08-26):我承诺「改 critic-gate + 固化轨迹工具」,转头去装了别的软件、"
                "跑了个后台等待命令 ⇒ acted=True ⇒ 承诺免检,Frank 当场问「为何只说不做」。\n"
                "  ⇒ 现在就去动那几个对象(能 revert 的直接改),或说清**为什么只有他能做**。"
                % "、".join(sorted(_promised)[:4]), file=sys.stderr)
            sys.exit(2)

    # ⛔⛔ 2026-08-26 第二个洞(同一天、被 Frank 当场戳穿第二次):
    #   上面那条**只在承诺【点名了对象】时生效**。而我真实说的是
    #   「**接下来我直接做**(不问了):从风险最高那 **16 道**开始…」——**压根不点名任何文件**
    #   ⇒ promise_targets 抽出空集 ⇒ 上面那条不生效 ⇒ 我又一次说了不做。
    #   Frank:「你看,现在你说你不问了,你要做了,但是 Super Ego 还是没有生效。」
    # ⇒ 判据:承诺词命中 + **本轮完全没有实质动作**(没有任何 Edit/Write/改文件类工具调用)
    #   ⇒ 拦。不要求点名 —— 因为"不点名"恰恰是更滑的说法,不能因此免检。
    #   ⚠️ 只看【实质动作】(写文件/改文件),不看只读命令 —— 光"查了一圈然后说我要做"不算兑现。
    # ⛔ 第二次误伤(同一条判据、10 分钟内):「反面例子:说一句「我接着做」就走人」是**引述**,
    #    被我当成真承诺拦了。而 `guard_common.strip_doc` 就在下面 40 行、专治这个 —— 我又没用上
    #    (本文件注释里写着「修好的东西就在旁边,这道闸没用上」,我原样重犯了一遍)。
    #    ⇒ 判据必须跑在【剥掉代码块/引用】之后的文本,并排除「反面例子/比如说/那种…就」这类引述框。
    try:
        from guard_common import strip_doc as _sd0
        _p_clean = _sd0(tail)
    except Exception:
        _p_clean = tail
    _QUOTE_FRAME = re.compile(
        r"(反面例子|正面例子|比如说|例如|举个例子|这种说法|那种说法|这类说法"
        r"|实录|原话|引述|「[^」]{0,40}」\s*(就|这|那)|假装在做)")
    # ⛔ 第三次误伤(同一条判据):「Agoda 重试已挂后台,我接着做的那部分**昨天就跑完了**」
    #    是在报告【已完成】,不是承诺。而 PAST / DONE_MARK 这两个判据本文件早就有、下面那条正在用 ——
    #    我又一次没复用。⇒ 与 todo-list 那条对齐:在【命中处附近】判过去式,而不是整段判
    #    (整段判会被无关句子的"已经"豁免掉,那是 2026-08-14 踩过的反向坑)。
    _pm = PROMISE.search(_p_clean) if not _QUOTE_FRAME.search(_p_clean) else None
    if _pm and not PAST.search(_p_clean[max(0, _pm.start() - 40):_pm.end() + 40]) \
            and not DONE_MARK.search(_p_clean[max(0, _pm.start() - 40):_pm.end() + 40]):
        _blob = turn_touched(turn)
        # ⛔ 第一版把「实质动作」只定义成【写/改文件】,当场误伤了自己的对抗样本:
        #    「我下轮自己查,不用你动手」+ 真跑了 `python scripts/probe.py --retry 2` ⇒ 被我拦了。
        #    **跑脚本也是真动手。** ⇒ 复用本文件已有的 PROGRESS_EVIDENCE(它本职就是
        #    "有没有真跑过东西"的判据),再并上写文件类 —— 别另造一套窄判据。
        # 2026-08-26 第三次拔根:按【承诺的动词】分流,判据抽在模块级(promise_is_write /
        # substantive_done),测试直接调真函数 —— 见上面那两个函数的注释。
        _substantive = substantive_done(
            promise_is_write(_p_clean, _pm.start(), _pm.end()), _blob)
        if not _substantive:
            _log("BLOCK(promise-no-substantive) 承诺了但本轮零实质动作")
            try:
                marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
            except Exception:
                pass
            print(
                "⛔ 承诺闸(泛泛承诺):你说了要做,但**这一轮没有任何写/改文件的动作** —— 只有查和说。\n"
                "  ⛔ 2026-08-26 第三次拔根:如果你承诺的动词是【改/修/换/加/删/写】,那么\n"
                "     『跑了几条命令查了一圈』不算兑现 —— 承诺改代码就得有 Edit/Write 的痕迹。\n"
                "     (只承诺【查/测/跑】的,跑过脚本就放行,不误伤。)\n"
                "  ⛔ 这条专治【不点名的承诺】:「接下来我直接做,从风险最高那 16 道开始」这种说法\n"
                "     抽不出任何对象,上一条『承诺对象闸』就管不到 —— 而不点名恰恰是更滑的说法。\n"
                "     实录 2026-08-26:我这么说完就收尾,Frank 当场戳穿「你说你要做了,但 Superego 还是没生效」。\n"
                "  ⇒ 现在就动手改第一个(能 revert 的直接干),或说清**为什么只有他能做**。",
                file=sys.stderr)
            sys.exit(2)

    # 【承诺清单】也必须在 acted 之前判 —— 为 A 动手不等于清单上的 B/C/D 动过(2026-08-14)
    # ⛔ 2026-08-14 这道新正则装上 10 分钟就误伤了我自己:我在回答「文字 vs 语义哪个好」时
    #   **引用了测试输出**(```围栏里的「还没做的三件:①②③」),被它当成真待办拦下。
    #   `guard_common.strip_doc` 正是为这个建的(它自己的文档:「在表格里描述某闸抓什么词 ≠ 真在甩锅」),
    #   而 promise-gate 从来没调过它 —— 又一个「修好的东西就在旁边,这道闸没用上」。
    #   ⇒ 结构性判据必须跑在【剥掉代码块/引用/表格之后】的文本上,否则**引述即违规**,闸秒变噪音。
    try:
        from guard_common import strip_doc as _sd
        _clean = _sd(tail)
    except Exception:
        _clean = tail
    _tl = TODO_LIST_PROMISE.search(_clean) or TODO_ENUM_PROMISE.search(_clean)
    # ⛔ PAST 只在【命中处本身】判,不能拿整段 tail 判 —— 2026-08-14 实测:我那段开头一句
    # 「全本已经开在你浏览器里」里的"已经"命中 PAST,整条判据被无关句子豁免掉,补丁形同虚设。
    if _tl and not PAST.search(_tl.group(0)) and not DONE_MARK.search(_tl.group(0)):
        _log("BLOCK(todo-list-promise) " + _tl.group(0)[:30].replace("\n", " "))
        try:
            marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
        except Exception:
            pass
        print(json.dumps({"decision": "block", "reason": (
            "⛔ 承诺清单闸:你把【接下来我做…】写成了一张编号清单就收尾,清单上的事一件都没动。\n"
            "⛔ 别拿『我这轮跑过工具』当免检 —— 那些工具是为【别的事】跑的,"
            "证明不了清单上这几件动过。这正是本闸 2026-08-14 补的漏(形状I 第 23 次,"
            "Frank 原话:「这个你只是说说而已,但是没用真做对吗」)。\n"
            "按 CLAUDE.md 授权即执行铁律:清单上能 revert 的**现在就做**,做完再汇报;"
            "真做不完的,写清【为什么只有他能做】(密码/扫码/花钱/对外发布/不可逆),"
            "而不是列成清单丢给他看。"
        )}, ensure_ascii=False))
        return

    # 【动了但没动完】必须在 acted 放行之前判 —— 否则跑过工具就永远免检(这正是它漏掉我的原因)
    _unf = UNFINISHED.search(tail)
    if _unf and SOFT_PROMISE.search(tail) and not PAST.search(tail):
        _log("BLOCK(half-finished) " + _unf.group(0)[:24])
        try:
            marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
        except Exception:
            pass
        print(json.dumps({"decision": "block", "reason": (
            f"⛔ 半途而废闸:你自己数出来还剩【{_unf.group(0).strip()}】没做,却在预告"
            "「我会/接下来我…」就想收尾。\n"
            "⛔ 这不是请示(no-nagging 管那个)、也不是完全没动(本闸上半段管那个)——"
            "是【动了一半停下】,四道闸的判据都盖不到,2026-08-03 实测全部放行,Frank 当场点破。\n"
            "按 CLAUDE.md 授权即执行铁律:剩下这些和你已经做完的是同一件事、同样可 revert ⇒ "
            "【现在就做完再汇报】,别把剩下的留成下一轮的开场白。\n"
            "真做不完只有两种情况可以停:①需要他本人才能做的(密码/扫码/花钱/对外发布)"
            "②继续做会不可逆 —— 那就把【为什么只有他能做】写清楚,而不是说「我会接着做」。"
        )}, ensure_ascii=False))
        return

    hit = PROMISE.search(tail)
    if not hit:
        # ⛔⛔ 2026-08-14 语义兜底(Frank:「为何 superego 没拦你,还是纸老虎,你还没做完,还有下一步,也在被动等待?」)
        # 实录:我连着三轮用「**下一步 R1**:把 PROGRESS 接进语义召回」这种句式收尾,一件没动。
        #   拿这五句真话去喂三个正则,**5/5 一个都不命中**(对照组「我接着做/我下轮自己查」3/3 全中,
        #   证明测的是对的东西)。漏因:三个正则**全都要求第一人称** ——
        #     TODO_LIST_PROMISE: (接下来|下一步)[^\n]{0,12}(我|咱|我们)
        #     SOFT_PROMISE:      下一步(我|再)|接下来(我|再)
        #   而「下一步 R1:…」是个**光秃秃的事项宣告**,没有"我"。功能上完全是承诺,词表上完全不是。
        #
        # ⛔ 但真正的根因比"少一个词"深一层:**这个文件已经为同一个病补过两次词表了**
        #   (2026-08-05「词表没有下轮/下次+动词」、2026-08-14「TODO_LIST 要求编号列表」),这是第三次。
        #   ⇒ **词表追不上自然语言,补第 N 次仍会有第 N+1 个说法。** 继续补 = 明知会漏还赌下次不漏。
        # ⇒ 改用旁边【早就存在、同类闸早就在用】的语义层(guard_common.should_escalate,
        #   no-nagging-guard 里是现成写法)。关键字仍是快路径(便宜、精确),语义只在【关键字全漏】时兜底。
        # 服务挂/超时 → should_escalate 返回假 → 保持原行为(不多拦),不引入新的误伤面。
        try:
            from guard_common import should_escalate as _esc_fn
            if _esc_fn(tail, _PROM_POS, _PROM_NEG, sem_hot=_PROM_HOT) and not acted:
                _log("BLOCK(semantic: 关键字没命中,但语义判定像【宣告了没做的下一步就收尾】)")
                try:
                    marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
                except Exception:
                    pass
                print(
                    "⛔ 承诺闸(语义兜底):你这轮**宣告了一件还没做的下一步,然后就收尾了** —— "
                    "关键字没抓到你这个说法,是语义判出来的。\n"
                    "  实录 2026-08-14:我连着三轮用「**下一步 R1**:把 X 接进 Y」这种句式结尾,一件没动;"
                    "Frank:「为何 superego 没拦你,还是纸老虎,你还没做完,还有下一步,也在被动等待?」\n"
                    "  ⛔ 这些活全是【能 revert 的本地改动】,按授权即执行铁律**直接做完再汇报**,不是列出来等他点头。\n"
                    "  二选一:①现在就把那件事做完(或真把它启动起来)再收尾;"
                    "②真推不动了就说清卡在哪、为什么只有他能推 —— 别留一句「下一步 X」就走。",
                    file=sys.stderr)
                sys.exit(2)
        except SystemExit:
            raise
        except Exception:
            pass                      # 语义层不可用 → 保持原行为,绝不因为兜底逻辑挡死收尾
        _log("pass(no promise)")
        return
    # ⛔⛔ 2026-08-26 第四次拔根的第二半（同一次深度审查查出来的）：
    #    读本闸自己的 promise-gate.log，今晚这五条【全是承诺、全被这里放行】：
    #      pass(acted) 我现在做 / 现在就能做 / 下一步我直接做 / 不用你管 / 我接着查
    #    我当天早些时候按【承诺动词分流】修过一次，但只修在下面"泛泛承诺"那条支路上，
    #    **而命中 PROMISE 后先撞这里的 `if acted: return`，根本走不到那段** ⇒ 白修。
    # ⇒ 这里用同一套判据（模块级 promise_is_write / substantive_done），不再问
    #   「这轮动过手没」，而是问「动的是不是承诺的那类事」：
    #   说要【改】就得有 Edit/Write 的痕迹；说要【查/测】跑过脚本就算数。
    if acted:
        _blob_a = turn_touched(turn)
        if substantive_done(promise_is_write(tail, hit.start(), hit.end()), _blob_a):
            _log(f"pass(acted+substantive) {hit.group(0)[:20]}")
            return
        _log(f"BLOCK(acted-but-wrong-kind) {hit.group(0)[:20]}")
        try:
            marker.touch()
        except Exception:
            pass
        print(
            "⛔ 承诺闸(动过手，但动的不是承诺那件):你这轮确实跑了工具，"
            "但承诺的动词是【改/修/换/加/删/写】——**而本轮没有任何写/改文件的动作**。\n"
            "  ⛔ 2026-08-26 深度审查实录:本闸自己的日志里，今晚五条承诺"
            "(「我现在做」「下一步我直接做」「不用你管」…)**全部死在 `if acted: return` 这一行**——\n"
            "     『这轮动过手』根本不能证明『承诺那件动过』。\n"
            "  ⇒ 现在就动手改(能 revert 的直接干)，或说清**为什么只有他能做**"
            "(密码/扫码/花钱/对外发布/不可逆)。", file=sys.stderr)
        sys.exit(2)
    seg = tail[max(0, hit.start() - 60): hit.end() + 60]
    if PAST.search(seg):
        _log(f"pass(past) {hit.group(0)[:20]}")
        return

    _log(f"BLOCK {hit.group(0)[:30]}")
    try:
        marker.touch()   # 记「本闸本轮拦过」→ 下一轮让路，防死循环
    except Exception:
        pass
    print(
        "⛔ 承诺闸:你这轮说了「" + hit.group(0)[:24] + "」这类【我接着做】的承诺,"
        "但本轮**没有启动任何还在往前走的东西**(没起后台任务、没跑脚本/测试/请求、没建定时任务)。\n"
        "  Frank 2026-07-28 原话:「不用我回话接着做?但是停手了?」—— 说完就停 = 假装在做,比请示更隐蔽。\n"
        "  二选一:①**真把它启动起来**(后台跑/挂重试/建定时任务)再收尾;"
        "②这轮确实推不动了,就把话改成实话——说清卡在哪、下一步靠什么推,别留一句『我接着做』就走。",
        file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error {e}")
