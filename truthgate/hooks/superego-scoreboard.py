#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Superego 记分板 —— 闸的【measure + improve】那一半。

跑法:
    py -3.12 ~/.claude/hooks/superego-scoreboard.py            # 全部历史
    py -3.12 ~/.claude/hooks/superego-scoreboard.py --days 7   # 最近 7 天
    py -3.12 ~/.claude/hooks/superego-scoreboard.py --json     # 机器读

⛔ 为什么必须有它(2026-09-06,Frank 原话):
   「已经迭代了3个月没有一点进步还是要我每天都改…**这么久了,数据应该很够了**,
     而且没有一点长进…很多时候变成了累赘的工具」
   他两句都对,第二句是对第一句的诊断。当天量出来的真相:

     · 真实开火日均: 2026-07 **182** → 08 **98** → 09 **128**  —— 三个月没有下降
     · 聚合统计 `hook-stats.jsonl` **只留 5 小时**,另有 190+ 个 `.lost.<PID>.log`(写失败丢的)
     · 11,619 次开火里 **2,593 次(22%)是跑回归写进去的**(已于同日分流修掉)
     · **43% 的开火没留触发词** ⇒ 事后无法判断那次是真拦还是误伤

   ⇒ **只有 enforce,没有 measure,没有 improve** —— 这就是"三个月没进步"的机制。
   行业把这一条点名为规则式护栏的头号死因:
     "Security teams can't identify patterns in false positives,
      can't refine rules based on actual usage"
     "A Guardrails Feedback Loop = boundaries are enforced, **measured, and improved** over time"

⛔ 它【不】做的事(老实说):
   · 判不了"这次拦得对不对" —— 那要理解语义。它给的是**嫌疑排序**,由人/我去看。
   · 只读 `<gate>.log`(生产),不读 `.test.log` —— 分流之前的历史数据仍混着测试,
     所以带 `--days` 看近期才干净。
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATE = re.compile(r"^(20\d\d-\d\d-\d\d) (\d\d:\d\d:\d\d)")
PROJ = re.compile(r"\[([^\]|]+)\|")
FIRE = re.compile(r"\bBLOCK\b|\bDENY\b|\bNUDGE\b|⛔", re.I)
# ⛔⛔ 2026-09-09:光靠 FIRE 会把【放行日志】误判成开火 —— 实测 `nudge-escalation-gate`:
#   FIRE 判定 538 次开火、521 次"无证据",而其中 **507 次是 `allow(no-hot-nudge)`**
#   —— `\bNUDGE\b` 把 "no-hot-**nudge**" 匹配上了。真正的开火 BLOCK 只有 14 次。
#   后果不是数字难看,是**它生成了一份假的待办清单**:「10 道闸开火却不留证据」——
#   我(2026-09-09)差点照着它逐个去改 8 道本来没问题的闸。
#   ⇒ 判"开火"前先排除明确的放行/跳过动作。这是【尺子自己坏了】,不是被测对象的问题。
NOT_FIRE = re.compile(r"\b(?:allow|pass|skip|ok|clean|silent|noop)\s*\(", re.I)


# ⛔ 2026-09-11 修坏尺子:原来只认 `trig='...'` 一种格式 ⇒ 把证据【写在消息正文里】的闸
#   全判成"没留证据"。实证:launch-bound-guard 的 `DENY:train_raw.py miss=显存封顶(...)`
#   证据俱全,却被算进"99% 无证据",每日体检据此天天报警 —— 报的是假的。
#   ⇒ 判据改成"这行有没有可供事后复核的具体内容",而不是"有没有用某个字段名"。
_ACT_TAG = re.compile(r"\b(?:BLOCK|NUDGE|DENY|WARN|FIRE|ESCALATE)\b[^\s]*\s*[:：(]?", re.I)


def _has_inline_evidence(ln, min_chars=16):
    """动作词之后还带着 >=min_chars 个实质字符(不含纯标点/空白) = 这行是可复核的。"""
    m = _ACT_TAG.search(ln)
    if not m:
        return False
    rest = ln[m.end():].strip()
    rest = re.sub(r"[\s:：()\[\]{}<>,，.。;；'\"|/\\-]+", "", rest)
    return len(rest) >= min_chars


def is_fire(line):
    """这行日志是不是【真的开火】。⛔ 放行/跳过即使字面含 nudge/block 也不算。"""
    return bool(FIRE.search(line)) and not NOT_FIRE.search(line)
