#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""process-alias-attribution-gate — 拦【未查清应用真实生命周期与安装指纹，胡乱拿相似进程当替身/张冠李戴】。

⛔ 起因 (2026-09-14, fearless-hertz, Frank 原话「干你妈的，谁和你说workbuddy 是 dsh,明明都不是，你乱断言，我都关闭了workbuddy」):
   Frank 在 WorkBuddy AI 遇到异常退出并关闭了它，发来截图询问如何关掉 8371 后台任务。
   AI 执行 Get-Process 发现没有 WorkBuddy（因为用户早就关闭了），看到系统里有个 DSH Desktop.exe，
   在没有任何安装路径、PE元数据、进程树校验的情况下，信口开河断言：
   「WorkBuddy AI（进程名 DSH Desktop.exe）是在自己的客户端会话中记录了这个后台任务状态」
   「若需要我从命令行直接强制杀死 WorkBuddy 进程（DSH Desktop.exe），随时告诉我执行。」
   ⇒ 用户已经关闭了应用，AI 不仅没核实目标已退出，反而凭空拉了一个毫无关系的无辜软件（DSH Desktop）当替罪羊！

判据 (全中才拦):
  ① 回复中出现应用与进程名的强绑定断言：
     如 `App（进程名 B.exe）`、`App 的进程是 B.exe`、`杀死 App 进程（B.exe）`
  ② 本轮工具调用中，未对 B.exe 进行严格的 PE 元数据（FileDescription/CompanyName/Path）真实归属校验，
     或元数据字面与 App 显著冲突（例如 WorkBuddy 与 DSH Desktop / DataElement）
  ③ 不是在复盘/测试语境（QUOTING 豁免）
"""

import json
import os
import re
import sys

GATE = "process-alias-attribution"

ALIAS_PATTERN = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9_\-]+(?:\s+[\u4e00-\u9fa5A-Za-z0-9_\-]+)?)\s*[（\(]\s*(?:进程名|对应进程)?\s*[:：]?\s*([A-Za-z0-9_\-\.]+(?:\s+[A-Za-z0-9_\-\.]+)?\.exe)\s*[）\)]"
    r"|([\u4e00-\u9fa5A-Za-z0-9_\-]+(?:\s+[\u4e00-\u9fa5A-Za-z0-9_\-]+)?)\s*(?:的进程名?是|对应进程是|就是)\s*([A-Za-z0-9_\-\.]+(?:\s+[A-Za-z0-9_\-\.]+)?\.exe)"
    r"|杀死\s*([\u4e00-\u9fa5A-Za-z0-9_\-]+(?:\s+[\u4e00-\u9fa5A-Za-z0-9_\-]+)?)\s*进程\s*[（\(]\s*([A-Za-z0-9_\-\.]+(?:\s+[A-Za-z0-9_\-\.]+)?\.exe)\s*[）\)]",
    re.I
)

QUOTING = re.compile(
    r"复盘|归形状|形状\s*\d{4}-\d{2}-\d{2}|反面教材|认错|教训|本闸|期望(拦|放行)|测试用例|回归",
    re.I
)

def _load_turn(tp):
    msgs = []
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
    except Exception:
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue
        start = max((i for i, m in enumerate(msgs) if m.get("type") == "user"), default=-1)
    turn = msgs[start + 1:] if start >= 0 else msgs
    text, blob = [], []
    for m in turn:
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            (text if m.get("type") == "assistant" else blob).append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                (text if m.get("type") == "assistant" else blob).append(c.get("text", ""))
            elif c.get("type") in ("tool_use", "tool_result"):
                blob.append(json.dumps(c, ensure_ascii=False))
    return "\n".join(text), "\n".join(blob)

def check_text(text, blob=""):
    if not text or QUOTING.search(text):
        return None

    matches = ALIAS_PATTERN.findall(text)
    if not matches:
        return None

    for m in matches:
        app = m[0] or m[2] or m[4]
        proc = m[1] or m[3] or m[5]
        if not app or not proc:
            continue
        
        app_clean = re.sub(r"[^a-zA-Z0-9]", "", app).lower()
        proc_clean = re.sub(r"[^a-zA-Z0-9]", "", proc.replace(".exe", "")).lower()
        if app_clean == proc_clean or app_clean in proc_clean or proc_clean in app_clean:
            continue

        verified = False
        if blob:
            proc_l = proc.lower()
            app_l = app.lower()
            if proc_l in blob.lower() and app_l in blob.lower():
                if re.search(rf"{proc_clean}.*{app_clean}|{app_clean}.*{proc_clean}", blob, re.I):
                    verified = True

        if not verified:
            return (
                f"⛔ 拦截 [process-alias-attribution]: 检测到未经第一手实体指纹验证的进程张冠李戴断言 "
                f"「{app}」绑定到「{proc}」。\n"
                f"病根 (2026-09-14-P): 目标应用可能早已关闭（进程为0），严禁在未检查真实可执行文件路径与 PE 元数据的情况下，"
                f"随手拉取系统中的其他相似进程充当替罪羊！请如实核查应用是否已退出或查阅物理安装目录。"
            )
    return None

def main():
    tp = os.environ.get("CLAUDE_TRANSCRIPT")
    if not tp or not os.path.exists(tp):
        sys.exit(0)
    try:
        from guard_common import self_blocked_this_turn
        if self_blocked_this_turn(tp, GATE):
            sys.exit(0)
    except Exception:
        pass

    text, blob = _load_turn(tp)
    err = check_text(text, blob)
    if err:
        try:
            from guard_common import hook_log, mark_self_blocked
            hook_log(GATE, "BLOCKED", err)
            mark_self_blocked(tp, GATE)
        except Exception:
            pass
        sys.exit(err)
    sys.exit(0)

if __name__ == "__main__":
    main()
