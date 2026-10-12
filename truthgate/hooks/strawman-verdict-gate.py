#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""strawman-verdict-gate — 拦【拿我自己造的替身，去否定他提的方案】。

⛔ 起因(2026-09-05,Frank 一句「你连 obsidian 都没装,你测试什么鬼?」):
   他问「能不能利用 obsidian 当记忆库自动联动」。我做了个"对照实验",表格里明明白白写着
     A: 现有语义召回 = 67%
     B: **Obsidian 知识库** = 0%
   然后下结论:「用 Obsidian 当记忆库这条路,方向上不成立」。
   真相:**Obsidian 根本没装**(桌面版四个位置全空、注册表无、CLI 从来不存在),
   我测的是 `.brain2list.db` 这个 SQLite 文件、而且用的是 LIKE 字面匹配。
   ⇒ 我自己搭了一个劣质实现,**贴上他方案的标签**,再拿它的 0 分去否决他的想法。

⛔ 为什么这个形状比普通错误更危险:
   它**带着"我做过实验、有数据、有表格"的权威感** —— 比单纯说"我觉得不行"更难被质疑。
   一个零编程的人看到 0/18 这种数字,很难想到"你测的根本不是我说的东西"。
   **用假实验否定真想法,是在用他的信任成本替我的偷懒买单。**

⛔ 与既有闸的分工(别重复造):
   · `blame-check` 第三类管的是【说用户环境没装 X】——我这次**没说**它没装,所以那道闸抓不到。
   · 本闸管的是【否定一个方案/路线】,判据是"你否定的那个东西,本轮探测过它存在吗"。

判据(全中才拦,宽放窄拦):
  ① 本轮文本里出现【否定式判决】:不成立 / 行不通 / 不可行 / 这条路不行 / 方向(上)不对 / 没戏 / 走不通
  ② 判决句附近出现一个【具体产品/工具名】(反引号内、或首字母大写的英文标识符、或已知产品词)
  ③ 本轮**没有**对那个名字做过探测(probe.py / Test-Path / import / which / where / 注册表查询…)
  = 你在拿没验过的东西下判决 → deny,要求先探测再说

安全:fail-open(任何异常都放行) / 只读 transcript / 只拦一次(per-gate 标记) / 留日志。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, turn_start_index, self_blocked_this_turn
except Exception:
    def hook_log(*a, **k):
        pass

    def turn_start_index(msgs):
        return -1

    def self_blocked_this_turn(*a, **k):
        return False

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GATE = "strawman-verdict"

# ① 否定式判决 —— 「这个方案不行」这一类话
# ⛔ 2026-09-05 故障注入抓到的冗余(只跑绿永远发现不了):
#   原词表里同时有 `方向上?[也都]?不成立` 和更宽的 `不成立`,后者**完全覆盖**前者
#   ⇒ 把前者整条删掉,行为一个字都不变,任何测试都测不出来 = 那一段是死代码。
#   同理 `走不通` 出现了两次(一次在「这条路(...|走不通|...)」组里,一次单列)。
#   ⇒ 冗余分支不是无害的:它让人以为"这一族被专门覆盖了",而实际删了也没人知道,
#     下次真要收窄某一族时会误判"改了没效果"。**能被更宽的那条吃掉的,就该删。**
VERDICT = re.compile(
    r"(不成立|行不通|走不通|不可行|没戏|白搭"
    r"|这条路[也都]?不通|没用的?[,，。]|不值得(做|搞|上)"
    r"|(替代|换成|改用)[^\n]{0,12}(不行|没用|更差))",
)

# ② 产品/工具名:反引号内的标识符,或独立的大写开头英文词(Obsidian/Notion/Redis…)
# ⛔ 2026-09-06 补丁:排除集里没有反斜杠 `\`,导致 Windows 路径里被反斜杠夹住的每一段
#   (`F:\Users\User\AppData\Local\hermes\` → AppData/Local/Users)全被当成"待评判的产品名"。
#   实录:我说"这条路(指提权流程)走不通",闸判决对象抓成了 AppData/Local/PowerShell,
#   而路径片段根本不是候选方案,是数据位置。补 `\\` 到左右两个负向环视里即可,
#   跟 `/` `.` `-` 反引号 那批本来就在防的东西是同一类噪音。
NAME_TICK = re.compile(r"`([A-Za-z][\w.\-]{2,30})`")
NAME_CAP = re.compile(r"(?<![\w`/.\\-])([A-Z][a-zA-Z]{3,20})(?![\w`\\])")

