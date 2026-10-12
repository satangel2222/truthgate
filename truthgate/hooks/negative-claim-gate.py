#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""negative-claim-gate — 往文件里写「某系统不提供 / 拿不到 / 都不带 / 做不到」，
同一句里却没有「测了多少」时，写入前拦下。

来历（同一个形状，三次都是【写进了交付物】）
  · 2026-08-19-G：证伪了一条路（某功能在云端跑不起来），就在代码注释里宣布
    「这是环境硬边界…只能靠…」—— 目标其实有另一条路（尾帧继承首帧）。
  · 2026-08-25：只拿当天 9 张同一类图测，就在代码注释 + 用户看得见的提示框里写
    「…三个接口和 PNG 元数据都不带当时的提示词」「…不提供当时的提示词」，
    提交说明里还写「⛔ 别再花时间猜」。2026-09-10 用户一问，三条路全通（PNG 里就内嵌着）。
  · 2026-09-10，修上面那件事的同一个会话里：只抽 2 个 mp4 就写下「mp4 实测没有、别白读」，
    全量一查 72 个里 27 个有 —— 连「实测」两个字都写了。
  ⇒ 光靠「记住」拦不住：写下它的那一刻我觉得自己是查过的。
  ⇒ 写进文件的阴性结论比聊天里说的更毒：下一个会话会把它当第一手事实读回来，
    用户也看得见。所以在【写进文件】这一步拦；聊天回复里的「我够不到」归 capability-boundary-gate。

判据（纯文本、客观；按【分句】判，不按行）
  一个分句里同时有：
    ① 阴性能力断言（不提供/不返回/不带/拿不到/做不到/无法获取/只能靠/硬边界/被剥掉/…里没有 …）
    ② 技术主语（大写缩写、驼峰/首字母大写的名字，或 接口/平台/官方/元数据/端点/环境/模型/上游 …；
       句子折行时往上多看两行；异常类名 ValueError 这种不算）
  且这个分句里没有【测了多少】的证据 → 拦。证据只认：分数（100/100）、百分比、
    「实测/抽/查了/试了 + N 个」、「N 个…里 M 个」、「N 个…全」。
    ⛔ 光有数字不算：8-25 那句「三个接口和 PNG 元数据都不带」里的「三个」是在数主语，
       不是在数样本 —— 第一版把它当证据，那句真错话被原样放过去了（自测当场抓到）。
  「别再查 / 别白读 / 死心」这类焊门语句：不管有没有技术主语都要证据，还必须写明范围
    （只测了… / 没测…）—— 8-25 那条写了「八个候选全 404」，有证据，但没写「只测了一类端点」，照样错。
  为什么按分句不按行：9-10 那句「…实测 311 张图里 75 张有（24%）；mp4 没有（…转码丢了）」，
    同一行里那个 311 张跟 mp4 毫无关系 —— 按行找证据，这句假话就被放过去了。
  放行：阴性词在「」“”『』里（在引用旧说法）；前后两行写着 假话/推翻/证伪/原本写/别再写 …（在纠错）。

不管：lessons.md（教训正文就是在引用错话，另有 lessons-write-gate）、测试文件、scratchpad、本闸自身；
      文本里写了 NEG-CLAIM-OK 的（确需原样保留时用，会留在文件里，看得见）；
      Edit 里原文就有、这次没新写的行。

⛔ 诚实边界：它只能逼我【把样本数和范围写出来】，判断不了样本有没有代表性
   （9 张同一类图算不算「全部」）。那一半要靠外审和用户追问 —— 它的作用是把前提摆到明面上，
   让读的人（包括下一个我）一眼看出这个结论有多窄。

