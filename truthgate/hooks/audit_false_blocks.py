#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""误拦审计 —— 回答「这套闸到底有没有用,还是在白拦」。

⛔ 存在的理由(Frank 2026-07-29:「我整套 superego 到底有没有真正作用,居然没有一个脚本做外审统计,
   没有一个抓包污染和错拦,或者过度设计导致更多问题和后遗症的?」——他说对了):
   现有 `superego-metrics.py` 只统计【活动量】(开几次火/注多少字/延迟/送达率),
   **没有任何一项测【拦对了没有】**。后果:开火次数越多的闸看起来越勤奋,
   而今天开火最多的两个恰恰伤害最大 —— critic-gate 把我锁进 6 小时死循环、
   prior-art-gate 拦 15 次却 0 次避免重复造轮子。**活动量指标会把有害的闸表彰成劳模。**

⛔ 先查现成(2026-07-29 WebSearch + gh search):行业确实把 FP/FN 复盘当标配,且实测
   **pattern-based(正则/关键词)guardrail 假阳性率 30~60%**(LLMJudge 类才 5.6%)——
   而本套闸绝大多数正是 pattern-based,却从没测过一次。
   GitHub 头部:`disler/claude-code-hooks-multi-agent-observability`(hook 事件实时监控)、
   `karanb192/claude-code-hooks`(★460,含 observability)、`parcadei/Continuous-Claude-v3`
   (主打 without context pollution)—— 三者都做【事件可观测】,**没有一个测「这次拦对不对」**。
   ⇒ 借鉴其 observability 思路,判据自建。

核心判据(便宜且高信噪比):**同一会话 + 同一目标 + 同一道闸 反复拦 >= 2 次 = 误拦嫌疑**。
   我被拦一次必然照它说的做;还拦 = 要么判据坏了,要么它要的东西我根本给不了。
   实录:`mdtable.js` 被 prior-art-gate 连拦 4 次,我每次都真跑了 WebSearch + gh search,
   根因是它的主题词算法切不出 `md`+`table`(2 字母前缀)⇒ 4 次全是误拦。

⛔ 写这个脚本时我自己踩的坑(留着防复发):第一版用 `[^\s]+` 提路径,
   而日志里的路径**带空格**(`d:\airbnb ai manager\lib\x.js`)⇒ 在第一个空格断掉 ⇒
   目标名全变成残缺的 `airbnb` ⇒ 聚合失效 ⇒ **报出"误拦 0%"这个假结论**。
   尺子坏了比被测物坏了更常见 —— 所以本文件底部带自测。

