#!/usr/bin/env python3
"""vibe-spec 的机器强制层(双入口:PostToolUse 软提醒 + Stop 计量)。

2026-07-28 建。起因:Frank 问「speckit 是大佬写的,你的 vibe-spec 能比吗?该不该深度融合」
→ 逐项 diff spec-kit 真实文件后发现:vibe-spec 把【怎么写规格】七项机制全搬到了,
漏的全在【怎么验规格】。已给 SKILL.md 补上 ①稳定编号 V-### ②收尾覆盖率表 ③宪法冲突检查。
但 SKILL.md 是【文字】—— 形状P:纯文字注入 = 纸老虎,我每轮读到、每轮能绕过
(`prior-art-gate` 就是为治同一个病而生的先例)。本闸给它加机器层。

⛔ 先查现成(2026-07-28):
  · `rtmx`(★26,Go,Apache-2.0):CSV in Git + **自动跑测试**(pytest/npm/cargo)推导需求状态。
    文档明确**不支持非代码验收标准**;Frank 的验收单是【截图判对错】、没有测试框架 ⇒ 用不上。
  · `traceability-check`(Claude 插件) / `Requirement Trace Checker`(MCP):都要 spec 文件 +
    **带注解的测试代码**才能算覆盖 ⇒ 同一堵墙。
  · 三者都不是 hook 形态 —— 它们出报告,拦不住我。
  · ⇒ 判定:**只能自建**(形态=Claude Code hook;证据=截图而非测试用例)。

⛔ 档位:**首版一律 nudge,不 block** —— 这是 2026-07-28 当天钉死的新规矩。
   当天我刚跟 Frank 说完「新闸首版必然误伤(multi-option v1 被 33 样本打回 18 条)」,
   转头自己造 time-sanity-guard 就直接上了 block,**上线当轮就误伤自己**。
   ⇒ 本闸先跑软档,靠 `spec-coverage-guard.log` 攒真实误伤率,够数据再谈升级。

━━ 两个入口 ━━
 ① PostToolUse(Write/Edit):我【新建】一个够分量的实现文件,而本轮从没出现过 `V-###` 验收单
    → 注 additionalContext 提醒去起验收单。**只提醒,不阻塞**(通道照抄 ui-edit-guard)。
 ② Stop:我宣称做完(DONE_RE) + 本轮确实起过验收单(有 V-###) + 却没交覆盖率表
    → **只记日志**(Stop 没有非阻塞注入通道,强行 exit 2 就是 block,违反本闸档位)。
    这一路先纯计量,两周后拿日志决定要不要升。

安全:fail-open;只读;per-turn 只提醒一次;scratchpad/测试/hook 自身一律不碰。
回归:`test_spec_coverage.py`。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k): pass
try:
    from guard_common import strip_doc
except Exception:
    def strip_doc(t): return t
try:
    from guard_common import trig          # critic 中危8:日志要记【惹祸的原文】,不只记判决
except Exception:
    def trig(s, n=120): return (s or "")[:n]
try:
    from guard_common import load_transcript_tail
except Exception:
    def load_transcript_tail(*a, **k): return []
try:
    from guard_common import DONE_RE
except Exception:
    import re as _re
    DONE_RE = _re.compile(r"已生效|跑通了|已修好|做完了|完成了|搞定")

import sys, os, json, re, time   # ⛔ time:新鲜度判据要用;漏了会被下面的 except 吞掉 ⇒ 整道闸恒不开火

# 2026-07-28:判据统一到 guard_common(critic:两个闸各抄一份 = 补豁免只补一边)。
#   取不到就回退本文件下面那份 —— 共享失败绝不能让整道闸失效。
try:
    from guard_common import (SHARED_EXEMPT_PATH as _SHARED_EXEMPT,
                              SHARED_CODE_EXT as BUILD_EXT, SHARED_EXEMPT_HOOKS)
    # 本闸【额外】豁免 Superego 自己的 hooks(不该对自家闸要求截图验收单);
    # coherence 反过来要数它 —— 差异部分各自保留,共同部分走共享。
    EXEMPT_PATH = type("_X", (), {"search": staticmethod(
        lambda p: _SHARED_EXEMPT.search(p) or SHARED_EXEMPT_HOOKS.search(p))})
    _SHARED_OK = True
except Exception:
    _SHARED_OK = False


try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

NAME = "spec-coverage"
MIN_LINES = 40                      # 照 prior-art-gate:一次性小脚本不折腾

# ⛔ 2026-07-28 critic 抓到:原表只有代码扩展名,**漏掉 html/css/sql/ps1/sh** ——
#    而这道闸的整个理由就是"Frank 验收的是截图长什么样",页面文件恰恰是最该有验收单的那类。
if not _SHARED_OK:
    BUILD_EXT = re.compile(
    r"\.(py|mjs|cjs|js|jsx|ts|tsx|vue|svelte|go|rs|java|rb|php|html|htm|css|scss|sql|ps1|sh)$", re.I)
# 不碰:临时区 / 测试 / Superego 自身 / 依赖目录 / 机器生成物
# ⛔ critic 抓到的误伤:migrations、conftest、generated、vendor 都是正当新建、不需要截图验收单。
if not _SHARED_OK:
    EXEMPT_PATH = re.compile(
    r"scratchpad|[\\/]tmp[\\/]|[\\/]temp[\\/]|AppData[\\/]Local[\\/]Temp"
    r"|[\\/]test_|[\\/]tests?[\\/]|\.test\.|\.spec\.|_test\.|conftest\.py"
    r"|[\\/]migrations?[\\/]|[\\/]generated[\\/]|[\\/]vendor[\\/]|\.generated\."
    r"|[\\/]\.(?:claude|truthgate)[\\/]hooks[\\/]|node_modules|[\\/]\.git[\\/]|dist[\\/]|build[\\/]",  # 2026-09-27 新旧路径都认
    re.I,
)
# vibe-spec 的验收单编号:V-001
ACCEPT_ID = re.compile(r"\bV-\d{2,4}\b")
# ⛔ 覆盖率表的形态。critic 抓到原版两头都错:
#    D2「句尾写『覆盖率』三个字」= 零成本免检;D3「真贴了 V-001 ✅ shot.png 但没写『覆盖率』」= 做对了反被记。
#    ⇒ 改成认【逐条结论】或【带数字的分母】,不认光秃秃的"覆盖率"二字。
COVERAGE_SIG = re.compile(
    r"\|\s*V-\d{2,4}\s*\|"                      # 表格行
    r"|V-\d{2,4}[^\n]{0,40}(?:✅|❌|✔|✗|通过|未做|零覆盖)"   # 逐条带结论
    r"|覆盖率[^\n]{0,10}\d"                      # 覆盖率 + 数字
    r"|\b\d+\s*/\s*\d+\s*条"                     # 7/9 条
)


def turn_has_acceptance(turn_msgs):
    """本轮(我或用户)有没有出现过 V-### 验收单编号。解析不了 → 当作有(fail-open,不烦人)。"""
    try:
        for m in turn_msgs or []:
            for c in (m.get("message") or {}).get("content") or []:
                if isinstance(c, dict):
                    blob = c.get("text") or json.dumps(c.get("input") or {}, ensure_ascii=False)
                elif isinstance(c, str):
                    blob = c
                else:
                    continue
                if ACCEPT_ID.search(blob or ""):
                    return True
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    ti = c.get("input") or {}
                    if ACCEPT_ID.search(str(ti.get("content") or "")):
                        return True
    except Exception:
        return True
    return False