# ⛔⛔ 2026-09-08:占位符不是产品名。
#   实录(当晚它真拦了我一次):我写 `--since "YYYY-MM-DD HH:MM"` 只是在**说明参数格式**,
#   闸把 **YYYY** 抽成了「我正在宣判走不通的那个东西」,报「YYYY 本轮从没被探测过」。
#   ⛔ 修法用【结构判据】,不是往 NOT_PRODUCT 里逐个加词 —— 逐个加 = 下次换成 XXXX/NNNN 又中,
#     而且同一份"什么不算产品名"会被抄成两份(今晚已经因为词表抄两份栽过一次)。
#   ⛔ 同一个形状今晚第 4 次:兄弟闸 `search-breadth-gate` 早有 PLACEHOLDER 这一档
#     (引号里的模板占位符),唯独这道没有。**建闸时抄了判据,没抄豁免。**
# ⛔⛔ 2026-09-26:判决对象只在【判决词所在的那一句】里找 + 这几类形状不是产品名。
#   实录:09-09~09-26 共 33 次"否定某产品"拦截,≥15 次抓到的"对象"是文件名(worker.js / metadata.json)、
#   配置键(min_machines_running)、git hash(f859eff)、闸名、hook 事件(Stop / UserPromptSubmit)、
#   全大写词(CLAUDE / PROGRESS)。当天两次:"外审那一点不成立" 被绑到隔一段的 Antigravity;
#   解释本闸时引述的"方向上不成立"被当成判决、对象抓成 Obsidian。
#   病根是【前后 200 字窗口】跨句跨段乱绑 + 只认"紧贴引号"才算引述。
SENT_END = "。！？!?；;\n"
# 引号/代码块里的判决词 = 在【提到】它(引述/举例/给别人的指令),不是在下判决。
QUOTED = re.compile(r"```.*?```|`[^`\n]*`|「[^」\n]*」|『[^』\n]*』|“[^”\n]*”|\"[^\"\n]*\"", re.S)
NOT_NAME_SHAPE = re.compile(r"\.\w{1,5}$|_|^[0-9a-f]{7,40}$|-(gate|guard)$", re.I)
HOOK_EVENTS = {"Stop", "SubagentStop", "SessionStart", "SessionEnd", "UserPromptSubmit",
               "PreToolUse", "PostToolUse", "Notification", "PreCompact"}

PLACEHOLDER_NAME = re.compile(
    r"^(?:(.)\1{2,}"                    # 同一个字符重复 ≥3 次:YYYY / XXXX / NNNN / AAAA
    r"|FOO\w*|BAR\w*|BAZ|QUX|XYZ|ABCD?|TBD|LOREM|IPSUM)$", re.I)

# 明显不是"待探测的产品"的词,别误伤
NOT_PRODUCT = {
    "The", "This", "That", "They", "There", "These", "Those", "When", "What",
    "With", "From", "Have", "Been", "Will", "Would", "Could", "Should",
    "TODO", "NOTE", "HTTP", "HTTPS", "JSON", "HTML", "PASS", "FAIL", "OK",
    "True", "False", "None", "Error", "Warning", "Windows", "Linux", "MacOS",
    "Frank", "Claude",
}

# ③ 算"探测过"的动作 —— 只认真的去问了机器的
PROBE = re.compile(
    r"probe\.py|Test-Path|Get-ItemProperty|Get-Command|Get-Package|winget\s+list"
    r"|\bwhich\b|\bwhere\b|npm\s+(ls|list)|pip\s+show|--version|import\s+\w"
    r"|sqlite3|os\.path\.exists|Path\([^)]*\)\.exists|existsSync",
    re.IGNORECASE)

