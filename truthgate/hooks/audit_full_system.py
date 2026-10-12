#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Superego 全系统体检 —— 一次扫出【每个脚本的真实状态】,给 Frank 看的那张表。

⛔ 存在的理由(Frank 2026-07-29:「整套 superego 重新系统结构级别因果链全部审查,
   给我一个完整的工作流,用户看得懂的整套设计逻辑」):
   此前我只能回答"某一道闸对不对",答不出"整套长什么样、谁在跑、谁是死的、谁在烦人"。
   `audit_paper_tigers.py` 只查"装了没生效";`superego-metrics.py` 只查活动量;
   `audit_false_blocks.py` 只查误拦 —— **没有一个给出全系统的结构视图**。

每个脚本报 6 个事实(全部来自第一手,不猜):
  ①挂载状态(在 settings.json 里吗 / 挂在哪个事件)  ②判据类型(关键字/语义/结构/外部调用)
  ③近 7 天真实拦截数  ④有没有回归测试  ⑤依赖 guard_common 的哪些函数  ⑥代码行数
跑法: python ~/.claude/hooks/audit_full_system.py [--md]
"""
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SETTINGS = os.path.join(ROOT, "settings.json")

# 判据类型:决定这道闸【怎么判断】,也决定它的假阳性率量级
#   语义 = 调分类器服务(准但依赖服务) · 关键字 = 正则匹配文本(行业实测假阳性 30~60%)
#   结构 = 看工具调用/文件存在等客观事实(最可靠) · 外部 = 调别的进程
KIND_PAT = [
    ("语义", re.compile(r"intent_margin|should_downgrade|should_escalate|7911")),
    ("结构", re.compile(r"tool_use|tool_name|transcript_path|os\.path\.exists|Write|Edit")),
    ("关键字", re.compile(r"re\.compile|re\.search|re\.match")),
]
GC_FUNCS = re.compile(r"\b(hook_log|trig|strip_doc|load_transcript_tail|turn_start_index|"
                      r"is_real_user_msg|self_blocked_this_turn|intent_margin|should_downgrade|"
                      r"should_escalate|DONE_RE|SUCCESS_RE)\b")


def mounted():
    """哪些脚本挂在 settings.json 里 → {脚本名: [事件,…]}"""
    try:
        d = json.load(open(SETTINGS, encoding="utf-8"))
    except Exception:
        return {}
    out = collections.defaultdict(list)
    for ev, arr in d.get("hooks", {}).items():
        for grp in arr:
            for h in grp.get("hooks", []):
                for m in re.findall(r"[\w.-]+\.(?:py|cjs|mjs|js|sh|ps1)", h.get("command", "")):
                    out[m].append(ev)
    return out


def blocks_7d():
    """近 7 天各闸真实拦截数(排除 skip/ALLOW/无日期,与 audit_false_blocks 同口径)"""
    days = {(dt.date.today() - dt.timedelta(days=i)).isoformat() for i in range(7)}
    cnt = collections.Counter()
    for fp in glob.glob(os.path.join(HERE, "*.log")):
        g = os.path.basename(fp)[:-4]
        try:
            lines = open(fp, encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            continue
        for ln in lines:
            if not re.match(r"^\d{4}-\d{2}-\d{2}\b", ln):
                continue
            if not any(d in ln for d in days):
                continue
            if re.search(r"skip\(|ALLOW", ln, re.I):
                continue
            if re.search(r"\bDENY\b|\bBLOCK\b|BLOCK\(", ln):
                cnt[g] += 1
    return cnt


def scan():
    mnt = mounted()
    blk = blocks_7d()
    tests = {os.path.basename(f) for f in glob.glob(os.path.join(HERE, "test_*.py"))}
    rows = []
    for fp in sorted(glob.glob(os.path.join(HERE, "*.py")) +
                     glob.glob(os.path.join(HERE, "*.cjs")) +
                     glob.glob(os.path.join(HERE, "*.mjs"))):
        base = os.path.basename(fp)
        if base.startswith("test_") or base in ("guard_common.py",):
            continue
        try:
            src = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        kind = "-"
        for name, pat in KIND_PAT:
            if pat.search(src):
                kind = name
                break
        stem = base.rsplit(".", 1)[0]
        has_test = any(stem.replace("-", "_") in t or stem in t for t in tests)
        deps = sorted(set(GC_FUNCS.findall(src)))
        rows.append({
            "name": base,
            "mount": mnt.get(base, []),
            "kind": kind,
            "blocks": blk.get(stem, 0),
            "test": has_test,
            "deps": deps,
            "lines": src.count("\n") + 1,
        })
    return rows, mnt, blk


def main():
    rows, mnt, blk = scan()
    live = [r for r in rows if r["mount"]]
    dead = [r for r in rows if not r["mount"]]
    print("═" * 78)
    print("  SUPEREGO 全系统体检 · %s" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("═" * 78)
    print("  磁盘上 %d 个脚本 · 挂载运行 %d 个 · 停用 %d 个" % (len(rows), len(live), len(dead)))
    print()
    print("【在跑的 %d 个】" % len(live))
    print("  %-30s %-16s %-6s %-6s %-4s %s" % ("脚本", "挂在哪", "判据", "7天拦", "测试", "行"))
    print("  " + "-" * 74)
    for r in sorted(live, key=lambda x: -x["blocks"]):
        print("  %-30s %-16s %-6s %-6d %-4s %d" % (
            r["name"], ",".join(sorted(set(r["mount"])))[:15], r["kind"],
            r["blocks"], "有" if r["test"] else "⛔无", r["lines"]))
    print()
    print("【已停用但还在磁盘上的 %d 个】" % len(dead))
    for r in sorted(dead, key=lambda x: -x["blocks"]):
        tag = ("  (近7天曾拦 %d 次)" % r["blocks"]) if r["blocks"] else ""
        print("  ✂ %-30s %s%s" % (r["name"], r["kind"], tag))
    print()
    nt = [r["name"] for r in live if not r["test"]]
    print("⛔ 在跑但【没有回归测试】的 %d 个(改坏了没人知道):" % len(nt))
    for n in nt:
        print("   · " + n)
    sem = [r["name"] for r in live if r["kind"] == "语义"]
    print()
    print("⚠️ 依赖【语义服务】的 %d 个(服务挂了会变笨,但不崩):" % len(sem))
    for n in sem:
        print("   · " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
