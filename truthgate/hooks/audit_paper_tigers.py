#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""纸老虎普查 —— 把 Superego 里【装了但不生效】的闸全部揪出来。

⛔ 先查现成(2026-07-29,按铁律):WebSearch「Claude Code hooks audit / dead hook detection」
   + `gh search repos "claude code hooks audit" --sort stars`
   → 头部是 `karanb192/claude-code-hooks`(★460, MIT),其 `dead-rules-audit` 插件审的是
   **CLAUDE.md 的规则我遵不遵守**(合规记分卡),**不是审闸本身是否生效** —— 对象不同,不可复用。
   `gh search "hook coverage dead code detection"` → 0 结果。⇒ **只能自建**。
   (借鉴了它一个思路:`promote→hook` —— 长期失效的东西要自动升级成强制项。)

⛔ 存在的理由(Frank 2026-07-29:「不能遗漏一个纸老虎,必须穷尽方法」):已知实录 ——
   `show-open-guard.py` 在磁盘上、有完整 docstring,但 settings.json 里搜不到 = **零效果**;
   `spec-coverage-guard` 把 PreToolUse 的判据抄进 PostToolUse ⇒ 判据恒假、**从挂上到被发现一次没开过火**;
   `prior-art-gate` 拿整段历史当"本轮" ⇒ **一次搜索免检以后所有轮**;
   `false-done-gate` 规则3 上线首日**真实精度 0**(开火 4 次全误报)。
   这些都不是"忘了写",是**装好之后没人验它到底开不开火**。

⛔⛔ 与 `~/.claude/superego-health.py` 的分工(2026-07-29 外部 critic 点破我造了重复轮子):
   那个**早一天(07-28)就存在**,也在查"每道闸真的开过火吗",而且它的日志名解析**比我对**
   —— 它的 docstring 第 6 行写着「拿脚本文件名猜日志名 → 18 道被误报」,那正是我原来的做法。
   我的"先查现成"**只查了 GitHub、没查同一个目录**,结果两个探测器对同一批闸给出相反结论
   (它说"没有可疑死闸"、我说"14 无法判断") —— 这正是 Frank 那条「散清单 = 骗下一个新 chat」。
   ⇒ **现在的分工(别再各查各的)**:
     · `superego-health.py` = 权威的【日志名解析】(从源码抠 `hook_log()` 第一个实参)+ 开火盘点;
       本脚本**动态调用它的 `log_name_of()`**,不复制、不另写一套。
     · `audit_paper_tigers.py`(本脚本) = 更宽的**五维体检**:接线/开火/回归/兜底/事件,
       宇宙**从 settings 的已接线集合出发**(不靠文件名猜),并入磁盘上像闸的。
   两者结论若再打架 = 说明分工没守住,先修这里再信任任何一方的数字。

判据(全部机械可判、有客观证据):
  A  未接线        —— 文件在,但 settings*.json 里没有它 ⇒ 永远不会被调用
  A2 挂了但文件没了 —— settings 里有、磁盘上没有 ⇒ 每次触发都静默失败
  B0 零日志证据    —— 一行日志都没有 ⇒ **无法判断死活**(它可能只在开火时才写日志)。
                     ⚠️ 这不是"健康",是"没证据" —— 必须和 B 分开显示,否则就是把
                     "我没查到"说成"我查过了"(critic 打回来的正是这个病)。
  B  有日志却没开火 —— 有日志、但全是 allow/skip/pass 这类"什么也没做" ⇒ 判据可能恒假
  C  无回归        —— 没有对应 test_*.py ⇒ 改坏了没人知道(已发作 3 次)
  D  兜底静默      —— 最后一道 except 直接 pass/exit(0) 且不留痕 ⇒ 闸死了也看不见
  ⛔ 原 E(提示自指)**已删**:全库 0 真阳性 = 那条判据自己就是纸老虎。真正的自指风险只在
     「拿词表去扫 tool_result」的闸上,全库仅 false-done 规则3 一处,已就地打码修掉。

