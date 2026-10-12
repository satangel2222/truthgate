#!/usr/bin/env python3
"""Stop hook: 拦截「虚报生效/装好/跑通」—— 声称交付物工作,但本轮没跑任何核实工具。

2026-07-19 humanizerai 教训固化:手写完 vibe-spec v1(从脑袋编、没测)就喊「已焊好、已生效」,
Frank「白干了吗」。CLAUDE.md 已 4 处规定「说完成前必须有实测证据」仍犯 → 软规则拦不住,上机器闸。

触发(全满足才拦):本轮助手文本含【交付物工作/上线】口吻的完成claim(生效/焊好/装好/跑通/部署成功/
上线/建好了…),且本轮【没有任何核实类工具调用】(Bash/PowerShell/Read/Grep/Glob —— 即我没去看/没去跑核过)。

安全设计(照 blame-check.py):
- fail-open:任何异常一律放行。
- 只拦一次:只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我,避免死循环。
- 只读:只读 transcript + 打印决策,从不碰代码/文件/git。
- 窄触发:只认「工作/上线」类强 claim(不是泛泛的「完成」),纯讨论/复述完成不拦。
- 每次留一行日志到 false-done-gate.log(可核验它真在跑)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, turn_start_index# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def turn_start_index(msgs):          # guard_common 挂了时的保守桩:-1=整份算本轮,宁可少拦
        return -1
    def hook_log(*a, **k):
        pass
try:            # ⛔ 独立一条:trig 缺失不许连累 hook_log(2026-07-26 critic 实测过的静默故障)
    from guard_common import trig
except Exception:
    def trig(x, n=120):
        return "trig=?"
import sys
import json
import re
import os
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# (原来这里有个 LOG 常量 —— 全文件零引用的死代码,早就改用 hook_log 了。2026-09-07 删)

# 【弱验证】的机械痕迹 —— 出现这些时,"全绿"没有判别力(形状V:被测物没跑也照样通过)。
# ⛔ 词表刻意收窄到【测试框架/闸自己的日志】的固定输出,不认散文里的"跳过"二字,
#    否则 rsync/npm/git 之类的正常输出会把它变成噪音闸。
# ⛔⛔ 外部 critic 2026-07-29 实测:第一版**注释写的和正则做的相反**。我写着"收窄到测试框架固定输出",
#    实际把 `SKIPPED` 放进 `re.I` 且无词边界 ⇒ 它匹配**任何地方的裸词 skipped**:
#    `12 passed, 1 skipped`(最常见的 pytest 输出)/ `rsync: 2 skipped` / 连 `0 skipped`、
#    子串 `unskipped_files` 都拦;而我精心写的窄分支(要求跟数字)**永远到不了 = 死代码**。
#    真 transcript 逐回合回放:开火 4 次、**真阳性 0**。
# ⇒ 现在:去掉 re.I;`SKIPPED` 只认大写(pytest 逐条标记本来就是大写)+ 词边界;
#    小写 skipped 必须跟正整数(`0 skipped` 不算)。
WEAK_VERIFY = re.compile(
    r"skip\(self-blocked"
    r"|\bSKIPPED\b"
    r"|\bskipped\b\s*[:=]?\s*[1-9]"
    r"|\b0\s+passed\b|no\s+tests?\s+ran|collected\s+0\s+items"
    r"|\b0/\d+\s*(?:通过|passed)|全部跳过|(?:被|已)跳过\s*[1-9]")


# 【在跑闸自己】的命令特征 —— 这类调用的输出里必然带闸的日志格式,不能当"被测物的成绩单"。
# ⛔ 别写成 `test_.*guard` —— 那会把用户项目里正常的 `test_auth_guard.py` 也豁免掉(误豁免=漏拦)。
#    Superego 自己的测试全在 hooks/ 下,路径判据已经覆盖;文件名判据只认本家的 -guard/-gate 命名约定。
# ⛔ `hooks` 后面【不一定跟分隔符】—— 最常见的写法就是 `cd .../.claude/hooks && python …`
#    (后面跟的是空格)。第一版写成 `hooks[/\\]` ⇒ 这条最常见的命令匹配不到、误报残留
#    (真 transcript 回放:4 次降到 1 次,剩的就是它)。⇒ 用 \b 收尾。
SELFTEST = re.compile(r"\.claude[/\\]hooks\b|(?<![\w-])hooks[/\\]"
                      r"|[-_]guard\.py|[-_]gate\.py|superego-regress", re.I)


def _result_text(content):
    """把 tool_result 的 content 抠成文本。照抄 reference-diff-guard.py:94(已验证实现)。
    ⛔ 别用 json.dumps:它把换行变成字面 \\n,跨行的 `0 passed` 之类会失配(critic 指出)。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict):
                out.append(c.get("text", "") if c.get("type") == "text"
                           else json.dumps(c, ensure_ascii=False))
            else:
                out.append(str(c))
        return "\n".join(out)
    return json.dumps(content, ensure_ascii=False)