自测：python negative-claim-gate.py --self-test
"""
import json
import os
import re
import sys

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import guard_common  # 记账 + 留触发原文
except Exception:
    guard_common = None

GATE = "negative-claim-gate"

NEG = re.compile(
    r"不提供|不返回|不带|不给|不暴露|不支持|不包含|不保留|拿不到|取不到|查不到|读不到|获取不到|做不到|办不到"
    r"|无法(?:获取|拿到|读取|读出|提取|得到|访问|实现|做到)|没法(?:拿|取|读|查|做)"
    r"|没有(?:接口|端点|办法|这个能力)|(?:里|中|上)(?:都|也|根本|全)?没有"
    r"|被剥掉|被剥离|剥掉了|转码丢了|只能(?:显示|靠|这样)|硬边界|能力边界|全\s*404|都\s*404"
    r"|(?:does|do)(?:n't| not) (?:provide|return|expose|include|support|keep|store|have|carry)"
    r"|\bhas no\b|\bno (?:api|endpoint|way to)\b"
    r"|\b(?:cannot|can't|unable to) (?:get|fetch|retrieve|access|read|extract)\b|\bstripped\b",
    re.I)
DOOR = re.compile(
    r"别再(?:花时间|查|试|猜|找|碰|浪费|读)|不用再(?:查|试|找)|不必再(?:查|试)|别白(?:读|查|试|费)"
    r"|死心|这条路走不通|放弃这条路|don't bother|no need to (?:check|try|retry)",
    re.I)
SUBJ = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{1,}(?![A-Za-z0-9_])"      # 缩写：API / PNG / TG
    r"|(?<![A-Za-z])[A-Z][a-z]+[A-Z][A-Za-z]*"                   # 驼峰名
    r"|(?<![A-Za-z])[A-Z][a-z]{2,}(?![A-Za-z])"                  # 首字母大写的名字
    r"|接口|平台|官方|服务端|服务器|上游|第三方|元数据|端点|环境|模型|云端|后台|返回值|字段|容器|mp4|png|webp|jpe?g")
# 代码里满地都是、却不是「某个外部系统」的大写词
_NOT_SUBJ = re.compile(r"(?:Error|Exception|Warning)$|^(?:True|False|None|Path|Image|Object|Array|String|Promise"
                       r"|Date|Math|Number|Boolean|TODO|FIXME|NOTE|OK)$")
_NUM = r"(?:\d+|[一二两三四五六七八九十百千]+)"
_UNIT = (r"\s*(?:个|张|条|次|份|篇|页|种|组|项|处|轮|样本|候选"
         r"|samples?|files?|items?|images?|cases?|requests?|calls?)")
EVID = re.compile(
    r"\d+\s*/\s*\d+"                                                              # 100/100
    r"|\d+(?:\.\d+)?\s*%"                                                         # 24%
    r"|(?:实测|测了|测过|抽查|抽了|抽|查了|查过|试了|试过|跑了|扫了|验了|全量)[^，。；;\n]{0,10}?" + _NUM + _UNIT
    + r"|" + _NUM + _UNIT + r"[^，。；;\n]{0,8}?(?:里|中)\s*" + _NUM               # 72 个 mp4 里 27 个
    + r"|" + _NUM + _UNIT + r"[^，。；;\n]{0,6}?全",                                # 8 个候选全 404
    re.I)
SCOPE = re.compile(r"只测|只查|只试|只抽|只拿|只用|只看了|仅测|仅查|没测|没查|没试|未测|未覆盖|范围|样本"
                   r"|only (?:tested|checked)|not (?:tested|checked)", re.I)
REFUTE = re.compile(r"假话|推翻|证伪|是错的|已作废|原本写|原来写|以前写|曾经写|旧版这里写|别再写|误判|错判")
QUOTED = re.compile(r"「[^」]*」|“[^”]*”|『[^』]*』")
STOPS = "；;。！!？?"


def _exempt(path):
    p = str(path or "").replace(chr(92), "/").lower()
    # 2026-09-27(考卷 c015 / c023):故障注入测试(faults/ 目录、fault_*.js)也是测试文件
    return (p.endswith("lessons.md") or "/scratchpad/" in p or "/tests/" in p or "/test/" in p or "/faults/" in p
            or re.search(r"/test_[^/]*$|_test\.[a-z0-9]+$|\.test\.[a-z0-9]+$|/fault_[^/]*$", p) is not None
            or p.endswith("negative-claim-gate.py"))


# 2026-09-27(考卷 c028 / c029 / c066 / c067):代码文件里【字符串里】的字是数据 —— 测试用例名、给用户看的提示、
#   正则词表、拦截文案 —— 不是写代码的人下的结论。注释、文档里的照查(第一章真抓到的 c002 / c004 / c010 / c022 都在注释里)。
_CODE_FILE = re.compile(r"\.(?:py|js|mjs|cjs|ts|tsx|jsx|go|rb|java|cs|rs|php)$", re.I)
_STR_LIT = re.compile(r"(?:[rbfuRBFU]{0,2})(?:\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)")


def _blank_strings(text):
    """把字符串字面量换成同样长度的空格(行号、位置不变);三引号的 docstring 除外 —— 那是在讲代码,照查。"""
    def sub(m):
        s = m.group(0)
        if s.lstrip("rbfuRBFU").startswith(('"""', "'''")):
            return s
        return "".join(ch if ch == "\n" else " " for ch in s)
    return _STR_LIT.sub(sub, text)


def _has_subject(text):
    return any(not _NOT_SUBJ.search(m.group(0)) for m in SUBJ.finditer(text))


