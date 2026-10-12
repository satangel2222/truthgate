#!/usr/bin/env python3
"""Stop hook: 固化反射闸 —— 本轮我 Write 了「可复用的脚本/工具」，却没把它固化成【日后能复用的 CLI + 注册/更新进全局 skill】就想收尾。

2026-07-21 Frank 钉死:「我说的是任何形式的东西，你做好的任何东西，思考是不是可以直接做成 CLI 给你日后复用、
直接做成全局通用 skill、skill 需要就自己同步更新 —— 而不是我说一次你就做一次！」
上一轮 yunwu 成本查询就是:我建了 report/daily 命令，却做成桌面 cmd、还要 Frank 逼我才注册进 skill。
软规则(lessons/CLAUDE)拦不住「我当下没想到要固化」→ 上机器闸:每轮收尾时结构性逼我自检。

触发(全满足才拦一次):
  ① 本轮有 Write 一个「可复用脚本」(.py/.mjs/.cjs/.js/.ts/.sh/.ps1)，且不在 scratchpad/tmp/temp、非 .bak；
  ② 该 Write 不在 ~/.claude/(hooks/skills/scripts —— 写这些【本身就是】固化，放行)；
  ③ 本轮没有【固化动作/意图】的证据:没 Write/Edit 任何 SKILL.md，助手文本也没提「注册/更新 skill、做成 CLI 复用、固化」。

安全设计(照 false-done-gate.py):fail-open 异常放行 / 只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我 / 只读 transcript / 窄触发(只认 Write 新脚本) / 每次留日志。
放行的正当出口(拦截语里给):这脚本若确实一次性、不值得复用，一句话说明为什么不固化即可。
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
import sys
import json
import re
import os
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "institutionalize-guard.log")

# regex-sanity: ok — 本职就是认脚本扩展名,命中 .py 正确
SCRIPT_EXT = re.compile(r"\.(py|mjs|cjs|js|ts|sh|ps1)$", re.I)
# Edit/MultiEdit 的【新增内容】里出现"给 CLI 加新命令/子命令"的模式 = 也是在造可复用能力(补 2026-07-21 漏洞:
# yunwu report/daily 就是 Edit 加命令、原 hook 只认 Write 会漏)。窄:只认命令派发分支,不认普通改代码。
# ⛔ 收窄(2026-07-25 审计:裸 `.command('...')` 会误配 db.command('ping')/bot.command('start')/client.command('help')
#    等【任何名为 command 的方法调用】,对普通 Edit 误开火要求固化)。只认真·CLI 子命令特征:
#    ①顶层 commander/yargs(program./yargs.command);②链式 commander builder(.command('x').action/.description...)。
CMD_ADD = re.compile(
    r"else\s+if\s*\(\s*(?:cmd|command|sub|argv)\b[^)]*===|elif\s+(?:args\.)?(?:cmd|command|sub)\b[^:]*==\s*['\"]"
    r"|subparsers\.add_parser\s*\("
    r"|(?:program|yargs)\.command\s*\(\s*['\"]"
    r"|\.command\s*\(\s*['\"][^)]*\)\s*\.(?:action|description|argument|option|requiredOption|alias)\b"
    r"|@(?:cli|app|group)\.command|case\s+['\"][\w-]+['\"]\s*:\s*(?://|#|$)")
# 排除:临时/构建/备份路径 —— 这些不是"要复用的工件"
EXCLUDE_PATH = re.compile(r"scratchpad|[\\/]tmp[\\/]|[\\/]temp[\\/]|\.bak|node_modules|[\\/]dist[\\/]|[\\/]build[\\/]", re.I)
# 排除:写 .claude 基建(hooks/skills/scripts)本身就是"固化"，放行
CLAUDE_INFRA = re.compile(r"[\\/]\.claude[\\/](hooks|skills|scripts|commands|bin|superego-semantic)[\\/]|[\\/]\.truthgate[\\/](hooks|semantic)[\\/]", re.I)  # 2026-09-27 新旧路径都认
# 文本里出现"固化/注册skill/做成CLI/复用"等 = 我已经在固化 → 放行
INSTITUTIONALIZE = re.compile(
    r"注册.{0,8}skill|更新.{0,6}SKILL|写进.{0,8}skill|做成 ?CLI|做成 ?命令|固化.{0,6}(cli|skill|命令)"
    r"|invoke.{0,8}skill|可复用|日后复用|复用.{0,6}(cli|skill)|SKILL\.md|注册进.{0,8}skill|沉淀成.{0,6}(cli|skill)",
    re.I)
# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ 第四条判据(2026-09-06 加):**纯调查(零 Write/Edit)查出了根因/方法论,却没写进
#   lessons.md 或项目 memory → 拦。**
#   Frank 原话:「换个new chat会不会忘记了，不用固化流程？我superego没有这个gate？
#   是不会拦，还是不会hook?」
#   实录(airbnb ai manager):同一轮对话里,我用 `wa-baileys/auth-*/lid-mapping-<手机号>.json`
#   破解了"手机号↔WhatsApp lid"的对照方法,并靠"图片时间戳 vs 第三方系统建号时间戳"分钟级比对,
#   几秒内锁定了 4 个客人的关键消息——这是换任何项目都能复用的调查方法,但那一轮【零 Write/Edit】
#   (纯 Bash/Read 查证),①②③三条判据全部没触发(没写脚本、没自认错、没做 UI),这个发现就这么
#   滑过去了,直到 Frank 自己问出那句话才被追认写进项目 memory。
#   ⇒ 前三条判据的共同盲区:全部要求"本轮有 Write/Edit 某种文件"才可能触发,
#     而"纯调查发现方法论"恰恰不产生任何文件改动 —— 这道判据专门补这个盲区。
DISCOVERY_LANG = re.compile(
    r"找到了|根因(是|查到|找到)|终于查到|真相是|铁证|破案|锁定了|查到了根因|100%\s*(确认|闭环|复原)"
    r"|真正的答案|已经查清|水落石出|100%查到|查穿了", re.I)
# 项目级 memory 文件:.claude/projects/<slug>/memory/*.md(跨平台都认 \ 和 /)
MEMORY_FILE = re.compile(r"[\\/]\.claude[\\/]projects[\\/][^\\/]+[\\/]memory[\\/]", re.I)
# 纯查证类工具(不产生任何持久改动的读取动作)
READONLY_TOOLS = {"Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch"}
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ 第二条判据(2026-08-13 加):**认了错,但错误免疫没落地 → 拦。**
#   实录:那天同一个病根(分子分母不对应)发作 5 次,4 次是 Frank 揪出来的。
#   `dissatisfaction-postmortem` 当天开火 30 次、每次都喊「先做复盘」——**我 4 次全跳过,零后果**,
#   因为它是 UserPromptSubmit hook:**只能往上下文塞文字,拦不住任何东西**。
#   而 lessons.md 的 mtime 停在 08:05,5 个错全发生在 08:40 之后 ⇒ **一条都没记**。
#   `superego-health.py` 只查「开没开火」,所以它照报「✅ 没有可疑死闸」。
#   ⇒ **纸老虎的准确定义不是「没跑」,是「跑了但没有后果」。度量要从【开火率】改成【落地率】。**
#   为什么加在这个文件里而不是新建第 127 个 hook:同属「做了事就要沉淀下来」这一族,
#   复用已有挂载点 = 不给已经 126 个文件 / 50 个挂载点的系统再添一份污染。
SELF_ERROR = re.compile(
    r"我错了|我算错|算错了|我的错|是我造成的|我漏了|我漏算|我漏扣|我搞错|我判断错|我诊断错"
    r"|错了\s*\d+\s*倍|作废|我之前.{0,14}(是错|错的|错了)|上一版.{0,10}错|那是假的|我又错|我彻底错",
    re.I)
# 排除:只是在复述历史教训、而不是本轮新认错
HIST_ONLY = re.compile(r"历史上|以前那次|那一次的教训|lessons 里(写着|已有)|已经记进|早就记过")
LESSON_FILE = re.compile(r"lessons\.md", re.I)

# ─────────────────────────────────────────────────────────────────────────────
# ⛔⛔ 第三条判据(2026-08-13 加):**做了【给人看的页面】,却没 invoke 设计 skill → 拦。**
#   Frank 原话:「我说了很多次我眼睛看不清太小的东西,而且你也不该给我那么杂乱的排版,
#   你到底有没有 taste skill 还有 open design?为何做网页你没自动 invoke 做网页的 ui/ux 的 skill,
#   难道只有关键字 ui/ux 才匹配也太狭隘了不是吗」
#   当天实录:我生成了一份现金流报告网页,**正文 11.5px / 表头 10px、五张表挤成三列 grid**,
#   而他早就说过看不清小字。每轮注入的自检第 ④ 条明写「设计别凭感觉(底座 design-taste-frontend)」——
#   **我读到了,照样没 invoke**。⇒ 又一次证明:UserPromptSubmit 只能塞文字,拦不住行为。
#   ⛔ 触发面故意【不靠关键字 ui/ux】:靠【产物形态】——写了 .html,或往任何文件里写了 CSS。
#     只认关键字正是他批评的「太狭隘」:我做网页时嘴里根本不会出现 "ui/ux" 这两个字。
UI_FILE = re.compile(r"\.(html?|jsx|tsx|vue|svelte)$", re.I)
# 往任何文件(含生成器脚本)里写 CSS = 也是在做视觉,同样要过设计这关
CSS_IN_CODE = re.compile(
    r"<style\b|font-size\s*:|grid-template|flex-direction|border-radius\s*:|@media\s*\(", re.I)
# 本会话真的 invoke 过设计类 skill(Skill 工具的调用记录) = 放行。
# ⛔ 2026-10-04:原来还有一条「正文里提到 ui/ux / 设计 skill 就算过」——那是看措辞不是看事实:
#   我写一句「我没调用设计 skill」同样命中。当天实录(novel2drama 库页面):11~12px 字、六列并排,
#   整个会话 0 次设计 skill 调用,ui-edit-guard 提醒 9 次全被我无视。⇒ 只认调用记录。
DESIGN_SKILL = re.compile(
    r"design-taste-frontend|artifact-design|design[- ]?system|frontend[- ]?design"
    r"|ui-?humanity|ui-ux-pro-max|open-design", re.I)


def _soft():
    """本闸 2026-09-26 起整道只记账(看措辞的判据居多);2026-10-04 移出名单后,
    只有设计闸(看事实:写了页面 + 有没有 Skill 调用)真拦,其余判据在闸里自己降成只记账。
    测试里照常出结论(回归要看真结论),与 guard_common 只记账模式是同一个约定。"""
    try:
        from guard_common import _test_run
        return not _test_run()
    except Exception:
        return True      # 拿不到 = 不拦(与原来只记账一致,绝不因此多拦)
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

try:
    from guard_common import trig   # 2026-07-28 C3:BLOCK 日志要记【惹祸的原句】
except Exception:
    def trig(s, n=120): return (s or "")[:n]

def _log(msg, ctx=""):
    # 2026-07-28 C3:加 ctx 透传【惹祸的原句】。此前 BLOCK 只记判据类别
    #   (如 "BLOCK(claimed+code+no-critic)"),事后无法判断是真拦还是误伤 ——
    #   要复算就得回去翻 transcript。trig() 早就在 guard_common 里,只是没接上。
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("institutionalize-guard", msg, ctx)
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
        self_blocked_this_turn("institutionalize-guard", turn_start=True)
    elif self_blocked_this_turn("institutionalize-guard"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no transcript_path)")
        return
    try:
        import os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
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
    made_scripts = []      # 本轮 Write 出的可复用脚本
    touched_skill = False  # 本轮碰过 SKILL.md 或 .claude 基建 = 已在固化
    touched_lessons = False  # 本轮往 lessons.md 写过东西 = 错误免疫已落地
    made_ui = []             # 本轮产出的「给人看的页面」
    design_done = False      # 本轮 invoke 过设计 skill / 明说按设计规范做
    touched_memory = False   # 本轮写过项目 memory 文件 = 发现已经落地
    readonly_call_count = 0  # 本轮纯查证类工具调用次数(Bash/Read/Grep…)
    any_mutation = False     # 本轮有没有任何 Write/Edit/MultiEdit(不分文件类型,比 made_scripts 更宽)
    # ⛔ 2026-09-10:被 PreToolUse 闸拦下的 Write【没落盘】,不算"建了能力"。原来只看 tool_use、
    #   不看 tool_result ⇒ 我两次被拦的 Write 都被当成"写了脚本没固化"开火(ls 实证文件不存在)。
    errored_ids = set()
    for m in turn:
        cc = (m.get("message") or {}).get("content")
        if isinstance(cc, list):
            for x in cc:
                if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("is_error") \
                        and x.get("tool_use_id"):
                    errored_ids.add(x["tool_use_id"])
    for m in turn:
        if m.get("type") != "assistant":
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
                if c.get("id") and c["id"] in errored_ids:
                    continue        # 调用被拦/报错,什么都没产出
                nm = str(c.get("name", ""))
                inp = c.get("input") or {}
                fp = str(inp.get("file_path") or "")
                low = fp.lower()
                if nm in READONLY_TOOLS:
                    readonly_call_count += 1
                if nm in ("Write", "Edit", "MultiEdit"):
                    any_mutation = True
                if CLAUDE_INFRA.search(low) or "skill.md" in low:
                    touched_skill = True
                # 写 lessons.md 有两条路:file_path(Write/Edit) 或 Bash 命令里 append —— 两条都认,
                # 否则用 heredoc 追加的那种写法会被判成"没落地"而误拦。
                if LESSON_FILE.search(low) or LESSON_FILE.search(str(inp.get("command") or "")):
                    touched_lessons = True
                # 项目 memory 同理:Write/Edit 直接给 file_path,Bash heredoc 追加给 command
                if MEMORY_FILE.search(low) or MEMORY_FILE.search(str(inp.get("command") or "")):
                    touched_memory = True
                # ── 第三条判据的取证:产出了页面吗?invoke 设计 skill 了吗? ──
                if nm == "Skill" and DESIGN_SKILL.search(str(inp.get("skill") or "")):
                    design_done = True
                if not EXCLUDE_PATH.search(low) and not CLAUDE_INFRA.search(low):
                    body = str(inp.get("content") or "") + str(inp.get("new_string") or "")
                    for e in (inp.get("edits") or []):
                        if isinstance(e, dict):
                            body += str(e.get("new_string") or "")
                    if nm in ("Write", "Edit", "MultiEdit") and (UI_FILE.search(low) or CSS_IN_CODE.search(body)):
                        made_ui.append(os.path.basename(fp) or "(inline)")
                is_script = bool(SCRIPT_EXT.search(low)) and not EXCLUDE_PATH.search(low) \
                    and not CLAUDE_INFRA.search(low)
                if not is_script:
                    continue
                if nm == "Write":
                    made_scripts.append(os.path.basename(fp))  # 写了新脚本
                elif nm in ("Edit", "MultiEdit"):
                    adds = []
                    if inp.get("new_string"):
                        adds.append(str(inp["new_string"]))
                    for e in (inp.get("edits") or []):
                        if isinstance(e, dict) and e.get("new_string"):
                            adds.append(str(e["new_string"]))
                    if any(CMD_ADD.search(a) for a in adds):
                        made_scripts.append(os.path.basename(fp) + "(加了命令)")  # 给现有CLI加了新命令
    text = "\n".join(text_parts)

    institutionalized = touched_skill or bool(INSTITUTIONALIZE.search(text))
    # 设计 skill 按【会话】算(读到的整段尾部),不按本轮:一个页面常常跨好几轮改,
    # 头一轮 invoke 过就不该每轮再拦。只认真实的 Skill 调用,不认正文里提到。
    for m in msgs:
        cc = (m.get("message") or {}).get("content") if m.get("type") == "assistant" else None
        for c in (cc if isinstance(cc, list) else []):
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill" \
                    and DESIGN_SKILL.search(str((c.get("input") or {}).get("skill") or "")):
                design_done = True

    # 尾部只读 4MB:截图多的会话里,前面的 Skill 调用会被挤出去(2026-10-05 实录:当场误拦了自己)。
    # 只在「做了页面且尾部没找到」时才整份逐行扫,且只解析含 "Skill" 的行,不重读整份历史进内存。
    if made_ui and not design_done:
        try:
            with open(tp, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    if '"Skill"' not in ln:
                        continue
                    try:
                        cc = (json.loads(ln).get("message") or {}).get("content")
                    except Exception:
                        continue
                    for c in (cc if isinstance(cc, list) else []):
                        if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill" \
                                and DESIGN_SKILL.search(str((c.get("input") or {}).get("skill") or "")):
                            design_done = True
                    if design_done:
                        break
        except Exception:
            pass

    # ── 第三条判据:做了给人看的页面,却没过设计这关 ──
    if made_ui and not design_done:
        _log(f"BLOCK(made_ui={made_ui[:3]} no-design-skill)", trig(text.replace(chr(10), " "), 160))
        why = (
            "⛔ 设计闸:你这轮做了【给人看的页面/UI】(" + "、".join(sorted(set(made_ui))[:3]) + ")"
            "，但整轮没 invoke 过任何设计 skill。"
            " Frank 2026-08-13 原话:「我说了很多次我眼睛看不清太小的东西,而且你也不该给我那么杂乱的排版…"
            "为何做网页你没自动 invoke 做网页的 ui/ux 的 skill,难道只有关键字 ui/ux 才匹配也太狭隘了不是吗」"
            " 当天实录:我生成的报告用了【正文 11.5px / 表头 10px】、五张表挤成三列 grid ——"
            "而每轮注入的自检第④条早就写着「设计别凭感觉」,我读到了照样没做。"
            " ⇒ 现在做:①`invoke skill design-taste-frontend`(或 artifact-design,看产物类型);"
            "②先声明一句 Design Read(这是给谁看的、什么语气、什么密度);"
            "③**Frank 的硬约束:两条同时成立:(a)一眼看完——他的屏幕(1920 宽)上不滚动看到全部条目,用满整个屏幕宽度排大卡片,别排成一长列、别在两边留大片空白;(b)可见文字最小 17px、数字 20px+、关键数字 40px+。放不下时先压表现(顶栏并成一行、缩留白、状态写短、每项一行),不许缩字,也不许改成往下滚;(2026-10-05:这里原写「单列优先」,我照做把 33 部排成十几屏,Frank:「为何不是一眼看完,还要滚动,为何不是大卡片」)"
            "结论和「该做什么」放第一屏;他讨厌折叠,所以别折叠**;"
            "④做完自己截图 + 用脚本量两样再交付:字号(`getComputedStyle(e).fontSize < 17` 的元素数必须为 0)、滚动(1920 宽视口下 `document.documentElement.scrollHeight <= innerHeight`,做不到要写明为什么)。"
            " 若这轮的 HTML/CSS 不是给他看的(测试夹具、临时探针、纯后端模板),一句话说明即可放行。"
        )
        print(json.dumps({"decision": "block", "reason": why}, ensure_ascii=False))
        return

    # ── 第二条判据:本轮【自己承认算错/搞错/要撤回】,但整轮没往 lessons.md 写一个字 ──
    if SELF_ERROR.search(text) and not HIST_ONLY.search(text) and not touched_lessons:
        if _soft():
            _log("WOULDBLOCK(soft)(self-error but lessons untouched)", trig(text.replace(chr(10), " "), 160))
            return
        _log("BLOCK(self-error but lessons untouched)", trig(text.replace(chr(10), " "), 160))
        why = (
            "⛔ 错误免疫闸:你这轮【自己承认算错/搞错/要撤回】了,但整轮没往 ~/.claude/lessons.md 写一个字。"
            " 实录 2026-08-13:同一个病根一天发作 5 次、4 次是 Frank 揪出来的;"
            " dissatisfaction-postmortem 当天开火 30 次喊「先做复盘」,我 4 次全跳过 ——"
            " 因为它是 UserPromptSubmit hook,只能塞文字、拦不住。当天 lessons.md 停在 08:05,错全在 08:40 之后 ⇒ 一条没记。"
            " ⇒ 纸老虎不是「没跑」,是「跑了但没有后果」。现在补上:"
            " ①归【形状】不是记细节(细节没复利,形状有);编号用「形状 YYYY-MM-DD-X」——"
            "字母编号已污染(AH 用过 4 次、AI 用过 2 次)。"
            " ②写清【通用判据】:换个完全无关的项目还管不管用?不管用=只记了死例子。"
            " ③写清【反向指纹】:下次凭什么一眼认出来。"
            " ④判断机器能不能防:能防的当场落成代码/自检,不能防的老实登记。"
            " 写完再收尾。若这轮的『错』只是复述历史、不是本轮新发现,把措辞改成过去式即可放行。"
            " 若本轮根本没动手过(纯文本回应 Stop hook 的拦截),说明已经在自审,放行。"
        )
        print(json.dumps({"decision": "block", "reason": why}, ensure_ascii=False))
        return

    # ── 第四条判据:纯调查(零 Write/Edit)却像是破了案/找到了可复用方法,没写进 lessons/memory ──
    if (DISCOVERY_LANG.search(text) and not any_mutation and readonly_call_count >= 3
            and not touched_lessons and not touched_memory and not HIST_ONLY.search(text)):
        if _soft():
            _log("WOULDBLOCK(soft)(discovery but not persisted)", trig(text.replace(chr(10), " "), 160))
            return
        _log("BLOCK(discovery but not persisted)", trig(text.replace(chr(10), " "), 160))
        why = (
            "⛔ 发现未固化闸:你这轮【纯查证,零 Write/Edit】(跑了 " + str(readonly_call_count) + " 次 Bash/Read/Grep 这类只读工具),"
            "但用词像是破了案/找到了可复用的方法(命中「根因/找到了/终于查到/铁证」这类词),"
            "却没往 ~/.claude/lessons.md 或本项目 `.claude/projects/<slug>/memory/` 写一个字 ——"
            "新开一个 chat 就得从零重新摸索这条调查路径,等于这次的功夫白费。"
            " Frank 原话(2026-09-06):「换个new chat会不会忘记了，不用固化流程？我superego没有这个gate？」"
            " ⇒ 现在补:①这是不是换个项目也用得上的通用方法(不是这个项目独有的事实)?是→写进全局 lessons.md;"
            "②只是这个项目的事实/号码/路径 → 写进项目 memory;③写完再收尾。"
            " 若这次发现纯属一次性、不值得复用(比如答案只对这一个客人有效,换个人就作废),"
            "一句话说明为什么不固化即可放行。"
        )
        print(json.dumps({"decision": "block", "reason": why}, ensure_ascii=False))
        return

    if made_scripts and not institutionalized:
        if _soft():
            _log(f"WOULDBLOCK(soft)(made={made_scripts})", trig(text.replace(chr(10), " "), 160))
            return
        _log(f"BLOCK(made={made_scripts})", trig(text.replace(chr(10), " "), 160))
        sample = "、".join(made_scripts[:3])
        reason = (
            f"⛔ 固化反射闸:你这轮建/改了可复用的能力({sample})，但没把它固化成【日后能复用】就想收尾。"
            "Frank 铁律(2026-07-21):做好任何可复用的东西 → 主动固化，别等他提醒。现在自问三条并【立刻执行】:"
            "①它能不能做成可复用 CLI/命令(而非一次性脚本)? "
            "②该注册/更新进哪个全局 skill，让日后任何 chat 的我能直接 invoke?"
            "【工具·按场景分流】把一个【大软件/开源项目】变成我可调的 CLI → `/cli-anything <它>`(现成框架,自带测试+自动生成 SKILL.md,别重造轮子);"
            "建/改 skill → invoke `skill-creator`;做成 agent 可调的 API/MCP 工具 → invoke `mcp-builder`;"
            "【我随手写的小工具/API 查询】→ 写个带 `--json` 的小 CLI + 直接 Edit 对应 SKILL.md(别套 cli-anything 的重型8阶段,杀鸡用牛刀)。 "
            "③需要就【现在自己同步更新】那个 SKILL.md(用法/触发词/关键事实)。"
            "做完再收尾。若确实一次性、不值得复用(如临时诊断),一句话说明为什么不固化即可放行。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    else:
        _log(f"allow(made={len(made_scripts)},institutionalized={institutionalized})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