sys.path.insert(0, HERE)
# 2026-07-24 审计 finding#9:false-done 是家族里唯一没接 strip_doc 的闸(表格/代码块里的词照样触发);
# finding#5:DONE 词表太窄(漏已修复/搞定/OK了/英文)。→ 接 guard_common 共享层。
try:
    from guard_common import strip_doc, DONE_RE
except Exception:
    def strip_doc(t):
        return t or ""
    DONE_RE = None

# 「交付物真的工作/装上/上线」类强 claim —— 这类必须有实测证据。用共享加宽词表(命中日常自然说法)。
DONE = DONE_RE if DONE_RE is not None else re.compile(
    r"已生效|生效了|已装好|装好了|已部署|部署成功|已上线|上线了|建好了|跑通了|已跑通|已修好|修好了|已修复|修复了|搞定了?|已完成")
# 核实类工具:我真的去看/去跑核过(而非只是 Write/Edit 写了文件)
VERIFY_TOOLS = {"Bash", "PowerShell", "Read", "Grep", "Glob"}
# 本轮真的产出/改了工件才可能触发 —— 纯讨论/提案轮(没 Write/Edit)不该被拦(2026-07-19 首次实战误伤 humanizerai 讨论轮后加)
MADE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# 2026-07-25 finding#2:Bash/PowerShell 的 `cat >> f`/`> f`/`tee`/`sed -i`/`Set-Content` 也是真写文件,
# 旧版只认 Write/Edit → 我用 `cat >> lessons.md` 真写了却被判"虚报没改"(本轮亲身误伤两次)。→ 认 shell 写文件。
# regex-sanity: ok — 只在 command 字符串上判;npm 输出里的 `> app@1.0.0` 在 tool_result 里,不经过它
BASH_WRITE = re.compile(
    r"(?:^|[\s;|&])>>\s*(?!/dev/null)[\w./~$'\"-]"          # 追加重定向 >> file
    r"|(?:^|[\s;|&])>\s*(?!/dev/null|&|\$|\d)[\w./~'\"-]"    # 写重定向 > file(排除 /dev/null、>&、比较 >$var / >100)
    r"|\btee\b|\bsed\b[^\n|]*\s-i|\bdd\b[^\n|]*\bof="        # tee / sed -i / dd of=
    r"|\bcp\b|\bmv\b|open\s*\([^)]*['\"][wax]"               # cp/mv 复制移动、python open(...,'w'/'a'/'x')
    r"|Set-Content|Add-Content|Out-File|New-Item"            # PowerShell 写文件
)
# ponytail: `python 某脚本.py` 若脚本内部写文件是静态判不出的残留盲区;真遇到就用过去式或 PAST_TURN 措辞,不硬猜
# 明确标注「上一轮/之前那轮已做、本轮只是复述」→ 不当本轮虚报(但必须本轮【也核实过 verified】才豁免,防拿它当挡箭牌)
PAST_TURN = re.compile(r"上一轮|上一次|前一轮|上一段|之前(?:那轮|已)|先前已|earlier turn|previous turn")
# 「文件/代码已被我改动」类完成态 claim —— 这类必须本轮真有 Write/Edit,否则=虚报「已改文件」。
# 2026-07-20 humanizerai 教训:我说「已 Edit lessons.md 删掉错指路」却根本没调 Edit(本轮只 WebSearch),
# 原闸因为①"已Edit"不在功能claim词表 ②made=False 反而放行 → 最该拦的"说改了文件却没写"全漏。
# 文件类宾语:出现这些才算真在说「改了某个文件」,而非「更新了理解/判断/记忆/待办」这类概念收尾。
_FILE_OBJ = (
    r"(?:文件|脚本|代码|配置|[\w./~-]*\.(?:md|json|py|js|cjs|mjs|ts|tsx|txt|html|css|ya?ml|sh|log|toml|ini|env|cfg|xml|csv))"
)
FILE_CLAIM = re.compile(
    # 强动词:动作本身即指向文件改动(不必近旁有文件宾语)。已 Edit / 改文件类。
    r"已\s*Edit|已改回|改回了|已改好|已改掉|已删掉|删掉了|已写进|写进了"
    r"|已写好文件|已建好文件|已创建.{0,6}文件"
    # 把/将 + 真·文件动词(改回/改好/改掉/删掉/写进):本义即改文件,无条件命中。
    r"|已(?:把|将).{0,24}(?:改回|改好|改掉|删掉|写进)"
    # 2026-07-25 复审 finding:把/将 句式里的概念易撞词(加进/更新/保存/落进)也必须近旁有【文件类宾语】才算虚报改文件;
    # 否则「已把这笔款的判断更新了」「已把这条待办加进去了」「已把结论保存了」是概念收尾——旧版无条件 BA 分支把它们误拦(原缺陷的把/将改写版复活)。
    r"|已(?:把|将)(?=[^。\n]{0,44}?" + _FILE_OBJ + r")[^。\n]{0,24}(?:加进|更新|保存|落进)"
    # 2026-07-25 finding:概念易撞词(更新/保存/加进/落进)必须近旁出现【文件类宾语】才算虚报改文件;
    # 否则「已更新了对这笔款的判断」「已加进去了这条待办」「已保存到记忆里」是概念收尾,不是改文件,别误伤。
    r"|(?:已更新了?|更新好了|已保存|已加进去?|加进去了|已落进|落进了)[^。\n]{0,20}?" + _FILE_OBJ
    # ⛔ 2026-08-26 补 5 个盲区(写回归时逐条打靶打出来的,全是我日常真会说的话)。
    #   ⛔ 新增的每一条都【必须近旁有文件类宾语】—— 沿用上面两条的保护,不做无条件命中。
    #     这道闸吃过反方向的亏:无条件的「把/将」分支把「已把这笔款的判断更新了」也拦了(概念收尾)。
    #   ⛔ 为什么值得放宽:这道闸防的是【我骗他】。漏拦=我虚报交付,误伤=我多跑一次验证。
    #     两边代价不对等,所以在【带宾语保护】的前提下宁可多拦。
    # ① 「我已**经** Edit x.md」——原判据 `已\s*Edit` 只差一个「经」字就瞎(写回归时当场撞到)
    + r"|已经\s*Edit"
    # ② 「已修改/已写入/已改写/已覆盖 + 文件」
    + r"|(?:已修改|已写入|写入了|已改写|已覆盖|覆盖了)[^。\n]{0,12}?" + _FILE_OBJ
    # ③ 「我把 lessons.md 改好了」——主语在「把」之前,且动词后置带「了」
    + r"|(?:把|将)[^。\n]{0,24}?" + _FILE_OBJ + r"[^。\n]{0,12}(?:改好|改完|改掉|删掉|写好|建好|改回)了"
    # ④ 宾语前置:「lessons.md 已更新」
    + r"|" + _FILE_OBJ + r"[^。\n]{0,8}(?:已更新|已改好|改好了|已改完|已写好|已建好)"
)