def needs_spec(fp, content, tool_name="Write"):
    """这次写入是不是【该先有验收单】的那种活。纯结构判据。

    ⛔⛔ 2026-07-28 外部 critic 抓到的【最高危】:原版有 `if os.path.exists(fp): return False`
       ——那行是从 `prior-art-gate` 抄的,而它是 **PreToolUse**(文件尚未写入);
       本闸是 **PostToolUse**(Write 已成功执行)⇒ 文件必然存在 ⇒ **本函数恒返回 False,
       整道闸从挂上到被发现一次都没开过火**(铁证:`spec-coverage.log` 当时根本不存在)。
       ⇒ 改用 tool_name 区分:Write=可能新建(该管);Edit=天然只改现有(不管)。
    """
    # ⛔⛔ 2026-09-07 补 Bash 盲区(形状 2026-09-07-C 第 4 处):
    #   tool_name=="Write" 这条【是修复不是病】(见上面那段病历),保留;
    #   但我用 Bash 跑脚本新建 .py 时 tool_name 是 Bash ⇒ 这道闸看不见。
    #   ⇒ 非 Edit/Write 路径改用【效果版】判据:这文件是不是【刚被创建】的。
    #     Windows 上 st_ctime = 创建时间,改内容不动它 —— 实测验过(2026-09-07):
    #     新建时 mtime-ctime=0.00s;2.5 秒后改内容,ctime 纹丝不动、只有 mtime 变。
    #   ⛔ 绝不退回 `os.path.exists`:那正是这道闸历史上"恒假、从没开过火"的死因。
    if tool_name == "Edit":                      # Edit 只改现有 ≠ 开新功能
        return False
    if tool_name != "Write":
        try:
            _st = os.stat(fp)
            _fresh = (time.time() - _st.st_ctime) < 90
            _born = (_st.st_mtime - _st.st_ctime) < 2.0
            if not (_fresh and _born):           # 不是刚创建的 ⇒ 只是改了现有,不管
                return False
        except Exception:
            return False
    if not fp or EXEMPT_PATH.search(fp):
        return False
    if not BUILD_EXT.search(fp):
        return False
    return (content or "").count("\n") + 1 >= MIN_LINES


