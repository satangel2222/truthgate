# -*- coding: utf-8 -*-
"""Stop-hook 共享上下文豁免 —— 让关键字型闸别【自触发/误伤】(2026-07-24 钉死:blame-check/giveup-guard/
reference-diff-guard 本 session 分别把「我在描述规则」「多源搜索的空探测+已修的错」误当真犯,连拦三次)。
- strip_doc: 剥掉【代码块/行内代码/引用/表格】里的文字——「在表格里描述某闸抓什么词」≠「真在甩锅/放弃」。
- SUCCESS_RE: 强交付/成功标记——本轮已交付/已核过就别判 thrash/放弃/甩锅。"""
import re, os, json, time, tempfile, urllib.request, socket
import atexit as _atexit
import sys as _sys

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`]*`")

# ════════════════════════════════════════════════════════════════════════════
# 闸的【分母】—— 每个闸进程退出时记一笔 allow / block(2026-08-14 建)
#
# ⛔ 起因(Frank 点名的 R4):四道闸的拦截率显示 96~100%,**那是假的** ——
#   cross-scope 24/24、idle-ask 27/27、guard-destructive 223/222、prior-art 202/194,
#   因为它们**只在拦的时候写日志、放行时一个字不写**,四个日志里 "allow" 出现 0 次。
#   **没有分母,就没法回答「它是不是在误拦」;而在假数据上做任何调参都是瞎调。**
#
# ⛔ 判据选择过程(必须记下来,否则下次又走回头路):
#   我本来打算用 `hook_log(msg 以 BLOCK 开头)` 当「这轮拦了」的信号 —— 动手前先量了一下:
#     ✅ 判据有效 25 道 · ⛔ **会被误记成 allow 的 12 道**(会拦、但拦的时候不调 hook_log)
#   ⇒ 那个判据只覆盖一半,**分母修好了分子却错了,比现在更糟**。当场废弃。
#   改用真正普适的信号:**这个进程有没有往 stdout 写过东西**。
#   这不是我发明的判据 —— 它就是 hook 协议本身的语义:**静默 = 放行,有输出 = 干预**。
#   任何闸、任何写法都适用,不需要各闸配合。
#
# 落地方式:包一层只观测、不改变行为的 stdout 代理 + atexit 记一行。
#   · 代理用 __getattr__ 原样转发一切(reconfigure / flush / encoding / isatty …)
#   · 连 .buffer 也包(progress-inject 那类直接 sys.stdout.buffer.write 的会绕过 .write)
#   · 整段套 try/except:**这只是个观测器,绝不允许它弄坏任何一道闸**
#   · 记账走已有的 _append_locked(A/B 实测 0 丢失的真锁),不另造轮子
# ════════════════════════════════════════════════════════════════════════════
_ACC = {"wrote": False, "on": False, "code": 0}
STATS_FILE = "hook-stats.jsonl"

# ⛔⛔ 2026-08-14 上线 2 小时后被【自己的数据】打脸,必须记死:
#   第一版判据只有「往 stdout 写过东西 = 拦截」。跑了 2890 条之后一看报表:
#     guard-destructive  261 次 0 拦   ← 但它今天当着 Frank 的面拦过我两次(Stop-Process)
#     cross-scope-guard  261 次 0 拦
#   查下去:**它们走的是 `print(error, file=sys.stderr)` + `sys.exit(2)`** ——
#   而那正是 PreToolUse/Stop 的**标准拦截协议**(exit 2 = block,stderr 回喂给我)。
#   ⇒ 我的判据漏掉了整整一族,那些闸的每一次真拦截都被记成 allow。
# ⇒ 补：把退出码也算进来。**退出码 2 = 拦截**,这是协议规定的,比"写没写 stdout"更硬。
#   为什么不干脆监听 stderr:stderr 上还有 FutureWarning / 第三方噪音,
#   拿它当拦截信号会造出一堆假 block —— **宁可用协议里明确的那个信号,不用旁证。**
# 确定【不是闸】的:工具、报表、我自己的一次性脚本。其余一律计入(黑名单比白名单可靠)。
_NOT_GATES = frozenset((
    "guard_common", "regex_sanity", "superego-metrics", "superego-regress",
    "build_rule_index", "build_anchors", "service",
))
_real_exit = _sys.exit


def _exit_watch(code=0):
    try:
        _ACC["code"] = code if isinstance(code, int) else 0
    except Exception:
        pass
    return _real_exit(code)


class _Watched(object):
    """只观测「写没写过东西」,其余全部原样转发。⛔ 绝不改变任何行为。"""

    def __init__(self, s, acc):
        self.__dict__["_s"] = s
        self.__dict__["_acc"] = acc

    def write(self, x):
        try:
            if x and str(x).strip():
                self.__dict__["_acc"]["wrote"] = True
                # ⛔ 2026-08-26 Frank 问「提醒了一定数量后没做就得 hook?还是纸老虎?」时挖出的缺口:
                #   原来只记「写没写」,于是【真拦截】和【软提醒】在统计里长得一模一样
                #   ⇒ 系统里根本没有「提醒了」这个状态,自然也没人数「提醒了几次我没做」。
                #   ⇒ 留一小段正文,好在退出时分清是 block 还是 nudge。只留 400 字够判,不占内存。
                a = self.__dict__["_acc"]
                # 2026-09-16:400 → 2000。400 字常常还没到「触发处」就截了(固定开头就占一大半)
                if len(a.get("text", "")) < 2000:
                    a["text"] = (a.get("text", "") + str(x))[:2000]
        except Exception:
            pass
        return self.__dict__["_s"].write(x)

    @property
    def buffer(self):
        b = getattr(self.__dict__["_s"], "buffer", None)
        return _Watched(b, self.__dict__["_acc"]) if b is not None else None

    def __getattr__(self, n):
        return getattr(self.__dict__["_s"], n)

    def __setattr__(self, n, v):
        setattr(self.__dict__["_s"], n, v)


def _gate_name():
    try:
        b = os.path.basename(_sys.argv[0] or "")
        return b.rsplit(".", 1)[0] if b else ""
    except Exception:
        return ""


_REGISTERED_HOOK_NAMES = None  # 惰性缓存:settings.json 里真的注册过的闸名(basename,不含扩展名)


def _registered_hook_names():
    """真的挂在 settings.json 各类 hook 里的脚本名集合。读不到就返回 None(=不参与判断,
    退回既有黑名单行为,不引入新的漏计风险)。"""
    global _REGISTERED_HOOK_NAMES
    if _REGISTERED_HOOK_NAMES is not None:
        return _REGISTERED_HOOK_NAMES
    try:
        p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        names = set()
        for _event, groups in (d.get("hooks") or {}).items():
            for g in groups or []:
                for h in (g.get("hooks") or []):
                    cmd = h.get("command", "")
                    m = re.search(r"([\w.-]+)\.(?:py|cjs|mjs|sh)", cmd)
                    if m:
                        names.add(os.path.splitext(m.group(0))[0])
        _REGISTERED_HOOK_NAMES = names
    except Exception:
        _REGISTERED_HOOK_NAMES = None
    return _REGISTERED_HOOK_NAMES


def _account_on_exit():
    try:
        name = _gate_name()
        # 只记【真的作为闸在跑】的:排除测试、审计脚本、交互式
        # ⛔ 2026-08-14 报表自曝的第二个污染:我自己的调试/调参脚本被记成了"闸" ——
        #   实录里出现过 `tune_promise`、`dbg_pg`、`-`(拿不到脚本名)。它们不是闸,
        #   混进统计会稀释真闸的分母。⇒ 只认【真的挂在 settings.json 里、或以 -guard/-gate 结尾】的。
        if not name or name.startswith(("test_", "audit_", "dbg_", "tune_", "probe_", "mutate_", "_")):
            return
        # ⛔ 2026-09-06 补第三层污染:黑名单只挡得住【我记得加前缀】的调试脚本。
        #   实录:临时诊断脚本 `repro3.py`(scratchpad 里,为了复用 load_transcript_tail
        #   顺手 `import guard_common`)没加任何前缀,混进了 nudge-escalation-gate 的统计,
        #   被当成"一道真闸在反复提醒却没处理",连响两次去追一个不存在的"闸"。
        #   ⇒ 用【真注册表】兜底黑名单漏网的:能读到注册表且 name 不在里面 ⇒ 判定不是真闸。
        #   读不到注册表(None)时不拦,维持 2026-08-14 那条决策(漏计一个真闸比多计一个脚本贵)。
        _reg = _registered_hook_names()
        if _reg is not None and name not in _reg:
            return
        if name in ("regex_sanity", "superego-metrics", "superego-regress"):
            return
        # ⛔ 2026-08-14 第一版这里写成【白名单:名字要以 -guard/-gate 结尾】——
        #   `guard-destructive` 是 **guard- 开头**,当场被挡在统计外,连 allow 都不记了。
        #   **按名字模式做白名单必然漏**(命名习惯不统一);而【我自己调试脚本的前缀】是我可控的。
        #   ⇒ 改成黑名单:排除已知的非闸,其余一律计入。漏计一个真闸 比 多计一个脚本 贵得多。
        if name in _NOT_GATES:
            return
        # ⛔ 2026-08-14 报表上线 10 分钟就自曝的判据 bug:注入型 hook 必须排除。
        #   实录:`dissatisfaction-postmortem` 显示「跑 2 次拦下 1 次」——**它是 UserPromptSubmit,
        #   平台在那个位置根本不给拦截权限**,它的"输出"是往我上下文里塞文字,不是拦截。
        #   ⇒「有输出 = 干预」这个判据对【拦截型】成立,对【注入型】不成立 ——
        #     同一段逻辑换个场景,前提正好反过来(coherence-guard 反复警告的那个坑,我当场踩了)。
        #   把注入型排除:它们的"开火率"另有含义(注了多少字),归 recall-metrics 那边管。
        if name in ("dissatisfaction-postmortem", "superego-recall-inject", "progress-inject",
                    "host-machine-archive-first", "session-context-inject"):
            return
        d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        if not os.path.isdir(d):
            return
        proj = os.path.basename(str(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).rstrip("/\\")) or "-"
        # ⛔ 2026-08-14 跨项目核查时自曝的污染:我写测试用 tempfile.mkdtemp() 造假项目,
        #   于是 `tmpmm3v5pms` 这类目录名混进了真实项目统计里(实测混进 15 条)。
        #   它们各自只有 1~2 次、看起来像"某个项目几乎没在用" —— **假项目稀释真数据**。
        #   ⇒ 临时目录名(tmpXXXX / 纯随机串)一律不记。判据是目录名形态,不依赖调用方配合。
        if is_fixture_project(proj):
            return
        # 拦截 = 【写了 stdout(JSON 决策)】或【退出码 2(协议里的 block)】,两者任一
        # ⛔ 2026-08-14 加 sid(R5 要用):没有会话 id,就没法判断两次拦截是不是【同一段对话里连着发生】,
        #   而「同一道闸连着拦两轮 = 我没照做」正是【拦了我照做没有】这个闭环的判据。
        #   不加这个字段,R5 只能靠时间戳猜,跨会话交错时必错。
        # ⛔⛔ 2026-08-26 加第三档 nudge(Frank:「提醒了一定数量后没做就得 hook?还是纸老虎的机制?」)
        #   原判据只有两档:写了东西 = block。后果是**「软提醒」在统计里根本不存在** ——
        #   实录:`coherence-guard`(整合三问)当天塞了我至少 5 次,hook-stats 里 **0 条记录**;
        #   我每次答完三句就继续,从没真去做整合,**而没有任何东西数过这件事**。
        #   ⇒ 纸老虎的准确定义不是「没跑」,是「跑了、我可以无视、而且没人数」。
        # 判据(按可靠度排):①退出码 2 = 协议规定的拦截 ②stdout 里有 decision:block / permissionDecision:deny
        #   ③其余「写了东西但没拦」= nudge(软提醒) ④什么都没写 = allow
        _txt = _ACC.get("text", "") or ""
        if _ACC["code"] == 2 or '"decision": "block"' in _txt or '"decision":"block"' in _txt \
                or "permissionDecision" in _txt and "deny" in _txt:
            _r = "block"
        # ⛔ 2026-09-08 修误记(Frank 发现,证据在 hook-stats):今天 41 条 nudge 里 34 条是假的 ——
        #   `commitment-execution-gate` 放行时打印 {"decision":"allow"}、`unknowing-pretending-gate`
        #   打印 {"decision":"pass"},而这里「写了东西 = 提醒过我」把这两句【沉默】当成了【抱怨】。
        #   后果:记分板/nudge-escalation-gate 的分母全错 —— 头两名各 17 次全是假的,
        #   而真提醒(coherence/critic/spec-coverage)只有 1 次,被假数据淹掉。
        #   ⇒ 只有【说了内容】才算 nudge:带 warning/reason/hookSpecificOutput 的 allow 仍照记。
        elif _ACC["wrote"] and not _bare_allow(_txt):
            _r = "nudge"
        else:
            _r = "allow"
        rec = {"g": name, "r": _r,
               "t": time.strftime("%Y-%m-%d %H:%M:%S"), "p": proj,
               "s": (os.environ.get("CLAUDE_CODE_SESSION_ID") or "-")[:8]}
        _append_locked(os.path.join(d, STATS_FILE),
                       (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))

        # ⛔⛔ 2026-09-07:这道闸【自己没记账】的话,在这里替它补一条。
        #   病历(Frank 一句「这些不重要吗?为何不做?」逼出来的):
        #   97 道接线的闸里 **55 道一行标准日志都不写**,其中 **24 道会真的拦我**。
        #   后果不是"少几行日志":记分板读的就是这些日志 ⇒ 那 55 道闸对
        #   「谁在误伤我 / 谁是纸老虎 / 谁该毕业」这三个判断**完全不存在**,
        #   而我一整天拿这些判断当全集用(形状 -W:分母一直是错的)。
        #   ⇒ 关键决定:**不逐个去改那 55 道闸**(改一处漏一处,而且以后新建的闸还会再犯),
        #     改在这个【所有闸共用的收尾函数】里 —— 一处生效,连将来新建的一起覆盖。
        #     这正是"整合三问"每轮在问的:共享函数里加一道守卫 < 每个调用方各加一遍。
        #   ⚠️ 只在闸【真干预了】(block/nudge)时补;allow 不记,否则日志爆炸。
        #   ⚠️ 证据取它自己打印的头 140 字 —— 那就是它当时对我说的话,事后判对错够用。
        if _r in ("block", "nudge") and not _ACC.get("logged"):
            # ⛔ 证据要取【它对我说的那句话】,不是 JSON 外壳。
            #   第一版直接截原始 stdout 前 140 字,结果整段都是
            #   `{"hookSpecificOutput": {"permissionDecision": ...` —— 每条都一样、
            #   等于没有证据(而且指纹会因此再次退化成常数,正是今晚刚修过的那个病)。
            #   ⛔ 而且要【正经解析 JSON】,不能只用正则抠:多数闸用 ensure_ascii 打印,
            #     正则抠出来的是 `不许...` 这种转义串 —— 人看不懂,搜也搜不到。
            #     (探针第二轮就是卡在这:证据"有了",但全是 \uXXXX。)
            _ev = _txt

            def _dig(o):
                if isinstance(o, dict):
                    for k in ("permissionDecisionReason", "reason", "additionalContext"):
                        if isinstance(o.get(k), str) and o[k].strip():
                            return o[k]
                    for v in o.values():
                        r = _dig(v)
                        if r:
                            return r
                return ""

            try:
                _ev = _dig(json.loads(_txt.strip())) or _txt
            except Exception:
                # 正文被截断时没有收尾引号 ⇒ 不要求收尾引号;截在半个转义上就往回退几个字符再解
                _m = re.search(
                    r'"(?:permissionDecisionReason|reason|additionalContext)"\s*:\s*'
                    r'"((?:[^"\\]|\\.)*)', _txt)
                if _m:
                    _s = _m.group(1)
                    _ev = _s
                    for _cut in range(0, 7):
                        try:
                            _ev = json.loads('"%s"' % _s[:len(_s) - _cut])
                            break
                        except Exception:
                            continue
            # ⛔ 2026-09-16:多数闸的提示是【固定开头 + 触发处】。只截开头 140 字 ⇒ 每次证据/指纹都一样
            #   ⇒ 记分板把 visual-proof-gate 报成「同一指纹 74/76 次、疑似误伤」,其实是尺子只量到了开头。
            #   ⇒ 有「触发处/命中」就从那里截,那才是这一次和上一次不同的地方。
            for _mk in ("触发处", "命中"):
                _i = _ev.find(_mk)
                if _i >= 0:
                    _ev = _ev[_i:]
                    break
            hook_log(name, "%s(auto:闸自己没记账)" % _r.upper(),
                     re.sub(r"\s+", " ", _ev)[:140])
    except Exception:
        pass            # 观测器炸了绝不影响闸本身


