#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""churn-guard —— 拦【在同一个文件/同一段上原地打转】。

⛔ 起因(2026-08-25, Frank 原话:「那么为何 superego 没有任何作用,没制止你一直绕了 6 小时?」):
   抖音图文帖那一件事,我把判据改了 **8 版、实跑 5.5 小时**,而正确答案在【第一次探测】就打印在眼前
   (`~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images` —— aweme-images 就是抖音给帖子图打的标记)。
   实测 churn:`user_browser.js` 被编辑 **52 次 / 9.4 小时**,其中 `sendViaUserBrowser` 那段改了 6 次、
   `NOTE_IMG_JS` 整体重写 3 次。

⛔ 为什么现有的闸一个都没拦住(这是结构洞,不是词表不全):
   · 所有闸都是【单轮】检查「我这一轮的动作做全没有」—— 写了进度、跑了测试、跑了故障注入、
     派了外部审查、截了图 ⇒ **每一轮都合法结束**。没有任何东西在数「这是你第 8 次改同一个判据」。
   · 唯一沾边的 `coherence-guard` 数的是【本轮碰了几个文件】(跨文件·单轮),
     而且只输出 additionalContext = **纯提示不阻塞**。它当天问了 18 次,我 18 次都略过了。
   · 同源已记形状:2026-07-29「闸全在验【有没有做该做的动作】,验不了【做出来的东西对不对】」
     + 2026-08-19-N「所有闸都是拦,没有一个是推」。本闸补第三个缺口:**没有一个在数【原地打转】**。

先查现成(2026-08-25):
   · 本机 `~/.claude/hooks/*.py` 无一个数 churn(grep 过)。
   · GitHub 有 `joeyism/opencode-anti-loop` 等,业界通行做法是 **exact loop detection**:
     hash 工具调用,连续几轮 same tool + same args 就判循环(见 DEV/futureagi 的同类文章)。
   ⛔ **但那类判据抓不到我这个病**:我每一版判据都【不一样】
     (猜宽度 → note-detail 容器 → player-container → 跳转 → 等更久 → aweme-images),
     参数次次不同 ⇒ exact-loop 永远不命中。
   ⇒ **改造复用**:借它「hook 层拦截 + 保持短期记忆」的思路,判据换成 churn(同一文件/同一段反复改),
     这才抓得到"每次换个写法的猜"。

判据(三条,任一命中即拦):
  A. 同一文件本 session 被 Edit/Write ≥ CHURN_FILE 次 **且集中**(平均每处 ≥ CHURN_DENSITY 次)
     —— 2026-09-16 加的集中度:27 次分布在 21 处是"改得广",不是打转(闸日志里这种误拦占 49.6%)
  A2. 同一文件 ≥ CHURN_FILE_HARD 次,不看集中度 —— 兜底:同一个函数每次从不同行开始改,
     指纹(首行)次次不同,A 和 B 都看不见;改到 40 次无论如何该停下看数据了(真打转那次是 52 次)
  B. 同一文件的【同一段】(old_string 归一化前 40 字)被改 ≥ CHURN_SPOT 次   ← 更强的信号
阈值依据(实测,不是拍脑袋):正常一次性修完的文件 12~15 次(同 session 的 caption_html 那批);
改得广的 27 次(21 处);绕圈的 52 次。取 20 / 2.0 / 40 留足余量;同一段 4 次已经明显是在猜。

⛔ 放行条件(避免变成"拦死我"):本轮若已经有【回去读第一手数据】的动作
   (Read / 跑探针脚本 / grep 原始日志),就放行 —— 本闸要的是"回去看数据",不是"别改代码"。
⛔ 同一文件只拦一次(记在 state 里),拦完就放行,绝不锁死。

回归:test_churn_guard.py(含故障注入:判据恒假 / 阈值失效 / 指纹不归一 / 锁死)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, trig, load_transcript_tail
except Exception:                                    # 单测/裸跑时的退化实现
    def hook_log(*a, **k): pass
    def trig(s, n=120): return (s or "")[:n]
    def load_transcript_tail(*a, **k): return []

