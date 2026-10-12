#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PostToolUse(Write|Edit) 元闸:gate-generality-gate
监督【我建的闸是不是全局通用规则,而不是头疼医头针对单一事件】。

Frank 2026-09-09 钉死:「你建立的是专属针对这个事件的 gate 你就错了,我要建立的是全局通用规则……
每次你建立 gate 的时候都必须往这个方向,而不是针对单独事件…… 这个监督你建立对的 gate 的 gate 必须也做。」

病根 = 元根因 2026-08-20【实例思维】的又一次发作:我建防御时只防眼前那一个实例(硬编码项目名/文件清单/端口),
换个无关项目就失效。postmortem-to-guard 的 ⑤ 早写了这条自检(「换到另一个无关项目还管用吗?不管用=只记了死例子」),
但那是【软规则】,想不起来就没执行 → 上真闸,在我建闸的当下逼我答。

⛔ 它自己必须是【通用】的:按【模式】触发(不锁死任何项目/文件名),写在全局 hooks/。这就是它示范的方向。

⛔ 功能回退闸说明:本闸【故意不依赖 guard_common】(不用 hook_log/turn_start_index/self_blocked_this_turn/
   strip_doc/trig 那套)—— 它是极简 PostToolUse 独立闸,只读 stdin + 正则 + 自带 _log,零依赖让 fail-open 更稳
   (guard_common 挂了也波及不到它)。那些标识符属于 Stop 闸(如 false-done-gate)的 turn 追踪需求,本闸
   是 PostToolUse、当下即判、用不上,不是漏带。

触发(全满足才 nudge 一次):
  ① 本次 Write/Edit 的目标是【闸/钩子/检查】类工件:
     路径含 /hooks/ 或以 -gate.py/-guard.py 结尾,或内容新增 `def check_*(`(doctor 检查),或是明显的 gate 测试;
  ② 内容里有【单一实例硬编码】信号:绝对盘符项目路径 / ≥3 个四位端口 / ≥3 个具体数据文件名清单;
  ③ 没有【通用化意识】标记:既没参数化(argv/environ/入参喂变化的数据),文本也没说明"本就项目特有,因为…"。

设计:fail-open(任何异常放行) · 只 nudge 不硬拦(建的当下提醒,不阻断你继续) · 每次留日志。
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

import sys
import os
import json
import re

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate-generality-gate.log")


def _log(msg):
    try:
        import time
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ── 判据(全按【模式】,不含任何具体项目/文件名 —— 元闸自己必须通用)──────────────
GATE_PATH = re.compile(r"[\\/]hooks[\\/].*\.py$|[-_](gate|guard)\.py$", re.I)
CHECK_FN = re.compile(r"\bdef\s+check_[a-z0-9_]+\s*\(")            # doctor 风格检查函数
GATE_TESTNAME = re.compile(r"test_.*(gate|guard|intact|manifest|corrupt)", re.I)

ABS_PROJ_PATH = re.compile(r"['\"][a-zA-Z]:[\\/][^'\"]{2,}['\"]")   # 硬编码绝对盘符项目路径
PORTS = re.compile(r"\b(?:8[0-9]{3}|3[0-9]{3}|9[0-9]{3})\b")        # 四位服务端口
DATA_FILE = re.compile(r"['\"][\w.-]+\.(?:json|ps1|jsonl|db|csv|cmd)['\"]", re.I)

GENERAL_MARK = re.compile(
    r"sys\.argv|os\.environ|argparse|add_argument"
    r"|def\s+\w+\s*\([^)]*\b(?:path|dir|root|proj|target|manifest|cfg|config)\b"
    r"|参数化|可迁移|全局通用|换.{0,4}项目.{0,6}(还|仍|也)|项目特有.{0,10}因为|by nature|per-project by design",
    re.I)