# ③b ⛔⛔ 2026-09-05 当天扩判据(形状 D:同一个病第二次犯,而这道闸放行了它):
#   上一版只问「那个名字探测过【装没装】吗」。而那次我**确实探测过**(知道 Obsidian 没装),
#   于是闸放行 —— 然后我拿他 vault 里【一个自制小脚本】的关键词打分,
#   当成「Obsidian 那套检索」,宣布"方向上不成立"。
#   Frank:「你根本没有真正了解什么是 obsidian…整套系统有多逆天和多少 plugin…
#          你没去深度搜索?包括 obsidian 记忆库里的知识库你也查了吗?30days skill 查了?」
#   一搜就打脸:社区有 Smart Connections(本地嵌入语义检索)、
#   `smart-connections-mcp`(★55,一句话就是"给 Claude 提供你 Obsidian vault 的语义记忆")——
#   **他问的那件事早有人做成现成的**,而我说它不成立。
#   ⇒ 「装没装」和「我了不了解它」是两回事。判一个【产品/平台/生态】不行,
#     必须本轮真的**搜过这个生态**(WebSearch / last30days / gh search / 官方文档 / 插件市场),
#     否则手上那个样本几乎必然只是生态的一个角落。
#   ⛔ 用户自己写的脚本 ≠ 那个平台的能力上限。
# ④ ⛔⛔ 2026-09-06 形状 D:**近亲形状 —— 不是判"它不行",而是给自己找个"不去用它"的理由**。
#   实录:我探测到 GPU 是好的(RTX 3070/驱动 616.56),却写下
#   「不装的真实理由是【换 torch 会降级、可能拖累本机其它吃 torch 的项目】」,
#   然后准备干等 2.5 小时让 CPU 跑。Frank:「你没有给我 cuda 装 gpu 最好兼容版本,然后测试再跑?」
#   一查双重塌掉:`pip show torch` → **Required-by 只有 sentence-transformers**(没有"别的项目");
#   `pip index versions` → CUDA 版是 **2.14.0+cu126**,和当前 CPU 版**同一个版本号**(降级不存在)。
#   代价:那个编的理由让全量索引从 **6 分钟变 150 分钟**,还把 1024 维的 SOTA 模型整条路判死。
#   ⛔ 上一版闸只认 VERDICT("不可行/走不通"),这句话一个都不命中 ⇒ 放行了。
AVOID_REASON = re.compile(
    r"(会|可能|怕|担心|恐|以免)[^\n]{0,24}(影响|拖累|降级|冲突|破坏|搞坏|带崩|不兼容)"
    r"|(兼容|稳妥|保险)起见"
    r"|影响[^\n]{0,10}(别的|其他|其它|另外)[^\n]{0,10}(项目|服务|功能|包|依赖)")
AVOID_ACTION = re.compile(r"(不装|不换|不上|不用|先不|暂不|没必要|不值得|放弃)")
# 算"量过了"的动作 —— 必须是真去问了依赖/版本,不是嘴上说评估过
DEP_PROBE = re.compile(
    r"pip\s+show|Required-by|pip\s+index\s+versions|pipdeptree|npm\s+ls|npm\s+list"
    r"|pip\s+list|requirements\.txt|package\.json|conda\s+list",
    re.IGNORECASE)

ECO_PROBE = re.compile(
    r"WebSearch|WebFetch|last30days|gh\s+search|api\.github\.com|/search/repositories"
    r"|community\.obsidian|marketplace|plugins?\b.*(search|list)|awesome-",
    re.IGNORECASE)


def _sentence(text, span):
    """判决词所在的那一句(按句末标点/换行切)。"""
    s = max(text.rfind(c, 0, span[0]) for c in SENT_END) + 1
    ends = [i for i in (text.find(c, span[1]) for c in SENT_END) if i >= 0]
    return text[s:min(ends) if ends else len(text)]


def _names(seg):
    out = {n for n in NAME_TICK.findall(seg)
           if not PLACEHOLDER_NAME.match(n) and not NOT_NAME_SHAPE.search(n)}
    out |= {n for n in NAME_CAP.findall(seg)
            if n not in NOT_PRODUCT and n not in HOOK_EVENTS
            and not n.isupper() and not PLACEHOLDER_NAME.match(n)}
    return out