import sys, os, json, re

NAME = "churn-guard"
CHURN_FILE = int(os.environ.get("CHURN_FILE", "20"))   # 同一文件改这么多次 = 该停下来看数据了
CHURN_SPOT = int(os.environ.get("CHURN_SPOT", "4"))    # 同一段改这么多次 = 在猜
# ⛔ 2026-09-16:文件总次数这条(A)单独用会把【改得广】误判成【在打转】。
#   闸自己的日志:577 次拦截里 286 次(49.6%)同一段 < 4 次;当天实测 index.js 27 次改动分布在 21 处
#   (平均 1.29 次/处,最多 2 次),全是有新证据的不同修复。真打转是"同一判据猜 8 版"—— 那是 B 的活。
#   ⇒ A 只在改动【集中】时才成立:平均每处 ≥ CHURN_DENSITY 次。B(同一段 ≥ CHURN_SPOT)不变。
CHURN_DENSITY = float(os.environ.get("CHURN_DENSITY", "2.0"))
CHURN_FILE_HARD = int(os.environ.get("CHURN_FILE_HARD", "40"))   # 兜底:再"广"也不许无限改下去(指纹看不见的打转)
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".churn-guard-state.json")

CODE_EXT = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".go", ".rs", ".java", ".rb", ".php", ".sh")