def stop_missing_coverage(text):
    """Stop 侧:宣称做完 + 真走了验收单流程 + 没交覆盖率表 = 该记一笔。

    ⛔ critic 抓到同一个"描述 vs 执行"病根(镜头7):我只是【解释】验收单机制、
       举个例子写了「V-001 新用户打开看到登录页」,就被当成"走了验收单流程"。
       ⇒ 要求**至少两个不同编号**才算真在跑这套流程(举例通常只写一个)。
    """
    t = strip_doc(text or "")
    if not t or not DONE_RE.search(t):
        return False
    if len(set(ACCEPT_ID.findall(t))) < 2:       # 没真走验收单流程(或只是举例)→ 不管
        return False
    return not COVERAGE_SIG.search(t)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    try:
        # ── 入口②:Stop(只计量,绝不 block)
        if "last_assistant_message" in data and "tool_name" not in data:
            msg = data.get("last_assistant_message") or ""
            if stop_missing_coverage(msg):
                ids = sorted(set(ACCEPT_ID.findall(strip_doc(msg))))
                hook_log(NAME, "METRIC stop: claimed-done, no coverage table",
                         trig(f"ids={ids} | {msg[:120]}", 160))
            sys.exit(0)

        # ── 入口①:PostToolUse(软提醒)
        tool = data.get("tool_name")
        if tool not in ("Write", "Edit"):
            sys.exit(0)
        ti = data.get("tool_input") or {}
        fp = str(ti.get("file_path") or "")
        content = str(ti.get("content") or ti.get("new_string") or "")
        if not needs_spec(fp, content, tool):
            sys.exit(0)

        turn = load_transcript_tail(data.get("transcript_path"))
        if turn_has_acceptance(turn):
            sys.exit(0)                          # 已经有验收单 → 安静

        # ⛔ 原本这里有一段 per-turn 去重,critic 实测它【根本没生效】(mark=True 只在写不进去时
        #    返 True,从不查已有标记)。修法不是"修好它",而是**整段删掉**:
        #    PostToolUse 没有 stop_hook_active 之类的轮次信号,做不出真正的"本轮一次";
        #    而 guard_common 的注释早已警告——nudge 档硬套这个标记会退化成
        #    「每 15 分钟只提醒一次」,比设计意图弱一个量级、且不会报错。
        #    重复提醒的代价只是多一段 additionalContext(无害);哑掉才是真危害。
        hook_log(NAME, "NUDGE no acceptance list before building",
                 trig(f"{os.path.basename(fp)} | {content.splitlines()[0] if content else ''}", 100))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"📋 vibe-spec 提醒:你刚新建了 {os.path.basename(fp)}"
                f"（{content.count(chr(10))+1} 行实现），但本轮**没有任何 `V-###` 验收单**。\n"
                "Frank 是零编程 vibe coder —— 他验收的不是代码、是【截图长什么样】。"
                "没有验收单 = 收尾时没有分母，你只能说\"我扫了一遍\"，那是纸老虎。\n"
                "现在补一张（skill `vibe-spec` ② 有格式）：每条带稳定编号、写成能截图判对错的话，"
                "例 `V-001 ✅ 新用户打开 → 3秒内看到登录页`；我猜的默认全列进「🔧 我替你定了这些」。\n"
                "⛔ 别问他要不要 —— 自动起草完摆给他看，他说「对」就开干（授权即执行）。"
            ),
        }}, ensure_ascii=False))
        sys.exit(0)
    except Exception:
        sys.exit(0)                              # fail-open


if __name__ == "__main__":
    main()