def _texts_and_tools(turn):
    """返回(本轮我说的文本, 本轮跑过的命令/参数拼成的一大坨)"""
    said, ran = [], []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content")
        if isinstance(content, str):
            said.append(content)
            continue
        for c in content or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                ran.append(json.dumps(c.get("input") or {}, ensure_ascii=False))
    return "\n".join(said), "\n".join(ran)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return 0
    if self_blocked_this_turn(GATE):
        return 0

    try:
        # 2026-09-06:走共享的 load_transcript_tail —— 它内含【回合拦截预算】,
        #   本轮被 Stop 闸拽回次数到上限就返回空列表 => 本闸自然放行,防无限 loop。
        #   实测:55 道 Stop 闸只有 64% 受管,自己 open() 读的 12 道完全绕过,
        #   而本闸就在那 12 道里(Frank:「触发了无限Loop的bug…think twice 然后阻塞」)。
        #   安全类闸在 _BUDGET_NEVER 白名单里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。
        from guard_common import load_transcript_tail as _ltt
        msgs = _ltt(tp)
    except Exception:
        return 0
    start = turn_start_index(msgs)
    turn = msgs[start:] if start >= 0 else msgs[-60:]

    said, ran = _texts_and_tools(turn)
    if not said:
        return 0

    # ⛔ 2026-09-06 补丁(真根因,不是"AppData 那一个例子"这个实例):
    #   VERDICT 正则不管这句话是【我在下判决】还是【我在举例/转述/解释这个词长什么样】,
    #   逐字匹配就算命中。实录:我写"一沾上"走不通"这种词就误拦"来解释上一个 bug,
    #   "走不通"三个字被引号夹着、明显是在【提到】这个词而非【使用】它做判决,
    #   闸照样把它当成了一次真判决。这是同一个病根的第二个实例(第一个是路径片段被当产品名),
    #   两次都是"字面命中,不管这段文字在【引用】还是在【断言】"。
    #   ⇒ 通用修法:被引号(中英文直引号/弯引号/「」『』)**紧贴前后**夹住的判决词,
    #     算"提到"不算"断言",跳过继续找下一个未加引号的命中。全部命中都被引号夹住才放行。
    QUOTE_BEFORE = set('"\'“‘「『')
    QUOTE_AFTER = set('"\'”’」』')

    def _is_quoted_mention(text, span):
        s, e = span
        before = text[s - 1] if s > 0 else ""
        after = text[e] if e < len(text) else ""
        return before in QUOTE_BEFORE and after in QUOTE_AFTER

    masked = QUOTED.sub(lambda m: " " * len(m.group(0)), said)   # 同长度抹掉,位置不变
    v, any_verdict, names = None, False, set()
    for cand in VERDICT.finditer(masked):
        if _is_quoted_mention(said, cand.span()):
            continue
        any_verdict = True
        got = _names(_sentence(said, cand.span()))        # 对象只在这一句里找
        if got:
            v = v or cand
            names |= got
    if not any_verdict:
        rc = _check_avoid(said, ran)   # 近亲形状:不判它不行,而是给自己找个不用它的理由
        if rc:
            return rc
        hook_log(GATE, "pass(no verdict)")
        return 0
    if not names:
        hook_log(GATE, "pass(no product name near verdict)")
        return 0

    # 本轮探测过的名字。两种探测各管一件事,**都没有才拦**:
    #   PROBE     = 问机器「它装没装」
    #   ECO_PROBE = 搜生态「它到底能干什么」(2026-09-05 形状 D 补:只有前者时,
    #               我探测出"没装"后照样拿一个自制脚本代表整个生态下了判决,闸放行了)
    # ⛔ 第一版我写成 `PROBE or ECO_PROBE`(任一满足即放行)——**逻辑正好反了**,
    #   回归当场抓到:那样"只探了装没装"照样放行,而那正是形状 D 的原样重演。
    #   正确语义:**搜生态(ECO_PROBE)是判决一个产品/平台时的必要条件**;
    #   PROBE(装没装)只在"判的是本机某个具体东西在不在"时才够用。
    #   ⇒ 保守取法:必须有 ECO_PROBE 才算"我了解它";光有 PROBE 不放行。
    unprobed = []
    for n in names:
        eco = False
        for line in ran.splitlines():
            if n.lower() in line.lower() and ECO_PROBE.search(line):
                eco = True
                break
        if not eco:
            unprobed.append(n)
    if not unprobed:
        hook_log(GATE, "pass(all probed) " + ",".join(sorted(names)))
        return 0

    self_blocked_this_turn(GATE, mark=True)
    # ⛔ 2026-09-07 补触发词:记分板实测这道闸 318 次开火【100% 无证据】⇒ 事后判不了对错。
    #   第三个参数传【命中的那句原话】,hook_log 自动包成 trig='...' 并打码(不用 import trig)。
    hook_log(GATE, "BLOCK verdict=%s unprobed=%s" % (v.group(0)[:24], ",".join(sorted(unprobed))),
             v.group(0))
    print(json.dumps({
        "decision": "block",
        "reason": (
            "⛔ 稻草人判决闸:你正在宣判【%s】,而判决对象 %s **本轮从没被探测过**。\n"
            "⛔ 实录(2026-09-05,Frank 原话「你连 obsidian 都没装,你测试什么鬼?」):\n"
            "   他问「能不能用 Obsidian 当记忆库」,我做了个对照表写着「B: Obsidian 知识库 = 0%%」,\n"
            "   据此宣布「这条路方向上不成立」。真相:**Obsidian 根本没装**,\n"
            "   我测的是另一个 .db 文件 + LIKE 字面匹配 —— 我自己搭了个劣质实现,贴上他方案的标签,\n"
            "   再拿它的 0 分去否决他的想法。**带表格的假实验,比直说「我觉得不行」更难被质疑。**\n"
            "现在二选一,别第三条:\n"
            "  (A) 先真的探测它 —— `py -3 ~/.claude/probe.py <名字>` 或 Test-Path/注册表/--version,\n"
            "      确认它存在、确认你测的就是它本身,再谈结论;\n"
            "  (B) 改口径 —— 明说「我测的是 X(不是 %s),所以这只能说明 X 不行,\n"
            "      说明不了他那个方案行不行」。\n"
            "⛔ 不许把「我造的替身考砸了」写成「你的方案不成立」。"
        ) % (v.group(0)[:24], "、".join(sorted(unprobed)[:3]), sorted(unprobed)[0]),
    }, ensure_ascii=False))
    return 0


