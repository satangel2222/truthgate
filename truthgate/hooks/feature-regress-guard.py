#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""feature-regress-guard — 拦【新写一个文件替代旧的,静默丢掉旧功能】。

⛔ 来历(2026-08-14,Frank:「为何你把之前那么好用的筛选搞没了」):
   我给他做过一张可交互清单 `mklist.py`,6 个筛子(搜索/星数/时间/领域相关/出片方向/剔噪音)。
   后来要加"六个宇宙",我**新写了 `mkuniverse.py`**(而不是在旧的上面改),
   从零把 HTML/CSS/JS 重敲一遍 ⇒ 只剩 2 个筛子,**fresh/dom/pro/noi 四个静默消失**。
   我验了新功能(点宇宙按钮数字都对),**却从没把新旧的能力清单对一遍**。

⛔ 机制(可迁移,不是这一次的偶然):
   **重写 = 只保留我当下想得起来的;改旧文件 = 旧的自动保留。**
   从零写时我脑子里只有"这次的新需求",旧功能不在我脑子里 —— 它在旧文件里。
   ⇒ 所以这不是记性问题,是流程问题:**新写替代旧的,必须先 diff 能力清单**。

⛔ 现有闸都不管这个(实测):spec-coverage 管规格验收、media-regression 管媒体、
   regress-on-guard-edit 管"改闸就跑测试"。WebSearch 找到的 VART/RESTORE/视觉回归
   全都要跑测试或比截图,和"新旧文件能力清单比对"不是一回事 ⇒ 只能自建。

判据(结构性比对,不靠关键词,避免"词表抓字面"那类误伤):
  ① 本轮要 Write 一个【新文件】(尚不存在)
  ② 同目录存在【同类旧文件】(同后缀 + 文件名相似度高)
  ③ 从两边各抽"能力标识符"(HTML id/name、CLI 参数、def 函数名)
  ④ **旧的有、新的没有** 的标识符 >= 2 个 ⇒ ask,并把丢掉的逐个列出来
安全:任何异常一律放行(fail-open);找不到同类旧文件就放行。
"""
# ⛔ 2026-09-10 接进账本(Frank:「为何 superego 没拦你还是没开火?」):本闸此前从没 import guard_common,
#   于是它每次开火 hook-stats.jsonl 里都是 0 条 ⇒ 记分板看不见它、nudge-escalation-gate 也数不到它
#   (同日扫出 10 道同病,ui-edit-guard 一天响 8 次账本 0 条)。guard_common 一 import 就自动观测 stdout、
#   退出时按内容判 nudge/block/allow,本闸逻辑一字不改。自包含写法:不依赖本文件已有的 import。
try:
    import os as _gc_os, sys as _gc_sys
    _gc_sys.path.insert(0, _gc_os.path.dirname(_gc_os.path.abspath(__file__)))
    import guard_common  # noqa: F401  接线即记账;失败不影响本闸(fail-open)
except Exception:
    pass

import difflib
import json
import os
import re
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "feature-regress-guard.log"
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".sh", ".ps1", ".html"}

# 能力标识符:用户能感知到的"功能点"通常以这些形式出现
IDENT_PATS = [
    re.compile(r"""id=['"]([A-Za-z_][\w-]{1,24})['"]"""),          # HTML 控件 id
    re.compile(r"""name=['"]([A-Za-z_][\w-]{1,24})['"]"""),        # 表单 name
    re.compile(r"""add_argument\(\s*['"]--([\w-]{2,24})['"]"""),   # CLI 参数
    re.compile(r"""^\s*def\s+([a-z_][\w]{2,30})\s*\(""", re.M),    # 函数名
    re.compile(r"""data-([a-z][\w-]{1,20})=""" ),                  # data-* 钩子
]
# 噪音标识符:框架/样板产生的,不代表功能
NOISE_IDENT = {"main", "init", "self", "args", "kwargs", "data", "value", "type",
               "content", "text", "root", "app", "body", "html", "head", "script",
               "style", "div", "span", "tb", "cnt", "log", "run", "get", "set"}


def _log(m):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def idents(text):
    out = set()
    for p in IDENT_PATS:
        for m in p.findall(text or ""):
            s = m if isinstance(m, str) else m[0]
            if s and s.lower() not in NOISE_IDENT and len(s) >= 2:
                out.add(s)
    return out


