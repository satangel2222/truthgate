# -*- coding: utf-8 -*-
"""Superego 计量报表(2026-07-25)—— 把「从没量过」变成「随时能看」。

跑法:  py -3.12 ~/.claude/hooks/superego-metrics.py [天数,默认7]

回答的问题(此前全靠估,而估错过 5 倍):
  · 语义召回每轮到底注了多少字?命中几条?延迟多少?
  · 【送达率】多少 —— 超时/出错被静默吞掉的占几成?(这条曾经是 70% 却没人知道)
  · 跨项目噪音占比 —— 召回给我的教训里,有多少讲的是【别的项目】的事?
  · 各道闸各在哪个项目开过几次火?(改成带项目/会话的单行日志后才答得出)
"""
import collections
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from guard_common import stats_lines as _stats_lines  # noqa: E402  hook-stats 唯一读法(含存档)
METRICS = os.path.join(HERE, "recall-metrics.jsonl")
# 项目专名 → 用于估跨项目噪音;只用于统计,不参与任何拦截判定(按专名降权已被否决,见 SUPEREGO.md)
PROJ_WORDS = re.compile(
    r"airbnb|民宿|房东|Booking|Agoda|TNB|对账|zimagen|clawbot|hermes|dola|manju|bananaflow|"
    r"即梦|mytg|social_media|xhs|小红书|抖音|osidian|obsidian|evisitor|eCommunity|myTNB", re.I)