def _log(msg):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("false-done-gate", msg)
# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("false-done-gate", turn_start=True)
    elif self_blocked_this_turn("false-done-gate"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no transcript_path)")
        return
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)   # 只读尾部,别每回合重读整份历史(Frank卡顿真凶)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue

    # 定位本轮:最后一个真实 user 消息(非 tool_result)之后
    # 回合边界走 guard_common 的共享实现:本闸原来自己写了一份,和另外 5 道闸一样
    # 【漏掉了后台 Agent 完成通知】(type=user 但自称 NOT USER INPUT)⇒ 回合被重置、
    # 本轮已做的验证/审查/固化全部失效 ⇒ 反复开火。见 test_turn_boundary.py。
    last_user = turn_start_index(msgs)
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs

    text_parts = []
    verified = False
    made = False
    # ⛔ 2026-07-25 目标绑定(治 target-blind):原判据是"本轮调过任意 Bash/Read/Grep 就算核实过" ——
    #   于是 `ls` 一下、读一个毫不相关的文件,都能换来"已核实"的通行证。核实必须核【这轮改的那个东西】。
    #   两条都算核实(避免误杀真实核法):①目标绑定 —— 命令/路径里出现本轮改过的文件名;
    #   ②真跑了 —— 命令形如跑测试/启服务/发请求(即便没点名文件,它确实在运行被改的代码)。
    #   ⚠️ 刻意【不】加"输出里有报错就不算核实":外部 critic 实测 70 个工具结果里只有 1 个带明显报错标志,
    #     而那 20 多轮 500 错误退出码全是 0 —— 那条判据近乎失明,加了只是自我安慰。
    EXERCISE = re.compile(
        r"\b(pytest|unittest|npm\s+(test|run)|yarn\s+(test|run)|jest|vitest|go\s+test|cargo\s+test"
        r"|curl|Invoke-WebRequest|Invoke-RestMethod|netstat|nvidia-smi|schtasks|playwright"
        r"|python\s+\S+\.py|node\s+\S+\.js|py\s+-3)", re.I)
    changed_names = set()
    verify_calls = []
    # ⛔⛔ 只收【让 verified 变 True 的那次调用】的输出,不是本轮所有 tool_result
    #    (外部 critic 2026-07-29:第一版收全部 ⇒ `ls`/`cat 闸日志`/`Read 闸源码`/WebFetch 的内容
    #     都能否决一次真实的测试通过,真 transcript 上 4 次开火全是这么来的)。
    #    照抄 reference-diff-guard.py:118 的 tool_use_id 配对;`blame-check.py:321` 那条
    #    「只收 input、绝不收 tool_result」的既有设计决定,规则3 是有意反过来的 —— 但必须**绑定**。
    exercise_ids = set()       # EXERCISE 命中的 tool_use id(= 真在跑被测代码的那次)
    tool_out = []              # 只装这些 id 对应的输出,见下方 WEAK_VERIFY
    for m in turn:
        if m.get("type") != "assistant":
            _c = (m.get("message") or {}).get("content")
            if isinstance(_c, list):
                for _x in _c:
                    if (isinstance(_x, dict) and _x.get("type") == "tool_result"
                            and _x.get("tool_use_id") in exercise_ids):
                        try:
                            _t = _result_text(_x.get("content"))
                            # ⛔ 头尾各留 8000:测试摘要永远在【尾部】,单纯截头 20000 会漏
                            #    (critic 实测:skip 出现在第 20000 字之后 → 漏拦)
                            tool_out.append(_t if len(_t) <= 16000 else _t[:8000] + "\n…\n" + _t[-8000:])
                        except Exception:
                            pass
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            text_parts.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                text_parts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                nm = str(c.get("name", ""))
                inp = c.get("input") or {}
                cmd = str(inp.get("command", "") or "")
                fp = str(inp.get("file_path", "") or "")
                if nm in VERIFY_TOOLS:
                    verify_calls.append((cmd or fp, cmd))
                    # 记下"真在跑被测代码"的那次调用 id —— 规则3 只读它的输出。
                    # ⛔ 但【跑闸自己】的那些调用要排除:`.claude/hooks/` 是日常主战场,
                    #    跑闸的回归、cat 闸的日志、看闸的源码,输出里**必然**出现
                    #    `skip(self-blocked…)` 这种闸自己的日志格式 ⇒ 结构性自撞
                    #    (critic 实测 4 次开火全是这么来的;绑定 id 后仍剩 2 次,就是这一类)。
                    #    改闸的覆盖不丢:`regress-on-guard-edit` 会自动跑回归并报红。
                    if EXERCISE.search(cmd or "") and not SELFTEST.search(cmd or ""):
                        exercise_ids.add(c.get("id"))
                if nm in MADE_TOOLS:
                    made = True
                    if fp:
                        changed_names.add(os.path.basename(fp))
                # finding#2:shell 写文件(cat>>/>/tee/sed -i/Set-Content)也算本轮真改了文件
                if nm in ("Bash", "PowerShell"):
                    w = BASH_WRITE.search(cmd)
                    if w:
                        made = True
                        for tok in re.findall(r"[\w.-]+\.[A-Za-z0-9]{1,6}", cmd):
                            changed_names.add(os.path.basename(tok))
    # ⛔⛔ 2026-07-29 升级:原来这道闸【只验我有没有做动作】,验不了【做出来的东西对不对】。
    #   实录(Frank「hook 也防治不了的话,我的 superego 创建来就是废项目」):
    #   我虚报「🎉 登录成功 34 条 cookie」时本闸放行,日志 `allow(...verified=True)` ——
    #   因为 EXERCISE 含 `python \S+\.py`,我跑了那个脚本就算"核实过",
    #   而**那条命令的输出正是虚报的来源**(脚本自己的成功判据是恒真的)。
    #   ⇒ 现在补一层【读产物】:扫本轮工具输出,认出【弱验证】的机械痕迹 ——
    #     ①用例被跳过(skip) ②没有任何用例真跑(0 passed / no tests ran) ③收集为 0。
    #   这三种情况下"全绿"毫无判别力(形状V:被测物没跑也照样通过)。
    #   实录佐证:同夜我给新闸写的第一版回归"7/7 通过",实为 5 个用例被 skip、结论无效,
    #   靠日志里 5 行连续 skip 才发现 —— 而那 5 行【就在工具输出里】,机器扫得到。
    weak = None
    for _t in tool_out:
        m = WEAK_VERIFY.search(_t)
        if m:
            weak = m.group(0)[:60]
            break

    for target, cmd in verify_calls:
        if EXERCISE.search(cmd or ""):
            verified = True
            break
        if changed_names and any(n and n in target for n in changed_names):
            verified = True
            break
    if not changed_names and verify_calls:
        verified = True      # 没识别出改了哪个文件(如纯 shell 改动) → 退回旧的宽松判据,别凭识别失败去多拦
    text = "\n".join(text_parts)
    scan = strip_doc(text)   # finding#9:剥代码块/表格/引用后再判 claim,别把"文档里描述完成词"当真交付

    # 2026-07-26:留下【因为哪句话】——只记类别("哪条判据触发")仍然算不出误伤率的分母(critic 抓到)。
    _m_done, _m_file = DONE.search(scan), FILE_CLAIM.search(scan)
    _w = lambda m: scan[max(0, m.start() - 40): m.end() + 40] if m else ""
    claimed = bool(_m_done)
    # ⛔⛔ 2026-09-06:词表漏了就问语义 —— 这道闸是【第一个】迁到共享判别器上的。
    #   起因(Frank):「重构把所有用关键词的全部变成语义…是不是可以统合集成全部合并?」
    #   当天量出来:36 道「读我说的话」的闸,判据区共 **230 个正则**,
    #   光 15 个 claim 词就被各自重复实现 **98 次**(「没有」28 道、「成功」8、「跑通」7…)
    #   ⇒ 每次翻车我只补【其中一份】词表,其余几十份照漏 —— 这就是"改三个月还漏"的机制。
    #   ⇒ 通用件 `guard_common.claim_kinds()`:一个语义判别器答"我有没有做出某类断言";
    #     各闸只留自己那半【证据核查】(本闸的 made/verified/weak 三条一个字没动)。
    #   ⛔ 安全方向:只在词表【没命中】时才问,不改变已命中的路径;
    #     语义层挂/超时 → 空集 → claimed 保持词表原判 ⇒ 行为与接线前完全一致(fail-open)。
    file_claimed = bool(_m_file)
    # 2026-09-06 全量串行回归里唯一的红,就是这段第一版造成的【真误伤】:
    #   「Write 工具真写 + 已写好文件」-> 期望 ALLOW,实际 BLOCK(claimed+made+unverified)。
    #   根因不是阈值、不是锚点,是**语义类别的粒度和这道闸词表的语义对不上**:
    #     · 本闸 DONE 词表专指「交付物真的工作」(已生效/跑通了/已上线);
    #     · claim_kinds("done") 是「我做完了某事」—— 明显更宽;
    #     · 「已写好文件」落进更宽那个,被塞进一条为更窄概念写的规则里。
    #   => 全量换语义的系统性风险:**不是每个词表都有同粒度的语义类**。
    #   => 修法(尊重本闸原有分工):写文件这类断言归 file_claimed 那条路(它自己会查 made),
    #      语义只在【不是文件断言】时才补,别让两条路抢同一句话。
    if not claimed and not file_claimed:
        try:
            from guard_common import claim_kinds as _ck
            if "done" in _ck(scan[-1500:], kinds=("done",)):
                claimed = True
                _log("semantic-claim(done): 词表没命中,语义判定为交付断言")
        except Exception:
            pass

    # 规则2(2026-07-20 新增):说「已改/已写/已Edit 文件」但本轮【没有任何写操作 made】= 虚报改文件。
    # 精准命中 Auto-dream 打脸那次的漏网结构(claim改文件+本轮只WebSearch)。复述历史误伤→按提示改措辞即可。
    # 上一轮已做、本轮只复述(且本轮也核实过)→ 不是虚报,放行
    if file_claimed and not made and PAST_TURN.search(scan) and verified:
        _log("allow(past-turn-restate+verified)")
        file_claimed = False
    if file_claimed and not made:
        _log("BLOCK(file-claim-no-write) " + trig(_w(_m_file)))
        reason = (
            "⛔ 虚报闸(改文件):你这轮说了「已改/已写/已 Edit/已删/已更新 某文件」这类话,"
            "但本轮【没有任何 Write/Edit/MultiEdit 调用】—— 你并没有真的改那个文件。"
            "2026-07-20 你就这样虚报过「已 Edit lessons.md」。现在【真的去调 Edit/Write 改掉它】再收尾;"
            "若这句只是复述以前轮次已做的改动,改成过去式明确标注(如『上一轮已改』)避免被读成本轮交付。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return

    # 规则3(2026-07-29 新增·读产物层):做了动作 + 说它工作 + 【工具输出里有弱验证痕迹】
    #   ⇒ 那个 verified=True 是假的,拦。这是本闸唯一一条**看"跑出来什么"**而不是"跑没跑"的判据。
    #   ⛔ 只在 claimed+made+verified 三者同现时才看 weak ⇒ 纯讨论轮/没宣称完成的轮次不受影响。
    if claimed and made and verified and weak:
        _log("BLOCK(weak-verification) " + trig(weak))
        # ⛔ 触发词必须【打码后】才能出现在提示里(2026-07-29 本闸上线首日自撞):
        #   我的回归用例通过时会打印这条提示 → 提示里原样带着 `skip(self-blocked` →
        #   下一轮扫工具输出时**匹配到闸自己的提示语** → 自指误报。
        #   通用形状:任何词表闸,只要把触发词原样回显,就会拦下"讨论/测试这道闸"的那些轮。
        safe = weak.replace("(", "（").replace("0", "０")
        reason = (
            f"⛔ 虚报闸(弱验证):你说了「生效/跑通/修好」,本轮也确实跑了东西 —— "
            f"但工具输出里有【{safe}】这种痕迹,说明**有用例根本没执行**(或压根没收集到用例)。\n"
            "   这种情况下的「全绿」没有判别力:被测的东西就算完全坏掉/压根没跑,你的断言照样通过"
            "(lessons 形状V)。2026-07-29 实录:我给新闸写的回归报「7/7 通过」,实为 5 个用例被 "
            "`skip(self-blocked-this-turn)` 放行、结论无效,而那 5 行 skip 就明晃晃打在输出里。\n"
            "   ⇒ 现在【让那些用例真的跑起来】(隔离标记/清状态/换独立目录)再重跑,"
            "拿到一份没有 skip 的结果再收尾。若那些 skip 是无关用例、与本次交付无关,说明清楚即可。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
        return

    # 规则1(原有):三者同现才拦:本轮【真造/改了工件 made】+【说它工作 claimed】+【却没核实 not verified】。纯讨论/提案轮(not made)放行。
    if claimed and made and not verified:
        _log("BLOCK(claimed+made+unverified) " + trig(_w(_m_done)))
        reason = (
            "⛔ 虚报闸:你这轮说了「生效/焊好/装好/跑通/上线」这类【交付物真的工作】的话,"
            "但整轮没有任何核实类工具调用(Bash/PowerShell/Read/Grep 去看过/跑过结果)。"
            "按 CLAUDE.md 验证铁律:说『生效/完成』前必须有实测证据。现在【回去实测】——"
            "跑一下/读一下/截个图确认它真的能用,把凭证贴出来再收尾;若这轮本就无需核实(纯讨论/复述),"
            "改掉那句会被误解成『已验证工作』的措辞即可。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    else:
        _log(f"allow(claimed={claimed},file_claimed={file_claimed},made={made},verified={verified})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