跑法: python audit_paper_tigers.py           # 人看
      python audit_paper_tigers.py --json    # 机器读(可挂 doctor / CI)
      python audit_paper_tigers.py --strict  # 有 A 类问题就 exit 1
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELF = os.path.basename(__file__)


# 【这次什么也没做】的记法白名单 —— 反向判据的核心。整行搜索,不锚行首。
# ⛔ 每一条都来自本库真实日志(critic 2026-07-29 在真数据上核过),不是我想象的:
#   · `pass(no promise)` / `pass(past)` / `pass(acted)`  ← promise-gate,本库最主流的写法
#   · `trig='…' allow: options but no choice-signal`     ← multi-option,allow 在行尾
#   · `skip(self-blocked-this-turn)` / `skip(not-bg)`    ← 各闸通用
#   · `ok(no dup)`                                        ← rule-dup-guard
#   · `error(fail-open…)`  ← ⚠️ 崩溃留痕【绝不能算开火】:否则一道每次调用都崩的闸
#     会被报成"开火 N 次、健康"(我今天为修 D 才加的留痕,当场把 B 判据喂坏)
NOOP = re.compile(
    # ⛔ 收尾用前瞻,别写死"必须跟空格/括号":真实日志里是 `no match, nothing to do`(跟逗号)、
    #    也有跟行尾的。写死分隔符 ⇒ 这类"什么也没做"漏进 hard ⇒ 纸老虎被洗白(回归⑮④抓到)。
    # ⛔ `ok` 必须收窄成 `ok(` / `ok:` / 行首 `ok` —— 否则 `HTTP/1.1 200 OK`(curl 的正常输出)
    #    里的 ` OK` 会被当成"什么也没做" ⇒ 某闸日志里只要有 curl 输出就少算开火 ⇒ 洗白纸老虎。
    #    **这条是"判据过宽体检"上线后抓到的第一个真阳性,而且抓的就是我自己刚写的判据。**
    r"(?:^|[\s\]:])(?:allow|skip|pass|none|noop|no[\s_-]?match|ignore|unchanged)(?=[\s(:\[,.\-]|$)"
    r"|(?:^|[\s\]])ok\s*[(:]"
    r"|\berror\(fail-open"
    r"|干净|无事|通过|未触发|不适用|无需",
    re.I)          # ⛔ (?i) 只能放整条开头,别在中间再写一个(PatternError: global flags not at start)


def wired_map():
    """settings*.json 里挂上的每个 hook → {文件名: {"events": {...}, "paths": {...}}}。

    ⛔ 必须连【事件名】一起记(外部 critic 2026-07-29 指出):原版 `for _evt, groups` 直接把事件名丢了,
       于是 `spec-coverage-guard` 那种**「PreToolUse 的判据挂在 PostToolUse 上」的历史 bug,
       这套判据结构上就看不见**;matcher 写错同理。
    ⛔ 文件名正则必须带结尾锚:原版把 `check-existing-first.json` 截成 `…first.js`,造出假的 MISSING。
    """
    out = {}
    for fn in ("settings.json", "settings.local.json"):
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf8"))
        except Exception:
            continue
        for evt, groups in (d.get("hooks") or {}).items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                matcher = g.get("matcher", "")
                for h in (g.get("hooks") or []):
                    cmd = str(h.get("command", "") or "")
                    for m in re.finditer(r"([A-Za-z0-9_.$~/\\-]+[/\\])?([A-Za-z0-9_.-]+\.(?:py|cjs|js|sh))(?=[\"'\s]|$)", cmd):
                        name = m.group(2)
                        e = out.setdefault(name, {"events": set(), "matchers": set(), "cmds": set()})
                        e["events"].add(evt)
                        e["matchers"].add(matcher)
                        e["cmds"].add(cmd[:160])
    return out