def _clause(text, pos):
    """pos 所在的分句（逗号不算断句 —— 「…端点，八个候选全 404」是一句话）。"""
    b = max(text.rfind(c, 0, pos) for c in STOPS) + 1
    ends = [j for j in (text.find(c, pos) for c in STOPS) if j != -1]
    return text[b:min(ends) if ends else len(text)]


def _hits(lines, i):
    """第 i 行里要问证据的那几处：返回 [(断言原文, 是否焊门, 所在分句)]。"""
    line = QUOTED.sub("", lines[i])           # 「」里的是在引用，不是在断言
    out = [(m.group(0), False) for m in NEG.finditer(line)] + [(m.group(0), True) for m in DOOR.finditer(line)]
    if not out:
        return []
    top = max(0, i - 2)
    window = chr(10).join(QUOTED.sub("", ln) for ln in lines[top:i + 2])
    base = sum(len(QUOTED.sub("", ln)) + 1 for ln in lines[top:i])
    return [(w, door, _clause(window, base + line.find(w))) for w, door in out]


def check(path, new_text, old_text=""):
    """返回拦截消息；放行返回 None。"""
    if not new_text or _exempt(path) or "NEG-CLAIM-OK" in new_text:
        return None
    if _CODE_FILE.search(str(path or "")):
        new_text, old_text = _blank_strings(new_text), _blank_strings(old_text or "")
    old = {ln.strip() for ln in (old_text or "").splitlines() if ln.strip()}
    lines = new_text.splitlines()
    for i, raw in enumerate(lines):
        if not raw.strip() or raw.strip() in old:
            continue
        for word, door, clause in _hits(lines, i):
            if REFUTE.search(chr(10).join(lines[max(0, i - 2):i + 3])):
                continue
            if not door and not _has_subject(clause):
                continue                      # 没有技术主语的「不支持」多半是产品文案/报错语
            if not EVID.search(clause):
                return _msg(path, raw.strip(), word, door)
            if door and not SCOPE.search(clause):
                return _msg(path, raw.strip(), word, door, scope_only=True)
    return None


def _msg(path, line, word, door, scope_only=False):
    need = ("写明范围（只测了什么、没测什么）" if scope_only
            else "「测了多少」（100/100、24%、实测 72 个里 27 个）" + ("，还要写明范围（只测了什么、没测什么）" if door else ""))
    return (
        "[X] 阴性断言闸：你正要往 %s 写一句「做不到 / 不提供 / 拿不到」类的结论（命中「%s」）：\n"
        "      %s\n"
        "    同一句里没有%s。\n\n"
        "⛔ 这个形状写进文件已经 3 次，每次写的时候我都觉得自己查过：\n"
        "   · 2026-08-25 只测当天 9 张同一类图，就写「三个接口和 PNG 元数据都不带提示词」→ 其实 PNG 里就嵌着\n"
        "   · 2026-09-10 只抽 2 个 mp4 就写「mp4 实测没有、别白读」→ 全量 72 个里 27 个有（写了「实测」也没用）\n"
        "   · 2026-08-19-G 一条路不通就写「这是环境硬边界，只能靠…」→ 目标另有一条路\n"
        "   写进文件的阴性结论会被下一个会话当第一手事实读回来，用户也看得见。\n\n"
        "三选一：\n"
        "  (1) 真去测，把测了多少写进同一句：「实测 72 个里 27 个有」「8 个候选全 404（只测了任务详情这一类端点）」\n"
        "  (2) 改成有范围的说法：「只测了 X，没测 Y」—— 别把一条路走不通写成目标做不到\n"
        "  (3) 你是在引用/纠正旧说法：放进「」里，或前后两行写明「假话/推翻/原本写」；确需原样保留写 NEG-CLAIM-OK\n"
    ) % (os.path.basename(str(path or "?")), word, line[:160], need)


def _payloads(data):
    ti = data.get("tool_input") or {}
    tool = data.get("tool_name")
    path = ti.get("file_path") or ti.get("path") or ""
    if tool == "Write":
        # 整份重写一个已存在的文件时，只判【这次新写的行】—— 外审实测：拿空串当原文，
        # 重写现有文件就得把每一行旧内容重判一遍(42 个项目文件里 19 个会被拦)
        old = ""
        try:
            if path and os.path.exists(path):
                old = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            old = ""
        yield path, ti.get("content") or "", old
    elif tool == "Edit":
        yield path, ti.get("new_string") or "", ti.get("old_string") or ""
    elif tool == "MultiEdit":
        for e in ti.get("edits") or []:
            yield path, e.get("new_string") or "", e.get("old_string") or ""