# 这条日志【干了什么】—— 取时间戳/项目标记之后的第一个动作词。
# ⛔ 2026-09-07:光有 FIRE 不够。SKIP/allow/pass 也是行为,只认 FIRE 会把它们当成"没有行为"。
# ⚠️ 两种格式都要认:带 `[项目|会话]` 的(多数闸),和时间戳后直接跟动作词的(turn-budget 就是)。
#   只认第一种的话,turn-budget 那 2344 条 SKIP 会显示成"日志没有动作词" —— 又是一次
#   「判据只认自己见过的形状」。
ACT = re.compile(r"\]\s*([A-Za-z][\w-]{1,20})")
ACT2 = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\s+([A-Za-z][\w-]{1,20})")
TRIG = re.compile(r"trig='([^']{0,80})")
FP = re.compile(r"fp=([0-9a-f]{6,})")


# 真会话号 = 8 位十六进制;夹具用的是 sess-xxx / t1 / probe 这类。
_REAL_SESS = re.compile(r"^[0-9a-f]{8}$")
FIXTURE = collections.Counter()


def _is_fixture(ln):
    """这一行是【测试夹具】写进来的吗?没有会话标记的一律当真(宁可算多,不许算少)。

    ⛔⛔ 2026-09-08 补【项目名】那一半 —— 它是当晚最贵的一个错的根源:
      本函数原来只看**会话号形态**。而测试夹具常常是"真会话号 + 临时项目目录"
      (`tempfile.mkdtemp()` 造出来的 `tmpa2hbetvx`)⇒ 一条都滤不掉。
      后果:`already-known-guard` 被报成「开火 184 次、100% 开火率」,
      我据此向 Frank 汇报「我还在踩的坑第一名是话多」——
      **那 184 条全是另一个项目跑测试写进来的夹具(内容是 Airbnb 抽成),一条都不是我的。**
      我还据此下了结论「这三样加闸治不好」。**拿夹具当病症,比没数据更糟。**
    ⇒ 判据不再自己抄:直接调 `guard_common.is_fixture_project`(唯一出处)。
      今晚第 5 次「同一条规则存两份」,这次的代价是一个错误的自我诊断。
    """
    m = re.search(r"\[([^\]|]*)\|([^\]]*)\]", ln)
    if not m:
        return False
    proj, sid = m.group(1).strip(), m.group(2).strip()
    if not _REAL_SESS.match(sid):
        return True
    try:
        from guard_common import is_fixture_project
        return is_fixture_project(proj)
    except Exception:
        return False