def find_sibling(fp):
    """同目录里最像的【同类旧文件】:同后缀 + 文件名相似度 >= 0.45。"""
    d = os.path.dirname(fp) or "."
    base = os.path.basename(fp)
    ext = os.path.splitext(base)[1].lower()
    if ext not in CODE_EXT or not os.path.isdir(d):
        return None
    best, score = None, 0.0
    for f in os.listdir(d):
        if f == base or os.path.splitext(f)[1].lower() != ext:
            continue
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            continue
        r = difflib.SequenceMatcher(None, base.lower(), f.lower()).ratio()
        if r > score:
            best, score = p, r
    return best if score >= 0.45 else None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Write":
        return 0
    inp = data.get("tool_input") or {}
    fp = inp.get("file_path") or ""
    content = inp.get("content") or ""
    if not fp or os.path.exists(fp):        # 只管【新建】,改已有文件不归本闸
        _log("pass(not new): %s" % os.path.basename(fp))
        return 0
    if os.path.splitext(fp)[1].lower() not in CODE_EXT or content.count("\n") < 30:
        return 0

    old_path = find_sibling(fp)
    if not old_path:
        _log("pass(no sibling): %s" % os.path.basename(fp))
        return 0
    try:
        old_text = open(old_path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return 0

    old_ids, new_ids = idents(old_text), idents(content)
    lost = sorted(old_ids - new_ids)
    if len(lost) < 2:
        _log("pass(lost<2): %s vs %s" % (os.path.basename(fp), os.path.basename(old_path)))
        return 0
    # ⛔ 2026-09-10 一天误配两次(mystic_scan.py vs main.py / test_guard_common_wiring.py vs guard_common.py):
    #   「文件名像」只能挑候选,挑不出「是不是重写」。真重写会【继承】旧文件的一部分标识符
    #   (08-14 那次:6 个筛子留了 2 个丢了 4 个);而无关的新文件和旧文件几乎零交集。
    #   ⇒ 看【继承率】= 共享 / 旧文件标识符数,不看绝对数。第一版写成「共享 < 3 个」,
    #     立刻把原有测试里两个小文件的真重写(shared=1/3、2/4)放了 —— 绝对数随文件大小变,那是旋钮。
    #     无关文件继承率 ≈ 0(mystic_scan 对 main.py 几百个里共享 1 个);真重写哪怕丢一半也 ≥ 30%。
    #     取 10%:两个分布之间隔 3 倍,不是在旋钮上滑。
    shared = old_ids & new_ids
    inherit = len(shared) / max(1, len(old_ids))
    if inherit < 0.10:
        _log("pass(unrelated,inherit=%d/%d): %s vs %s" % (len(shared), len(old_ids),
                                                          os.path.basename(fp), os.path.basename(old_path)))
        return 0

    # 2026-09-08 ask -> deny 时同时加的逃生口(deny 没出口的话,误判一次就把 AI 彻底卡死)。
    # 要走这条:必须在新文件里写清【哪些能力是有意去掉的、为什么】,不是喊口号就放行。
    if "INTENTIONAL-REWRITE:" in content:
        _log("pass(INTENTIONAL-REWRITE declared): %s" % os.path.basename(fp))
        return 0

    _log("DENY %s vs %s lost=%s" % (os.path.basename(fp), os.path.basename(old_path), lost))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "⛔ 功能回退闸:你在新建 `%s`,而同目录已有很像的 `%s` —— "
                "看起来是**新写一个替代旧的**。\n"
                "⛔ 旧文件里有、你这份里【没有】的能力标识符 %d 个：%s\n"
                "  实录(2026-08-14,Frank:「为何你把之前那么好用的筛选搞没了」):我给他做的可交互清单\n"
                "  有 6 个筛子,加新功能时我从零重写了一份 ⇒ **fresh/dom/pro/noi 四个静默消失**,\n"
                "  而我只验了新功能、从没把新旧能力清单对一遍。\n"
                "⛔ 机制:**重写 = 只保留我当下想得起来的;改旧文件 = 旧的自动保留。**\n"
                "现在二选一:\n"
                "  ① **改旧文件**(Edit `%s`)而不是新写 —— 默认更安全;\n"
                "  ② 确要新写:先逐个确认上面那些标识符是【有意去掉】还是【忘了带】,"
                "把有意去掉的理由写进新文件注释,再继续。"
            ) % (os.path.basename(fp), os.path.basename(old_path),
                 len(lost), "、".join(lost[:12]) + ("…" if len(lost) > 12 else ""),
                 os.path.basename(old_path))
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