def self_test():
    ok = [True]
    nl = chr(10)

    def t(name, text, want_block, path="D:/proj/app/static/index.html", old=""):
        got = check(path, text, old) is not None
        if got != want_block:
            ok[0] = False
        print("  [%s] %-34s -> %s" % ("PASS" if got == want_block else "FAIL", name, "block" if got else "allow"))

    # ── 真实写进文件的错话（逐字）——必须拦 ──
    t("8-25 注释(折行,三个=数主语)",
      "    // RH 官网跑的图（历史同步搬回来的）src 里只有工作流名字 —— RH 三个接口和 PNG 元数据" + nl
      + "    // 都不带当时的提示词，所以那批只能显示「没留提示词」，不能装作有。", True)
    t("8-25 同句单行版", "RH 三个接口和 PNG 元数据都不带当时的提示词。", True, path="D:/proj/a.md")
    t("8-25 卡片提示框",
      "          box.title = '这张是在 RunningHub 官网跑的，本站只把成品同步了回来，'" + nl
      + "            + 'RH 不提供当时的提示词。改用本站创作台跑，提示词会自动跟着图存下来。';", True)
    t("9-10 docstring(同行有不相干数字)",
      "                离线、免费、零 API。实测 311 张图里 75 张有（24%）；mp4 没有（RH 转码丢了）。", True,
      path="D:/proj/prompt_recover.py")
    t("9-10 焊门(写了实测没数字)",
      '    """图片文件（路径或字节）里 ComfyUI 写的 `prompt`。mp4 实测没有，别白读。', True,
      path="D:/proj/prompt_recover.py")
    t("8-19-G 硬边界",
      "# 这是环境硬边界，不是配置口味。跨段一致性在本环境只能靠 global.refs + global.prompt。", True,
      path="D:/proj/director/patches.py")
    t("8-25 焊门(有证据没范围)",
      "⛔ 别再花时间猜 RH 的任务详情端点，八个候选全 404，端点表来自它自己的前端 bundle。", True,
      path="D:/proj/CLAUDE.md")
    t("证据在下一句(不同分句)", "RH 不提供当时的提示词。实测 9 张。", True, path="D:/proj/a.md")

    # ── 该放行的 ──
    t("纠错句(引用+推翻)",
      "          // ⛔ 这里原本写「RH 不提供当时的提示词」——假话，2026-09-10 实测推翻：", False)
    t("只靠引号的引用(附近没反驳词)", "卡片上挂着「RH 不提供当时的提示词」这句提示。", False)
    t("纠错段落第三行(推翻在两行前)",
      "// ⛔ 这里原本写「X」——假话，2026-09-10 实测推翻：" + nl + "// RH 历史每条都带 workflowId。" + nl
      + "// 现在拿不到只剩下面这几个真原因，别再替 RH 背一个不存在的限制。", False)
    t("正面陈述", "          // RH 历史每条都带 workflowId，PNG 文件里还内嵌着当时那次的完整节点参数。", False)
    t("带样本数(分数)", "# RH 的 history 接口不返回任务输入（实测 100/100 条）", False, path="D:/proj/a.py")
    t("带样本数(N 个里 M 个)", "# 本地 72 个 mp4 里 27 个有，其余 45 个的容器标签里没有节点图", False, path="D:/proj/a.py")
    t("焊门+证据+范围",
      "⛔ 别再花时间猜任务详情端点：只测了 8 个候选、全 404，没测工作流节点那条路", False,
      path="D:/proj/a.md")
    t("报错文案(异常类名不算主语)", '        raise ValueError("不支持的格式")', False, path="D:/proj/a.py")
    t("产品文案", "本站不提供下载", False, path="D:/proj/a.md")
    t("原文就有(没新写)", "RH 不提供当时的提示词" + nl + "# 新加一行", False,
      path="D:/proj/a.py", old="RH 不提供当时的提示词")
    t("lessons.md 不管", "RH 不提供当时的提示词", False, path="C:/Users/x/.claude/lessons.md")
    t("测试文件不管", "RH 不提供当时的提示词", False, path="D:/proj/tests/test_x.py")
    t("NEG-CLAIM-OK", "RH 不提供当时的提示词  # NEG-CLAIM-OK 引用原话", False, path="D:/proj/a.md")

    print(nl + ("全绿" if ok[0] else "有 FAIL"))
    return 0 if ok[0] else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)                               # fail-open：解析不了就放行
    try:
        for path, new, old in _payloads(data):
            msg = check(path, new, old)
            if msg:
                if guard_common is not None:
                    try:
                        guard_common.hook_log(GATE, "BLOCK " + os.path.basename(str(path)), ctx=msg.split(chr(10))[1])
                    except Exception:
                        pass
                sys.stderr.buffer.write(msg.encode("utf-8"))
                sys.stderr.flush()
                sys.exit(2)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
