#!/usr/bin/env python3
"""Stop hook:【相对时间词 vs 绝对日期 自相矛盾】= 拦。纯算术判据,零语义。

2026-07-28 Frank 钉死:「我发现一个很大的bug,每次你和我说的时间都是错的,
是什么污染让你有这种误差,是哪里造成幻觉?」

实录(本次):vibe-spec 的 SKILL.md 写着 `2026-07-19`,当天是 `2026-07-28`(差 9 天),
我却在同一段话里写下「**去年** 7 月我扒的」+「然后**放了 9 天**没人回来填」
—— 9 天和一年不可能同时成立,**我自己的两句话互相打脸**。
第一手三方核实:①chat-archive `humanizerai` 2026-07-19 当天原话("派出去了…扒 4 个头部项目"
/"vibe-spec 技能 v2…6737字节");②SKILL.md 写 spec-kit"12万⭐"⇄ 当天实测 124.1k(9 天几乎没变;
若真隔一年该差一大截,且 spec-kit 2025-09 才发布、2025-07 根本不存在);③全库最早记录
2026-03-25、**零 2025 年记录**。⇒ 真实是 9 天前。

⛔ 根因(不是外部文件污染,是我内部两套时间感没对账):
  · 【上下文事实】系统每轮注入 `Today's date is YYYY-MM-DD` —— 我读得到,也真的拿它算出了"9 天"。
  · 【权重先验】训练语料里"现在是哪一年"的隐含分布停在更早 —— 生成**措辞**("去年/上个月")时,
    我不是每次都回去算,而是凭这个先验"感觉"一个词。
  · 两套并行、无人校验 ⇒ 同一段话里算术用事实、措辞用先验 = 本次这种自相矛盾。
  · 行业已确认同一机制(2026-07-28 检索):"LLMs do not share a consistent notion of 'now' —
    some backends are given the real-world date at inference time while others infer it from
    training priors" ⇒ 范式级缺陷,不是这台机器的配置问题。
  ⇒ 正解不是"提醒自己注意年份"(措辞是无意识生成的,提醒进不去),
    而是**把算术摆到输出后面强制对账一次** —— 这道闸。

⛔ 先查现成(2026-07-28,被 prior-art-gate 拦下两次后照做;第一次拦得对——我确实没查,
   第二次拦是因为**搜索词与要建的东西字面对不上**=它 2026-07-27 为形状Q「免死金牌漏洞」
   加的 topics 校验在正常工作,不是误伤):
  · `Time Judge`(PLTM-MCP 的 time_judge.py):"validates temporal consistency and detects
    time-based conflicts / temporal contradictions" —— **思想最对口**,但嵌在别人 MCP 项目里、
    非独立可安装库、非 hook 形态。
  · `whenis`:把日期解析移进确定性工具供 agent 调用 —— 治**输入侧**(要算"下周五"时调它);
    本次错在**输出侧**(我算对了 9 天、措辞却写"去年"),它管不到。
  · `Chronyk`:解析人写时间("10 minutes ago")—— 解析≠校验。
  · `gh search` 三组词零命中 hook 形态实现。
  · ⇒ 判定:**改造复用**(Time Judge 的矛盾检测思路 + whenis 的确定性算术)+ **落地自建**。

⛔ 为什么必须是可执行闸:lessons.md 里"去年"零记录、"时间线"零记录 —— 而 Frank 说的是
  「**每次**你和我说的时间都是错的」。用户观察到反复发生、我的免疫记忆里一次都没有
  = 这个形状一直在漏网(Superego 对时间类错误此前**零抗体**)。纯文字提醒治不了无意识措辞(形状P)。

━━ 判据(两条,都是纯算术,不需要理解语义) ━━
 A. 相对年份词 vs 绝对日期矛盾:窗口(±80字)内出现"去年/前年/今年/明年"且出现 YYYY 日期,
    按当前年换算该词应指的年份;窗口内**所有**日期都对不上才拦(有一个对得上就放行,防误伤)。
 B. 自相矛盾:同一窗口内既说"N 天/N 周"又说"去年/前年" —— 差一个量级以上,必错。

安全:fail-open(任何异常放行);只读;strip_doc 先剥掉代码块/引用/表格(引用别人原话里的
"去年"不算我犯);per-turn 只拦一次(self_blocked_this_turn)。
回归:`test_time_sanity.py`(含本次真实错误原文作为 repro)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ⛔ 逐个 import 带兜底:打包成一条时只要少一个名字,完好的其它函数会被一起降级成哑巴
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k): pass
try:
    from guard_common import strip_doc
except Exception:
    def strip_doc(t): return t
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k): return False
try:
    from guard_common import trig
except Exception:
    def trig(s, n=120): return (s or "")[:n]

import sys, json, re
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "time-sanity"
WIN = 80          # 邻近窗口(字符)

# 相对年份词 → 相对当前年的偏移。⛔ 2026-07-28 补 critic 点名的两个零覆盖盲区:
#   L6 月级词("上个月/前阵子")、L7 英文("last year")。月级词按 0 处理(同年),
#   它与"N 天"不构成年量级矛盾,但与【年份对不上的日期】仍构成矛盾 → 判据 A 能抓。
REL_YEAR = {
    "前年": -2, "去年": -1, "旧年": -1, "今年": 0, "本年": 0, "明年": 1, "后年": 2,
    "上个月": 0, "上月": 0, "下个月": 0, "下月": 0, "前阵子": 0, "前几个月": 0,
    "last year": -1, "the year before": -2, "this year": 0, "next year": 1, "last month": 0,
}
REL_RE = re.compile("|".join(sorted(REL_YEAR, key=len, reverse=True)), re.I)
# ⛔ 2026-07-28 外部 critic 抓到的崩溃:REL_RE 用 re.I 匹配,但下面按 m.group(0) **精确查表**
#   ⇒ "Last year"(句首大写=英文最常见写法)直接 KeyError → 被 main 的 except 吞掉 →
#   **整道闸对那条消息静默死亡**(连同一条里的中文矛盾一起失效)。查表一律先 .lower()。
# 绝对日期:2026-07-19 / 2026/07/19 / 2026年7月 / 2026-07 / 2026.07.19(critic-L4 原本漏)
DATE_RE = re.compile(r"(20\d{2})\s*[-/年.]\s*\d{1,2}")
# 短间隔:N 天 / N 周("9 天"),含中文数字(critic 造的 L5「也就九天」原本漏拦)
SHORT_RE = re.compile(r"(?:\d{1,3}|[一二两三四五六七八九十几半])\s*(?:天|日|周|礼拜|星期)")
# 断句:只按句末标点切,**不切逗号** —— 本次真错误原文正是靠逗号连起来的一整句
# regex-sanity: ok — 分句用的,命中换行是它的本职
SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")
# ⛔ 2026-07-28 上线当天就误伤我自己:我在【复盘描述】这个错误(引用「去年」「9 天」当例子),
#    被判成【正在犯】。同 SUPEREGO 记载的老病根「分不清描述一个模式 vs 执行它」。
#    修法两条(都只缩小触发面,不给整段免检——避免 EXEMPT 全文短路那种后门):
#    ① 窗口内出现否定/纠正语("不是去年"/"错了"/"纠正")→ 这是在澄清,不是在犯。
#    ② 中文直角引号「」内容按引用剥掉(和 strip_doc 剥 markdown 引用同理)。
#       真犯错时是自然叙述("去年 7 月我扒的"),不会给自己加引号。
NEG_RE = re.compile(r"不是|并非|而非|≠|纠正|误写|误报|说成|错的|错了|打脸|矛盾|自相")
QUOTE_RE = re.compile(r"[「『][^」』]{0,40}[」』]")


def _window(text, m):
    lo = max(0, m.start() - WIN)
    hi = min(len(text), m.end() + WIN)
    return text[lo:hi]


def check(text, today=None):
    """返回 (是否违规, 说明)。纯函数,便于回归测试。

    ⛔ 2026-07-28 外部 critic 审查后大改。**删掉两个后门**:
      · **NEG_RE 窗口豁免**:critic 造的真错误里 L1/L2 只要句中随便出现一个「不是/矛盾」
        就整段免检 —— 那是后门不是豁免。
      · **QUOTE_RE 剥引号**:L3 证明给「去年」加一对引号就能躲闸,而闸自己写着"别改措辞躲闸";
        且它只认直角引号「」、真实文本用全角"",补全角也治不了根。
    **判据 A 保留**(critic 证明它误报高:5 条正常文本全中,"去年的账我核完了,今天 2026-07-28
      开始核今年的"这种 Frank 日常口吻会被打中)。留它的理由是**档位变了**:整道闸已降成
      计量档(见 main),误报的代价 = 日志里多一行,而不是打断交付。既然要靠日志决定
      "将来升不升 block",就该让两条判据都留下真实数据、分别评估,而不是凭我拍脑袋先砍一条。
      ⇒ 返回值带 kind(A/B),日志分类记,两周后分别算准确率。
    """
    today = today or date.today()
    t = strip_doc(text or "")
    # ⛔ 2026-07-28 补 critic 盲区④:`strip_doc` 会把表格行整行剥掉(它是给别的闸防误伤用的),
    #   而 Frank 的交付**大量用表格** ⇒ 写在表格里的时间错误此前 100% 漏检。
    #   这里把原文的表格行单独接回来一起扫。计量档下多扫的代价 = 日志多一行,划算。
    tbl = "\n".join(l for l in (text or "").splitlines() if l.lstrip().startswith("|"))
    if tbl:
        t = (t + "\n" + tbl) if t else tbl
    if not t:
        return False, "", ""

    # ── 判据 B(同一句内 相对年份词 × 短间隔 = 真·量级矛盾;本次真实错误就是这条抓到的)
    for sent in SENT_SPLIT.split(t):
        m = REL_RE.search(sent)
        if not m or REL_YEAR[m.group(0).lower()] == 0:
            continue
        sh = SHORT_RE.search(sent)
        if sh:
            return True, "B", (f'同一句里既说「{m.group(0)}」(差 {abs(REL_YEAR[m.group(0).lower()])} 年)'
                               f'又说「{sh.group(0)}」—— 量级对不上 · 今天 {today}'
                               f' · 触发句: {trig(sent.strip(), 60)}')

    # ── 判据 A(相对年份词 vs 邻近绝对日期年份换算;误报率高,仅计量)
    for m in REL_RE.finditer(t):
        word = m.group(0)
        win = _window(t, m)
        want = today.year + REL_YEAR[word.lower()]
        years = [int(y) for y in DATE_RE.findall(win)]
        if years and all(y != want for y in years):
            return True, "A", (f'「{word}」应指 {want} 年,但邻近日期是 {sorted(set(years))}'
                               f' · 今天 {today} · 触发处: {trig(win.strip(), 60)}')

    return False, "", ""


# ── 第二类判据:【复述陈旧的"现在"】(2026-07-29 Frank「我明明都已经恢复了他,为何你没有检查完整
#    看到最新消息?有Bug?」当场抓到)──────────────────────────────────────────────
# 实录:我 08:39 查了一次消息库,看到客人 08:25 发的紧急退房没人回。之后 **1 小时 20 分钟里
# 每一轮结尾都复述"客人从 08:25 等到现在(3.5 小时)"** —— 而 Frank **09:00 就回了**、
# 客人 09:01 回"Perfect 👍🏻",早就闭环。我制造了整整一小时的假紧急感。
# ⛔ 这不是系统 bug,是【查过一次就一直当事实复述】—— 我自己钉过的"别拿工具输出当事实"的变种:
#    第一次查是对的,**错在没重查就继续用**。
# 判据(两条同时成立才记):①在断言"某人还在等/还没处理"且带具体时刻或时长;②本轮**零查询动作**。
# ⛔ 窄到只管【人还在等】这一类,不碰其它时间表述 —— 泛化的时效判据必然变噪音闸(我今天已学到)。
WAITING_CLAIM = re.compile(
    r"(?:客人|房东|清洁|对方|他|她)[^。\n]{0,12}(?:还在等|仍在等|等了|等到现在|没人(?:处理|回)|还没(?:人|有人)?回)"
    r"|从\s*\d{1,2}[:：]\d{2}\s*等到(?:现在|目前)"
    # ⛔ 这条原本【不要求主语】,于是任何"等了 N 分钟"都中。2026-07-29 critic 回放真实 transcript:
    #   唯一一次开火是假阳性——「刚才那次等了 4 分钟你没看到(Google 两步验证通知)」,跟"客人在等"无关。
    r"|(?:客人|房东|清洁|对方|他|她)[^。\n]{0,12}等(?:了|到现在)\s*(?:快|约)?\s*\d+(?:\.\d+)?\s*(?:分钟|小时|个小时)",
)
# 查过消息库 = 这个"现在"有据可依。
# ⛔⛔ 2026-07-29 critic 判【「动作 vs 产物」老病的完整复发】,实测证据(回放 48 轮真实 transcript):
#   开火 1 次(还是假阳性)、真阳性 0、**漏报 4/4** —— 我今天那句"客人从 08:25 等到现在"
#   正则抓得到,却全被豁免掉。time-sanity.log 里零条 NUDGE stale-now = 这道判据上线至今从没开过火。
#   两个病因,都比我自己担心的("只 ls 一下也算查过")更糟:
#   ① 匹配的是【整个 input blob】⇒ Edit 正在写的源码内容(23 次)、发给子 agent 的散文(6 次)都算"查过"。
#      关键词命中排行榜首是 `disconnect.log` 19 次 —— 那是源码里的一个日志文件名,跟查询毫无关系。
#   ② ⛔ 最讽刺:**这道闸的源码里含有它自己的豁免口令** —— nudge 文案里写着 `select … from msg`,
#      于是【任何编辑 time-sanity-guard.py 的轮次自动免检】。豁免基础率 38%(18/48 轮)。
#   → 收窄成"真的读了消息表",且只扫 shell 命令(不扫源码/散文)。critic 实测:1火/0真 → 4火/3真/1假,
#     再给 WAITING_CLAIM 第三条补主语后 = 3火/3真/0假。
FRESH_LOOKUP = re.compile(r"wa_live\.db|from\s+msg\b", re.I)
_SHELL = {"Bash", "PowerShell"}


def _stale_waiting(turn_msgs, text):
    """本轮在报"某人还在等",但没重查过数据源 → 这个'现在'可能是上一轮的。"""
    if not WAITING_CLAIM.search(text or ""):
        return None
    for m in turn_msgs or []:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                if c.get("name") not in _SHELL:
                    continue               # 只认真正【跑】了查询的;写源码/发散文不算
                cmd = str((c.get("input") or {}).get("command", ""))
                if FRESH_LOOKUP.search(cmd):
                    return None            # 本轮真查过,放行
    mm = WAITING_CLAIM.search(text)
    return mm.group(0)[:60] if mm else None


# ⛔⛔ 2026-09-05 新增一层:【拿 UTC 时间戳当本地时间比,得出"断更/落后 N 小时"的假结论】
#   实录(同一天犯 2 次):
#   ① chat-archive 最新记录 `2026-09-05T05:53Z`,我看本地 13:55 ⇒ 断言"断了 8 小时"
#      —— 实际那是 UTC,当时 UTC 正好 05:5x,**根本没断,差的整整是时区**。
#   ② 同步日志最后一条 `10:45:17Z`,我又说"断了"—— 当时 UTC 10:50,**只差 5 分钟**。
#   本机在 UTC+8,所以**任何存 UTC 的时间戳看起来都会比本地"晚 8 小时"** ——
#   这正好落在"断更了"的错觉区间里,而且两次我都当成了故障去查。
#   ⇒ 判据(纯算术,零语义):文中出现【落后/断了/停在/没更新 + 约 7~9 小时】这种说法,
#     而本轮**没有任何一次换算时区的动作**(没出现 utcnow/gmtime/UTC/时区/timezone)⇒ 拦。
#   ⛔ 只拦 7~9 小时这个窄区间 —— 那正是 UTC+8 的时差;真的断 2 小时或 3 天不受影响。
_TZ_GAP = re.compile(
    r"(?:落后|断[了更]|停在|没(?:有)?更新|滞后|差(?:了)?)[^。\n]{0,24}?"
    r"([7-9])\s*(?:个)?小时"
    r"|([7-9])\s*(?:个)?小时[^。\n]{0,12}?(?:没(?:有)?更新|断|落后|滞后)")
_TZ_AWARE = re.compile(
    r"utcnow|gmtime|utctimetuple|timezone|astimezone|UTC|世界时|时区|\+08|GMT", re.I)


def _tz_blind_gap(turn_msgs, text):
    """说"落后 7~9 小时"但本轮没换算过时区 ⇒ 返回命中片段(极可能是把 UTC 当本地读)。"""
    m = _TZ_GAP.search(text or "")
    if not m:
        return None
    if _TZ_AWARE.search(text or ""):
        return None                      # 自己已经提到时区/UTC ⇒ 说明算过了,放行
    for msg in turn_msgs or []:
        if msg.get("type") != "assistant":
            continue
        for c in (msg.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                blob = str(c.get("input") or {})
                if _TZ_AWARE.search(blob):
                    return None          # 本轮真跑过换算 ⇒ 放行
    return m.group(0)[:60]


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)                                   # fail-open

    try:
        if not data.get("stop_hook_active"):
            self_blocked_this_turn(NAME, turn_start=True)   # 新一轮:清自己的旧标记
        if self_blocked_this_turn(NAME):
            sys.exit(0)                               # 本轮我已拦过,不连拦第二次

        text = data.get("last_assistant_message") or ""
        if not text:
            sys.exit(0)

        # 第二类判据:复述陈旧的"现在"(见上方 WAITING_CLAIM 的实录)
        try:
            from guard_common import load_transcript_tail
            _msgs = load_transcript_tail(data.get("transcript_path") or "") or []
            _lu = -1
            for _i, _m in enumerate(_msgs):
                if _m.get("type") != "user":
                    continue
                _c = (_m.get("message") or {}).get("content")
                if isinstance(_c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in _c):
                    continue
                _lu = _i
            _stale = _stale_waiting(_msgs[_lu + 1:] if _lu >= 0 else _msgs, text)
        except Exception:
            _stale = None
        if _stale:
            hook_log(NAME, "NUDGE stale-now", trig(_stale, 80))
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
                f"⏱ 陈旧的『现在』:你这轮说了「{_stale}」,但**本轮没有重查过消息库/接口** ——"
                "这个『现在』可能是上一轮甚至更早查到的。\n"
                "⛔ 实录(2026-07-29 Frank 当场抓到):我 08:39 查了一次,看到客人 08:25 的紧急退房没人回,"
                "然后**接下来 1 小时 20 分钟每轮都复述「客人从 08:25 等到现在」** —— 而他 09:00 就回了、"
                "客人 09:01 回了 Perfect,早就闭环。我制造了整整一小时的假紧急感。\n"
                "⇒ 报「谁还在等/还没处理」之前,**重查一次**(select … from msg order by ts desc),"
                "或者把话改成「我 XX:XX 查的时候还没回,现在没重查」。"
            )}}, ensure_ascii=False))
            sys.exit(0)

        # ⛔ 2026-09-05:同族的第二种时间错 —— 把 UTC 时间戳当本地时间读,凭空得出"断更 8 小时"。
        #   放在这里(与 stale-now 并列),因为它同样是"我把时间读错了",而不是措辞矛盾。
        try:
            _tz = _tz_blind_gap(_msgs[_lu + 1:] if _lu >= 0 else _msgs, text)
        except Exception:
            _tz = None
        if _tz:
            hook_log(NAME, "NUDGE tz-blind-gap", trig(_tz, 80))
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": (
                f"⏱ 时区盲区:你这轮说了「{_tz}」,但**本轮没有任何一次换算时区** ——\n"
                "⛔ 本机在 UTC+8,凡是存 UTC 的时间戳(数据库 ts、同步日志、API 返回)\n"
                "   看起来都会比本地时间**晚整整 8 小时** —— 这正好落在你说的那个区间里。\n"
                "⛔ 实录(2026-09-05 同一天犯 2 次):\n"
                "   ① 聊天档案最新记录 `05:53Z`,我看本地 13:55 ⇒ 断言「断了 8 小时」,\n"
                "      实际当时 UTC 正好 05:5x —— **根本没断,差的整整是时区**;\n"
                "   ② 同步日志最后一条 `10:45Z`,我又说「断了」—— 当时 UTC 10:50,**只差 5 分钟**。\n"
                "   两次我都当成故障去查,浪费的是他的时间。\n"
                "⇒ 下结论前先跑一句换算:\n"
                "   `py -3.12 -c \"import time;print('UTC',time.strftime('%H:%M:%S',time.gmtime()),"
                "'本地',time.strftime('%H:%M:%S'))\"`\n"
                "   两个时间都摆出来再比,或者把话改成「按本地时间看差 8 小时,还没换算时区」。"
            )}}, ensure_ascii=False))
            sys.exit(0)

        bad, kind, why = check(text)
        if not bad:
            sys.exit(0)

        # ⛔ 2026-07-28 外部 critic 后【降成计量档】:原本首版就上了 block,而我在【同一天】
        #    刚给自己定下"新闸首版一律 nudge、拿真实误伤率再升 block"的规矩 —— critic 原话:
        #    「同一天定的规矩,同一天没对自己执行」。它随后用 5 条正常文本 + 本 session 47 条
        #    真实语料证明 block 档会反复打断正常交付。⇒ 现在只记日志、绝不阻塞。
        #    升 block 的前置条件(缺一不可):①`time-sanity.log` 攒够两周真实触发
        #    ②误报率可算且低 ③接上 guard_common.should_downgrade 语义层兜住残余误报。
        hook_log(NAME, "METRIC time contradiction", trig(why, 160))
        sys.exit(0)
    except Exception:
        sys.exit(0)                                   # fail-open:闸自己坏了绝不挡路


if __name__ == "__main__":
    main()