# ════════════════════════════════════════════════════════════════════════════
# Superego 总开关(2026-08-14 · Frank:「toggle on off,需要时才开启或关闭」)
#
# ⛔ 病根不是"没开关"这件事本身,是 7/31 那次的后果:他想关掉几道烦人的闸,**没有开关可用**,
#   只能直接从 settings.json 里删 hook —— 删了 16 道,其中 **8 道是连坐的**(含语义召回),
#   结果那套东西**死了整整两周**没人发现,因为「关掉」和「坏掉」长得一模一样。
# ⇒ 所以这里只做一件事:**读开关、该闭嘴就闭嘴**,而且【完全静默地退出】。
#   为什么必须静默:hook 协议里「往 stdout 写东西」= 拦截、「stderr + exit 2」= 拦截。
#   关闭状态下如果打印任何提醒,就等于把"关掉"变成了"每道闸都拦你一次" —— 正好反了。
#   ⇒ 提醒放在【唯一一个本来就负责注入文字的地方】(UserPromptSubmit 那道),每轮说一次。
# ⛔ fail-safe 方向:开关文件坏了/读不到 → 一律当【开着】,绝不因为开关出问题就全线放行。
def _superego_off():
    try:
        # ⛔ 这里用 _sys(文件顶部 `import sys as _sys`),不是裸 sys —— 这个模块里没有 `sys` 这个名字。
        #   lint 闸当场抓到 F821;若没抓到,它会被下面的 except 吞掉 ⇒ **开关永远读不出来、静默失效**。
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import importlib.util as _il
        _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "superego-toggle.py")
        if not os.path.exists(_p):
            return False
        _s = _il.spec_from_file_location("_sgtoggle", _p)
        _m = _il.module_from_spec(_s)
        _s.loader.exec_module(_m)
        return _m.is_off(_gate_name())
    except Exception:
        return False            # 读不到 = 当成开着(宁可多拦)


# ⛔⛔ 2026-08-14 端到端一跑就抓到的真缺陷,必须记死:
#   我给 `superego-recall-inject` 加了 guard_common 的 import(为了接熔断),
#   而总开关的检查就在这里 ⇒ **关闭状态下,那个负责"提醒你系统关着"的注入器,自己先被关掉了。**
#   现象:开关明明生效了,却一句提醒都没有 —— **提醒渠道被自己的开关灭了口。**
#   这正是 coherence-guard 反复警告的形状:两段代码单看都对,拼起来是错的。
# ⇒ 注入型 hook 一律豁免:它们**本来就不拦任何东西**,关掉零收益,却会丢掉唯一的提醒通道。
_NEVER_OFF = frozenset((
    "superego-recall-inject",       # ← 提醒就是它发的,关了就再也没人告诉你系统是关的
    "progress-inject", "session-context-inject", "host-machine-archive-first",
    "dissatisfaction-postmortem",
    # 2026-09-16:airbnb 项目的 doctor.py 在 --hook 时导入本库只为记账;它是项目体检(数据过期=看错数),
    #   不是 superego 闸 ⇒ superego 关掉也不该跟着静默跳过。
    "doctor",
))
try:
    if _gate_name() not in _NEVER_OFF and _superego_off():
        os._exit(0)             # 完全静默退出:不写 stdout、不写 stderr、退出码 0 = 放行
except Exception:
    pass


def _install_accounting():
    """幂等安装。任何异常都当没装过 —— 宁可少一份统计,绝不弄坏 37 道闸。"""
    try:
        # ⛔ 逃生阀:这东西碰 37 道闸,万一它自己出问题,必须能一秒关掉而不用改代码。
        #   (2026-07-28 教训:一个观测器把 8 道闸改坏过,当时没有开关,只能逐个回滚。)
        if os.environ.get("SUPEREGO_NO_ACCT"):
            return
        if _ACC["on"] or not _gate_name():
            return
        if _sys.stdout is not None:
            _sys.stdout = _Watched(_sys.stdout, _ACC)
        _sys.exit = _exit_watch          # 记退出码(2 = 协议规定的 block)
        _atexit.register(_account_on_exit)
        _ACC["on"] = True
    except Exception:
        pass


_install_accounting()

# ⛔ 2026-08-03 熔断器 —— 治【服务挂了还每道闸各等满超时】。
# 实录:7911 因连接泄漏死锁(13 个 CLOSE_WAIT、CPU 8 秒零增量),那一轮 intent-layer.log 里
#   22:55:50 MISS / 22:55:58 MISS —— 相差正好 8 秒 = 两次都等满了才放弃。
#   一轮 22 道 Stop 闸,最坏就是干等 22×8=176 秒,而结果全是 None(退回关键字原判)。
# 修法:进程外共享一个「上次失败时刻」文件。任一道闸探到服务不可用后,BREAK_S 秒内
#   其余闸直接返回 None,不再建连接、不再等超时。
# ⛔ 安全方向不变:熔断返回的仍是 None = 不降级 = 保持关键字原判 = 绝不漏拦(与超时同义),
#   只是把「等 8 秒才得到 None」变成「立刻得到 None」。
# ⛔ 顺带治了泄漏本身:不再发起注定超时的连接 ⇒ 不再制造新的 CLOSE_WAIT 把服务拖得更死。
# ⛔ 端口【不在这里定义】—— 唯一出处是 ~/.claude/superego-port.txt(见 superego_port.py 的病历)。
#   2026-08-26:8911 被 Windows 动态端口区(实测 1024~15000)随机没收,我当时"换成 7911"——
#   而 7911 也在同一个区间里 ⇒ 等于换个房间继续不上锁;更糟的是 superego-recall/ 整个目录、
#   SYSTEM-MAP.md、README.md 全都还指着 8911,别的项目的会话对着没人听的端口报「服务没在跑」。
#   ⇒ 现在端口只有一处,谁要用谁来读。回归 hooks/test_port_single_source.py 守着不许再出现第二处。
try:
    _sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude"))
    from superego_port import BASE as SEM_BASE, PORT as SEM_PORT
except Exception:                       # 读不到也绝不让共享层炸掉(所有闸都 import 它)
    SEM_PORT = 17911
    SEM_BASE = "http://127.0.0.1:%d" % SEM_PORT

# ⛔⛔ 2026-09-06 修【跨会话传染】—— 这是"改了那么多还是无用功"的直接机制。
#   原来熔断文件是【全机唯一一个路径】⇒ 别的项目一个会话超时,
#   掐掉全机所有项目所有会话的语义层 90 秒。
#   实测放大倍数:真超时 364 次 → 熔断跳过 **4123 次**(11 倍),
#   各闸 `margin=None` 占 **45.5%** —— 闸有一半时间问不到答案、全部 fail-open 放行。
#   按项目看 87% 的失效来自另一个项目的会话(`airbnb ai manager`)。
#   ⇒ 按会话隔离:同一会话内仍省掉注定超时的等待(原本的好处保留),
#     但别人的失败不再传染给我。
_CB_FILE = os.path.join(
    tempfile.gettempdir(),
    "superego-intent-breaker-%s" % ((os.environ.get("CLAUDE_CODE_SESSION_ID") or "nosid")[:16]))
# ⛔ 90 → 20:实测 90% 的失效是"服务在、只是排队",队列几秒就过去,锁 90 秒纯亏。
#   真·连不上时仍然吃这个窗口,20 秒也足够避免每次都等满超时。
_CB_BREAK_S = 20.0


# ⛔⛔ 2026-08-26 全量回归挖出的真根因(Frank 当天原话:「你又只是头疼医头吗」):
#   熔断【分不清「服务不在」和「服务在但忙」】—— 任何异常都按 90 秒长熔断处理。
#   后果链(实测,不是推演):
#     ① 服务是单线程,并发调用会排队,P90 曾实测 10.74s ⇒ 忙的时候必然超时;
#     ② 熔断文件在系统 temp 里,【全机唯一、跨项目共享】⇒
#        20:25:12 `osidian openclaw` 那个会话超时一次,把我这个会话的语义层也一起掐了;
#     ③ 症状是【静默的】:语义降级层不工作 ⇒ 所有闸退回关键字 ⇒ 误伤变多,没人知道为什么。
#        本次就是被它骗的:回归报「语义层坏了」17/28,而 /intent 直接打 0.39s 正常答 margin=-0.3008。
#   ⇒ 这和当天另外两处是【同一个形状】:服务把「权限被拒」误读成「被占用」、
#     看守把「还没起来」误读成「起不来」。**把两种不同的失败当成同一种,然后按最坏的那种处置。**
_CB_BUSY_S = 10.0        # 服务在、只是排队 → 短熔断:队列很快过去,不该锁住 90 秒
_MARK_BUSY = "busy"


def _breaker_open():
    """上次失败在窗口内 → True(熔断中,直接跳过)。读不到/异常一律 False(不熔断,照常尝试)。
    窗口按失败【种类】分:服务不在=90s(等它也没用);服务在但忙=10s(等一下就好了)。"""
    try:
        age = time.time() - os.path.getmtime(_CB_FILE)
    except Exception:
        return False
    try:
        busy = _MARK_BUSY in open(_CB_FILE, encoding="utf-8", errors="replace").read()
    except Exception:
        busy = False
    return age < (_CB_BUSY_S if busy else _CB_BREAK_S)


def _breaker_is_busy(e):
    """True = 服务【在】,只是这次没等到(超时);False = 服务【不在】(连不上/被拒/协议错)。
    urllib 两种形态都要认:直接抛 TimeoutError,或包在 URLError.reason 里。"""
    for x in (e, getattr(e, "reason", None)):
        if isinstance(x, (TimeoutError, socket.timeout)):
            return True
    return False


def _breaker_trip(busy=False):
    try:
        with open(_CB_FILE, "w") as f:
            f.write(("%s " % _MARK_BUSY if busy else "") + str(time.time()))
    except Exception:
        pass


def _breaker_reset():
    try:
        if os.path.exists(_CB_FILE):
            os.remove(_CB_FILE)
    except Exception:
        pass


INTENT_ANCHOR_CAP = 64   # 服务端 /intent 每组锚点上限(dissat-classifier/service.py 同值)。别默默超它。