def gate_files():
    """要审的全集 = 【已接线的每一个 hook】∪【hooks/ 下像闸的文件】。

    ⛔⛔ 原版只 glob `hooks/` 且要求文件名**以** guard|gate|… **结尾** ——
       外部 critic 实测:38 个已接线 hook 只审了 26 个,**漏掉的恰恰包括最重的那道**
       `guard-destructive.py`("guard" 是前缀不是后缀!)、`blame-check.py`(57KB 日志)、
       `regress-on-guard-edit.py`、`dissatisfaction-postmortem.py`、
       `superego-health.py`(在 ~/.claude/ 不在 hooks/)、`session-context-inject.py`(在 scripts/)
       + 3 个 .sh(压根不在 glob 里)。
       ⇒ **"26 道闸全绿" ≠ "Superego 全绿"** —— 那是我自己划的圈里的 0。
       现在:**从 settings 的已接线集合出发**(它才是"真的会被调用"的权威定义),再并上磁盘上像闸的。
    """
    out = set(wired_map().keys())
    for pat in ("*.py", "*.cjs", "*.js", "*.sh"):
        for p in glob.glob(os.path.join(HERE, pat)):
            b = os.path.basename(p)
            if b.startswith("test_") or b == SELF or "_fix." in b:
                continue
            if not re.search(r"(guard|gate|watchdog|sweep|sentinel|inject|check|postmortem|health)", b, re.I):
                continue
            # ⛔ 名字像闸 ≠ 是闸:`guard_common.py` 是共享库、`doctor.py` 是项目脚本,
            #    它们没接线是**正常**的,报 A 类是误报(第一版扩大宇宙后当场造出 2 个假警报)。
            #    真 hook 的结构特征 = 从 stdin 读 harness 传来的 JSON。
            try:
                src = open(p, encoding="utf8", errors="replace").read(4000)
            except Exception:
                continue
            if re.search(r"stdin|process\.argv|readFileSync\(0", src):
                out.add(b)
    return sorted(out)


