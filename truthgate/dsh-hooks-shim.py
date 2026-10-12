# -*- coding: utf-8 -*-
"""dsh-hooks-shim.py —— 给 Claude Code 闸门补上 DSH 桥接缺失的 transcript_path。

【为什么需要它】
DSH 官方桥接 `@deepseek-ai/dsh-hooks-claude-code` 在 payload 里把 `transcript_path`
恒置为空串（README 原文：「持久化 seam 不暴露产物路径，且默认使用 Zstandard 压缩的
会话日志无法被 hook 脚本读取」）。而本机 TruthGate 的 120 道接线闸门里有 73 道要读
transcript 才能判「本轮到底做了什么」⇒ 桥接下它们会静默不触发（实测是优雅失效，
code=0 无输出，不崩不误报，但等于没干活）。

【怎么补】
DSH 侧 `truthgate-guard` 插件已经在写闸门可解析的 transcript（Antigravity 格式）：
    ~/.truthgate/dsh-bridge/<session_id>.jsonl
而桥接 payload 里带 `session_id`，实测与本机 DSH 会话 id 完全一致
（例：session-91a2815a-33b1-4763-84e4-239bbb08175e）。
⇒ 本壳把该文件路径注入 payload 的 `transcript_path`，再喂给真实闸门。

【用法】桥接配置里把命令从
    py -3 <gate>.py
改成
    py -3 ~/.truthgate/dsh-hooks-shim.py --gate <gate>.py
（若闸门需要 argv 参数，用 `--gate-arg` 逐个追加。）

【设计约束】
· 绝不修改上游闸门源码（单源闸规则）—— 只做 stdin 注入与输出透传。
· fail-open：任何异常都退化为「按原样喂给闸门」，绝不因壳故障卡死会话。
· 透传闸门的 stdout 与退出码，桥接照常折叠决策（deny > ask > allow）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TG_HOME = Path(os.environ.get("TRUTHGATE_HOME") or (Path.home() / ".truthgate"))
BRIDGE_DIR = TG_HOME / "dsh-bridge"
HOOKS_DIR = TG_HOME / "hooks"
DEBUG_LOG = BRIDGE_DIR / "shim-debug.log"
PYTHON = os.environ.get("TRUTHGATE_PYTHON") or sys.executable


def dbg(line: str) -> None:
    try:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:
        pass


def resolve_transcript(session_id: str) -> str:
    """按 session_id 找插件写出的 transcript；找不到返回空串（=桥接原行为）。"""
    if not session_id:
        return ""
    p = BRIDGE_DIR / ("%s.jsonl" % session_id)
    if p.exists() and p.stat().st_size > 0:
        return str(p)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--gate", required=True, help="闸门文件名或绝对路径（相对 ~/.truthgate/hooks 解析）")
    ap.add_argument("--gate-arg", action="append", default=[], help="追加给闸门的 argv 参数")
    ap.add_argument("--timeout", type=float, default=120.0)
    args, _unknown = ap.parse_known_args()

    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception as e:
        dbg("stdin 读取失败: %s" % e)

    payload = {}
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        dbg("payload 解析失败（按原样透传）: %s" % e)

    # ---- 注入 transcript_path ----
    #
    # 关键约束：本壳对 **Claude Code 原生运行必须完全透明**。
    # 同一份 settings.json 既被 Claude Code 直接执行、也被 DSH 桥接执行；
    # Claude Code 会给出真实的 transcript_path，而 DSH 桥接恒给空串。
    # 所以：只在「桥接给了空 transcript_path 且我们能按 session_id 找到 DSH transcript」
    # 时才替换；其余情况一律保持原值不动 —— 否则会把 Claude Code 的有效路径抹成空（回归）。
    injected = ""
    replaced = False
    if isinstance(payload, dict):
        original_tp = str(payload.get("transcript_path") or "")
        sid = str(payload.get("session_id") or "")
        dsh_tp = resolve_transcript(sid)
        if dsh_tp and not original_tp:
            payload["transcript_path"] = dsh_tp
            injected = dsh_tp
            replaced = True
        elif original_tp:
            # 已有有效 transcript（Claude Code 原生运行）→ 原样保留
            injected = original_tp

    gate = args.gate
    gate_path = Path(gate)
    if not gate_path.is_absolute():
        gate_path = HOOKS_DIR / gate
    if not gate_path.exists():
        dbg("闸门不存在: %s" % gate_path)
        return 0  # fail-open：桥接不因壳故障卡死

    out_payload = json.dumps(payload, ensure_ascii=False)
    dbg("gate=%s sid=%s transcript=%s%s"
        % (gate_path.name, payload.get("session_id"),
           injected or "(无)", " [注入]" if replaced else " [保留原值/无]"))

    try:
        proc = subprocess.run(
            [PYTHON, str(gate_path)] + list(args.gate_arg),
            input=out_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired:
        dbg("闸门超时: %s" % gate_path.name)
        return 0
    except Exception as e:
        dbg("闸门执行异常（放行）: %s" % e)
        return 0

    if proc.stdout:
        sys.stdout.write(proc.stdout)
        sys.stdout.flush()
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()
    return proc.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 最外层 fail-open
        try:
            dbg("顶层异常（放行）: %s" % e)
        except Exception:
            pass
        sys.exit(0)