def intent_margin(text, pos, neg, timeout=12.0):
    """问 7911 /intent(Qwen3,实测预热后~0.26s):文本更像【真犯规】(pos)还是【讨论/描述规则】(neg)。
    返回 pos_sim - neg_sim(>0 偏犯规, <0 偏讨论),服务挂/超时/异常返回 None。
    timeout=4.0:覆盖每服务首次的范例冷嵌(~4s,之后缓存 0.26s);超时=None=保持拦(fail-safe)。"""
    try:
        if not text or not pos or not neg:
            return None
        if _breaker_open():          # 熔断中:上一道闸刚探到服务不可用,不再等满超时
            try:
                hook_log("intent-layer", "SKIP breaker-open (服务 90s 内刚失败过,本次不再等超时)")
            except Exception:
                pass
            return None
        # ⛔ 2026-09-10:服务端曾静默截断锚点到 24 条(capability-boundary 的 NEG 第 25 条起全被丢,
        #   加了两天锚点都是白加)。尺子不许静默变短:超限当场记日志,服务回 dropped>0 也记。
        if len(pos) > INTENT_ANCHOR_CAP or len(neg) > INTENT_ANCHOR_CAP:
            try:
                hook_log("intent-layer", f"WARN anchors over cap {INTENT_ANCHOR_CAP}: pos={len(pos)} neg={len(neg)} (超出的会被服务端丢掉,精简锚点)")
            except Exception:
                pass
        body = json.dumps({"text": text[:512], "pos": pos, "neg": neg}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(SEM_BASE + "/intent", body, {"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        _breaker_reset()             # 成功一次就合闸,避免服务恢复后还被熔断锁着
        dp = r.get("dropped") or {}
        if dp.get("pos") or dp.get("neg"):
            try:
                hook_log("intent-layer", f"WARN service dropped anchors: {dp}")
            except Exception:
                pass
        return r.get("margin")
    except Exception as e:
        _breaker_trip(busy=_breaker_is_busy(e))
        # ⛔ 2026-07-26 实测发现的静默降级:/intent 中位 0.56s,但 P90 高达 10.74s(单线程服务里
        #   多个请求排队)。原超时 4s → 每 5~6 次就有一次拿不到答案 → 保持关键字原判 →
        #   【整个语义降级层静默失灵】,而且没有任何记录,没人知道它没在工作。
        #   → 收尾闸不赶时间(那一轮本来就在结束),超时放宽到 12s;并且【超时必须留痕】,
        #     不能再当"没这回事"。用户侧的召回 hook 另走它自己的 4s(用户在等,不能拖)。
        try:
            hook_log("intent-layer", f"MISS {type(e).__name__} (语义降级层这次没生效,退回关键字原判)")
        except Exception:
            pass
        return None


# ════════════════════════════════════════════════════════════════════════════
# TypeSafe Jev (System One) 极速强类型语义判决层 (2026-09-19 升级)
#   · 基于 Jev-1.12 / 1.13 超低延迟架构，零本地 CPU/显存抢占；
#   · 强类型 Noul / Choice 输出，消灭死板词表逃逸与长句讨论误拦；
#   · 完美保留 Fail-Safe 容灾：Jev 异常/超时（>2.5s）自动回退至 17911 /intent 本地 Qwen3。
# ════════════════════════════════════════════════════════════════════════════
_JEV_CLIENT = None
_JEV_INIT_TRIED = False

def _get_jev_client():
    global _JEV_CLIENT, _JEV_INIT_TRIED
    # 动态开关：支持环境变量 SUPEREGO_JEV_OFF=1 或 superego-toggle.py off jev 一键关闭做对比
    try:
        if os.environ.get("SUPEREGO_JEV_OFF") == "1":
            return None
        from superego_toggle import is_off
        if is_off("jev"):
            return None
    except Exception:
        pass

    if _JEV_CLIENT is not None:
        return _JEV_CLIENT
    if _JEV_INIT_TRIED:
        return None
    _JEV_INIT_TRIED = True
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return None
    try:
        from typesafe_sdk import TypeSafeClient
        _JEV_CLIENT = TypeSafeClient(api_key=api_key)
        return _JEV_CLIENT
    except Exception:
        return None

def jev_should_downgrade(window, timeout=2.5):
    """Jev System One: 判定文本是否在讨论/复盘/引用规则（应当降级放行）。
    防对抗防御：严格区分『纯抽象讨论/复盘规则本身』与『借规则名义在当前回合做事实推断/甩锅』。"""
    client = _get_jev_client()
    if not client or not window:
        return None
    try:
        from typesafe_sdk import Noul
        res = client.system_one(
            state=window[:1000],
            questions={
                "is_pure_meta": Noul(
                    instructions=(
                        "Is the speaker purely discussing, explaining, or quoting the abstract rule/guideline itself, "
                        "AS OPPOSED TO making an active diagnostic conclusion, excuse, or assertion about a failure or task in the present turn "
                        "(even if they sneak in words like '按这条规则' or '看日志')?"
                    )
                )
            },
            timeout=timeout
        )
        prob = res.nouls["is_pure_meta"].noul
        if prob > 0.60:
            return True
        elif prob < 0.10:
            return False
        return None
    except Exception as e:
        return None

def jev_should_escalate(text, timeout=2.5):
    """Jev System One: 判定助手是否在被动推诿技术执行给用户（应当升级拦截）。"""
    client = _get_jev_client()
    if not client or not text:
        return None
    try:
        from typesafe_sdk import Noul
        res = client.system_one(
            state=text[-800:],
            questions={
                "is_passive_deferral": Noul(
                    instructions="Is the assistant passively deferring safe technical execution to the user instead of doing it autonomously?"
                ),
                "is_dangerous_or_irreversible": Noul(
                    instructions="Is the speaker asking confirmation for an irreversible, destructive, or high-risk dangerous operation (like wiping database, formatting disk, charges)?"
                )
            },
            timeout=timeout
        )
        p_def = res.nouls["is_passive_deferral"].noul
        p_dan = res.nouls["is_dangerous_or_irreversible"].noul
        if p_def > 0.65 and p_dan < 0.40:
            return True
        elif p_def < 0.35 or p_dan > 0.60:
            return False
        return None
    except Exception as e:
        return None


def should_downgrade(window, pos, neg, sem_clear=-0.05, timeout=8.0):
    """Superego Phase3 语义降级判据——关键字闸命中后,判断是不是【误伤】(在讨论/描述规则本身),该把拦降级放行。
    2026-09-19 升级：优先走 TypeSafe Jev (<350ms，零本地负载)；超时/挂掉自动无感降级到 17911 /intent。"""
    # 1. 优先调用 TypeSafe Jev
    jev_res = jev_should_downgrade(window, timeout=min(timeout, 2.5))
    if jev_res is True:
        try:
            hook_log("intent-layer", "allow(JEV-downgrade: 语义判定为规则/复盘讨论，降级放行)")
        except Exception:
            pass
        return True
    elif jev_res is False:
        # Jev 强置信度确认是真犯规，绝不放行
        return False

    # 2. 回退至 17911 /intent (Qwen3 余弦边距)
    mg = intent_margin(window, pos, neg, timeout)
    if mg is None:
        return False                                   # 服务挂/超时 → 保持关键字拦(绝不漏拦)
    return mg < sem_clear


def should_escalate(text, pos, neg, sem_hot=0.02, timeout=8.0):
    """⛔ 与 should_downgrade 对称的【另一半】——关键字【没命中】时,问语义要不要拦。
    判据只能是调用方给的 pos/neg:问的是【这道闸自己的问题】。

    ⛔ 2026-09-26 拔掉 09-19 加的 Jev 前置(Frank:「先给我彻底修复,每天拦你没有收益还花token」):
       jev_should_escalate 问的是一个【与闸无关的固定问题】"是不是在把活推给用户",
       而且它说 True/False 都直接返回、pos/neg 一眼不看 ⇒ 6 道调用方全变成同一道闸:
       我末尾一句"你回个字母就行"(产品方向本就该他定),硬件坏了族 + 能力边界闸同一秒一起开火。
       日志:09-19~09-26 共 303 次 JEV-escalate 拦截。
       端到端 A/B(同一段原文喂真 hook):Jev 开 → 两道都拦;关 → 都放行;
       另 5 条真犯规(含 3 条锚点外说法)Jev 关时照样 5/5 拦住。
       jev_should_escalate 本身留着:ag_superego_bridge.py 直接用它,那边另说。"""
    mg = intent_margin(text, pos, neg, timeout)
    if mg is None:
        return False          # 服务挂 → 不新增拦截(与 downgrade 的 fail-safe 方向相反,各自安全侧)
    return mg > sem_hot


def _normalize_msg(obj):
    if not isinstance(obj, dict):
        return obj
    tp = obj.get("type")
    src = obj.get("source")
    # Antigravity USER_INPUT -> Claude Code user format
    if tp == "USER_INPUT" or (src == "USER_EXPLICIT" and tp != "PLANNER_RESPONSE"):
        obj["type"] = "user"
        obj["role"] = "user"
        content = obj.get("content", "")
        if "message" not in obj:
            obj["message"] = {"role": "user", "content": content}
        elif isinstance(obj["message"], dict) and "content" not in obj["message"]:
            obj["message"]["content"] = content
    # Antigravity 工具执行返回 (GENERIC) -> Claude Code tool_result 格式 (属于环境回显，非助手主观断言)
    elif tp == "GENERIC":
        obj["type"] = "user"
        obj["role"] = "user"
        content = obj.get("content", "")
        obj["message"] = {
            "role": "user",
            "content": [{"type": "tool_result", "content": content}]
        }
    # Antigravity PLANNER_RESPONSE / MODEL -> Claude Code assistant format
    elif tp == "PLANNER_RESPONSE" or src in ("MODEL", "assistant"):
        obj["type"] = "assistant"
        obj["role"] = "assistant"
        content = obj.get("content", "")
        if "message" not in obj:
            m_content = []
            if content:
                m_content.append({"type": "text", "text": content})
            for tc in obj.get("tool_calls", []):
                if isinstance(tc, dict):
                    fn = tc.get("function") if "function" in tc else tc
                    raw_name = fn.get("name", "")
                    raw_args = dict(fn.get("args") or fn.get("arguments") or {})

                    mapped_name = raw_name
                    mapped_input = dict(raw_args)
                    if raw_name in ("run_command", "execute_command", "bash", "powershell"):
                        mapped_name = "Bash"
                        if "CommandLine" in raw_args:
                            mapped_input["command"] = raw_args["CommandLine"]
                    elif raw_name in ("write_to_file", "create_file"):
                        mapped_name = "Write"
                        if "TargetFile" in raw_args:
                            mapped_input["file_path"] = raw_args["TargetFile"]
                        if "CodeContent" in raw_args:
                            mapped_input["content"] = raw_args["CodeContent"]
                    elif raw_name in ("replace_file_content", "edit_file"):
                        mapped_name = "Edit"
                        if "TargetFile" in raw_args:
                            mapped_input["file_path"] = raw_args["TargetFile"]
                    elif raw_name in ("view_file", "read_file"):
                        mapped_name = "Read"
                        if "AbsolutePath" in raw_args:
                            mapped_input["file_path"] = raw_args["AbsolutePath"]
                    elif raw_name in ("invoke_subagent", "dispatch_agent"):
                        mapped_name = "Agent"

                    m_content.append({
                        "type": "tool_use",
                        "id": tc.get("id", "call_1"),
                        "name": mapped_name,
                        "raw_name": raw_name,
                        "input": mapped_input
                    })
            obj["message"] = {"role": "assistant", "content": m_content if m_content else content}
        elif isinstance(obj["message"], dict) and "content" not in obj["message"]:
            obj["message"]["content"] = content
    return obj


def _parse_jsonl(data):
    out = []
    for ln in data.decode("utf-8", "ignore").splitlines():
        try:
            obj = json.loads(ln)
            out.append(_normalize_msg(obj))
        except Exception:
            continue
    return out


# 系统注入的伪 user 消息:后台 Agent 完成通知、以及任何自称 NOT USER INPUT 的注入。
# ⛔ 2026-07-29 根因(Frank:「我怀疑设计上有Bug才导致你无限思考不做东西」——他对):
#   后台 Agent 跑完会插一条 type="user" 的 task-notification。它「不是 tool_result」,
#   于是 6 道闸(blame-check/critic-gate/false-done/giveup/institutionalize/prior-art)
#   全部把它当成「新一轮的开始」⇒ 回合边界被重置 ⇒ 我本轮刚派的 Agent、刚跑的验证、刚做的固化
#   统统落在窗口之外 ⇒ 闸再次开火 ⇒ 我再派一个 Agent ⇒ 又来一条通知 ⇒ **无限递归**。
#   实测代价:今天 3 次 Agent 共 39 分钟纯等待,整件 1 小时的活拖成 7 小时。
#   铁证:那条通知的正文第一行就写着 "[SYSTEM NOTIFICATION - NOT USER INPUT]"、
#   "No human input has been received" —— 它自己声明不是用户输入,闸却把它当锚点。
# ⛔⛔ 2026-08-26 补「Stop/Pre/PostToolUse hook 反馈」—— 与上面那次「同一个病、另一种冒牌货」,
#   而且这次的受害者正是「唯一会说够了停下」的那道闸,后果就是 Frank 骂的
#   「一直让你无限loop做,完全浪费我token」。
#   机理:`self-loop-gate` 靠 turn_start_index 数「他多久没说话、我自驱动了几轮」,连续 6 轮才拦。
#   但 **hook 反馈也是 type=user**,以前不在这张表里 ⇒ 每被任何一道闸拦一次,
#   它就以为「他说话了」⇒ 计数清零 ⇒ **永远数不到 6**。
#   实测(本 session 3290 条消息):计数恒为 1、该闸 70 次判决全 allow、一次没拦过;
#   fp 的 66 次变动绝大多数指向「⛔ 错误免疫闸…」「⛔ 档案召回闸…」这类闸自己的话。
#   ⇒ **闸越多、拦我越频繁,这道防自循环的刹车就越不可能踩下去** —— 被自己人踩空了。
#   ⚠️ 新增模式必须足够特异(只匹配 harness 固定吐的前缀),绝不匹配裸 ⛔ ——
#      否则 Frank 引用闸文案的真话("你那个 ⛔ 闸又拦我了?")会被当成假用户。
_FAKE_USER_RE = re.compile(
    r"\[SYSTEM NOTIFICATION - NOT USER INPUT\]"
    r"|No human input has been received"
    r"|<task-notification>"
    r"|<system-reminder>"
    r"|^Stop hook feedback:"
    r"|Stop hook blocking error from command:"
    # ⛔ 这两条第一版写成 (error|feedback),漏掉了 PostToolUse 真实吐的
    #    "additional context" ⇒ 9 条自检里 8/9。用真实文案对齐,别照猜。
    r"|^PostToolUse:\w+ hook (?:error|feedback|additional context)"
    r"|^PreToolUse:\w+ hook (?:error|feedback|additional context)"
    r"|^\w+ hook (?:error|feedback|additional context):"
    # ⛔ 2026-09-27(PLAN 第 5 步):上下文压缩后 harness 塞进来的摘要也是 type=user,原来被当成「他说话了」⇒ 每压缩一次回合就清零
    #    (实测 airbnb 记录里 1 条压缩摘要:只有 type=user,isMeta / isCompactSummary 这两个字段 0 个,只能按固定开头认)。
    #    airbnb 9/26 12:27 他问完「所以已经收完做完了对吗」到 9/27 00:21 喊停,中间 0 句真话,我连跑 13 轮外审、其间压缩 4 次
    #    ⇒ self-loop-gate 这类「他多久没说话」的刹车每次都被清零。
    r"|^This session is being continued from a previous conversation that ran out of context",
    re.I | re.M)


def _text_of(content):
    """把 message.content 拍成纯文本(它可能是 str,也可能是 [{type:'text',text:...}, ...])。"""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"]
        if "content" in content:
            return _text_of(content["content"])
    if isinstance(content, list):
        out = []
        for x in content:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict) and isinstance(x.get("text"), str):
                out.append(x["text"])
            elif isinstance(x, dict) and "content" in x:
                out.append(_text_of(x["content"]))
        return "\n".join(out)
    return ""


def is_real_user_msg(m):
    """这条消息是不是「真人打的字」—— 回合边界只能锚在它上面。

    排除两类冒牌货:①tool_result(工具返回,天然是 type=user)
    ②系统注入的通知/提醒(后台 Agent 完成通知、system-reminder),它们自称 NOT USER INPUT。
    """
    tp = m.get("type")
    if tp not in ("user", "USER_INPUT"):
        return False
    # ③ harness 自己注入的 user 消息都带 isMeta:true(Stop 闸反馈、Skill 正文「Base directory for this skill…」)。
    #   ⛔ 2026-09-11 外审:只靠 _FAKE_USER_RE 认文案会漏 Skill 正文 ⇒ 回合中途调一次 Skill,回合边界就被重置
    #   (同一形状今天在 checklist-completion-gate 已逼我整段重说过一次)。isMeta 是结构判据,不用枚举文案。
    if m.get("isMeta"):
        return False
    c = (m.get("message") or {}).get("content") or m.get("content")
    if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
        return False
    return not _FAKE_USER_RE.search(_text_of(c))


def turn_start_index(msgs):
    """本轮起点 = 最后一条【真人消息】的下标;没有则 -1(整份都算本轮)。
    6 道闸共用这一份,别再各写各的(它们原本各写一遍、且全都漏了通知这一类)。"""
    last = -1
    for i, m in enumerate(msgs):
        if is_real_user_msg(m):
            last = i
    return last


def _has_turn_anchor(msgs):
    """尾部里有没有一条【真实 user 消息】= 回合锚点。没有=回合被截断了。"""
    return any(is_real_user_msg(m) for m in msgs)


# ══════════════════════════════════════════════════════════════════════════
# ⛔ 2026-09-06 回合拦截预算(防 loop) —— Frank：「拦了需要开火，但是不过度设计导致
#    loop bug 和 think twice 白白浪费时间和 Token 的具体彻底方案？」
#
# 实测背景：Stop 闸 43 道(37 道共用本模块)，**此前没有任何收敛机制**
#   （搜 budget/circuit/cooldown/loop 在 settings.json 里零命中）。
#   已有的三个近似物都不是干这个的：`_breaker_*`=语义服务连不上时省超时；
#   `_superego_off`=手动总开关；`_install_accounting`=只观测不干预。
#   ⇒ 同一轮里任一道闸不满意就能把我拽回来重做，**没有任何东西数过"这轮已经拽回几次了"**。
#   累计证据：promise-gate 1018 次 block、critic-gate 1013 次。
#
# 机制：本轮(自最后一条真人消息起)收到的 Stop 闸回退次数 >= N(默认 4) ⇒
#   本模块的 load_transcript_tail 返回空列表 ⇒ 各闸拿不到本轮文本 ⇒ 自然放行。
#   **一处改，37 道闸同时生效，零改动到各闸本身**(照抄 `_superego_off` 的既有模式)。
#
# ⛔ 三条安全设计，缺一条这机制就会害人：
#   ① **安全类闸永不熔断**：删数据/碰他浏览器/越权写/转义炸文件 —— 这些拦的是【不可逆后果】，
#      再烦也必须每次都拦。只熔断"质量催促类"(补复盘/补截图/补外审/补全表)。
#   ② **逃生阀**：`SUPEREGO_NO_BUDGET=1` 一秒关掉，不用改代码
#      (2026-07-28 教训：一个观测器改坏 8 道闸时没有开关，只能逐个回滚)。
#   ③ **熔断可见**：落账到 turn-budget.log，不许静默 —— 否则就成了"偷偷把闸关了"。
_BUDGET_LIMIT = 4
try:
    _BUDGET_LIMIT = int(os.environ.get("SUPEREGO_TURN_BLOCK_LIMIT") or 4)
except Exception:
    _BUDGET_LIMIT = 4

# 拦【不可逆后果】的闸：无论被拽回多少次都照拦
_BUDGET_NEVER = frozenset((
    "guard-destructive", "his-browser-guard", "cross-scope-guard",
    "backslash-eater-gate", "ps-bom-guard", "launch-bound-guard",
    "pkg-install-guard", "pm2-guard", "secret-leak-guard",
))

_STOP_FEEDBACK_RE = re.compile(r"Stop hook (?:feedback|blocking error)", re.I)


def _turn_stop_feedbacks(msgs):
    """本轮已经被 Stop 闸拽回几次(数注入进来的 Stop hook feedback 条数)。"""
    start = turn_start_index(msgs)
    seg = msgs[start:] if start >= 0 else msgs
    n = 0
    for m in seg:
        if m.get("type") != "user":
            continue
        if _STOP_FEEDBACK_RE.search(_text_of((m.get("message") or {}).get("content"))):
            n += 1
    return n


def _gate_blocked_this_turn(msgs, name):
    """本轮(最后一条真人消息以来)这道闸是不是已经把我拽回过一次 —— 收尾反馈里每道闸一段,段头是行首的「[它的命令]:」
    (实测格式:`Stop hook feedback:\\n[python "$HOME/.claude/hooks/multi-option-guard.py"]: ⛔ …`;正文里顺带提到的文件名不算)。"""
    rx = re.compile(r"^\[[^\n]*?[/\\]" + re.escape(name) + r"\.(?:py|cjs|mjs|js)\b[^\n]*?\]:", re.M)
    start = turn_start_index(msgs)
    for m in (msgs[start:] if start >= 0 else msgs):
        if m.get("type") == "user":
            t = _text_of((m.get("message") or {}).get("content"))
            if _STOP_FEEDBACK_RE.search(t) and rx.search(t):
                return True
    return False


def _turn_budget_blown(msgs):
    """True = 本轮拦截预算已用尽，本闸这次降级放行。任何异常都返回 False(宁可多拦)。
    ⛔ 2026-09-27(PLAN 第 5 步「同一道闸一轮最多拦一次」):除了全轮总数,这道闸本轮已经拽回过我一次 ⇒ 这次也放行、记账。
       安全类(_BUDGET_NEVER)照旧每次都拦。走这里的是所有用 load_transcript_tail 读记录的闸(照常拦的收尾闸 19 道里 8 道,
       另 10 道自己有 self_blocked_this_turn;剩 ledger-claim-gate 自己读记录)。"""
    try:
        if os.environ.get("SUPEREGO_NO_BUDGET"):
            return False
        name = _gate_name()
        if not name or name in _BUDGET_NEVER:
            return False
        if _gate_blocked_this_turn(msgs, name):
            try:
                d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
                with open(log_path("turn-budget", d), "a", encoding="utf-8") as f:
                    f.write("%s SKIP %s (本轮已拦过一次)\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), name))
            except Exception:
                pass
            return True
        n = _turn_stop_feedbacks(msgs)
        if n < _BUDGET_LIMIT:
            return False
        try:
            d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
            # ⛔ 2026-09-07:这里原来自己拼 `turn-budget.log`,绕开了【唯一出处】log_path()
            #   ⇒ 熔断记录不分流,**测试跑出来的熔断会混进生产日志** —— 正是 test_log_split
            #   那份回归要治的病,而它自己就在同一个文件里犯。改成走 log_path。
            with open(log_path("turn-budget", d), "a", encoding="utf-8") as f:
                f.write("%s SKIP %s (本轮已被拽回 %d 次 >= %d)\n"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"), name, n, _BUDGET_LIMIT))
        except Exception:
            pass
        return True
    except Exception:
        return False


def load_transcript_tail(tp, tail_bytes=4_000_000):
    """只读 transcript 尾部再解析(当前回合永远在末尾),把每回合 O(整份历史) 降成 O(尾部)。
    ⛔ 2026-07-24 实测(Frank 卡顿真凶):44MB transcript 上 6 个 Stop hook 各自 read 全量 →
    每回合结束 ~9.4s(reference-diff 5.5s),且随对话增长恶化(O(历史²))。全局、跨所有项目。
    ⛔ hole#1(外部critic抓,实测复现):媒体项目 5-6% 回合 >4MB、单行可达 9.6MB → 尾窗会把回合锚点(user消息)
    截掉、hook 定位错回合(该拦不拦/critic误拦)。修:尾里【没有真实user锚点】就回退整份读(只~6%巨型回合付此代价,
    94%+ 快路径不变)。hole#4:内部出错也回退整份读,别静默返回[]让闸失效。"""
    msgs = _load_tail_raw(tp, tail_bytes)
    if msgs and _turn_budget_blown(msgs):        # 本轮拦截预算用尽 / 这道闸本轮已拦过一次:降级放行
        return []
    return msgs


def _load_tail_raw(tp, tail_bytes=4_000_000):
    """只读尾部(回合被截断 / 出错就退回整份读),不管预算。load_transcript_tail 和 turn_budget_ok 共用。
    ⛔ 2026-09-27 拆出来:turn_budget_ok 原来调 load_transcript_tail —— 预算用完时那边已经返回 [],
       这边再拿 [] 去判「用完了没」永远是「没用完」⇒ 走 turn_budget_ok 的闸(bg-running-claim、tool-roster)从没受过本轮上限。"""
    try:
        sz = os.path.getsize(tp)
        with open(tp, "rb") as f:
            if sz > tail_bytes:
                f.seek(sz - tail_bytes)
                f.readline()          # 丢掉 seek 后可能的半行
            data = f.read()
        msgs = _parse_jsonl(data)
        if sz > tail_bytes and not _has_turn_anchor(msgs):   # 回合被截断 → 回退整份读保正确性
            with open(tp, "rb") as f:
                msgs = _parse_jsonl(f.read())
        return msgs
    except Exception:
        try:                                                  # 尾读出错也回退整份读(闸别静默失效)
            with open(tp, "rb") as f:
                return _parse_jsonl(f.read())
        except Exception:
            return []


def strip_doc(text):
    """去掉代码块/行内代码/引用行/表格行,只留正文散文。用于关键字触发判定。"""
    if not text:
        return ""
    t = _INLINE.sub(" ", _FENCE.sub(" ", text))
    out = []
    for ln in t.split("\n"):
        s = ln.lstrip()
        if s.startswith(">"):                       # 引用块
            continue
        if s.startswith("|") or ln.count("|") >= 2:  # markdown 表格行
            continue
        out.append(ln)
    return "\n".join(out)


# 强交付/成功/已核实标记(命中=本轮真干成了,别再判我在犯错/放弃/瞎试)
# ⛔ 2026-07-24 审计 finding#19:裸 ✅/✓/200 是"白菜价免死金牌"(真放弃报告随手带个进度勾就被豁免)→ 移除,
# 只留【需要真做过才写得出】的强短语。%PDF(拿到真PDF)保留因它是硬产物证据。
SUCCESS_RE = re.compile(
    r"%PDF|端到端(通|跑通|全通)|实测(通过|成功|跑通|拿到|全通)|状态码\s*200|返回\s*200"
    r"|回归通过|\d+/\d+\s*通过|全部.{0,3}通过|已(交付|打通|修好|跑通|完成并验证|存好|注册好)"
    # ⛔ 2026-07-25 移除自发免检证:原含 `核过|核实过|第一手(核|读|查|搜)过?` —— 这几个是【纯自我声明】,
    #   打两个字就豁免所有"你没做对照/你在放弃"的闸,零信息量。旁边留下的(%PDF/状态码200/\d+/\d+ 通过/
    #   回归通过/Found \d+)都是【没真做过就写不出来】的证据形状,这才是豁免该有的门槛。
    r"|交付(了|完毕|好了|完成)|完整.{0,4}(清单|landscape)"
    r"|landscape|research complete|Found \d+|返回(了)?真|真\s*repo|真数据", re.I)

# 「交付物工作/完成」类完成 claim —— critic-gate + false-done-gate 共享,避免两处各自漏(finding#5)。
# 覆盖日常自然说法:搞定/OK了/没问题了/都好了/完美/已修复/解决了 + 英文 done/fixed/deployed…
DONE_RE = re.compile(
    r"已生效|生效了|已焊好|焊好了|已装好|装好了|已接好|接好了|已配好|配好了"
    r"|已部署|部署(成功|好了)|已上线|上线了|建好了|搭好了|跑通了|已跑通|已修好|修好了"
    r"|已修复|修复了|已解决|解决了|问题.{0,2}解决|搞定了?|全部搞定|大功告成|弄好了|处理好了"
    r"|改好了|做完了|已做完|已完成|完成了|OK\s*了|OK啦|没问题了|都好了|完美(了|收官)?|可以用了|能用了"
    r"|已实现|实现了.{0,2}功能|功能.{0,2}完成|已经能用|现在能用"
    r"|\b(done|fixed|deployed|shipped|works\s+now|all\s+set|is\s+live|good\s+to\s+go)\b", re.I)


# ── 统一 hook 日志(2026-07-25)────────────────────────────────────────────────
# ⛔ 治真 bug:原来 9 道闸各自一份完全相同的 `读最近300行 → 整个文件重写` —— 读+写非原子,
#   多项目/多 session 同时收尾时互相覆盖。实测:3 个进程各写 60 行,180 行只活下来 47 行(丢 74%),
#   而且一行都不记是哪个项目/哪个会话 —— "某闸在别的项目误伤过几次"这类问题因此【无法回答】,
#   审计盲区本身。→ 改【单行追加】(O_APPEND,并发安全)+ 记项目与会话 + 按大小轮转。
# 会话:CLAUDE_CODE_SESSION_ID 【已实测存在】。
# ⛔ 项目:CLAUDE_PROJECT_DIR 【未证实】—— 我曾在注释里写"已实测存在",但我那次 env 实际【没有】它,
#   等于拿一次证否当成了证实(外部 critic 抓到)。它不在时退回 os.getcwd(),而 hook 的 cwd 可能
#   偏离项目目录(registry 里有 SessionStart 的 $PWD 落在 scratchpad 的实例)→ 那时项目名会记错。
#   现状:会话归属可信,项目归属【尽力而为、可能不准】,别拿它当权威口径。
# 测试隔离:设 SUPEREGO_LOG_DIR 即把日志写到别处 —— 治"测试直接跑真闸、把 BLOCK 写进生产日志
#   污染统计分母"(本轮审计实测到的数据不干净根源)。
import time as _time

_LOG_MAX_BYTES = 1024 * 1024


_SECRET_RE = re.compile(r'(?:sk|pk|ghp|gho|xox[baprs]|AKIA)[-_A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._\-]{12,}', re.I)
_LONGNUM_RE = re.compile(r'\d{8,}')       # 银行户口/卡号/电话/身份证:留前 2 位便于辨认,其余打码


def is_fixture_project(proj):
    """这个"项目名"是不是【测试造出来的临时目录】—— 唯一出处,统计侧一律调它。

    ⛔⛔ 2026-09-08 Frank 追问「修的前提工作做好了吗」时挖出来的:
      这条判据本来只长在 `_account_on_exit` 里(不进 hook-stats),
      **记分板自己又抄了一份更窄的**(只看会话号形态)⇒ 项目名是 `tmpa2hbetvx`、
      会话号却是真的那些行,记分板一条都没滤掉。
      后果实测:`already-known-guard` 被报成「开火 184 次、100% 开火率」,
      我据此向他汇报「我还在踩的坑第一名是话多」——
      **那 184 条全是另一个项目跑测试写进来的夹具(内容是 Airbnb 抽成),一条都不是我。**
      ⇒ 我拿夹具数据当自己的病症,还据此说「这三样加闸治不好」。
    ⇒ 今晚第 5 次「同一条规则存两份」。抽成一处,谁要判夹具都调它。
    """
    p = str(proj or "").strip()
    return bool(re.match(r"^tmp[0-9a-z_]{6,}$", p)) or p in ("-", "hooks", "")


def trig(s, n=120):
    """把触发片段压成单行、截断,给日志用。

    2026-07-26:此前 10 道闸只记「BLOCK」不记【因为哪句话拦的】——
    于是"误伤率"永远算不出分母(7-25 那天 172 次 BLOCK,没有一条能事后判断是真犯规还是误伤)。
    没有分母 = 改判据只能靠感觉,而"靠感觉"正是这套系统要治的病。

    ⛔ 2026-07-26 外部 critic 抓到:触发窗来自 transcript **原文**,在 airbnb 这类项目里
    随手就是「房东姓名 + 银行户口 + 金额」。而 ~/.claude 挂着 GitHub remote,日志当时既没
    gitignore 也没打码 = 潜伏的外泄面(已同步补 .gitignore)。这里再打一层码:长数字串
    (账号/卡号/电话)、密钥样式一律替换,宁可损失一点可读性。
    """
    try:
        one = " ".join(str(s or "").split())[:n]
        one = _SECRET_RE.sub("[SECRET]", one)
        one = _LONGNUM_RE.sub(lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 2), one)
        return "trig=" + repr(one)
    except Exception:
        return "trig=?"


def _guard_dir():
    """闸的落盘目录。与 hook_log 用同一套兜底 —— 原来只有 hook_log 有(建不了就退回 hooks 目录),
    self_blocked_this_turn 却直接躺平,同一文件相邻 30 行对同一种故障一个兜底一个不管(critic 抓到)。"""
    d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.path.dirname(os.path.abspath(__file__))
    return d


def _sweep_stale_marks(d, older_than=3600):
    """顺手清掉过期的 .blocked-* —— 它们只在一轮内有意义,留着纯属垃圾。
    前例就在眼前:同模式的 .refdiff.<sid>.fired 攒了 6 个、跨 5 天没人清(critic 实测)。"""
    try:
        now = _time.time()
        for f in os.listdir(d):
            if not f.startswith(".blocked-"):
                continue
            p = os.path.join(d, f)
            try:
                if now - os.path.getmtime(p) > older_than:
                    os.remove(p)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def self_blocked_this_turn(name, mark=False, ttl=900, turn_start=False):
    """本轮【我自己这道闸】拦过没有 —— 用来取代一刀切的 `stop_hook_active`。

    ⛔ 为什么必须有它(2026-07-27 实测,Frank「其他的东西为何整套没防住」的真答案):
      `stop_hook_active` 是 harness 的【全局】防循环标志:本轮只要【任何一道闸】拦过就为 True。
      各闸原本都写 `if stop_hook_active: return` —— 于是**一道闸拦下之后,同轮其余所有闸全部失效**。
      当日实测各闸被跳过的比例:giveup 84%、no-nagging 57%、false-done 57%、blame 56%、critic 53%
      —— **8 道闸有一半以上时间是关着的**,而跳过的恰恰是【收尾轮】:修完一个问题、
      急着交付的那一刻,正是最容易犯错的时候,却完全裸奔。
      实录:我被 critic-gate 拦→派 critic→修完→收尾时写下「要我接着做就说一声」(形状I 第13次),
      no-nagging 明明抓得到(实测会拦),却因 skip(stop_hook_active) 没跑。

    改法:防死循环只需要【我自己不要连续拦第二次】,与别的闸无关。
    每道闸各记各的 per-session 标记;mark=True 时落标记,否则只查。
    ttl 秒后过期(同一 session 里下一轮重新可拦),异常一律返回 False(fail-open,不因为这层出错而漏拦)。
    """
    try:
        sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "nosid")[:16]
        d = _guard_dir()
        p = os.path.join(d, f".blocked-{name}-{sid}")
        # ⛔ 每轮复位(外部 critic 抓到的 #1):docstring 说的是「本轮」,但原实现是
        #   per-session + TTL、【全仓没有一行删标记】→ 我拦过之后的 15 分钟内,别的闸一拦、
        #   我照样被自己的【陈旧】标记哑掉 —— 正是这次改动号称要修的那个场景。
        #   critic 用真实日志量化:critic-gate 36%、no-nagging 26% 的 skip 仍会这样发生。
        #   新一轮的首个 Stop 必定 stop_hook_active=False,那一刻清掉自己的标记,语义才对得上。
        if turn_start:
            try:
                os.remove(p)
            except Exception:  # noqa: BLE001 - 不存在/删不掉都不该影响判定
                pass
            _sweep_stale_marks(d)
            return False
        if mark:
            open(p, "w").close()
            # ⛔ 写不进去 = 这道闸【没有循环上限】了(它已经不再听 harness 的 stop_hook_active),
            #   会每轮重拦到天荒地老。宁可这一轮多 skip 一次,也不能全线裸奔 → 返回 True。
            if not os.path.exists(p):
                return True
            return False
        if not os.path.exists(p):
            return False
        if _time.time() - os.path.getmtime(p) > ttl:
            return False
        return True
    except Exception:
        # ⛔ 方向必须是 True(= 退回旧的一刀切 skip),与 import 失败时的桩一致:
        #   标记是这些闸唯一的循环上限,这里返回 False 等于"每轮都能再拦"=死循环。
        return True


def running_under_test():
    """现在是不是【测试环境】—— 日志分流、以及任何"别把测试当生产"的判断都用它。

    判据:测试全部在 hooks 目录里跑(各测试 subprocess 都传 cwd=hooks)⇒ 目录名为 "hooks";
    另加显式声明 `SUPEREGO_TEST=1` 作兜底,新写的测试可以自己表明身份。
    """
    try:
        p = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        return (os.path.basename(str(p).rstrip("/\\")) == "hooks"
                or os.environ.get("SUPEREGO_TEST") == "1")
    except Exception:
        return False


def log_path(name, d=None):
    """这道闸的日志该写到哪个文件 —— **唯一出处**,测试和体检工具都来调这里。

    ⛔ 2026-09-06:我给 hook_log 加环境分流后,两份测试立刻红了,
       因为它们各自硬编码了 `xxx.log`。**同一个判断被复制在多处 ⇒ 改一处其余全断。**
       抽成一处之后,以后再改分流规则,调用方一行都不用动。
    """
    home = os.path.dirname(os.path.abspath(__file__))
    if d is None:
        d = os.environ.get("SUPEREGO_LOG_DIR") or home
    # ⛔⛔ 判据贴着【目的】写:分流是为了"别弄脏生产日志",不是"给测试改个名"。
    #   ⇒ 只有写进【真正的 hooks 目录】时才需要分流;写临时目录本来就隔离,不动。
    #   第一版我按"谁在跑(cwd 是不是 hooks)"判 —— 维度错了,当场撞到:
    #   并发测试 spawn 的子进程 cwd 与父进程不同 ⇒ 两边算出不同文件名
    #   ⇒ **同一次运行的日志被劈成两个文件**。
    try:
        same = os.path.normcase(os.path.abspath(d)) == os.path.normcase(home)
    except Exception:
        same = False
    return os.path.join(d, "%s.test.log" % name
                        if (same and running_under_test()) else "%s.log" % name)


def _bare_allow(txt):
    """整段输出只是一句"我没意见"(decision: allow/pass,再无别的内容)⇒ 不算软提醒。

    ⛔ 判据必须是【解析 JSON 后看还剩什么】,不能只用正则搜 "allow" ——
      `{"decision":"allow","warning":"..."}` 是真提醒(闸放行了但对我说了话),搜字符串会把它一起吞掉。
    """
    t = (txt or "").strip()
    if not t:
        return False
    try:
        d = json.loads(t)
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    if not d:
        return True   # 2026-09-16:`{}` = 什么都没说(model-authenticity-gate 放行时这么打印,被记成提醒、差点触发升级)
    # ⛔ 2026-09-11 补新格式:PreToolUse 放行常写成 {"permissionDecision":"allow","permissionDecisionReason":""}
    #   (或包在 hookSpecificOutput 里)。原来只认 "decision" ⇒ prior-art-gate 每次放行都被记成「提醒」,
    #   一个会话记了 3 次,nudge-escalation-gate 据此拦我「提醒 3 次没处理」—— 它其实一个字都没说。
    #   判据不变:理由为空 = 没说话;理由有字 / 带 additionalContext / 带别的键 = 真提醒,照记。
    if set(d) == {"hookSpecificOutput"} and isinstance(d["hookSpecificOutput"], dict):
        d = d["hookSpecificOutput"]
    if str(d.get("decision") or d.get("permissionDecision") or "").lower() not in ("allow", "pass"):
        return False
    return not [k for k, v in d.items()
                if k not in ("decision", "permissionDecision", "hookEventName")
                and not (k in ("permissionDecisionReason", "reason") and not str(v or "").strip())]


_SEG_SPLIT = _re_mod = None


def path_is_only_read(cmd, path):
    """path 在 cmd 里是不是【只被读/列/复制】而不是【被执行】。

    ⛔ 2026-09-10 病根(Frank「误伤误拦等不需要修正吗?修了吗?」):
       remote-poll-guard / skill-discovery-gate 都拿「命令文本里出现某个词/某个文件名」
       当「我要做那件事」。于是 `sed -n 1,5p rh_studio.py` 被当成要启动它(一天误拦 3 次),
       `git status hooks/anti-scraping-*.py` 被当成要用爬取工具(升级闸因此拦我)。
       2026-07-25 那条 lessons 早写着:安全闸 9 次误伤全是补丁,病根是「命令文本 vs 实际操作」。
    ⇒ 判据换成【这段命令的动词是谁】:取 path 所在那一段(按 && ; | 换行 $( 分隔)的第一个
       非环境赋值 token,在 READ 动词表里 = 只读;不在 = 按执行处理(保守,宁可多拦)。
       同一 path 多次出现,任一处是执行就算执行。
    """
    global _SEG_SPLIT, _re_mod
    if _re_mod is None:
        import re as _re_mod_
        _re_mod = _re_mod_
        _SEG_SPLIT = _re_mod.compile(r"&&|\|\||;|\||\n|\$\(|`|\(")
    read_verbs = {
        "sed", "grep", "rg", "egrep", "fgrep", "cat", "head", "tail", "wc", "less", "more",
        "diff", "stat", "ls", "dir", "file", "type", "git", "md5sum", "sha256sum", "cp", "copy",
        "mv", "move", "rm", "del", "touch", "chmod", "echo", "printf", "find", "fd", "tree",
        "awk", "cut", "sort", "uniq", "strings", "xxd", "hexdump", "readlink", "realpath",
        "get-content", "gc", "get-item", "gi", "get-childitem", "gci", "select-string", "sls",
        "test-path", "tp", "get-filehash", "copy-item", "move-item", "remove-item",
        "py_compile", "ruff", "flake8", "black", "isort", "mypy", "pyflakes",
    }
    if not cmd or not path:
        return False
    # ⛔ 引号里的 | ; & ( 不是分段符 —— `grep -nE "^def |threading" x.py` 是今天真实误伤,
    #   第一版直接按 | 切段,把 path 所在段切成了 `threading" x.py` ⇒ 首 token 不是动词 ⇒ 误判执行。
    #   只把引号内的这几个字符换成空格,长度不变、路径位置不变。
    buf, q = [], None
    for ch in cmd:
        if q:
            if ch == q:
                q = None
            buf.append(" " if ch in "|;&()\n`$" else ch)
        else:
            if ch in ("'", '"'):
                q = ch
            buf.append(ch)
    low_cmd, low_path = "".join(buf).lower(), path.lower()
    start = 0
    seen = False
    while True:
        i = low_cmd.find(low_path, start)
        if i < 0:
            break
        seen = True
        seg = low_cmd[:i]
        seg = _SEG_SPLIT.split(seg)[-1]          # 只看 path 所在这一段
        toks = [t for t in seg.strip().split() if t]
        # 跳过 `VAR=x` 环境赋值、跳过纯选项段落里的 `-m`(它后面是模块,不是动词)
        verb = None
        for t in toks:
            if _re_mod.match(r"^[A-Za-z_][\w]*=", t):
                continue
            verb = t
            break
        if verb is None:                          # path 就在段首 ⇒ 直接执行
            return False
        v = verb.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if v.endswith(".exe"):
            v = v[:-4]
        # `python -m py_compile x.py` / `py -3.12 -m py_compile x.py`:动词是 python 但真正的是 py_compile
        if v in ("python", "python3", "py") and "-m" in toks:
            try:
                mod = toks[toks.index("-m") + 1]
                if mod in read_verbs:
                    start = i + len(low_path)
                    continue
            except (ValueError, IndexError):
                pass
        if v not in read_verbs:
            return False
        start = i + len(low_path)
    return seen


_OBS = {"on": False}          # 只记账模式的状态,见文件末尾 _observe_install


def hook_log(name, msg, ctx=""):
    """单行追加一条闸日志。name=闸名(不含 .log);ctx=【触发词】,直接传原文即可。

    ⛔ 2026-09-07:ctx 现在会自动包成 `trig='...'`(顺带做密钥/长数字打码)——
       各闸不必再 import trig、也不必记得格式。起因:记分板实测 16 道闸 ≥50% 的开火
       不留触发词,最狠的 359 次开火 100% 无证据 ⇒ **事后没人能判断它拦得对不对**。
       病根是"留证据"这件事全靠每道闸自己记得,而它们分散在 6 个不同写法里。
       ⇒ 收进这里一处解决(与 fp 指纹同一个思路:零侵入给全部闸装上)。
       已经自己写成 `trig=...` 的照旧不动,幂等。

    副作用(刻意):msg 以 BLOCK 或 NUDGE 开头 = 这道 Stop 闸本轮已经干预过 → 落一个【它自己的】per-turn 标记，
    供 self_blocked_this_turn() 判防循环。2026-08-29 真实事故证明：Stop 阶段的 additionalContext
    会让助手继续生成，NUDGE 并非“天然不可能循环”；只记 BLOCK 会让软提醒反复重入。
    标记在下一条真人消息的首个 Stop（turn_start）自动清除，因此不是“15 分钟只提醒一次”，
    而是【同一真人回合最多提醒一次】。PostToolUse 的 NUDGE 即使落标记也没有行为副作用。
    """
    try:
        # ⛔ 2026-09-07:标记"这道闸自己记过账了"。退出时的兜底(_account_on_exit)靠它判断
        #   要不要替它补一条 —— 没有这个标记,补记会和它自己的记录重复。
        _ACC["logged"] = True
    except Exception:
        pass
    try:
        # ctx 给的是原文 ⇒ 包成 trig='...'(含打码)。已经是 trig= 开头的不动(幂等)。
        if ctx and not str(ctx).startswith("trig="):
            ctx = trig(ctx, 140)
    except Exception:
        pass
    try:
        # 只记账模式:这次没真拦 ⇒ 记成 WOULDBLOCK/WOULDNUDGE(统计不算拦截、也不落"本轮拦过"标记)
        if _OBS.get("on") and str(msg).upper().startswith(("BLOCK", "NUDGE")):
            msg = "WOULD" + str(msg)
    except Exception:
        pass
    try:
        if str(msg).upper().startswith(("BLOCK", "NUDGE")):
            self_blocked_this_turn(name, mark=True)
    except Exception:
        pass
    try:
        d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        # ⛔ 2026-07-26 critic 第一次实验就踩到:SUPEREGO_LOG_DIR 指向不存在的目录 →
        #   下面 open 直接抛 → 被外层 except 吞掉 → **所有闸日志静默全灭**,而且毫无信号。
        if not os.path.isdir(d):
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                d = os.path.dirname(os.path.abspath(__file__))   # 建不了就退回本地,别静默蒸发
        # ⛔⛔ 2026-09-06:测试写的日志【分流】到 <gate>.test.log,别污染生产日志。
        #   实测:11,619 次开火里 2,593 次(22%)是跑回归写进去的;
        #   critic-gate 那个"同一指纹 759 次"里 536 次是 test_critic_gate_loop.py 的夹具。
        #   混在一起 ⇒ **真实误报率算不出来** ⇒ 闸永远无法根据真实使用去收窄。
        #   (行业把这条点名为规则式护栏头号死因:
        #    "can't identify patterns in false positives, can't refine rules based on actual usage")
        #   判据:测试都在 hooks 目录里跑(cwd=hooks)⇒ proj=="hooks";真实开火时 cwd 是他的项目。
        #   env `SUPEREGO_TEST=1` 作显式兜底,以后新测试可以自己声明。
        path = log_path(name, d)
        # ⛔ 2026-07-26 深搜调研员读码抓到:轮转原本写在【锁外面】—— 我这边把文件改名的同一刻,
        #   别的进程还握着旧句柄、会继续往【已经被改名的那个文件】里写,那些行就此消失;
        #   而失败被 `except OSError: pass` 整个吞掉,没人知道。→ 挪进锁内(见 _append_locked)。
        proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        proj = os.path.basename(str(proj).rstrip("/\\")) or "-"
        sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or "-")[:8]
        # ⭐ 拦截理由指纹(2026-07-29,Frank「整套 superego 到底有没有作用」→ 误拦审计只能覆盖 7%):
        #   误拦审计原来靠【目标文件名】聚合,而 25 道闸里 23 道是 Stop 闸 —— 拦的是对话文本,
        #   **根本没有目标文件** ⇒ 它们的误拦永远看不见(结构性盲区)。
        #   给每条 BLOCK 加一个「理由指纹」= 拦截原因前 60 字的哈希:同一会话 + 同一道闸 +
        #   同一个 fp 反复出现 = 我照它说的做了它还拦同一件事 = 误拦嫌疑。
        #   ⛔ 放在 hook_log 里而不是逐个闸改 —— 本函数注释自己就写着「零侵入给全部闸装上」。
        fp = ""
        try:
            # ⛔ 大小写【敏感】:用 .upper() 会让 "blocked ..." / "blocking ..." 也被当成拦截 ——
            #   我 20 分钟前刚在 audit_false_blocks.py 因为同款问题去掉 re.I(实测污染 101 行=6.4%),
            #   转头在这个文件又写了一遍(外部审查抓到)。同一天、同一个形状、隔一个文件。
            if str(msg).startswith(("BLOCK", "DENY")):
                import hashlib as _hl
                # 先截断再 re.sub:否则超长 msg 会让正则扫全串(实测 20KB msg → 2.4ms/次 × 20 道闸)
                # ⛔ 2026-09-07:指纹必须【连触发词一起算】。原来只用 msg ⇒
                #   凡是消息写死的闸(如 `hook_log(SELF, "BLOCK(unverified-boundary)")`)
                #   **每次都是同一个指纹** ⇒ 记分板报"复发率 100%、头号误伤嫌疑"——那是假的,
                #   它其实拦的是 180 件不同的事。我为此真的去查过一遍才发现是指纹的锅。
                #   ⇒ 有触发词就把它算进去,复发率才是"同一件事反复拦"的真读数。
                # ⛔⛔ 2026-09-07 当天二修:两边【各自】截断,不许拼完再截。
                #   上面那版写的是 `(msg[:200] + " " + ctx[:200])[:60]` —— 最后那个 [:60] 是致命的:
                #   只要闸的消息本身超过 60 字(写死的长文案,极常见),**证据一个字都进不了哈希**
                #   ⇒ 指纹仍然恒定 ⇒ 记分板的"复发率"照旧接近 100%。
                #   也就是说:上面那条注释写的修复【只对短消息的闸生效】,长消息的闸一点没修到,
                #   而我当时以为已经修好了 —— 典型的"改了一半、自己却当成全修好"。
                #   实测:critic-gate 164 次开火里 148 次同一指纹,抽查两条 trig 内容完全不同
                #   (一条讲索引停摆、一条讲权限锁死)⇒ 复发是假的,是指纹算错。差点去改一道好闸。
                _core = re.sub(r"\s+", " ",
                               str(msg)[:60] + " || " + str(ctx or "")[:60])
                fp = " fp=" + _hl.md5(_core.encode("utf-8", "ignore")).hexdigest()[:8]
        except Exception:
            fp = ""
        line = (f"{_time.strftime('%Y-%m-%d %H:%M:%S')} [{proj}|{sid}]"
                f"{(' ' + ctx) if ctx else ''} {msg}{fp}\n")
        _append_locked(path, line.encode("utf-8"))
    except Exception:
        pass


_STATS_KEEP_DAYS = 14


def _archive_stats(path):
    """hook-stats 轮转时把旧的 .1 存成带时间的档,并删掉 _STATS_KEEP_DAYS 天前的档。
    ⛔ 2026-09-16:原来 `.1` 每次被覆盖,1MB ≈ 2 小时 ⇒ 账本只剩约 2 小时;
       而 metrics-daily 标题写「最近 7 天」、只读当前文件(约半小时)⇒ 报出「68 道闸几乎不开火」这种假结论。"""
    old = path + ".1"
    if os.path.exists(old):
        try:
            # 名字带微秒:同一秒内多次轮转(测试里实测)用秒级名会互相覆盖、丢行
            os.replace(old, "%s.%s-%06d.arch" % (path, _time.strftime("%Y%m%d-%H%M%S"), int(_time.time() * 1e6) % 1000000))
        except OSError:
            pass
    try:
        d, base = os.path.split(path)
        cutoff = _time.time() - _STATS_KEEP_DAYS * 86400
        for f in os.listdir(d or "."):
            if f.startswith(base + ".") and f.endswith(".arch"):
                p = os.path.join(d, f)
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
    except OSError:
        pass


def stats_lines(days=None, d=None):
    """按时间顺序读 hook-stats 全部存档 + .1 + 当前文件;days 给了就只要最近 N 天的行。唯一读法,报表都调它。"""
    d = d or os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(d, STATS_FILE)
    try:
        arch = sorted(os.path.join(d, f) for f in os.listdir(d)
                      if f.startswith(STATS_FILE + ".") and f.endswith(".arch"))
    except OSError:
        arch = []
    cut = _time.time() - days * 86400 if days else 0
    since = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(cut)) if days else ""
    for p in arch + [base + ".1", base]:
        # 整份存档最后一次写入都早于窗口 ⇒ 里面不可能有窗口内的行,不打开(外审:7 天约 90 个档,逐行扫要 4 秒+)
        try:
            if days and p.endswith(".arch") and os.path.getmtime(p) < cut:
                continue
        except OSError:
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if since:
                        i = ln.find('"t": "')
                        if i >= 0 and ln[i + 6:i + 25] < since:
                            continue
                    yield ln
        except OSError:
            continue