def _payload_of(tool_input):
    """把 Write 的 content / Edit 的 new_string / MultiEdit 的所有 new_string 拼起来。"""
    if not isinstance(tool_input, dict):
        return "", ""
    fp = str(tool_input.get("file_path") or tool_input.get("path") or "")
    parts = []
    if tool_input.get("content"):
        parts.append(str(tool_input["content"]))
    if tool_input.get("new_string"):
        parts.append(str(tool_input["new_string"]))
    for e in (tool_input.get("edits") or []):
        if isinstance(e, dict) and e.get("new_string"):
            parts.append(str(e["new_string"]))
    return fp, "\n".join(parts)


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return  # fail-open
    tool = data.get("tool_name") or ""
    if tool not in ("Write", "Edit", "MultiEdit"):
        return
    fp, body = _payload_of(data.get("tool_input") or {})
    if not body:
        return

    # 排除自留区:scratchpad / tmp / .bak / 本元闸自己
    if re.search(r"scratchpad|[\\/]te?mp[\\/]|\.bak|gate-generality-gate", fp, re.I):
        return

    # ① 是不是【闸/检查】类工件
    is_gate = bool(GATE_PATH.search(fp) or CHECK_FN.search(body)
                   or (GATE_TESTNAME.search(fp or "") and re.search(r"check_|gate|guard", body, re.I)))
    if not is_gate:
        return

    # ② 单一实例硬编码信号
    signals = []
    if ABS_PROJ_PATH.search(body):
        signals.append("硬编码了绝对盘符项目路径")
    if len(set(PORTS.findall(body))) >= 3:
        signals.append("硬编码了 %d 个具体端口" % len(set(PORTS.findall(body))))
    if len(set(m.group(0) for m in DATA_FILE.finditer(body))) >= 3:
        signals.append("硬编码了一串具体数据文件名")
    if not signals:
        return

    # ③ 有没有通用化意识(参数化 / 明说本就项目特有)
    if GENERAL_MARK.search(body):
        return

    # 命中:在【全局 hooks】里建反而是对的方向;但只要硬编码单一实例仍值得提醒
    scope = "全局 hooks" if re.search(r"[\\/]\.(?:claude|truthgate)[\\/]hooks[\\/]", fp, re.I) else "某个项目内"  # 2026-09-27 新旧路径都认
    _log("FIRE %s | %s | signals=%s" % (tool, fp, signals))
    msg = (
        "\u26d4 \u5143\u95f8\u00b7gate-generality:\u4f60\u521a\u5728\u3010" + scope + "\u3011\u5efa/\u6539\u4e86\u4e00\u9053\u95f8,"
        "\u800c\u5b83\u9501\u6b7b\u4e86\u5355\u4e00\u5b9e\u4f8b(" + "\u3001".join(signals) + "),\u6ca1\u53c2\u6570\u5316\u3002\n"
        "Frank \u81f3\u9ad8\u94c1\u5f8b:\u95f8\u8981\u5efa\u6210\u3010\u5168\u5c40\u901a\u7528\u89c4\u5219\u3011,\u4e0d\u662f\u3010\u5934\u75bc\u533b\u5934\u9488\u5bf9\u5355\u4e00\u4e8b\u4ef6\u3011\u3002\u73b0\u5728\u7b54\u4e09\u6761:\n"
        "  \u2460 \u8fd9\u9053\u95f8\u9632\u7684\u3010\u4e00\u822c\u5f62\u72b6\u3011\u662f\u4ec0\u4e48?\u6362\u4e2a\u5b8c\u5168\u65e0\u5173\u7684\u9879\u76ee\u8fd8\u6210\u7acb\u5417?\n"
        "  \u2461 \u6210\u7acb\u2192\u5b83\u8be5\u5728\u3010\u5168\u5c40 ~/.claude/hooks \u6216 bin\u3011,\u4e0d\u662f\u9501\u5728\u8fd9\u4e00\u4e2a\u9879\u76ee;\n"
        "  \u2462 \u5b83\u662f\u3010\u53c2\u6570\u5316/\u53ef\u8fc1\u79fb\u3011\u7684(\u53d6\u8def\u5f84/\u6e05\u5355/\u7aef\u53e3\u5f53\u53c2\u6570),\u8fd8\u662f\u786c\u7f16\u7801\u6b7b\u4e86\u8fd9\u4e00\u4e2a\u5b9e\u4f8b?\n"
        "\u2192 \u771f\u53ea\u80fd\u9879\u76ee\u7279\u6709(\u5982\u670d\u52a1\u7aef\u53e3\u6e05\u5355)\u2192\u628a\u3010\u673a\u5236\u3011\u62bd\u6210\u5168\u5c40\u5de5\u5177,\u3010\u6570\u636e\u3011\u7559\u9879\u76ee;\u5e76\u5728\u4ee3\u7801\u91cc\u4e00\u53e5\u8bdd\u5199\u660e\u4e3a\u4f55\u672c\u5c31\u9879\u76ee\u7279\u6709\u3002"
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": msg}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log("ERR %r" % e)  # fail-open