def locate(name):
    """在 hooks/ → ~/.claude/ → scripts/ 里找这个 hook 的真身。找不到返回 None。"""
    for d in (HERE, ROOT, os.path.join(ROOT, "scripts")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _health_log_name(path):
    """复用 `~/.claude/superego-health.py` 的日志名解析(**不复制**,避免两份实现漂移)。

    ⛔ 外部 critic 2026-07-29 点破:同目录里 `superego-health.py`(2026-07-28 建,早一天)
       在做同一件事,而且它的 docstring 第 6 行白纸黑字写着——
       「第一次拿**脚本文件名去猜日志名 → 18 道被误报成"从没开火"**」。
       **那正是我这里用的 glob 猜法。** 我不但重复造了轮子,还用了它一天前就证伪的做法。
       它的正解:从源码里抠 `hook_log(...)` 的第一个实参(字面量取字面量、是常量就回头解析)
       —— 那才是"闸真正写进哪个日志"的唯一事实来源。
    ⇒ 这里动态加载它的函数;加载失败时退回下面的 glob(fail-open,别整个哑掉)。
    """
    try:
        import importlib.util
        p = os.path.join(ROOT, "superego-health.py")
        if not os.path.isfile(p):
            return None
        spec = importlib.util.spec_from_file_location("_sh", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        name, _how = mod.log_name_of(path)
        return name
    except Exception:
        return None


def log_stats(gate, path=None):
    """这道闸的日志行数 / 开火次数。日志名优先用 superego-health 的源码解析,glob 只做兜底。"""
    cands = set()
    real = _health_log_name(path) if path else None
    if real:
        cands.add(os.path.join(HERE, real if real.endswith(".log") else real + ".log"))
    # ⛔ 2026-07-29 critic 抓到:shell 闸(git-auto-push.sh)把日志写到 ~/.claude/git-hook.log,
    #    脚本名(git-auto-push)和日志名(git-hook)没有字面公共子串 ⇒ 下面的 glob 永远猜不出来
    #    ⇒ 一个【每轮 Stop 都跑】的命脉闸被误标"零日志"。唯一可靠的是【从源码抠它写死的日志路径】。
    #    _health_log_name 只认 Python 的 hook_log(),不认 shell 的 LOG=;这里补 shell/py 通用的字面量抠取。
    if path and os.path.isfile(path):
        try:
            src = open(path, encoding="utf8", errors="replace").read()
            for m in re.finditer(r'(?:LOG|LOGFILE|LOG_FILE)\s*=\s*["\']?([^"\'\n]*?([\w.-]+\.log))',
                                 src, re.I):
                base = os.path.basename(m.group(2))
                cands.add(os.path.join(HERE, base))
                cands.add(os.path.join(os.path.dirname(HERE), base))   # ~/.claude/ 根目录
        except Exception:
            pass
    stem = re.sub(r"\.(py|cjs|js|sh)$", "", gate)
    short = stem.replace("-guard", "").replace("-gate", "")
    # ⛔ 2026-07-29 critic 抓到 under-report:根目录闸(git-auto-push.sh)把日志写到 ~/.claude/git-hook.log,
    #    而这里原来只 glob HERE(=hooks/) ⇒ 看不到 ⇒ 把一个【每轮 Stop 都跑】的闸误标"零日志无法判断"。
    #    ⇒ 父目录 ~/.claude/ 也是根目录闸的日志落点,一并搜。另外补一层「去掉 git-auto- 前缀」的短名,
    #    让 git-auto-push → git-hook.log 这种"日志名≠脚本名"的情况也能兜到(*hook*.log)。
    PARENT = os.path.dirname(HERE)
    extra = {short, stem.replace("git-auto-", "").replace("-push", "").replace("-init", "")}
    for s in {stem, short} | extra:
        if not s:
            continue
        for base in (HERE, PARENT):
            cands |= set(glob.glob(os.path.join(base, f"{s}.log")))
            cands |= set(glob.glob(os.path.join(base, f"*{s}*.log")))
    # ⛔ 拦截词表【必须覆盖各闸真实用的词】—— 第一版只认 `BLOCK`,而实测:
    #    `prior-art-gate` 记的是 **DENY**(它今天真拦了 3 次,含拦我造本脚本那次)、
    #    `coherence-guard` 记的是 **NUDGE**(提醒档,压根不拦停)。
    #    ⇒ 第一版把两个正常工作的闸误判成"从没开火的纸老虎"。判据写太窄,同今晚第 4 次。
    lines = hard = soft = skips = 0
    for lg in cands:
        try:
            t = open(lg, encoding="utf8", errors="replace").read()
        except Exception:
            continue
        lines += t.count("\n")
        # ⛔⛔ 改成【反向判据】(白名单),别再追各家的"开火"写法 —— 这是本普查器第 3 次因此翻车:
        #    先只认大写 BLOCK ⇒ 漏 `prior-art` 的 DENY;补了 DENY ⇒ 漏 `multi-option` 的小写 `block:`;
        #    补了小写 ⇒ 又漏 `dissatisfaction-postmortem` 的 `STRONG(score=…)` 和
        #    `regress-on-guard-edit` 的 `BG x -> y`。**每道闸的记法都不一样,黑名单永远追不完。**
        #    ⇒ 反过来数【明确表示"这次什么也没做"】的行(allow / skip / ok / none / 干净),
        #      其余全算"它做了点什么"。漏一种"没开火"写法只会让它显得更活跃(保守方向),
        #      而漏一种"开火"写法会把活闸误判成纸老虎(危险方向)—— 两害相权取其轻。
        for ln in t.splitlines():
            if not ln.strip():
                continue
            body = re.sub(r"^\s*[\d:\- ]{8,20}\s*(\[[^\]]*\]\s*)?", "", ln)   # 去掉时间戳+[项目|会话]
            # ⛔⛔ 白名单必须【整行搜索】而不是只看行首,且必须覆盖本库最主流的 `pass(` 记法。
            #    外部 critic 2026-07-29 在**真实日志上抓到现行**:
            #      promise-gate 274 行 → 我报 hard=222,实际 BLOCK 只有 51
            #        (被算成开火的是 `pass(no promise)`×79 / `pass(past)`×34 / `pass(acted)`×52);
            #      multi-option 133 行 → 我报 hard=133,实际 `block:` 只有 7
            #        (它把 `allow:` 写在 `trig='…'` **后面**,行首匹配看不见)。
            #    最反讽的一条:我今天为修 D 加的 `error(fail-open)` 留痕,直接喂给 B 当"开火" ⇒
            #    **一道每次调用都崩溃的闸会被报成"开火 N 次、健康"**。
            if NOOP.search(body):
                if re.search(r"(?i)\bskip[\s(:]", body):
                    skips += 1
                continue
            if re.search(r"(?i)\b(NUDGE|WARN|HINT|提醒)\b", body):
                soft += 1
            else:
                hard += 1
        skips += len(re.findall(r"\bskip\(", t))
    return lines, hard, soft, skips


_HS_CACHE = {}


def _hook_stats():
    """读 R4 的记账文件 → {闸名: [allow 次数, block 次数]}。
    ⛔ 2026-08-14 加:这是**独立于"闸自己写不写日志"的第二个数据源**,
      专门用来填 B0「零日志=无法判断」那个盲区 —— 判据是 hook 协议本身
      (静默=放行 / 有 stdout 或退出码 2 = 干预),不需要各闸配合。
      读不到就返回空 dict,普查退回原来的判法(绝不因为多了个数据源就崩)。"""
    if _HS_CACHE:
        return _HS_CACHE
    try:
        # 2026-09-16:原来只读当前文件(约半小时)⇒ 大量闸被判"没开过火";改读含存档的近 14 天
        from guard_common import stats_lines
        for ln in stats_lines(days=14):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            g = d.get("g")
            if not g:
                continue
            cur = _HS_CACHE.setdefault(g, [0, 0])
            # 开火 = 拦 + 提醒(与 superego-metrics 同口径;2026-09-16 前提醒被算成放行)
            cur[1 if d.get("r") in ("block", "nudge") else 0] += 1
    except Exception:
        pass
    return _HS_CACHE


def has_test(gate):
    # ⛔ 2026-07-29:原正则只剥 (py|cjs|js) ⇒ **`.sh` 闸的后缀留在 stem 里**,
    #   于是拿 "git-auto-push.sh" 去 glob `test_*git-auto-push.sh*`,永远匹配不到
    #   真实存在的 `test_git_auto_push.py` ⇒ **所有 shell 闸恒判"无回归"**,补了也不认。
    #   实录:刚给 git-auto-push.sh 补了 13 条回归并全套跑绿,普查照样把它列进"无回归"。
    #   7 道里有 4 道是 .sh(diary-capture / git-auto-init / git-auto-push / restore-sessions-index),
    #   都受这个 bug 影响 —— 普查器自己的判据坏了,比它要查的纸老虎更隐蔽。
    stem = re.sub(r"\.(py|cjs|js|mjs|sh|bash|ps1)$", "", gate)
    keys = {stem, stem.replace("-", "_"),
            stem.replace("-guard", "").replace("-gate", "").replace("-", "_")}
    for k in keys:
        if k and glob.glob(os.path.join(HERE, f"test_*{k}*")):
            return True
    return False


def source_risks(gate, path=None):
    """读源码找结构风险。

    ⛔ 删掉了原来的 E(提示自指):外部 critic 实测 **全库 0 命中** —— 它要求
       `reason=` 同一行 + f-string 花括号,而现实里的写法是 `_log(f"BLOCK(...)", trig(text,160))`。
       **一条从没有过真阳性的判据 = 判据自己就是纸老虎**,留着只会让报表显得很努力。
       这个形状(词表闸原样回显触发词 → 讨论/测试它时自撞)已记进 lessons,只有 false-done 规则3
       真踩过,已就地打码修掉。
    """
    p = path or os.path.join(HERE, gate)
    try:
        src = open(p, encoding="utf8", errors="replace").read()
    except Exception:
        return []
    risks = []
    # ⛔ 只看【最后一道兜底】(__main__ 块;没有就看文件尾部的顶层 try)——
    #    第一版扫全文任意 except ⇒ 把 9 道闸都报成 D,实际只有 3 道真的"崩了看不见"
    #    (`superego-recall-inject` 有手写日志、`multi-option` 压根没有顶层兜底)。判据太宽,第 6 次。
    m_main = re.search(r"if __name__ == [\"']__main__[\"']:(.*)$", src, re.S)
    tail = m_main.group(1) if m_main else src[-1200:]
    # ⛔ 别在 `)` 后面写 `\b`:`sys.exit(0)\b` 里 `)` 和后面的换行**都是非单词字符**,
    #    词边界永远不成立 ⇒ 这条判据对【最常见的 `except: sys.exit(0)` 写法恒假】,
    #    只对 `pass` 结尾的有效。2026-07-29 补 D 类测试时当场撞到(当天第 7 次判据写错)。
    #    ⇒ 用前瞻断言收尾,别用 \b。
    silent = re.search(r"except[^\n]*:\s*\n\s+(?:pass|sys\.exit\(0\)|exit\(0\)|return\s+0)\s*(?:#[^\n]*)?(?:\n|$)",
                       tail)
    # 认各种留痕写法:hook_log / _log / 手写 open(...).write / logging
    logged = re.search(r"hook_log\s*\(|_log\s*\(|\.write\s*\(|logging\.", tail)
    if silent and not logged:
        risks.append("D:兜底静默(崩了完全看不见)")
    # ⛔ E 判据已删(见 docstring):全库 0 命中 = 它自己就是纸老虎。
    #    真正有自指风险的只有【拿词表去扫 tool_result】的闸,全库仅 false-done 规则3 一处,已修。
    return risks


def audit():
    wired = wired_map()
    rows = []
    for g in gate_files():
        path = locate(g)
        lines, hard, soft, skips = log_stats(g, path)
        flags = []
        cmds = " ".join((wired.get(g) or {}).get("cmds", []))
        # ⛔ 项目内脚本(命令里带 $CLAUDE_PROJECT_DIR / 相对 scripts/)不归全局审:
        #    它们的真身在【每个项目自己的目录】里,全局找不到是正常的,报 A 是误报
        #    (第一版扩大宇宙后当场把 `doctor.py` 误判成未接线)。
        project_scoped = bool(re.search(r"CLAUDE_PROJECT_DIR|(?<![\w/\\])scripts[/\\]", cmds))
        if g not in wired:
            flags.append("A:未接线(永远不会被调用)")
        elif path is None and not project_scoped:
            # ⛔ 反方向也要查(critic #7):settings 里挂着、文件却不在磁盘上 = 每次触发都静默失败
            flags.append("A2:settings 里挂着但【文件不存在】")

        # ⛔⛔ B 判据重做 —— 原版是【判据划的圈里的 0】(外部 critic 2026-07-29 用它自己的
        #    脚手架证伪):要求 `lines>=20` 才评估,而全库有 **8 道闸只在开火时才写一行日志**
        #    (spec-coverage / coherence / lint-fatal / prior-art / time-sanity / show-open /
        #     dropped-output / unread-evidence)⇒ 从没开火 = 日志 0 行 = 不到阈值 = **判健康**。
        #    **当年 spec-coverage 判据恒假坏着的时候,这个普查器会说它健康** ——
        #    也就是说它抓不住自己的立项案例(和 unread-evidence 第一版同一个形状)。
        #    ⇒ 现在把「零证据」和「健康」**分开显示**:没有任何日志 ≠ 没问题,是【无法判断】。
        # ⛔⛔ 2026-08-14:B0「零日志=无法判断」这个坑,现在**有第二个数据源可以填了**。
        #   R4 给全部闸装了 allow/block 记账(hook-stats.jsonl,判据=写没写 stdout 或退出码 2),
        #   它**不依赖各闸自己写不写日志** ⇒ 正好补上 B0 的盲区。
        #   实录:普查报「零日志无法判断 18 道」的同一时刻,hook-stats 里对这些闸有精确的
        #   跑过/拦下次数 —— **数据就在隔壁,普查却说不知道**(和「PROGRESS 明明写了我却重查」同形状)。
        _acc = _hook_stats().get(g.rsplit(".", 1)[0])
        if lines == 0 and _acc and (_acc[0] + _acc[1]) >= 5:
            _tot, _blk = _acc[0] + _acc[1], _acc[1]
            if _blk == 0:
                flags.append("B:记账 %d 次全是放行、从没拦过(判据可能恒假)" % _tot)
            else:
                flags.append("✅记账 %d 次拦下 %d 次(有日志与否不影响,这道闸确实在工作)" % (_tot, _blk))
        elif lines == 0:
            flags.append("B0:零日志证据(它可能只在开火时才写日志 ⇒ 从没开火也长这样,无法判断死活)")
        elif hard == 0 and soft == 0:
            pct = f",其中 skip {skips} 次" if skips else ""
            flags.append(f"B:日志{lines}行但从没拦过/提醒过{pct}(判据可能恒假)")
        elif lines >= 100 and skips / max(lines, 1) > 0.9 and hard == 0:
            flags.append(f"B2:{skips}/{lines} 是 skip,几乎从不进判定分支")

        if not has_test(g):
            flags.append("C:无回归测试")
        flags += source_risks(g, path)
        rows.append({"gate": g, "wired": g in wired, "path": path,
                     "events": sorted((wired.get(g) or {}).get("events", [])),
                     "log_lines": lines, "hard": hard, "soft": soft, "skips": skips,
                     "has_test": has_test(g), "flags": flags})
    return rows


def main():
    rows = audit()
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    print(f"{'闸':32s} {'接线':5s} {'日志':>7s} {'拦停':>5s} {'提醒':>5s} {'回归':4s}  问题")
    print("-" * 118)
    for r in sorted(rows, key=lambda x: (-len(x["flags"]), x["gate"])):
        print(f"{r['gate']:32s} {'✅' if r['wired'] else '❌':5s} {r['log_lines']:7d} "
              f"{r['hard']:5d} {r['soft']:5d} {'✅' if r['has_test'] else '❌':4s}  "
              f"{' ; '.join(r['flags']) or '—'}")
    print("-" * 112)
    a = [r for r in rows if any(f.startswith("A") for f in r["flags"])]
    # ⛔ B0(零日志=无法判断)与 B(有日志却没开火=判据可能恒假)必须分开统计:
    #    原来 `startswith("B")` 把 B0 也算进"从没开火",表格标 B0、汇总却说"从没开火 14",
    #    同一份输出自相矛盾 —— 而人看的通常就是最后那行(critic 2026-07-29 指出)。
    b0 = [r for r in rows if any(f.startswith("B0") for f in r["flags"])]
    b = [r for r in rows if any(f.startswith("B:") or f.startswith("B2") for f in r["flags"])]
    c = [r for r in rows if any(f.startswith("C") for f in r["flags"])]
    print(f"共 {len(rows)} 道闸 | ❌未接线 {len(a)} | 有日志却没开火 {len(b)} | "
          f"零日志无法判断 {len(b0)} | 无回归 {len(c)}")
    if a:
        print("⛔ A 类必修(装了等于没装):" + ", ".join(r["gate"] for r in a))
    if "--strict" in sys.argv and a:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