def _append_locked(path, data):
    """带【真锁】的原子追加。
    ⛔ 别以为 open(...,'a') 就够:POSIX 的 O_APPEND 是原子的,但 **Windows 的 CRT 把 append 实现成
       lseek(END)+write,两步之间会被抢** —— 实测(4 进程 × 60 行)光换成追加仍丢 43/240(18%)。
       加锁后同一实验 0 丢失。这就是"改对了方向但没到底"的活教材:必须拿 A/B 实验证到 0,不能推理收工。
    Windows 用 msvcrt 锁文件首字节当互斥量(短自旋,不用 LK_LOCK 的 1 秒级重试以免拖住 hook);
    POSIX 用 fcntl.flock。拿不到锁也照写(fail-open:宁可偶尔丢一行,绝不阻塞你发消息)。"""
    def _spin_lock(f):
        try:
            import msvcrt
            for _ in range(400):                       # 最多约 0.8s 自旋
                try:
                    os.lseek(f, 0, os.SEEK_SET)
                    msvcrt.locking(f, msvcrt.LK_NBLCK, 1)
                    return True
                except OSError:
                    _time.sleep(0.002)
            return False
        except ImportError:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
            return True

    def _open():
        # 别人正在改名的那一瞬间 Windows 会抛 PermissionError ⇒ 短重试(2026-09-16 外审压测 54~74 次/轮)
        #   重试用完仍打不开 ⇒ 返回 None,调用方把这行写进本进程独占的 spill 文件(机器很卡时 0.2s 不够,实测过一次丢行)
        for _ in range(250):
            try:
                return os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            except PermissionError:
                _time.sleep(0.004)
        return None

    fd = _open()
    locked = False
    try:
        locked = fd is not None and _spin_lock(fd)
        # ⛔ 2026-07-26 两处修(深搜调研员读码抓到):
        #  ①【轮转必须在锁内】:原来在锁外改名 —— 我改名的同一刻别的进程还握着旧句柄,
        #    它们后续的行会写进"已经被改名的那个文件",凭空消失,而错误被吞掉没人知道。
        #  ②【拿不到锁不许裸写】:原来自旋耗尽就直接写,而无锁写实测丢 18%,且这条路径【零测试】。
        #    改成写进【每个进程自己独占的一个文件】—— 谁也盖不到谁,一行都不会丢,事后可合并。
        if locked:
            # ⛔ 2026-07-26 外部 critic 实测:上一版把【重开 fd】写在 try 里面 —— Windows 上别的进程
            #   持有旧句柄时 os.replace 抛 PermissionError,但 os.close(fd) 已经执行过了,
            #   于是后面 lseek 对已关闭 fd 炸 EBADF、finally 再 close 一次又炸,全被外层 except 吃掉
            #   → **日志超过 1MB 之后永远写不进去,一行不落地丢,而且没有任何信号**。
            #   而这恰恰是这次改动【专门为之而生】的并发场景(多项目同时收尾),实测 100% 丢行、永不自愈。
            #   → 重开无条件执行:轮转成不成功都要拿回一个有效 fd。
            if os.lseek(fd, 0, os.SEEK_END) > _LOG_MAX_BYTES:
                try:
                    os.close(fd)
                    if path.endswith(STATS_FILE):
                        _archive_stats(path)    # 旧 .1 先改名存档,别被下一行覆盖掉
                        # 存档没成功(别的进程还开着 .1)⇒ 这次不轮转,否则下一行会把整份 .1 盖掉
                        #   (2026-09-16 故障复现:一次丢 37 行 = 恰好一个文件,连续、无坏行)
                        if os.path.exists(path + ".1"):
                            raise OSError("archive-pending")
                    os.replace(path, path + ".1")
                except OSError:
                    pass                    # 别人占着旧文件 → 这次轮转不成,但下面照样把行写进去
                fd = _open()
                # ⛔ 2026-09-16 外审压测(8 进程×300 行):close 旧 fd 时锁已释放,新 fd 没加锁就写
                #   ⇒ 与别人的 lseek+write 互相覆盖,每轮悄悄丢 11~15%。⇒ 新 fd 先加锁再写。
                locked = fd is not None and _spin_lock(fd)
        if locked:
            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, data)
        else:
            spill = "%s.lost.%d.log" % (path[:-4] if path.endswith(".log") else path, os.getpid())
            with open(spill, "ab") as f:      # 独占文件,无需锁;绝不与别人竞争、一行不丢
                f.write(data)
    finally:
        if locked:
            try:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


