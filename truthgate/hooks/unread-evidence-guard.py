#!/usr/bin/env python3
r"""Stop hook: 拦截【本轮产生了截图/图片证据,却一次都没打开看,就下结论】。

⛔ 先查现成(2026-07-29,按铁律):WebSearch「Claude Code hook screenshot verification guard」
   + `gh search repos "claude code hooks guard" --sort stars`(rh-claude-framework / ccguard /
   guardrail-integrity / HAPPYWEEK7)—— 生态成熟但**做的全是安全护栏/配置漂移/工具泄漏**,
   没有一个做「证据生成了却没被消费」这个维度。判据是纯机械的(文件产生了、没被 Read 过),
   不需要任何依赖。⇒ **只能自建**。

⛔ 为什么必须是这一道(2026-07-28~29 一天内 Frank 用【同一句话】点破两次):
   ① 上午 Agoda:我报「Agoda 限流了,不发信」 → Frank「**我不相信,你没截图看真相**」
      → 真因是我自己三个 bug,平台每次都老实发信了。
   ② 深夜 Airbnb:我报「限流,只能等冷却」 → Frank「**你有截图看真相吗?给我看看**」
      → 打开图才发现:那红字只是个可叉掉的浮层,`Continue`/Google/Apple 三个入口全都可点,
        平台自己写着 "You can log in another way now"。**解法印在图上,我报了"无解"。**
   两次的共同点:**截图【已经存在磁盘上】,是我自己的脚本存的,我就是没打开。**
   我只读了 `body.innerText` —— 它把二维页面压成一行字符串,丢掉了「那是浮层不是拦截页」
   「按钮还能点」这些**只有图里才有**的信息。归形状 W(把降维后的表示当现场)。

⛔ 为什么现有的闸拦不住(实测,别再指望它们):
   `false-done-gate` 的 `EXERCISE` 正则含 `python \S+\.py` ⇒ 我跑了那个脚本就算
   `verified=True` 放行 —— 而**那条命令的输出正是虚报的来源**(脚本自己的判据是恒真的)。
   它验的是「我有没有做动作」,不是「做出来的东西支不支持我的话」。它的注释里自己承认
   「刻意不加『输出里有报错就不算核实』…那条判据近乎失明」。
   ⇒ 本闸补的是另一个维度:**证据【生成了】但【没被消费】**。纯机械可判,不靠语义、不靠词表。

触发(全满足才拦):
   ① 本轮有图片证据产生(命令/参数里出现 .png/.jpg,或 screenshot 类调用);
   ② 本轮【没有任何 Read 打开过图片】;
   ③ 本轮文本里在【下裁定】(限流/不通/只能/无法/根因…),而不只是描述动作。
纯中间步骤(没下结论)不拦;已经打开看过的不拦;只拦自己一次。

安全设计(照 false-done-gate.py):fail-open、只拦自己一次、只读 transcript、每次留一行日志。
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, strip_doc, self_blocked_this_turn, trig, is_real_user_msg
except Exception:                      # ⛔ 兜底桩必须可到达:裸 import 一坏,整道闸第一行就炸(critic 抓过)
    def is_real_user_msg(m):        # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(tp, tail_bytes=4_000_000):
        return []

    def strip_doc(t):
        return t or ""

    def self_blocked_this_turn(*a, **k):
        return False

    def trig(s, n=120):
        return (s or "")[:n]

import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "unread-evidence"

IMG = re.compile(r"[\w./\\-]+\.(?:png|jpe?g|webp)\b", re.I)
SHOT_CALL = re.compile(r"screenshot|save_screenshot|--shot\b", re.I)
# ③【下裁定】—— 只认对现状做出判决的措辞,不认单纯描述动作("我截了图""跑了脚本"不算)
VERDICT = re.compile(
    r"限流|冷却中|封了|被封|风控|拦住|不通|走不通|只能等|只能靠|无法|做不了|没辙|"
    r"没有.{0,4}(路|办法|选项|入口)|失败了|没成功|不存在|查不到|根因是|"
    r"所以.{0,8}(判断|结论|说明)|说明.{0,6}(是|不是)|"
    r"rate.?limit|blocked|not\s+available|no\s+(way|option)", re.I)


_SKIP = {"node_modules", ".git", "dist", "build", ".venv", "__pycache__", "venv", ".next"}


def _find_by_name(base, name, maxdepth=4, _cache={}):
    """在项目下按【文件名】找真身(有限深度)。

    ⛔ 为什么必须有它:`ls -la data/login-shots/` 的输出里只有**纯文件名**
       `ab-1-after-continue.png`,不带目录 ⇒ 拼成 `<cwd>/ab-1-after-continue.png` 必然不存在
       ⇒ produced 恒 0、整道闸对着真实事故一声不吭(2026-07-29 实测,连查三层才挖到)。
    """
    key = (base, name)
    if key in _cache:
        return _cache[key]
    hit = None
    try:
        bd = base.replace("\\", "/").rstrip("/").count("/")
        for root, dirs, files in _os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
            if root.replace("\\", "/").count("/") - bd >= maxdepth:
                dirs[:] = []
            if name in files:
                hit = _os.path.join(root, name)
                break
    except Exception:
        hit = None
    _cache[key] = hit
    return hit


def _ts(s):
    """transcript 的 ISO 时间戳 → epoch 秒。解析不了返回 None(调用方退回宽松路径)。"""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _hard_log(name, msg):
    """⛔ 不依赖 guard_common 的最后留痕 —— guard_common 坏掉正是闸集体哑掉的头号场景,
    而 hook_log 有静默降级桩(`def hook_log(*a,**k): pass`),那时留痕会跟着一起消失
    (外部 critic 2026-07-29 指出)。这里直接写文件,照 ui-edit-guard 的写法。"""
    try:
        import datetime
        d = _os.environ.get("SUPEREGO_LOG_DIR") or _os.path.dirname(_os.path.abspath(__file__))
        with open(_os.path.join(d, name), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        # ⛔ 同上:兜底加在 __main__ 上到不了这里(critic 真故障注入实测零留痕)
        _hard_log("unread-evidence.log", f"error(fail-open,stdin): {type(e).__name__}: {str(e)[:120]}")
        return 0
    tp = payload.get("transcript_path") or ""
    if not tp or not _os.path.exists(tp):
        return 0
    # ⛔ 必须有 turn_start 复位:全仓 13 道闸都有,唯独我漏了(外部 critic 2026-07-29 实测:
    #    第1轮拦=rc2,第2个【新回合】该拦却 rc0 —— 被自己 900s TTL 的陈旧标记哑掉,
    #    「本轮」退化成「最近 15 分钟」)。我当轮就撞上了这个:去删 .blocked-* 文件、
    #    删不掉就说"TTL 会自己过期" —— 那是治症状,这一行才是治根因。
    if not payload.get("stop_hook_active"):
        self_blocked_this_turn(NAME, turn_start=True)
    elif self_blocked_this_turn(NAME):
        hook_log(NAME, "skip(self-blocked-this-turn)")
        return 0

    msgs = load_transcript_tail(tp)
    if not msgs:
        return 0

    # 定位本轮:最后一个真实 user 消息(非 tool_result)之后 —— 照抄 critic-gate:204 已验证的写法。
    # ⛔ 不切轮 = 免死金牌漏洞(形状Q′:上一轮看过图,这一轮就永久免检)。
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
    t0 = None
    for m in turn:                       # 本轮起始时刻 —— 用来判"这张图是不是【本轮刚生成的】"
        t0 = _ts(m.get("timestamp"))
        if t0:
            break

    # ⛔⛔ 判据根因重做(外部 critic 2026-07-29 把【真实事故那一轮】回放进来,得到 allow(produced=0)):
    #    原判据只看【我发出去的命令字符串】里有没有 png —— 而真实那次命令是 `sh /tmp/ab_retry2.sh`,
    #    截图路径写在 `airbnb_login.py` 内部,命令里一个 png 都没有 ⇒ **闸拦不住它为之而生的那次坑**。
    #    而我的测试正样本能绿,是因为我在命令后面加了句现实中不存在的 `# 截图落到 <路径>` —— **加料**。
    #    同时反向也坏:`ls *.png` / `cat x.png` / 讨论时引用路径都被当成"产生了证据"(critic 实测误报 3/3,
    #    77 个真实回合里开火 3 次无一是干净真阳性)。
    #    ⇒ 现在:候选路径【命令和工具输出里都收】,再用**磁盘 mtime 是否晚于本轮起始**过滤。
    #      新生成的图才算证据;`ls` 一张旧图不算。这也顺带让 SHOT_CALL 那条原本必死的分支活过来。
    cand, read_paths, text_parts = set(), set(), []
    for m in turn:
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            if m.get("type") == "assistant":
                text_parts.append(content)
            cand.update(IMG.findall(content))
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            ctype = c.get("type")
            if ctype == "text" and m.get("type") == "assistant":
                text_parts.append(c.get("text", ""))
            elif ctype == "tool_result":         # ← 脚本 stdout / ls 输出里打印的路径
                cand.update(IMG.findall(json.dumps(c.get("content"), ensure_ascii=False)))
            elif ctype == "tool_use":
                nm = str(c.get("name", ""))
                inp = c.get("input") or {}
                fp = str(inp.get("file_path", "") or "")
                blob = str(inp.get("command", "") or "") + " " + fp
                if nm == "Read" and IMG.search(fp):
                    read_paths.add(_os.path.basename(fp))     # ✅ 真打开看了【哪一张】
                else:
                    cand.update(IMG.findall(blob))
                    if SHOT_CALL.search(blob):
                        cand.add("<screenshot-call>")

    # 只保留【本轮之后才变新】的真实文件 —— 这一步把"提到过路径"和"真产生了图"分开。
    # ⛔ 必须拿 cwd 当基准解析【相对路径】:transcript 里记的是 `data/login-shots/x.png`,
    #    而 hook 进程的工作目录不是项目目录 ⇒ 直接 isfile() 恒为假 ⇒ produced 永远是 0,
    #    整道闸静默失效。实测:真实事故轮里路径明明在,却因这一条判出 produced=0。
    #    (progress-inject.py:24 已有同款取法,照抄。)
    # ⛔ 路径要【逐段回退】拼:Frank 的项目目录 `d:\airbnb ai manager` **含空格**,
    #    而 IMG 正则的字符类不含空格 ⇒ 捞到的是残缺片段 `manager/data/login-shots/x.png`,
    #    直接 isfile 必假 ⇒ produced 恒 0、整道闸静默失效(回归当场变红抓到的)。
    #    ⇒ 对每个候选,从左往右逐段丢弃前缀再拼 cwd,第一个命中即真身。
    base = payload.get("cwd") or _os.environ.get("CLAUDE_PROJECT_DIR") or ""
    produced = set()
    for p in cand:
        # ⛔ 分隔符必须【折叠】不能简单 replace:路径经 json.dumps 后 `\` 变成 `\\\\`,
        #    单纯 replace("\\","/") 会得到 `manager//data//x.png` ⇒ 逐段拼接全部落空。
        #    实测:真实事故轮就卡在这里,produced 恒 0。
        q = re.sub(r"[\\/]+", "/", p.strip("'\"`,;)"))
        tries = [q] if _os.path.isabs(q) else []
        if base:
            seg = q.split("/")
            tries += [_os.path.join(base, "/".join(seg[i:])) for i in range(len(seg))]
        tries.append(q)
        if base:                        # 兜底:按文件名在项目下找(ls 输出常常只有裸文件名)
            tries.append(_find_by_name(base, _os.path.basename(q)))
        for cand_path in tries:
            if not cand_path:
                continue
            try:
                if _os.path.isfile(cand_path) and (t0 is None or _os.path.getmtime(cand_path) >= t0 - 5):
                    produced.add(_os.path.normpath(cand_path).replace("\\", "/"))
                    break
            except Exception:
                continue

    # ⛔ read 必须匹配到【本轮产生的那张】:原来"Read 任意一张图"就整轮免检 = 免死金牌换个壳
    #    (critic:本轮随便看一张不相干的图,对关键图的裁定就免检)。
    seen = {_os.path.basename(p) for p in produced} & read_paths
    if seen or not produced:
        hook_log(NAME, f"allow(produced={len(produced)},seen={len(seen)})")
        return 0

    scan = strip_doc("\n".join(text_parts))
    mv = VERDICT.search(scan)
    _semhit = ""
    if not mv:
        try:
            from guard_common import claim_kinds as _ck
            if "done" in _ck(scan[-1500:], kinds=("done",)):
                _semhit = "语义判定:词表没命中,但这话语义上就是该类断言"
        except Exception:
            pass
    if not mv and not _semhit:
        hook_log(NAME, f"allow(no-verdict,produced={len(produced)})")
        return 0

    self_blocked_this_turn(NAME, mark=True)
    hook_log(NAME, "BLOCK(unread-evidence) " + trig((mv.group(0) if mv else _semhit)))
    print(
        f"⛔ 证据没看闸:本轮【产生了图片证据却一次都没打开看】,却已经在下裁定(触发词「{(mv.group(0) if mv else _semhit)}」)。\n"
        f"   没被打开的:{', '.join(sorted(produced)[:4])}\n"
        "   ⛔ 这是 Frank 一天内用同一句话点破我两次的坑(Agoda「我不相信,你没截图看真相」/\n"
        "      Airbnb「你有截图看真相吗」)——两次截图都【已经在磁盘上】,我只读了 innerText,\n"
        "      而它把二维页面压成一行字,丢掉了「那红字只是可叉掉的浮层」「按钮全都还能点」。\n"
        "      第二次的代价:平台在图上写着 \"You can log in another way now\" 并给了 Google/Apple 两个入口,\n"
        "      而我报的是「无解,只能等冷却」。**解法印在图上。**\n"
        "   ⇒ 现在用 Read 打开那张图【真的看一眼】再回来。看完结论不变就原样说(本闸只拦一次)。",
        file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as _e:
        # ⛔ fail-open 保留(闸坏了绝不阻断工作),但**绝不静默**:
        #    静默的兜底 = 闸死了也没人知道。今晚 ruff 抓到 6 次 `F821 未定义名`,
        #    每一个都会被这种 `except: pass` 吞掉 ⇒ 整道闸从此哑掉、日志一片空白、
        #    而我还以为它在守着(2026-07-29 纸老虎普查抓到的 D 类)。
        try:
            hook_log(NAME, f"error(fail-open): {type(_e).__name__}: {str(_e)[:160]}")
        except Exception:
            pass
        sys.exit(0)