def collect(days=None, since=None):
    """days=最近 N 天;since=从某个【时刻】起(精确到小时/分钟)。

    ⛔⛔ 2026-09-08 加 since 的理由(当晚被同一个陷阱骗了两次,两个尺度各一次):
      我早上修好了指纹算法、傍晚加了自动补记账。之后跑记分板:
        · `--days 14` → 报「4 道误伤嫌疑」(critic-gate 同一指纹 389/594、跨 37 个项目)
        · `--days 1`  → 报「3 道开火不留证据」(launch-bound-guard 165 次、99% 无证据)
      两次我都差点据此去改**好闸**。逐小时一数才看清:
      那 164 条无证据开火**全部集中在 09:00 那一波**(修复之前),
      而修复之后唯一那次开火是**带证据的**。
      ⇒ 病根不在闸,在**这把尺子说不出「修复之后」这句话** —— 它只能按天切,
        而修复落在半天中间。⇒ 加 --since,并且把窗口打印在抬头上,让读的人一眼看见口径。
    """
    cutoff = None
    if days:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    if since:
        since = since.replace("T", " ").strip()
    gates = collections.defaultdict(lambda: {
        "calls": 0, "fires": 0, "no_trig": 0, "acts": collections.Counter(),
        "projs": collections.Counter(), "fps": collections.Counter(), "days": set()})
    for f in sorted(os.listdir(HERE)):
        if not f.endswith(".log") or f.startswith("hook-stats") or f.endswith(".test.log"):
            continue
        gate = f[:-4]
        try:
            fh = open(os.path.join(HERE, f), encoding="utf-8", errors="replace")
        except Exception:
            continue
        with fh:
            for ln in fh:
                m = DATE.match(ln)
                if not m:
                    continue
                day = m.group(1)
                if cutoff and day < cutoff:
                    continue
                # 时间戳是 `YYYY-MM-DD HH:MM:SS` 定长开头,按字符串比就是按时间比
                if since and ln[:len(since)] < since:
                    continue
                # ⛔⛔ 2026-09-07:把【测试夹具写进来的行】剔掉,别当成真实开火。
                #   实录:我读 stagnation 的影子日志,报出「8/8 真实开火」——
                #   那 8 条全是我自己用 `sess-sta` 这个假会话号造的夹具。
                #   **拿自己的测试数据当现实证据**(形状 -N),而它长得和真数据一模一样。
                #   判据:标记形如 `[项目|会话]`,真会话号是 8 位十六进制(如 deb7634c);
                #   夹具用的是 sess-xxx / t1 / probe 这类,一眼分得开。
                if _is_fixture(ln):
                    FIXTURE[gate] += 1
                    continue
                g = gates[gate]
                g["calls"] += 1
                g["days"].add(day)
                p = PROJ.search(ln)
                if p:
                    g["projs"][p.group(1)] += 1
                # ⛔ 2026-09-07:记下【这条日志的动作词】。原来只认 BLOCK/NUDGE/DENY,
                #   于是 SKIP/allow 这类行为被当成"没有行为" ⇒ 一律报成纸老虎(实测误判 3 道)。
                a_ = ACT.search(ln) or ACT2.match(ln)
                if a_:
                    g["acts"][a_.group(1).upper()] += 1
                if is_fire(ln):          # ⛔ 2026-09-09:改用 is_fire,放行日志不再算开火
                    g["fires"] += 1
                    t = TRIG.search(ln)
                    has_trig = bool(t and t.group(1).strip()) or _has_inline_evidence(ln)
                    if not has_trig:
                        g["no_trig"] += 1
                    fp = FP.search(ln)
                    # ⛔⛔ 2026-09-07:**没有触发词的行不许参与复发率统计**。
                    #   指纹 = 消息 + 触发词。触发词缺失时,指纹退化成"由写死的消息决定的常数"
                    #   ⇒ 同一道闸的每一次开火都是同一个指纹 ⇒ 复发率必然接近 100%,
                    #     而那**不是误伤,是这条日志根本没记证据**。两件事被算成了一件。
                    #   实测代价:记分板报 critic-gate 复发率 90%、capability-boundary 95%,
                    #   我据此把它们列为"头号误伤嫌疑",差一点就去改两道好闸。
                    #   只统计【留了证据的那些行】之后:critic-gate 14 次开火 = 14 个不同指纹,
                    #   capability-boundary 9 次 = 9 个不同指纹 —— **复发率 0%,它们没问题**。
                    #   ⇒ 一条判据只在它的输入完整时才有意义;输入缺失要当"未知",不能当"命中"。
                    if fp and has_trig:
                        g["fps"][fp.group(1)] += 1
    return gates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    # ⛔ 2026-09-08:按天切不够 —— 修复常常落在半天中间,读数的人会把"修复前的旧行"
    #   当成"现在的表现"(当晚我在 14 天和 1 天两个尺度上各被骗一次)。
    ap.add_argument("--since", default=None,
                    metavar="'YYYY-MM-DD HH:MM'",
                    help="从某个时刻起(可到小时/分钟)。修完一道闸后用它看【修复之后】的真实表现")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    gates = collect(a.days, a.since)
    if not gates:
        print("没有日志数据")
        return 0

    rows = []
    for name, g in gates.items():
        fires, calls = g["fires"], g["calls"]
        top_fp, top_n = (g["fps"].most_common(1) or [("-", 0)])[0]
        # 复发率:最常见的那个指纹占了这道闸多少次开火 —— 越高越像"同一件事反复拦"
        recur = (top_n / fires) if fires else 0.0
        # ⛔ 2026-09-08:「开火率」只有在这道闸【每次调用都记一行】时才有意义。
        #   只在开火那一刻才写日志的闸(commitment-execution / unknowing-pretending / coherence…)
        #   分母恒等于分子 ⇒ **恒 100%,是废数**。它会把"我犯得最多的病"和"这闸最爱误伤"
        #   混成同一个符号,而这两件事的处置完全相反。⇒ 标成 n/a,不再印一个假的百分比。
        only_on_fire = fires == calls and fires > 0
        rows.append({
            "gate": name, "calls": calls, "fires": fires,
            "fire_rate": None if only_on_fire else (fires / calls if calls else 0.0),
            "no_trig_rate": g["no_trig"] / fires if fires else 0.0,
            "top_fp": top_fp, "top_fp_n": top_n, "recur": recur,
            "projects": len(g["projs"]), "days": len(g["days"]),
        })
    rows.sort(key=lambda r: -r["fires"])

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    # ⛔ 窗口必须印在抬头上:同一批数据换个窗口能得出相反结论(当晚实证),
    #   读的人一眼看不见口径,就会拿旧行当现状。
    if a.since:
        span = "自 %s 起" % a.since + (" · 且最近 %d 天" % a.days if a.days else "")
    else:
        span = "最近 %d 天" % a.days if a.days else "全部历史"
    tot_c = sum(r["calls"] for r in rows)
    tot_f = sum(r["fires"] for r in rows)
    print("══ Superego 记分板 · %s ══" % span)
    print("闸 %d 道 | 调用 %d | 开火 %d (%.1f%%)\n"
          % (len(rows), tot_c, tot_f, 100.0 * tot_f / max(1, tot_c)))

    print("%-30s %7s %7s %7s %8s %s" % ("闸", "调用", "开火", "开火率", "无证据率", "复发率"))
    print("-" * 84)
    for r in rows[:18]:
        if not r["fires"]:
            continue
        rate = "   n/a" if r["fire_rate"] is None else "%5.1f%%" % (100 * r["fire_rate"])
        print("%-30s %7d %7d %7s %7.0f%% %6.0f%%"
              % (r["gate"][:30], r["calls"], r["fires"], rate,
                 100 * r["no_trig_rate"], 100 * r["recur"]))

    if any(r["fire_rate"] is None for r in rows[:18] if r["fires"]):
        print("\n   开火率 n/a = 这道闸【只在开火时才写日志】,分母恒等于分子 ⇒ 算不出开火率。")
        print("   它的绝对开火次数仍然是真的,看那一列。")

    print("\n🔴 误伤嫌疑(同一指纹占该闸开火 ≥50%,且跨 ≥2 个项目):")
    sus = [r for r in rows if r["fires"] >= 5 and r["recur"] >= 0.5 and r["projects"] >= 2]
    sus.sort(key=lambda r: -r["top_fp_n"])
    for r in sus[:10]:
        print("   %-30s 同一指纹 %d/%d 次,跨 %d 个项目"
              % (r["gate"][:30], r["top_fp_n"], r["fires"], r["projects"]))
    if not sus:
        print("   (无)")

    # ⛔⛔ 2026-09-07 修误判:原来只看 BLOCK/NUDGE/DENY,把下面三道全报成"纸老虎",而实测——
    #   · `turn-budget`     2344 条 **SKIP** = 它在压制别的闸(防死循环)。**那就是它的动作**,不是没干活;
    #   · `intent-layer`    4123 条 SKIP 是**语义层熔断**(09-05:2674 / 09-06:231 / 修好熔断后今天 0),
    #                       是"服务不可用"的症状,不是"判据太严";
    #   · `injection-claim` 3152 条 allow = 真评估过、判定没有违规。
    #   三种情况完全不同,却被同一个标签盖住 —— 我据此写下的"三道纸老虎"**是错的**。
    #   ⇒ 病根:**判据只认自己预设的那几个词,就会把没预设过的行为当成"没有行为"。**
    #   ⇒ 现在把【主要动作】一起打出来,让人自己判,别替他按死一个标签。
    print("\n⚪ 从未 BLOCK/NUDGE 的闸(调用 ≥200 次)—— ⚠️不等于纸老虎,先看它主要在干什么:")
    tig = [r for r in rows if r["calls"] >= 200 and r["fires"] == 0]
    for r in sorted(tig, key=lambda r: -r["calls"])[:10]:
        acts = gates[r["gate"]].get("acts") or {}
        top = ", ".join("%s×%d" % (k, v) for k, v in
                        sorted(acts.items(), key=lambda kv: -kv[1])[:3]) or "?(日志没有动作词)"
        print("   %-24s 调用 %-6d 主要动作: %s" % (r["gate"][:24], r["calls"], top))
    if not tig:
        print("   (无)")

    # ⛔ 2026-09-07:影子闸的账。shadow mode 的原话是
    #   「**Measure** shadow-mode numbers **before graduating**」——
    #   不量就永远毕不了业,那就从"建了没人看"变成"影子跑了没人看",还是纸老虎。
    import glob as _glob
    _sh = sorted(_glob.glob(os.path.join(HERE, "*.shadow.log")))
    if _sh:
        print("\n🌓 影子模式(只记账不拦人;判得准了就从 hooks/shadow-gates.txt 里删名毕业):")
        for _p in _sh:
            _name = os.path.basename(_p)[:-len(".shadow.log")]
            try:
                _lines = [l for l in open(_p, encoding="utf-8", errors="replace")
                          if "WOULD-BLOCK" in l]
            except Exception:
                _lines = []
            _recent = [l for l in _lines if not a.days or l[:10] >= (
                dt.date.today() - dt.timedelta(days=a.days)).isoformat()]
            print("   %-24s 影子开火 %d 次%s" % (_name, len(_recent),
                  "" if _recent else "  ← 一次没响:要么真没发生,要么判据太严"))
            for _l in _recent[-2:]:
                print("      %s" % _l.strip()[:96])

    nt = [r for r in rows if r["fires"] >= 10 and r["no_trig_rate"] >= 0.5]
    print("\n🟠 开火却不留证据(≥50%%的开火没记触发词,事后判不了对错): %d 道" % len(nt))
    for r in sorted(nt, key=lambda r: -r["fires"])[:8]:
        print("   %-30s %.0f%% 无证据 (%d 次开火)"
              % (r["gate"][:30], 100 * r["no_trig_rate"], r["fires"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