跑法: python ~/.claude/hooks/audit_false_blocks.py [天数,默认1]
"""
import collections
import datetime as dt
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# ⛔ 路径含空格,不能用 [^\s]+ —— 锚定到已知扩展名为止,允许中间有空格
PATH_RE = re.compile(r"([A-Za-z]:[\\/].+?\.(?:js|py|md|json|mjs|cjs|ts|ps1|sh))(?:\s|$)")
SESS_RE = re.compile(r"\[([^|\]]+)\|([^\]]+)\]")
# ⛔ 大小写不敏感的 BLOCK 会把 `skip(self-blocked-this-turn)` 里的 "block**ed**" 数成拦截 ——
#   实测污染 101 行(6.4%),而且污染的是【分母】。必须先排掉 skip/allow/期望值转储。
SKIP_RE = re.compile(r"\bskip\(|\bALLOW\b|self-blocked", re.I)
BLOCK_RE = re.compile(r"\bDENY\b|\bBLOCK\b|BLOCK\(|拦")     # 去掉 re.I:blocked/blocking 不再命中
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\b")
# 测试探针 / 改闸会话 —— 告警不许对着自己的测试套件叫(实测 7 天口径 59% 是探针)
PROBE_RE = re.compile(r"__.*probe.*__|zzprojnotreal|zzrepeat|zzneverseen|__probe_not_exist__", re.I)


def is_block_line(ln):
    """这一行是不是【真的一次拦截】。分母只认这个。"""
    if not DATE_RE.match(ln):        # promise-gate.log 有 442 行无日期(自测期望值转储),不是事件
        return False
    if SKIP_RE.search(ln):           # skip(...) / ALLOW = 闸主动放行,不是拦截
        return False
    return bool(BLOCK_RE.search(ln))


def parse_line(ln):
    """一行日志 → (会话, 目标文件名, 时间);解析不出/不是拦截的返回 None。

    「目标」**只认文件名**(PreToolUse 闸才有)。没有文件名的行一律返回 None ⇒ 不进聚合、
    在报表里显示 n/a。⛔ 别改成"退回理由指纹"—— 那条路 2026-07-29 试过并回退了,
    理由写在下面 return None 上方,是拿真实日志坐实的,不是推理。
    """
    if not is_block_line(ln):
        return None
    if PROBE_RE.search(ln):
        return None                  # 测试探针不进统计
    sm = SESS_RE.search(ln)
    if not sm:
        return None      # ⛔ 无 [proj|sid] 的老日志(2026-07-25 迁移前)不能当同一个会话:
                          #   实测它们会合并成一个假会话,占模拟标记数的 69%(外部审查坐实)
    sess = sm.group(2)
    parts = ln.split()
    when = parts[1] if len(parts) > 1 else ""
    pm = PATH_RE.search(ln)
    if pm:
        tgt = os.path.basename(pm.group(1).replace("\\", "/"))
        if PROBE_RE.search(tgt):
            return None
        return (sess, tgt, when)
    # ⛔⛔ 2026-07-29 我试过用【理由指纹 fp=】把 Stop 闸也纳入聚合,**这条路不通,已回退**。
    #   ⚠️ 真正的原因(外部审查用真实日志坐实;我第一版写的理由是【反的】,见文末):
    #   ★ 指纹几乎**恒定不变**,于是【什么都聚到一起】—— 不是聚合不到,是全都聚上。
    #     msg 模板实测:critic-gate 388 行全是 `BLOCK(claimed+code+no-critic)` 一个值;
    #     no-nagging 172 行全是 `BLOCK(nag)`;blame-check 170 行 + giveup 69 行都只是裸 `BLOCK`
    #     ——后两者连 md5 都相同。⇒ 同一道闸的【所有】拦截都会被判成"反复拦同一目标"。
    #   ★ 全覆盖模拟(7 天 1403 条):可见 1302 条,其中 **1133 条(87%)会被误判成误拦嫌疑**;
    #     critic-gate 97% / blame-check 97% / reference-diff 98%。而 guard-destructive 那几组
    #     (`rm -r` 拦 4 次、`rm -f` 拦 2 次)**每一次都是正当拦截**,却全部会被标红。
    #   ⇒ 这个判据对"没有目标文件"的闸从根上不成立,不是调参数能救的。
    #     宁可诚实地只覆盖 8%,也不要一个 87% 是噪音的指标。
    #
    #   ⛔ 我第一版把原因写成「理由里嵌着 trig='我的原话' ⇒ 指纹每次不同 ⇒ 聚合不到」——**错的,而且方向相反**。
    #     `trig=` 是 hook_log 的 **ctx 参数**,拼接在 msg 【前面】;而 guard_common 只 hash `msg`。
    #     铁证:两行 trig 文本完全不同,fp 都是 3cb092d2。照那个错理由读,下一个人会去
    #     "让指纹更稳定"(剥掉 trig / 归一化),那恰好一头撞进上面 87% 的陷阱。
    #   ⇒ 要真全覆盖,得让各闸把「这次拦的是哪条规则 + 我这轮满足条件了吗」**结构化落盘**,
    #     而不是从自由文本里猜。
    return None


def audit(days=1, logdir=None):
    logdir = logdir or HERE
    wanted = {(dt.date.today() - dt.timedelta(days=i)).isoformat() for i in range(days)}
    rows = collections.defaultdict(list)
    per_gate = collections.Counter()
    # ⛔ 分子分母必须【同源】:第一版 per_gate 数所有拦截行、rows 只收能提出路径的行 ⇒
    #   对 25 家里的 23 家(Stop hook,拦的是对话文本、根本没有"目标文件")s 恒为 0,
    #   于是报表显示"0% 误拦"—— 那是【数学必然,不是测量结果】,而我拿它当过"其余闸健康"的证据。
    #   现在额外统计 coverable(能提出目标的行数),没有覆盖就显示 n/a,不显示 0%。
    coverable = collections.Counter()
    for fp in glob.glob(os.path.join(logdir, "*.log")):
        gate = os.path.basename(fp).replace(".log", "")
        try:
            lines = open(fp, encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            if not any(d in ln for d in wanted) or not is_block_line(ln):
                continue
            per_gate[gate] += 1
            p = parse_line(ln)
            if p:
                coverable[gate] += 1
                rows[(gate, p[0], p[1])].append(p[2])
    return rows, per_gate, coverable


def report(days=1):
    rows, per_gate, coverable = audit(days)
    susp = sorted([(k, v) for k, v in rows.items() if len(v) >= 2], key=lambda x: -len(x[1]))
    total = sum(per_gate.values())
    cov = sum(coverable.values())
    n_susp = sum(len(v) for _, v in susp)
    out = []
    out.append("══ 误拦审计 · 最近 %d 天 ══" % days)
    out.append("  总拦截 %d 次 · 其中【本判据看得见的】%d 次(%d%%) —— 其余无目标文件,不适用"
               % (total, cov, cov * 100 // max(total, 1)))
    out.append("  可见样本里反复拦同一目标 %d 次 = %d%%"
               % (n_susp, n_susp * 100 // max(cov, 1)))
    out.append("  (行业基准:pattern-based guardrail 假阳性 30~60%,本套闸多为此类)")
    if susp:
        out.append("\n  【误拦嫌疑】同会话+同目标被同一道闸拦 >=2 次:")
        for (gate, _sess, tgt), times in susp[:15]:
            out.append("   %2d次  %-24s %-28s %s~%s" % (len(times), gate, tgt, times[0], times[-1]))
    else:
        out.append("\n  可见样本里无反复拦截")
    per_susp = collections.Counter()
    for (gate, _s, _t), times in rows.items():
        if len(times) >= 2:
            per_susp[gate] += len(times)
    out.append("\n  【各闸】拦截数 / 反复率 —— ⛔ n/a = 该闸日志无目标文件,本判据【测不了】,不等于健康:")
    for g, n in per_gate.most_common(20):
        c = coverable.get(g, 0)
        if not c:
            out.append("   %-26s 拦%4d  n/a (Stop 闸,拦的是对话文本,没有目标文件可聚合)" % (g, n))
            continue
        s = per_susp.get(g, 0)
        flag = "  ⚠ 误拦嫌疑高" if s and s * 2 > c else ""
        out.append("   %-26s 拦%4d  可见%3d  反复%3d (%d%%)%s" % (g, n, c, s, s * 100 // c, flag))
    out.append("\n  ⛔⛔ 读这份报告前必须知道的三条(外部审查 2026-07-29 坐实):")
    out.append("   ① 当前覆盖率 %d%% —— 只有带【目标文件】的闸(prior-art / guard-destructive)能被判定," % (cov * 100 // max(total, 1)))
    out.append("      其余 23 道 Stop 闸拦的是对话文本,**至今无法判定误拦**。")
    out.append("      ⛔ 我试过用【理由指纹】把它们纳入,实测不通已回退 —— 原因是指纹几乎**恒定**")
    out.append("      (critic-gate 388 行同一个值、blame-check/giveup 都只是裸 `BLOCK`)⇒ 全聚到一起,")
    out.append("      全覆盖模拟 7 天 1302 条里 **87% 会被误判成误拦**(含每一次正当的 rm 拦截)。")
    out.append("      要真全覆盖,得让各闸把「这次拦的是哪条规则」**结构化落盘**,而不是从自由文本里猜。")
    out.append("   ② 本判据【区分不了】「闸坏了」和「我没照它说的做」—— 日志里没有『本轮我搜过吗』这个字段。")
    out.append("      要出结论而不只是嫌疑,得在各闸落盘时多写一个字段。")
    out.append("   ③ prior-art-gate 已装【反复拦自动豁免】(它自己 :210+),会把第 3 次起的 DENY 吃掉 ⇒")
    out.append("      这个数往后自然下降,**不代表误拦真的减少**。别拿它做趋势。")
    return "\n".join(out)


def _selftest():
    """⛔ 尺子自测:第一版就是因为路径带空格而静默失效、报出假的「误拦 0%」。"""
    ok = True
    real = (r"2026-07-29 09:14:11 [airbnb ai manager|9488d721] "
            r"d:\airbnb ai manager\lib\mdtable.js DENY 未查现成就造")
    p = parse_line(real)
    checks = [
        (p is not None, "带空格路径能解析"),
        (p and p[1] == "mdtable.js", "目标名完整(不是残缺的 airbnb)"),
        (p and p[0] == "9488d721", "会话 id 正确"),
        (parse_line("2026-07-29 10:00:00 [x|y] d:\\a\\b.js 正常放行") is None, "非拦截行不计入"),
    ]
    for cond, msg in checks:
        print(("PASS  " if cond else "FAIL  ") + msg)
        ok &= bool(cond)
    return ok


def hook_mode():
    """SessionStart 用:平时【完全静默】,只有误拦率超标才出声。

    ⛔ 这是它跟 superego-metrics.py / audit_paper_tigers.py 的关键差别 ——
    那两个也存在,但【没挂进 settings.json】,只有我主动想起来才跑,
    而我今天 8.5 小时一次都没想起来 ⇒ 有等于没有(Frank 2026-07-29 点破)。
    挂上 + 平时静默 = 既不污染上下文,又不会被遗忘。
    """
    try:
        rows, per_gate, coverable = audit(1)
        bad = []
        for g, c in coverable.items():           # ⛔ 分母用【可见样本】,不用总拦截数(否则分母虚高)
            s = sum(len(v) for (gg, _s, _t), v in rows.items() if gg == g and len(v) >= 2)
            if c >= 5 and s * 2 > c:             # 可见样本够 5 条且过半是反复拦 = 该看了
                bad.append((g, c, s))
        if not bad:
            return 0                             # 静默
        # ⛔ 文案说"今天"不说"昨天":audit(1) 展开就是今天(外部审查抓到字面错报)。
        #   代价是当天第一个 session 大概率静默、晚开的才看得到 —— 采样偏置,不是恒假。
        msg = ["⚠️ 误拦审计(今天):有闸在反复拦同一个目标(= 我照做了它还拦,判据大概率坏了)"]
        for g, c, s in sorted(bad, key=lambda x: -x[2]):
            msg.append("   · %s 可见拦截 %d 次,其中 %d 次是反复拦同一目标(%d%%)" % (g, c, s, s * 100 // c))
        msg.append("   ⛔ 注意:prior-art-gate 已装反复拦自动豁免,这个数会自然下降,别当趋势看")
        msg.append("   查详情:python ~/.claude/hooks/audit_false_blocks.py 1")
        print("\n".join(msg))
    except Exception:
        pass                                     # fail-open,绝不因为统计脚本挂掉影响开工
    return 0


# ⛔ __main__ 必须在【所有函数定义之后】—— 第一版把它放在 hook_mode 之前,
#   `--hook` 分支会在 hook_mode 还没定义时执行 ⇒ NameError ⇒ 闸静默失效。
#   (同一天我在 doctor.py 也栽过"抄了写法没核 import"的同族错。)
if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    if "--hook" in sys.argv:
        sys.exit(hook_mode())
    print(report(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1))