def _check_avoid(said, ran):
    """④ 规避型理由:「因为会 X，所以不装/不换更强的那个」，而 X 从没量过。

    与主判据的分工:
      · VERDICT   = 我宣判【对方】不行  ("这条路不可行")
      · AVOID     = 我给【自己】找不去用的理由 ("怕影响别的项目,先不装")
    后者措辞完全不同、一个 VERDICT 词都不命中 ⇒ 必须单独一族,否则原样放行(2026-09-06 实证)。

    返回 0 表示不拦(交回主流程继续判 VERDICT);拦截时打印 block JSON 并返回 0。
    """
    r = AVOID_REASON.search(said)
    if not r:
        return 0
    # 理由和"不用它"的动作必须靠近,否则是两件不相干的事
    seg = said[max(0, r.start() - 150): r.end() + 150]
    a = AVOID_ACTION.search(seg)
    if not a:
        return 0
    if DEP_PROBE.search(ran) or DEP_PROBE.search(said):
        hook_log(GATE, "pass(avoid-reason but measured)")
        return 0

    self_blocked_this_turn(GATE, mark=True)
    hook_log(GATE, "BLOCK avoid reason=%s action=%s" % (r.group(0)[:24], a.group(0)[:12]),
             r.group(0))            # ⛔ 同上:留下命中的原话,否则这次拦截事后无法复核
    print(json.dumps({
        "decision": "block",
        "reason": (
            "⛔ 稻草人判决闸·规避型理由:你写了「%s」,据此【%s】更强的那个方案 ——\n"
            "   而本轮**没有任何一次依赖/版本查询**,那个理由是你编的。\n"
            "⛔ 实录(2026-09-06,Frank 原话「你没有给我 cuda 装 gpu 最好兼容版本,然后测试再跑?」):\n"
            "   我探测到 GPU 是好的,却写下「换 torch 会降级、可能拖累本机其它吃 torch 的项目」,\n"
            "   然后准备干等 2.5 小时让 CPU 跑。一查双重塌掉:\n"
            "     · `pip show torch` → Required-by **只有 sentence-transformers**(没有『别的项目』)\n"
            "     · `pip index versions` → CUDA 版是 **同一个版本号**(降级根本不存在)\n"
            "   代价:全量索引 6 分钟被我拖成 150 分钟,还把 1024 维的 SOTA 模型整条路判死。\n"
            "⛔ 更狠的一层:**我自己制造的约束,产生的结果不能当证据** ——\n"
            "   「不装 GPU ⇒ 慢 13 天 ⇒ 所以这模型不行」是循环论证。\n"
            "现在二选一:\n"
            "  (A) 先量 —— `pip show <包>`(看 Required-by) / `pip index versions`(看目标版本号)\n"
            "      / `npm ls <包>`;量完再决定装不装;\n"
            "  (B) 改口径 —— 明说「我没查过它到底影响谁,这只是我的猜测」,别写成结论。"
        ) % (r.group(0)[:28], a.group(0)[:8]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)      # fail-open:这道闸自己出错,绝不挡住正常收尾