def load(days):
    import datetime
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    if os.path.exists(METRICS):
        for ln in open(METRICS, encoding="utf-8"):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if d.get("ts", "") >= cutoff:
                rows.append(d)
    return rows, cutoff


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    rows, cutoff = load(days)
    print(f"══ Superego 计量 · 最近 {days} 天(自 {cutoff})══\n")

    if not rows:
        print("  语义召回:还没有数据(计量是 2026-07-25 才装的,跑几轮对话后再看)\n")
    else:
        n = len(rows)
        by = collections.Counter(r.get("outcome") for r in rows)
        inj = [r for r in rows if r.get("outcome") == "inject"]
        lost = by.get("timeout_or_error", 0)
        served = n - by.get("skip_short", 0) - by.get("skip_benign", 0)
        print(f"  语义召回:{n} 轮   注入 {by.get('inject',0)} · 无命中 {by.get('no_hit',0)} · "
              f"跳过(短/闲聊) {by.get('skip_short',0)+by.get('skip_benign',0)} · 超时/出错 {lost}")
        if served:
            print(f"  ⭐送达率:{100*(n-lost-by.get('skip_short',0)-by.get('skip_benign',0))//max(1,served)}% "
                  f"(超时被静默吞掉的比例 = {100*lost//max(1,served)}%)")
        if inj:
            chars = sorted(r.get("chars", 0) for r in inj)
            ms = sorted(r.get("ms", 0) for r in inj)
            print(f"  注入字数:中位 {chars[len(chars)//2]} · 最大 {chars[-1]} · 每轮平均 {sum(chars)//len(chars)}")
            print(f"  延迟(ms):中位 {ms[len(ms)//2]} · P90 {ms[int(len(ms)*0.9)-1] if len(ms)>1 else ms[0]} · 最大 {ms[-1]}")
            titles = [t for r in inj for t in (r.get("titles") or [])]
            if titles:
                cross = sum(1 for t in titles if PROJ_WORDS.search(t))
                print(f"  跨项目噪音:召回的 {len(titles)} 条里 {cross} 条标题带项目专名 = {100*cross//len(titles)}%")
            via = collections.Counter(v for r in inj for v in (r.get("via") or []))
            if via:
                print(f"  命中来路:{dict(via)}  (floor=规则文本命中 / anchor=靠触发情形锚点捞回来的)")
        print()

    # ════════════════════════════════════════════════════════════════════
    # 真·拦截率(2026-08-14 加)—— Frank 点名的 R4:
    #   在这之前,4 道闸的"拦截率"显示 96~100%,**那是假的** —— 它们只在拦的时候写日志、
    #   放行时一个字不写,所以分母 = 分子。cross-scope 24/24、idle-ask 27/27、
    #   guard-destructive 223/222、prior-art 202/194,四个日志里 "allow" 出现 0 次。
    #   ⛔ **没有分母就没法回答「它是不是在误拦」;在假数据上调任何参数都是瞎调。**
    # 修法:guard_common 里包一层 stdout 观测器 + atexit,每个闸进程退出时记一笔
    #   allow(静默=放行)/ block(有输出=干预)到 hook-stats.jsonl。
    #   判据不是我发明的 —— **静默=放行、有输出=干预,就是 hook 协议本身的语义**,
    #   任何闸、任何写法都适用,不需要各闸配合。
    #   (原打算用 hook_log 的 BLOCK 前缀当判据,动手前实测:只覆盖 25 道、
    #    另有 12 道会拦但不留痕、会被误记成 allow ⇒ 当场废弃,免得分母修好分子却错。)
    STATS = os.path.join(HERE, "hook-stats.jsonl")
    if os.path.exists(STATS):
        acc = collections.defaultdict(collections.Counter)
        first_t = ""
        # ⛔ 2026-09-16:原来只读当前文件(约半小时)却挂着「最近 7 天」的标题 ⇒ 大批闸被报「几乎不开火」
        for ln in _stats_lines(days=7):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            acc[d.get("g", "?")][d.get("r", "?")] += 1
            t = str(d.get("t") or "")
            if t and (not first_t or t < first_t):
                first_t = t
        try:
            import time as _tm
            cover_h = (_tm.time() - _tm.mktime(_tm.strptime(first_t, "%Y-%m-%d %H:%M:%S"))) / 3600
        except Exception:
            cover_h = 0.0
        # 账本不满 3 天就不下"恒假"结论:管少见错误的闸,几小时里 0 次开火是常态
        enough_cover = cover_h >= 72
        rows = []
        for g, c in acc.items():
            # 2026-09-16:开火 = 拦(block)+ 提醒(nudge)。原来 nudge 既不进分子也不进分母
            #   ⇒ lint-fatal-guard 半天提醒 7 次仍报「0% 几乎不开火」。
            fired = c["block"] + c["nudge"]
            tot = c["allow"] + fired
            if tot:
                rows.append((g, tot, c["block"], c["nudge"], fired / tot * 100))
        if rows:
            print("══ 真·开火率(拦 + 提醒;2026-08-14 起有分母了)══")
            print("  账本实际覆盖 %.1f 小时%s\n" % (cover_h, "" if enough_cover else "(不满 72 小时,「恒假」一律不判)"))
            print("  %-30s %8s %6s %6s %9s  %s" % ("闸", "跑过", "拦下", "提醒", "开火率", "判定"))
            print("  " + "-" * 84)
            for g, tot, blk, ndg, pct in sorted(rows, key=lambda x: -x[4]):
                if tot < 20:
                    v = "样本太少,先别下结论"
                elif pct > 50:
                    v = "⚠️ 开火太勤,会变噪音"
                elif blk + ndg == 0 and tot >= 200 and enough_cover:
                    # 判「恒假」只看【一次都没开过】:开过火就证明判据能成立;
                    #   管少见错误的闸(防误删等)开火率本来就低,按比例判会冤枉它(原阈值 <0.5% 报了 68 道)。
                    #   0 次也只是嫌疑 —— 终审靠故障注入(faults/*.js),不靠这张表。
                    v = "⚠️ 从没开过火,查判据是否恒假"
                elif blk + ndg == 0:
                    v = "0 次开火,样本还不够判恒假"
                else:
                    v = "✅ 开过火,判据能成立"
                print("  %-30s %8d %6d %6d %8.1f%%  %s" % (g[:30], tot, blk, ndg, pct, v))
            print()

    # ════════════════════════════════════════════════════════════════════
    # R5:【拦了之后我照做了没有】—— 2026-08-14 建。
    #   这是 2026-08-14 体检里最刺眼的空白:整套系统只知道「开火几次」,
    #   完全不知道「开火有没有用」。Frank 2026-07-29 原话:
    #   「我整套 superego 到底有没有真正作用,居然没有一个脚本做外审统计」。
    # 判据(纯机械、不需要理解语义):**同一道闸在同一会话里【连着两次】都是 block
    #   = 上一次拦完我没照做,所以它又拦了一次。**
    #   · 拦一次 → 下一次 allow  = 我照做了(闸达到了目的)
    #   · 拦一次 → 下一次还是 block = 没照做(闸变成了噪音,或我在硬闯)
    # ⛔ 诚实边界:这是【下限估计】不是精确值 ——
    #   ①我可能这一轮换了话题,下一次 allow 不代表我为那件事做了什么
    #   ②有些闸设计上就是"拦一次就放行"(already-known/ask-coverage),连拦率天然为 0
    #   所以它回答的是「**这道闸拦完之后,情况有没有变**」,不是「我内心有没有服气」。
    #   但这已经比【完全没有】强一个量级 —— 而且它是从现成数据算出来的,零额外开销。
    _stats = os.path.join(HERE, "hook-stats.jsonl")
    if os.path.exists(_stats):
        seq = collections.defaultdict(list)          # (gate, session) -> [r, r, ...] 按时间顺序
        for ln in _stats_lines(days=7):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            seq[(d.get("g", "?"), d.get("s", "-"))].append(d.get("r"))
        agg = collections.defaultdict(lambda: [0, 0])   # gate -> [拦截次数, 其中"下一次还是拦"的次数]
        for (g, _s), rs in seq.items():
            for i, r in enumerate(rs[:-1]):
                if r == "block":
                    agg[g][0] += 1
                    if rs[i + 1] == "block":
                        agg[g][1] += 1
        rows = [(g, n, again, (again / n * 100)) for g, (n, again) in agg.items() if n >= 3]
        if rows:
            print("══ 拦了之后我照做了没有(R5 · 连拦率越低越好)══\n")
            print("  %-30s %10s %10s %9s  %s" % ("闸", "拦过", "下次仍拦", "连拦率", "读法"))
            print("  " + "-" * 82)
            for g, n, again, pct in sorted(rows, key=lambda x: -x[3]):
                if pct >= 50:
                    v = "⛔ 拦完我基本没改 → 要么措辞没落地,要么判据误伤"
                elif pct >= 20:
                    v = "⚠️ 有时没改,值得看几条实例"
                else:
                    v = "✅ 拦完情况就变了 = 这道闸真的推动了行为"
                print("  %-30s %10d %10d %8.0f%%  %s" % (g[:30], n, again, pct, v))
            print("\n  (判据:同一会话里同一道闸连着两次都 block = 上一次没照做。样本 <3 不列。)\n")

    print("══ 各闸开火统计(按项目/会话,改成单行追加日志后才可信)══\n")
    any_log = False
    for lg in sorted(glob.glob(os.path.join(HERE, "*.log"))):
        name = os.path.basename(lg)[:-4]
        per_proj = collections.Counter()
        fired = 0
        total = 0
        try:
            for ln in open(lg, encoding="utf-8", errors="replace"):
                if not ln.strip():
                    continue
                total += 1
                m = re.search(r"\[([^\]|]+)\|", ln)
                # ⛔ 2026-08-03:原判据只认 BLOCK/NUDGE/⛔ —— 那是 Stop 闸(decision:block)的写法。
                # PreToolUse 闸走的是 permissionDecision:deny,日志写的是 "DENY:" ⇒ 全部被统计成
                # 【开火 0】。实录:pipe-truncation-guard 当天刚拦过我(我要把长输出接进 head),
                # 报表却显示 2769 行 0 开火;同样被漏掉的还有 launch-bound(9830 行)、
                # pkg-install(1770)、prior-art(99)。这四道全是 PreToolUse。
                # 后果:整张报表把「拦得最多的那类闸」判成纯噪音 —— 而这张表正是用来淘汰噪音闸的,
                # 尺子错了会把有用的闸砍掉。补上 DENY 与 deny(大小写)。
                if re.search(r"\bBLOCK\b|\bNUDGE\b|\bDENY\b|⛔", ln, re.I):
                    fired += 1
                    per_proj[m.group(1) if m else "(旧格式·无项目)"] += 1
        except Exception:
            continue
        if total:
            any_log = True
            tag = "  ".join(f"{k}:{v}" for k, v in per_proj.most_common(4)) or "-"
            print(f"  {name:<28} 行数 {total:<6} 开火 {fired:<5} {tag}")
    if not any_log:
        print("  (还没有日志)")
    print("\n注:标着「旧格式·无项目」的是 2026-07-25 改造前写的行,那时不记项目/会话,分不出来源。")

    # ⛔⛔ 2026-09-06 补:【记分板摘要】—— 闸的 measure 那一半,此前完全没有。
    #   Frank:「已经迭代了3个月没有一点进步…这么久了,**数据应该很够了**」
    #   实测他说的对:真实开火日均 07=182 → 08=98 → 09=128,三个月没下降;
    #   而 11,619 次开火里 22% 是测试写的、43% 没留触发词 ⇒ 真实误报率算不出来。
    #   行业把这条点名为规则式护栏头号死因:
    #     "can't identify patterns in false positives, can't refine rules based on actual usage"
    #   ⇒ 把三个可执行信号并进这份【每天都跑、且已有告警】的报表:
    #     误伤嫌疑(同一指纹反复) / 纸老虎(零开火) / 无证据开火(事后判不了对错)
    try:
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(HERE, "superego-scoreboard.py"),
                            "--days", "14", "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, cwd=HERE)
        rows = json.loads(r.stdout or "[]")
        sus = [x for x in rows if x["fires"] >= 5 and x["recur"] >= 0.5 and x["projects"] >= 2]
        tig = [x for x in rows if x["calls"] >= 200 and x["fires"] == 0]
        noev = [x for x in rows if x["fires"] >= 10 and x["no_trig_rate"] >= 0.5]
        print("\n══ 记分板(近 14 天) ══")
        print("  误伤嫌疑 %d 道 | 纸老虎 %d 道 | 开火不留证据 %d 道"
              % (len(sus), len(tig), len(noev)))
        print("  [scoreboard suspect=%d tiger=%d noevidence=%d]"
              % (len(sus), len(tig), len(noev)))       # 纯 ASCII,给 PS 告警正则匹配
        for x in sorted(sus, key=lambda y: -y["top_fp_n"])[:3]:
            print("    · %-28s 同一指纹 %d/%d 次,跨 %d 个项目"
                  % (x["gate"][:28], x["top_fp_n"], x["fires"], x["projects"]))
        print("  明细:py -3.12 ~/.claude/hooks/superego-scoreboard.py --days 14")
    except Exception as e:
        print("\n══ 记分板 ══\n  查不到(%s)" % str(e)[:60])

    # ⛔ 2026-09-06 补:【锚点覆盖率】—— 此前这个数没有任何人看。
    #   锚点 = 「Frank 会怎么开口」的样本,是语义召回从 ~80% 提到 96.5% 的东西,
    #   而它是 lessons.md 的派生物:写了新教训、没重跑锚点 ⇒ 那条教训召不回来。
    #   `refresh_anchors.py`(2026-08-25)就是为这件事建的,但**它没接进任何自动路径**
    #   ⇒ 实测:锚点停在 09-03,三天攒了 60 条无锚点规则,recall@3 从达标掉到 61%
    #   (地板 72%),**整个过程一个信号都没有**。这就是「建了没接线」又一次。
    #   ⇒ 不新造闸:并进这份【每天都跑、且已经有告警机制】的报表。
    try:
        import subprocess
        rec = os.path.join(os.path.dirname(HERE), "superego-recall")
        r = subprocess.run([sys.executable, os.path.join(rec, "refresh_anchors.py"), "--check"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=90, cwd=rec)
        d = json.loads((r.stdout or "{}").strip().splitlines()[-1])
        pct, miss = d.get("covered_pct", 0), d.get("missing", 0)
        print("\n══ 锚点覆盖 ══")
        # ⛔ 同时打一个【纯 ASCII】的标记给 start-dissat-service.ps1 的告警去匹配:
        #   那个 .ps1 被 PS 5.1 按 ANSI 读,中文正则可能静默匹配不上 ⇒ 告警天天误报。
        #   人看中文那行,机器读 ASCII 这行,两边都不将就。
        print("  锚点覆盖率:%s%% (%d/%d 个标题缺锚点)   [anchor_covered=%s%%]"
              % (pct, miss, d.get("total_titles", 0), pct))
        if miss:
            print("  ⇒ 补法:py -3.12 ~/.claude/superego-recall/refresh_anchors.py --jobs 4")
    except Exception as e:
        print("\n══ 锚点覆盖 ══\n  锚点覆盖率:查不到(%s)" % str(e)[:60])

    # ══ 图谱新鲜度(2026-09-11)══ lessons/CLAUDE 天天长,图谱是一次性 LLM 蒸馏的产物 ⇒ 会悄悄过期。
    #   规则/溯源/因果都基于蒸馏那一刻的 lessons,不重建就永远停在那天。这里只【报龄】不自动重建
    #   (重建要烧免费判官额度、跑十几分钟,不该塞进每日体检里偷偷跑)。
    try:
        import time as _t
        gp = os.path.expanduser("~/.claude/superego-semantic/superego_graph.json")
        src = [os.path.expanduser("~/.claude/lessons.md"), os.path.expanduser("~/.claude/CLAUDE.md")]
        if os.path.exists(gp):
            age_d = (max(os.path.getmtime(p) for p in src if os.path.exists(p)) - os.path.getmtime(gp)) / 86400
            g = json.load(open(gp, encoding="utf-8"))
            stale = age_d > 14
            print("\n══ 语义图谱 ══")
            print("  规则 %d / 闸 %d / 组 %d,建于 %s,落后源 %.1f 天   [graph_stale_days=%.1f]"
                  % (g["stats"]["rules"], g["stats"]["gates"], g["stats"]["groups"],
                     g.get("built", "?"), max(age_d, 0), max(age_d, 0)))
            if stale:
                print("  ⇒ 重建:py -3.12 ~/.claude/superego-semantic/build_superego_graph.py")
        else:
            print("\n══ 语义图谱 ══\n  图谱不存在   [graph_stale_days=999]")
    except Exception as e:
        print("\n══ 语义图谱 ══\n  查不到(%s)" % str(e)[:60])
    return 0


if __name__ == "__main__":
    sys.exit(main())