def norm_spot(s):
    """把 old_string 归一化成"改的是哪一段"的指纹。

    ⛔ 别用整段做 key —— 我每次改都会带上不同的注释,整段永远不重复 ⇒ 判据恒假(形状T:新闸出生即死)。
    ⛔ 也别简单"压空白取前 40 字" —— 回归当场抓到:`const X = ...\\n  // 注释0` 和 `...// 注释1`
       压完变成 `const X = ... // 注释0` vs `// 注释1`,**注释混进指纹里** ⇒ 同一段认不出来。
    ✅ 正解:只取【第一行的代码部分】—— 注释本来就是每次都变的东西,把它剥掉。"""
    raw = (s or "").strip()
    if not raw:
        return ""
    # 第一行(它才代表"改的是哪一段"),再剥掉行尾注释
    line = raw.splitlines()[0]
    line = re.sub(r"\s*(//|#).*$", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line[:40]


def scan(turn_msgs):
    """返回 {file: {"n": 次数, "spots": {指纹: 次数}}}。只看代码文件,文档不算。"""
    out = {}
    for m in turn_msgs:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            nm = str(c.get("name") or "")
            if nm not in ("Edit", "Write", "MultiEdit", "write_to_file", "replace_file_content"):
                continue
            inp = c.get("input") or {}
            fp = str(inp.get("file_path") or inp.get("TargetFile") or "")
            if not fp.lower().endswith(CODE_EXT):
                continue
            base = os.path.basename(fp)
            rec = out.setdefault(base, {"n": 0, "spots": {}})
            rec["n"] += 1
            spot = norm_spot(inp.get("old_string") or inp.get("TargetContent"))
            if spot:
                rec["spots"][spot] = rec["spots"].get(spot, 0) + 1
    return out


def looked_at_data(turn_msgs, fname):
    """【最后一次改这个文件之后】有没有回去看第一手数据?有就放行。

    ⛔ 第一版判据是「最近 40 条里有没有 Read/grep」—— 拿真 transcript 一跑就发现:
       我几乎每轮都会 Read 或 grep 点什么 ⇒ **恒为 True ⇒ 闸永久放行**。
       这正是形状T「新闸出生即死」:测试全绿、故障注入全红,真实场景零作用。
    ✅ 正解:只看【最后一次编辑该文件之后】的动作 —— 那才是"我停下来去看数据了",
       而不是"我在改代码的间隙顺手读了个文件"。"""
    last_edit = -1
    for i, m in enumerate(turn_msgs):
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if isinstance(c, dict) and c.get("type") == "tool_use":
                c_name = str(c.get("name") or "")
                c_inp = c.get("input") or {}
                c_fp = str(c_inp.get("file_path") or c_inp.get("TargetFile") or "")
                if c_name in ("Edit", "Write", "MultiEdit", "write_to_file", "replace_file_content") \
                   and os.path.basename(c_fp) == fname:
                    last_edit = i
    if last_edit < 0:
        return False
    for m in turn_msgs[last_edit + 1:]:
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            nm, inp = c.get("name"), (c.get("input") or {})
            if nm in ("Bash", "PowerShell", "run_command"):
                cmd = str(inp.get("command") or inp.get("CommandLine") or "")
                if re.search(r"probe|grep|tail |cat |head |node .*\.js|py -3", cmd):
                    return True
            elif nm in ("Read", "view_file"):
                return True
    return False


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                       # 解析不了 → 静默放行(fail-open)

    # ⛔ 不学 promise-gate 那个洞(形状 2026-08-19-N 洞一):它开头就
    #    `if stop_hook_active: return` ⇒ 只要本轮被别的闸拦过一次就跳过,实测 60 轮里只跑 27 轮。
    #    本闸【照常跑】—— 绕圈的那些轮,恰恰是别的闸最爱拦的轮。

    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        sys.exit(0)

    msgs = load_transcript_tail(tp)
    sess = (data.get("session_id") or "?")[:8]
    st = load_state()
    sd = st.setdefault(sess, {})
    if isinstance(sd, list):                    # 兼容旧格式(只存过 fired 列表)
        sd = {"fired": sd}
        st[sess] = sd

    # ⛔⛔ 跨轮【增量累计】,不是每轮重数尾窗 —— 实测缺陷:
    #    load_transcript_tail 只读尾部 4MB,而今天这份 transcript 有 22MB ⇒
    #    `user_browser.js` 真实被改 52 次,尾窗里只数到 10 次 ⇒ 永远够不到阈值 ⇒ **闸形同虚设**。
    #    (读全量也不行:lessons 记过 44MB × 6 个 Stop hook 各读全量 ⇒ 每回合 9.4 秒,是 Frank 卡顿真凶。)
    # ✅ 解法:每轮只读尾窗(快),把【比上次处理过的更新】的编辑累加进 state。跨轮累计 = 全量。
    last_ts = sd.get("last_ts") or ""
    new_msgs = [m for m in msgs if (m.get("timestamp") or "") > last_ts] if last_ts else msgs
    inc = scan(new_msgs)
    acc = sd.setdefault("acc", {})
    for f, rec in inc.items():
        a = acc.setdefault(f, {"n": 0, "spots": {}})
        a["n"] += rec["n"]
        for s, n in rec["spots"].items():
            a["spots"][s] = a["spots"].get(s, 0) + n
    newest = max((m.get("timestamp") or "") for m in msgs) if msgs else ""
    if newest:
        sd["last_ts"] = newest

    stats = acc
    if not stats:
        save_state(st)
        hook_log(NAME, "allow(no code edits)")
        sys.exit(0)

    fired = sd.setdefault("fired", [])

    # 找最该报警的那个:先按"同一段被改的最多次"排,再按总次数
    worst = None
    for f, rec in stats.items():
        spot_max = max(rec["spots"].values()) if rec["spots"] else 0
        distinct = len(rec["spots"]) or 1
        density = rec["n"] / distinct                    # 平均每处改了几次:1.x = 改得广,3+ = 在打转
        file_rule = (rec["n"] >= CHURN_FILE and density >= CHURN_DENSITY) or rec["n"] >= CHURN_FILE_HARD
        if not (file_rule or spot_max >= CHURN_SPOT):
            continue
        if f in fired:                    # 这个文件已经拦过一次,不重复拦
            continue
        key = (spot_max, rec["n"])
        if worst is None or key > worst[0]:
            worst = (key, f, rec, spot_max)

    # ⛔ 放行也【必须存 state】—— 否则跨轮累计全丢,计数永远回到 0、闸永远够不到阈值。
    #   (这就是"增量累计"最容易漏掉的那一半:只在拦停时存 = 等于没累计。)
    if not worst:
        mx = max((r["n"] for r in stats.values()), default=0)
        save_state(st)
        hook_log(NAME, f"allow(max={mx} < {CHURN_FILE})")
        sys.exit(0)

    _, fname, rec, spot_max = worst

    if looked_at_data(msgs, fname):
        save_state(st)
        hook_log(NAME, f"allow(churn {rec['n']} on {fname} but did look at data)")
        sys.exit(0)

    top_spots = sorted(rec["spots"].items(), key=lambda kv: -kv[1])[:3]
    detail = "  ".join(f"{n}次:{s[:34]}" for s, n in top_spots if n > 1) or "(散在各处)"

    hook_log(NAME, f"BLOCK {fname} n={rec['n']} spot_max={spot_max}", trig(detail, 120))
    fired.append(fname)
    save_state(st)                      # fired 已是 sd 里的引用，append 即生效

    if spot_max >= CHURN_SPOT:
        # B:同一段反复改 —— 这才是 2026-08-25 那种"猜了 8 版"的形状,讲那个故事
        head = (
            f"⛔ 原地打转闸:你在 `{fname}` 上已经改了 **{rec['n']} 次**,其中同一段被改了 **{spot_max} 次**。\n"
            "⛔ 2026-08-25 实录(Frank 原话「为何 superego 没制止你一直绕了 6 小时」):\n"
            "   抖音图文帖那件事我把判据改了 **8 版、实跑 5.5 小时**,而正确答案在【第一次探测】\n"
            "   就打印在我眼前 —— 那行地址里写着 `aweme-images`,是抖音给帖子图打的标记。\n"
            "   我盯着它,却去猜宽度、猜容器、猜等多久,连猜 6 版。churn 实测:同一文件 52 次编辑 / 9.4 小时。\n"
            "⛔ 病根不是不够努力,恰恰相反:**改判据(30秒)比逐字读数据(5分钟)快** ⇒\n"
            "   每一轮都跑得飞快 ⇒ **绕圈感觉像在推进**。而所有别的闸都只查【这一轮动作做全没有】,\n"
            "   我每轮都合法结束,没有任何东西在数「这是第 8 次改同一个判据」。\n"
            f"   最近反复改的段:{detail}\n"
        )
    else:
        # A:总次数多【且集中】(2026-09-16 起加了密度条件,改得广不再算) —— 别拿 B 的故事吓自己,说实话
        _d = len(rec["spots"]) or 1
        _why = ("改动密集 —— 大概率有一处判据在被反复微调" if rec["n"] / _d >= CHURN_DENSITY
                else f"不集中,但已经到了 {CHURN_FILE_HARD} 次的兜底上限 —— 同一个函数每次换起始行改,指纹看不见,人该停下看数据了")
        head = (
            f"⛔ 原地打转闸:你在 `{fname}` 上已经改了 **{rec['n']} 次**,落在 **{_d} 处**"
            f"(平均每处 {rec['n'] / _d:.1f} 次,同一段最多 {spot_max} 次)。\n"
            f"   这不是「同一判据猜了 8 版」那种打转(同段 ≥ 4 次才是),但{_why}。\n"
            f"   改得最多的段:{detail}\n"
        )
    print(
        head +
        "\n⇒ 现在【停止改判据】,二选一:\n"
        "   ① 回去把第一手数据【逐字】读一遍(原始响应 / 完整 URL / 页面真实 DOM / 日志原文),\n"
        "      问自己:我要的答案是不是已经写在里面了?\n"
        "   ② 说清楚为什么这次确实需要再改一版(有新证据、不是又一次猜)。\n"
        "(同一文件只拦这一次,拦完放行,绝不锁死。)",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