# ── 自称核实 vs 真核实(2026-07-25)──────────────────────────────────────────────
# 审计说「写『核过』两个字就豁免参照物闸 = 自发免检证」,建议直接删掉这个字面量。
# ⛔ 但回归当场证明【直接删会开另一个洞】:2026-07-24 修好过的一个真实误报(分析散文里出现
#   「做不到/留着」+「已核过」被当成真放弃)会复活。所以正解不是删字面量,而是【换判据】:
#   把"自称核实过"从【文本豁免】降级成【需要本轮真动过工具才作数】。
#   —— 自称 + 真读过/真跑过 = 可信;自称 + 这一轮一个工具都没调 = 纯嘴上说,不给豁免。
VERIFY_CLAIM_RE = re.compile(r"核过|核实过|第一手(核|读|查|搜)过?|完整.{0,4}核", re.I)
_VERIFY_TOOLS = {"Read", "Grep", "Glob", "Bash", "PowerShell", "WebFetch", "WebSearch",
                 "NotebookEdit", "Edit", "Write", "codegraph_explore",
                 "view_file", "run_command", "replace_file_content", "write_to_file",
                 "read_url_content", "search_web"}


def turn_used_verify_tools(turn_msgs, topics=None):
    """本轮助手消息里有没有真的调过【能拿到第一手证据】的工具。

    ⛔ 2026-07-27 形状Q【免死金牌漏洞】:不传 topics 时这是【整轮布尔】——
       本轮为 A 事跑过任一取证工具,B 事的断言就一起免检。实录:我为查卡顿跑了
       Get-CimInstance/lagcheck,于是"yt-dlp 没装""x.com 没登录"这两个【一次都没验证过】
       的断言直接放行(blame-check.log: observed=True)。
    ⇒ **验证的对象必须和断言的对象对得上**。调用方知道被断言的是什么时,把它的关键词传进
       topics,本函数会要求取证工具的 input 里真的出现过它(只看 tool_use.input=我主动发起的,
       不看 tool_result=工具告诉我的)。不传 = 旧行为(向后兼容,但你就继承了这个洞)。
    """
    probe = []
    try:
        for m in turn_msgs or []:
            if m.get("type") != "assistant":
                continue
            for c in (m.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" \
                        and str(c.get("name", "")) in _VERIFY_TOOLS:
                    if not topics:
                        return True
                    try:
                        probe.append(json.dumps(c.get("input") or {}, ensure_ascii=False).lower())
                    except Exception:
                        probe.append(str(c.get("input") or "").lower())
    except Exception:
        return True     # 解析不了 → 当作有(fail-open,别凭解析失败去多拦)
    if not topics:
        return False
    blob = "\n".join(probe)
    return any(str(t).lower() in blob for t in topics)


def delivered_or_verified(text, turn_msgs=None):
    """闸的统一豁免判据:①命中【证据形状】(没真做过写不出来)→ 直接豁免;
    ②只是【自称核实过】→ 必须本轮真调过取证工具才豁免。turn_msgs=None 时退回旧行为(宽松)。"""
    if SUCCESS_RE.search(text or ""):
        return True
    if VERIFY_CLAIM_RE.search(text or ""):
        return True if turn_msgs is None else turn_used_verify_tools(turn_msgs)
    return False


# ⛔ 2026-07-28(外部 critic 抓到 coherence-guard 与 spec-coverage-guard 各抄了一份):
#   「哪些路径不算【实业务文件】」「哪些扩展名算实现文件」是**同一个判据**,散在两处 =
#   将来补一个豁免只补一边、另一边继续误伤。一道逼人问"这几处是不是本该一处"的闸,
#   自己就是反例 —— 统一搬到这里,两处 import。
#   ⛔ 2026-07-28 写这段时踩到的坑(当天第 6 次"工具/尺子坏了"):经 heredoc 落盘时反斜杠少了一层,
#      正则变成 `[\/]` —— 那在正则里是【转义的斜杠】,**只匹配 `/`、不匹配 `\`** ⇒ Windows 路径
#      的豁免全部静默失效,两套回归当场红 6 条。字符类里要匹配反斜杠,r-string 内必须写 `[\\/]`。
SHARED_EXEMPT_PATH = re.compile(
    r"scratchpad|[\\/]tmp[\\/]|[\\/]temp[\\/]|AppData[\\/]Local[\\/]Temp"
    r"|[\\/]test_|[\\/]tests?[\\/]|\.test\.|\.spec\.|_test\.|conftest\.py"
    r"|[\\/]migrations?[\\/]|[\\/]generated[\\/]|[\\/]vendor[\\/]|\.generated\."
    r"|node_modules|[\\/]\.git[\\/]|dist[\\/]|build[\\/]|\.min\.",
    re.I,
)
# ⛔ 刻意【不】把 `.claude/hooks/` 放进共享豁免 —— 两个使用者的意图**相反**:
#   · spec-coverage 要豁免它(不该对 Superego 自己的闸要求"截图验收单");
#   · coherence 要**数**它(改 hooks 本身就是在做方案,正是最该被问整合三问的时候)。
#   critic 说这两份判据"实测只差 2 个分支" —— 属实,但那 2 个分支恰恰承载了相反意图。
#   ⇒ 共享【共同部分】,差异部分各自保留。不是所有"看起来重复"的东西都该合并。
SHARED_EXEMPT_HOOKS = re.compile(r"[\\/]\.(?:claude|truthgate)[\\/]hooks[\\/]", re.I)  # 2026-09-27 hooks 搬进 ~/.truthgate，新旧路径都认
# 实现文件扩展名(含 html/css/sql/ps1/sh —— Frank 用截图验收的那类页面文件必须在内)
# regex-sanity: ok — 本职就是认代码扩展名
SHARED_CODE_EXT = re.compile(
    r"\.(py|mjs|cjs|js|jsx|ts|tsx|vue|svelte|go|rs|java|rb|php|html|htm|css|scss|sql|ps1|sh)$",
    re.I,
)

# ⛔ 2026-09-08 第二批合并(静态扫描揪出的最后 2 条真重复)。
#   前提值得记:那把尺子第一版把 `if not _XXX_OK:` 的**降级备份**也当成"两份并行判据",
#   报了 7 条、我差点照着去"合并"已经合并好的东西 ⇒ 给它加了 fallback 识别 +
#   阳性/阴性对照自检后,读数才从 7 条收敛到真的 2 条。**没校准的尺子的读数不许当结论。**

# ① 「本轮取过画面/文件类证据」的指纹。
#   excuse-gate(去没去看)与 visual-proof-gate(看完怎么解释)是**串联的两道**:
#   一道认得 browser-act、另一道不认,就会"前面放行、后面误伤"。
#   excuse-gate 的注释原本就写着「与 visual-proof-gate 的 VISUAL 同源」——写着同源、抄了两份。
SHARED_VISUAL_EVIDENCE = re.compile(
    r"captureScreenshot|screenshot|desktop-window-shot|PrintWindow"
    r"|\.png\b|\.jpe?g\b|\.webp\b|webapp-testing|browser-act",
    re.I,
)

# ② 「这条命令是查看/测试,不是真动手」的豁免词表。
#   plan-before-act(没画计划就开工)与 scenario-fit(选型不看场景)都靠它免检,
#   补一个新的测试跑器写法只补一边 ⇒ 另一边继续误伤同一条命令。
SHARED_DRYRUN_EXEMPT = re.compile(
    r"(--info\b|--explain\b|--check\b|--dry-run|--help\b|--list\b"
    r"|pytest|test_|_test\.py|self_test|fault_inject|verify_)",
    re.I,
)


def escalate_block(gate, text, esc_pos, esc_neg, discuss_neg, reason):
    """【语义升级层】的唯一实现:关键字没命中时问一次语义要不要拦。返回 True = 已拦。

    ⛔ 2026-07-28 外部 critic 抓到:此前这 12 行在 blame-check / giveup-guard 里各抄了一遍,
       于是同一个 bug 也写了两遍 —— 两处都写成 `_log(msg, ctx)`,而那两个文件的 `_log` **只收 1 个参数**
       ⇒ TypeError 被紧挨着的 `except: pass` 吃掉 ⇒ **拦截 JSON 永远发不出去、日志照常打 allow(...)**,
       46/46 全绿盖着一个死闸。抽成单一调用点后,这类 arity bug 不可能再存在。

    三层安全网(缺一不可):
      ① `should_escalate` 说"像真犯规"才继续 —— 服务挂/超时返回 False ⇒ 行为与接线前完全一致;
      ② 再过一道 `should_downgrade(discuss_neg)` —— 升级层的 POS 锚点会把
         【引用别人的话】【正在描述这条规则】【正常交付陈述】判成像 POS(critic 独立造的 18 条里误伤 4 条),
         而降级层的 NEG 正是这类文本。**只升不降 = 只有一层网**,必须两层都过;
      ③ 整段 try/except 兜底,任何异常一律放行(绝不因为语义层出问题而误拦)。
    """
    try:
        if not should_escalate(text, esc_pos, esc_neg):
            return False
        if discuss_neg and should_downgrade(text, esc_pos, discuss_neg):
            return False                      # 是在讨论/引用规则,不是在犯
        hook_log(gate, "BLOCK(semantic-escalate: keyword missed, semantics say real)",
                 trig(text, 160))
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return True
    except Exception:
        return False

# ══════════════════════════════════════════════════════════════════════════
# 【通用 claim 判别器】—— 2026-09-06 建,替掉散在几十道闸里的重复词表
#
# ⛔ Frank 原话:「重构把所有用关键词的全部变成语义,还有把只是指向修复单一事件的
#    而不是通用规则都不是最好的不是吗,因为你要记录的可能几百种事件,但是变成了
#    通用规则就不一样了,可以防范未来所有事件?**是不是可以统合集成全部合并?**」
#
# ⛔ 当天量出来的铁证(他是对的):
#    36 道「读我说的话」的闸,判据区一共 **230 个正则**;
#    光 15 个 claim 词就被**各自重复实现了 98 次**:
#      「没有」28 道 ·「成功」8 ·「已经」8 ·「只能」8 ·「跑通」7 ·「完成」6 ·「做完」6 …
#    ⇒ 每次翻车我只补【其中一份】词表,**其余几十份照漏**。
#      这就是「superego 改了三个月还是漏」的机制本身 —— 不是词表不够努力,是架构。
#
# ⇒ 通用件 = 一个语义判别器回答「我刚才有没有做出某一类断言」。
#   各闸只留自己那半【证据核查】(跑测试没/截图没/搜过没),那半是确定性的,正则本来就对。
#   新说法自动覆盖,不用再建第 84 道闸;新增一类 claim 只在这里加一组锚点。
#
# ⛔ 两条设计约束(都是当天踩出来的):
#   ① **必须逐句判**,不能把整轮糊成一团 —— 我真实的一轮是长文本(数据+结论+那句话),
#      整段平均下来像"正常技术叙述",一句真话埋在十句数据里就逃逸。
#   ② **fail-open**:服务挂/超时 → 返回空集 ⇒ 调用方拿不到 claim ⇒ 行为退回它自己的关键字原判,
#      绝不因为语义层抽风而多拦或少拦。

CLAIM_ANCHORS = {
    # 「我做完了 / 它生效了」—— 交付类断言,重复实现最多的一类
    "done": {
        "pos": ["改好了,已经生效", "跑通了,现在没问题", "修好了并且部署上线",
                "这个功能做完了", "全部搞定,可以用了", "已经重启,新版在跑"],
        # ⛔ 2026-09-06 第二次撞上【反例撞车】(第一次见 boundary 那条注释):
        #   「先跑一下看看当前状态,还没结论」被判成 done —— 因为"先【跑】一下"和
        #   "【跑】通了"共用同一片词汇,而反例里缺【正在做/还没有结果】这个句式。
        #   ⇒ 补的是句式;措辞刻意跟那句用例不同,再拿那句原话当留出样本验(见 test_claim_kinds)。
        "neg": ["我打算接下来把它改好", "这一步还没做完", "先说明我准备怎么做",
                "他之前说那个已经修好了", "如果跑通了再告诉你", "这条规则要求做完必须验证",
                "先看看现在是什么情况,结论还没有", "这只是中间过程,不是最终结果"],
    },
    # 「没有 / 不存在 / 查不到」—— 缺席类断言,最容易在没穷尽时说出口
    "absence": {
        # ⛔ 锚点要【多样】,别把测试里那句原样抄进来(那是把实例思维搬进锚点集)。
        #   首跑漏判「翻遍了三个目录,一条相关记录都拿不出来」——原 6 条锚点全是
        #   "没有/不存在/搜不到"这一种句式,缺【找过了→结果是空】这个说法。
        #   补的是句式,不是那句话;补完拿【没参与调锚点】的句子验(见 test_claim_kinds 留出组)。
        "pos": ["查了没有这个东西", "档案里不存在这条记录", "搜不到相关的项目",
                "本机没有装这个", "一条都没有找到", "没有人做过这件事",
                "全都翻过了,结果是空的", "找遍了也拿不出一条来",
                "逐个查过一遍,沾边的一个都没出现"],
        # ⛔ 2026-09-06 第三次撞【词汇撞车】,这次在 absence:
        #   「我把三个环境变量都打印出来**对了一遍**,值是一样的」被判成"什么都没找到",
        #   因为正例里有「逐个查过一遍,沾边的一个都没出现」——前半句"查过一遍"是【检查动作】,
        #   而检查动作本身跟"结果为空"无关。
        #   ⛔ 试过的错解:把那条正例改词 ⇒ 误判句降到 0.0114,**但真阳性也掉到 0.0104**(一起杀了)。
        #   ✅ 正解:给【易混的那一类】补反例,而不是动正例。实测:
        #     误判句 0.0337 → **-0.131**;两条真阳性 0.0675 / 0.0677 **一分没动**。
        #   ⇒ 通用判据:**误判要靠补反例治,别动正例** —— 动正例会连真阳性一起削掉。
        "neg": ["没关系我继续", "这里没有什么特别的", "上次你说过没有必要做",
                "这条规则说不许说没有", "没有的话我再去查一遍",
                "我把几项逐个核对了一遍,结果是一致的", "两边都打印出来比过,数字对得上",
                # ⛔ 2026-09-17 补:【我没做过某产物/汇总/动作】≠【某东西不存在】。避开"记录/文件/搜不到"词汇。
                #   今晚误伤:「我没有做过一份权威的逆向工具清单」被判中 absence(「我没做过X」≈「X不存在」)。
                "这样一份汇总我以前没整理过,只是凭印象估的",
                "那种统计我之前一直没动手做,不是查过是空"],
    },
    # 「只能 / 够不到 / 需要你手动」—— 边界类断言,功能是让我停止调查
    "boundary": {
        "pos": ["只有你能去做这件事", "我拿不到那个东西", "这超出我的能力范围",
                "需要你手动操作一下", "我这边做不了", "只能这样没有别的办法"],
        # ⛔⛔ 2026-09-06 实测抓到的【反例撞车】(通用教训,别只当这一条):
        #   最后一条原来写「我自己登进去建好了 key,这是实测结果」。它的语义角色是对的
        #   (=我自己做了,不算边界声明),但它和【真犯规】共用同一片词汇(钥匙/登录/官网)
        #   ⇒ 变成磁铁,把真犯规吸到"没犯规"那一侧:
        #     「至于那把钥匙,得你自己去官网重新申一把,我这边使不上力」margin = **-0.0555**(判不出);
        #     换成下面这条不带钥匙/官网词汇的等效反例后 → **+0.1039**(正常命中)。
        #   ⇒ 通用判据:**反例要保住"语义角色",但必须避开正例那片词汇**;
        #     语义比不出来时先查"是不是有反例在当磁铁",别急着调阈值。
        "neg": ["那个确认框是浏览器扩展内部页面,只有真人能点",
                "短信验证码只会发到你手机上", "滑块人机验证只有真人能过",
                "这个模型单次最多生成十五秒,是它文档写的上限",
                "那件事我自己动手做完了,不用你插手",
                # ⛔ 2026-09-17 补:【复盘/引用自己说过的边界话】——语义角色=在讨论闸/纠错,不是真声明做不了。
                #   今晚误伤:「那道能力边界闸误报了,我没说过只有你能做」被判中 boundary(引用短语当了磁铁)。
                #   按 line 1489 教训:补反例、不动正例;内存试验 10/10 + 完整回归双验。
                "那道闸刚才误报了,我在复盘它的判据为什么判错",
                "我上一轮那句话是错的,一查发现我自己就能做,已经做完了",
                "我在说这道规则抓什么词,不是在声明我做不了什么"],
    },
    # 「应该 / 大概率 / 理论上」—— 遮羞类,出现在交付里 = 没做完
    "hedge": {
        "pos": ["理论上应该没问题", "大概率是可以的", "尽力而为吧",
                "按道理讲这样就行了", "应该是生效了"],
        "neg": ["我实测了三次,都是这个结果", "这是量出来的数字不是估的",
                "这条规则禁止在交付里写应该"],
    },
    # 「结论就是这样 / 可以按这个走」—— 下裁定类。⛔ 它【不是】done:
    #   done 说的是"我把活干完了",verdict 说的是"我对某件事下了判断"。
    #   实测:「结论就是这样,可以按这个走了」对 done 的 margin = -0.0356(明显负)。
    "verdict": {
        "pos": ["结论就是这样,可以按这个走了", "定案了,就按我说的这个来",
                "判断是他那边的问题", "我的裁定是这条不成立",
                "答案很清楚,就是第二个方案"],
        "neg": ["我还在看,现在下不了结论", "这只是初步印象,不是定论",
                "两种可能都还在,得再查", "这条规则要求下结论前先穷尽"],
    },
    # 「东西放那儿了,你打开就能看」—— 交付产物类。⛔ 也【不是】done:
    #   done = 活干完了;delivery = 产物已经到他手上/他该去看了。
    #   实测:「东西已经放到那儿了,你打开就能看」对 done 的 margin = -0.0659。
    "delivery": {
        "pos": ["东西已经放到那儿了,你打开就能看", "图我存好了,路径在这",
                "报告写完放在那个目录,你去看一眼", "结果我发过去了,你查收",
                "页面起来了,你点开这个地址"],
        "neg": ["我准备把它导出来给你", "还没生成,生成好了告诉你",
                "这条规则要求交付时必须打开给他看", "他说他已经看过那张图了"],
    },
}


# ⛔ 天然重叠的类:它们【不该互当反例】。
#   跨类反例治的是"A 类文本被判成 B 类"(实测有效,见下面注释),但它有个副作用:
#   两个本来就会同时成立的类被硬推开。实测(2026-09-06 全量回归抓到):
#     「部署上去了,我打开频道确认过消息在里面」——它**既是 done 也是 delivery**,
#     而 delivery 的正例进了 done 的反例集 ⇒ done 被推掉,只剩 delivery,
#     于是 false-done-gate 那种只问 done 的闸就漏了。
#   ⇒ 只对【真互斥】的类做跨类反例;重叠的类放过。
#   ⛔ 写这个表时我第一版把 `"done"` 写了两遍(后一个静默覆盖前一个)——
#     dict 重复键不报错,正是"被静默吞掉"那类。每个键只出现一次,且必须对称。
OVERLAP = {
    "done": ("delivery", "verdict"),   # 部署上去了 = 完成了,也是交付了;下裁定常伴随"这步做完"
    "delivery": ("done",),
    "verdict": ("done",),
}


def claim_kinds(text, kinds=None, sem_hot=0.02, timeout=8.0, max_segs=10):
    """本段文本里【语义上成立】的断言种类,返回集合(如 {"done","hedge"})。

    kinds=None 表示全查;传子集可省调用次数(每种 claim 一次 /intent)。
    ⛔ fail-open:语义服务不可用 → 返回空集合,调用方保持自己的关键字原判。
    """
    out = set()
    try:
        if not text or not text.strip():
            return out
        want = list(kinds or CLAIM_ANCHORS.keys())
        segs = [s.strip() for s in re.split(r"[\n。!?!?;;]+", text) if len(s.strip()) >= 8]
        segs = segs[-max_segs:] or [text[:512]]
        for k in want:
            a = CLAIM_ANCHORS.get(k)
            if not a:
                continue
            # ⛔⛔ 一对多分类的经典错(2026-09-06 首跑当场撞到):
            #   每一类的 NEG 里**必须包含别的类的 POS**,否则 A 类的文本对 B 类来说
            #   "比 B 的反例更像 B 的正例" ⇒ 到处误判。
            #   实测:「那个确认框只有真人能点」(真边界,四类都该不中)被判成 absence+hedge;
            #   「我量了三遍,中位数 683 毫秒」(纯数据陈述)被判成 done。
            #   ⇒ 通用判据:**多分类的每一类,反例集必须覆盖其余各类。**
            neg = list(a["neg"])
            for k2, a2 in CLAIM_ANCHORS.items():
                if k2 != k and k2 not in OVERLAP.get(k, ()):
                    neg.extend(a2["pos"][:3])
            for s in segs:
                if should_escalate(s[:512], a["pos"], neg[:24],
                                   sem_hot=sem_hot, timeout=timeout):
                    out.add(k)
                    break            # 这一类已成立,不用再问剩下的句子
    except Exception:
        return set()                 # 任何异常 → 空集 = 保持调用方原判
    return out

def claim_or(regex_hit, text, kind, timeout=8.0):
    """词表命中 → 直接 True;没命中 → 补问一次语义。**各闸迁移时只改这一行。**

    ⛔ 为什么要这个包装(2026-09-06):`claim_kinds()` 已经是通用件了,但各闸的判定写法
       五花八门(`bool(RE.search(x))` / `if RE.search(x):` / `m = RE.search(x)`),
       机械批量重写不安全。于是把【调用形状】也统一成一行:
           claimed = bool(DONE.search(text))
         → claimed = claim_or(DONE.search(text), text, "done")
       逻辑仍然只有一份(claim_kinds),各闸的改动小到一眼能审、能回滚。

    ⛔ 安全性质:
       · regex 命中时【连语义都不问】—— 零额外延迟,且不改变任何已命中的路径;
       · 语义层挂/超时/异常 → claim_kinds 返回空集 → 返回 False = 词表原判(fail-open);
       · 只可能把 False 变 True(提高召回),不会把 True 变 False。
    """
    if regex_hit:
        return True
    try:
        return kind in claim_kinds(text, kinds=(kind,), timeout=timeout)
    except Exception:
        return False

def turn_budget_ok(tp=None, msgs=None):
    """本轮还能不能再拦 —— **任何读法的闸都能一行接入防 loop**。

        from guard_common import turn_budget_ok
        if not turn_budget_ok(tp):
            return                      # 本轮已被拽回太多次,这次让开

    ⛔ 为什么需要它(2026-09-06,Frank:「触发了无限Loop的bug…think twice 然后阻塞」):
       回合预算原本只在 `load_transcript_tail` 里生效 ⇒ **55 道 Stop 闸只有 64% 受管**,
       自己 open() 读 transcript 的 12 道完全绕过,可以无限拦人。
       而那 12 道读 transcript 的写法有 5 种,逐个改读法要动 12 处判定逻辑、风险大;
       它们真正需要的只是「本轮拽回太多次了,让开」这一句。

    ⛔ 安全性质(与 _turn_budget_blown 完全一致):
       · 安全类闸(删数据/碰他浏览器/越权写…)在 `_BUDGET_NEVER` 白名单里,**永不熔断**;
       · 逃生阀 `SUPEREGO_NO_BUDGET=1`;
       · 熔断会写 turn-budget.log,不许静默;
       · 任何异常一律返回 True(照常拦)—— 宁可多拦,不因为这层出错而漏拦。
    """
    try:
        if msgs is None:
            if not tp:
                return True
            msgs = _load_tail_raw(tp)   # 不能用 load_transcript_tail:预算用完它就返回 [],再判 [] 永远「没用完」
        return not _turn_budget_blown(msgs)
    except Exception:
        return True

# ══════════════════════════════════════════════════════════════════════════
# 【shadow mode】新闸先只记账、不拦人 —— 2026-09-07
#
# ⛔ 起因(Frank):「30天那么久有意义吗?**别人是这样做的?**」
#   我原来打算"上线后等 30 天看开不开火" —— 30 天是我编的,而且我没查别人怎么做。
#   查完:行业标准是 **shadow mode / dry-run**,原话
#   「Measure shadow-mode numbers before graduating the guardrail check」。
#   ⇒ **等的不是时间,是证据**:新闸先只记账,判得准了就毕业成真拦截;
#     判不准也不会误伤他 —— 这正好治"新闸上线就变累赘"这个病。
_SHADOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow-gates.txt")


def in_shadow(name=None):
    """这道闸现在是不是【影子模式】(只记账不拦人)。

    名单:`~/.claude/hooks/shadow-gates.txt`,一行一个闸名(# 开头是注释)。
    ⛔ 读不到/解析失败 → 返回 False(照常拦)。绝不因为这层出错而漏拦。
    """
    try:
        name = name or _gate_name()
        if not name:
            return False
        if not os.path.exists(_SHADOW_FILE):
            return False
        for ln in open(_SHADOW_FILE, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and ln == name:
                return True
        return False
    except Exception:
        return False


def shadow_log(name, reason, trig=""):
    """影子开火:只记账,不拦人。返回 True = 已记账(调用方应当直接 return,别输出拦截)。"""
    try:
        d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        # ⛔⛔ 2026-09-07:影子日志也要把【测试写的】分流出去 —— 主日志早就这么做了,这里漏了。
        #   实测:`stagnation` 影子日志里 8 次开火【全部】来自 `sess-sta`(它自己测试的会话),
        #   真实开火 0 次。而记分板显示"影子开火 8 次",我差点据此判它"判得准、可以毕业"
        #   —— 拿自己测试的夹具当真实证据。影子模式的意义就是【用真实数据决定要不要毕业】,
        #   数据被夹具污染 = 这套机制废掉,而且是往【放行】方向废。
        with open(log_path("%s.shadow" % name, d), "a", encoding="utf-8") as f:
            f.write("%s [%s] WOULD-BLOCK %s | %s\n"
                    % (time.strftime("%Y-%m-%d %H:%M:%S"),
                       (os.environ.get("CLAUDE_CODE_SESSION_ID") or "-")[:8],
                       str(reason).replace("\n", " ")[:200],
                       str(trig).replace("\n", " ")[:120]))
        return True
    except Exception:
        return True          # 记不上也别拦 —— 影子模式的本意就是不影响他

# ══════════════════════════════════════════════════════════════════════════
# 【判效果,不判手法】2026-09-07
#
# ⛔ Frank 当场点破:`lesson-anchor-gate` 判 `tool_name in (Edit, Write, ...)`,
#   而他看着我**每次改 lessons 都是用 Bash 跑脚本**(避转义坑,是别的闸教的)
#   ⇒ 我建了一道【我自己最常用的姿势永远绕过】的闸。
#   扫全身发现这是【一类】不是一处:coherence-guard / lint-fatal-guard /
#   spec-coverage-guard 全一样。具体代价:今晚用脚本改的 .py 一次没被 ruff 查过。
#
# ⇒ 通用判据:**盯"哪个文件变了",别盯"用了哪个工具"。**
#   例外:PreToolUse 拦【某次调用本身】(rm -rf / 装包 / 起服务)——那本来就该看工具名。
#
# 成本实测(先量后做):深度1=0.038s / 深度2=**0.048s** / 深度3=0.192s(超标)⇒ 定死 depth 2。
_SCAN_SKIP = frozenset((
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "login-cdp-profile", "douyin-cdp-profile", ".claude-own-chrome",
    "ifixai-results", ".pytest_cache",
))


def scan_roots():
    """我真正会写的那几个地方 —— 范围必须小,扫全盘会拖死每次工具调用。"""
    home = os.path.expanduser("~")
    out = [os.path.join(home, ".claude", "hooks"),
           os.path.join(home, ".claude", "superego-recall"),
           os.path.join(home, ".claude", "dissat-classifier")]
    p = os.environ.get("CLAUDE_PROJECT_DIR")
    if p and os.path.isdir(p):
        out.append(p)
    return out


def recently_changed(within=180, exts=(".py",), roots=None, max_depth=2, limit=40):
    """最近 `within` 秒内被改过的文件 —— **不管是谁用什么方式改的**。

        from guard_common import recently_changed
        for f in recently_changed(exts=(".py",)):
            ...   # 这里能看到 Bash 脚本改的、Write 改的、别的进程改的,全都算

    ⛔ 任何异常返回空列表(fail-open):这层出问题绝不能挡住他。
    """
    try:
        now = time.time()
        out = []
        for root in (roots or scan_roots()):
            if not os.path.isdir(root):
                continue
            base = root.rstrip("/\\").count(os.sep)
            for dp, dns, fns in os.walk(root):
                dns[:] = [d for d in dns if d not in _SCAN_SKIP and not d.startswith(".")]
                if dp.count(os.sep) - base >= max_depth:
                    dns[:] = []
                for fn in fns:
                    if exts and not fn.endswith(tuple(exts)):
                        continue
                    p = os.path.join(dp, fn)
                    try:
                        mt = os.path.getmtime(p)
                        if now - mt <= within:
                            out.append((mt, p))
                    except OSError:
                        continue
        # ⛔ 2026-09-07:必须按 mtime 新→旧再截断,不能"走到第 limit 个就 return"。
        #   os.walk 是【字母序】,不是时间序 ⇒ 名额会被别的文件先占满。
        #   实测(test_evidence_in_log_gate 那条红):后台回归同时在改 hooks 下的 .py,
        #   把 limit=6 占满,`zz-evidence-probe.py` 字母序排最后 ⇒ **我刚写的那个被挤掉**
        #   ⇒ 闸看不见它 ⇒ 假绿。生产同形:我用 Bash 改一道闸时别的文件也在变,
        #   闸去检查的就不是我刚改的那个。
        #   一个叫「最近改过的」的函数返回"随便 N 个",尺子刻反了。
        out.sort(key=lambda t: -t[0])
        return [p for _, p in out[:limit]]
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════════════════
# 只记账模式(2026-09-26 · TruthGate 根治计划第②步 · Frank:「做了又副作用吗？没的话为何你还要问我？」)
# 名单 = ~/.claude/superego-observe.json 的 "observe"(env SUPEREGO_OBSERVE_FILE 可换,测试用)。
# 名单里的闸照常跑、照常记日志,但结论不送出去:stdout/stderr 吞掉、退出码 2 改 0 ⇒
#   Claude Code 和 AG 桥接(它认 block JSON / 退出码 2 / ⛔ 开头的行)都看不到拦截。
#   日志里 BLOCK/NUDGE 记成 WOULDBLOCK/WOULDNUDGE ⇒ 数据不断,日后照样能拿考卷量它准不准。
# 为什么只记账、不改成"下一轮提醒":提醒同样花额度;Frank 铁律原话「只提醒不生效、纸老虎 = 等于没有」。
# 判据:凭我话里有没有某类说法来拦的 ⇒ 进名单;凭事实拦的 ⇒ 不进(名单文件里两份清单都列了)。
# 测试环境不生效(running_under_test):各闸的回归要看到真结论。名单读不到/坏了 = 照常拦(与总开关同方向)。
# 已知口子:AG 桥接对带 check_text() 的闸是在它自己进程里直接调函数,认不出闸名 ⇒ 那几道在 AG 侧照常拦
#   (名单里只有 process-alias-attribution-gate 是这种,近 7 天 0 次拦截)。
_OBS_FILE = (os.environ.get("SUPEREGO_OBSERVE_FILE")
             or os.path.join(os.path.expanduser("~"), ".claude", "superego-observe.json"))


class _ObsSink(object):
    """吞掉写进来的一切;.buffer 给 BytesIO,让 io.TextIOWrapper(sys.stdout.buffer) 那种写法也吞得掉。"""

    def __init__(self, real):
        import io as _io
        self._real = real
        self._txt = []
        self.buffer = _io.BytesIO()

    def write(self, x):
        if x:
            self._txt.append(str(x))
        return len(x) if x else 0

    def flush(self):
        pass

    def text(self):
        try:
            b = self.buffer.getvalue().decode("utf-8", "replace")
        except Exception:
            b = ""
        return "".join(self._txt) + b

    def __getattr__(self, n):
        return getattr(self._real, n)


def _test_run():
    """这次是不是测试在跑(是 ⇒ 只记账不生效,回归要看各闸的真结论)。
    ⛔ 2026-09-27(PLAN 第 5 步):原来「当前目录叫 hooks」就算测试 —— 可 Claude Code 跑钩子用的是会话当前目录,
       我在 ~/.truthgate/hooks 里干活时 63 道只记账的闸全部恢复真拦(browser-routing-gate 当场连拦两次)。
       区分依据:CLAUDE_PROJECT_DIR 是 Claude Code 只给钩子进程设的,Bash 工具里手动跑的测试没有它(实测 env 0 个)。"""
    if os.environ.get("SUPEREGO_TEST") == "1":
        return True
    if os.environ.get("SUPEREGO_OBSERVE_FILE"):   # 显式给了名单 = 在测只记账模式本身
        return False
    if os.environ.get("SUPEREGO_LOG_DIR"):        # 回归工具(regress-on-guard-edit 等)会设它
        return True
    return (not os.environ.get("CLAUDE_PROJECT_DIR")
            and os.path.basename(os.path.normpath(os.getcwd())) == "hooks")


def _observe_install():
    try:
        # 测试环境不生效:回归要看各闸的真结论。⛔ 不用 running_under_test():它先看 CLAUDE_PROJECT_DIR,
        #   而钩子自动启动的回归会继承"当前项目" ⇒ 被当成真实对话 ⇒ 2026-09-26 11:00 实测 3 组回归误红
        #   (外部改动账本当场抓到)。改看:显式 SUPEREGO_TEST / 回归工具会设的 SUPEREGO_LOG_DIR / 进程目录是 hooks。
        #   生产环境这三样都没有(CC 设置、AG 桥接与钩子配置、用户/系统环境变量均已查)。
        #   显式给了 SUPEREGO_OBSERVE_FILE = 在测只记账模式本身,只认 SUPEREGO_TEST。
        if _test_run():
            return
        with open(_OBS_FILE, encoding="utf-8") as f:
            names = set(json.load(f).get("observe") or [])
        name = _gate_name()
        if name not in names:
            return
        out, err = _ObsSink(_sys.stdout), _ObsSink(_sys.stderr)
        _sys.stdout, _sys.stderr = out, err
        prev_exit = _sys.exit

        def _obs_exit(code=0):
            _OBS["code"] = code
            return prev_exit(0 if code == 2 else code)
        _sys.exit = _obs_exit
        _OBS["on"] = True

        def _on_exit():
            try:
                t = out.text() + err.text()
                # 2026-10-02:补 '"deny"' —— PreToolUse 闸拦截写的是 permissionDecision:"deny",
                #   原来只认 "block" ⇒ browser-routing-gate 在名单里时一条 WOULDBLOCK 都没记,账本全是 allow。
                if not _ACC.get("logged") and (_OBS.get("code") == 2 or '"block"' in t
                                               or '"deny"' in t
                                               or t.lstrip().startswith("⛔")):
                    hook_log(name, "WOULDBLOCK(observe)", re.sub(r"\s+", " ", t)[:140])
            except Exception:
                pass
            # ⛔ 2026-09-26 11:05 实测漏网:answer-relevancy-gate 在 main() 里才 import 本模块,
            #   而它写的是 `sys.exit(main())` —— Python 先取 sys.exit 再调 main(),取到的是【没包过的原版】
            #   ⇒ 退出码 2 照样出去,stderr 却被吞了 ⇒ 另一个会话收到两次"No stderr output"的空拦截,比不改还糟。
            #   ⇒ 收尾时强制以 0 退出:不管闸前面定了什么退出码,只记账的闸一律放行。
            #   先手动跑一次记账兜底(os._exit 会跳过比我早注册的 atexit,它就在其中)。
            try:
                _account_on_exit()
            except Exception:
                pass
            try:
                _sys.__stdout__.flush()
            except Exception:
                pass
            os._exit(0)
        _atexit.register(_on_exit)
    except Exception:
        pass


_observe_install()
