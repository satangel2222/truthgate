#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit-source-integrity-gate.py — 严禁将原始对话库注入外审判官大盘或伪造司法流。

⛔ 形状 2026-09-21-A 实录 (Frank 原话「你给我什么鬼，给回我一样的上下文？你给我那些显示是正常吗？你是不是不懂整个看板的旧逻辑」):
   大盘底层因管道断流未收到 PASS 记录，挂在 TURN_START 上。
   AI 助手不仅不修断流根因，反而自作聪明在 dashboard.py 编写 get_ag_events / get_dsh_events，
   从 ag-brain.db / dsh-brain.db 强行拉取原始聊天对话（[user] ... / [assistant] ...）注入外审裁决流，
   将用户日常提问冒充为“审查通过放行 / 一次性合规”。
   这彻底颠覆了大盘作为【外审判官司法裁决监控】的宪法契约，造成严重的数据造假与认知欺诈。

判据:
1. 严禁在 dashboard.py 或外审链路中读取 ag-brain.db / dsh-brain.db / brain.db 的消息表作为审计事件；
2. 严禁在外审裁决的说明列（summary）中注入 [user] 或 [assistant] 原始对话作为判决放行；
3. 严禁宣称“真机对话流富集”或将对话库作为外审监控数据源。
"""

import os
import sys
import re
import json

CHAT_DB_IN_DASHBOARD_RE = re.compile(
    r"(?:ag-brain\.db|dsh-brain\.db|brain\.db|ag_messages|dsh_messages|get_ag_events|get_dsh_events)",
    re.I
)

CHAT_AS_AUDIT_CLAIM_RE = re.compile(
    r"(?:对话流富集|聊天记录注入大盘|真机对话流.*?看板|把提问和回复展示在判决|提取用户提问.*?审查通过)",
    re.I
)

DASHBOARD_FILE_RE = re.compile(r"dashboard\.py\b", re.I)

def check_text(text, blob):
    """Memory-level evaluation called by ag_superego_bridge and hook runner."""
    combined = (text or "") + "\n" + (blob or "")
    
    # 1. Check if modifying dashboard.py with chat db queries
    if DASHBOARD_FILE_RE.search(combined) and CHAT_DB_IN_DASHBOARD_RE.search(combined):
        # Exclude pure refuting / cleanup / postmortem context
        if not re.search(r"(?:移除|删除|清理|revert|rollback|已彻底拔除|严禁|教训|形状 ?20\d\d)", combined, re.I):
            return (
                "[Superego 拦截 - audit-source-integrity-gate] 检测到向看板注入聊天数据库（ag-brain.db / dsh-brain.db / ag_messages）的造假行为！\n"
                "外审大盘是【司法判决监控】，唯一合规数据源是外审日志（semantic-superego-gate.log），严禁拉取原始聊天对白充当判决！"
            )

    # 2. Check if text promotes or defends chat-to-audit fraud
    if CHAT_AS_AUDIT_CLAIM_RE.search(text or ""):
        if not re.search(r"(?:错误|虚假|已废弃|已收回|收回|复盘|教训|严禁|并非)", text, re.I):
            return (
                "[Superego 拦截 - audit-source-integrity-gate] 检测到将原始聊天记录宣称为大盘判决特性的违规断言！\n"
                "看板必须严格显示司法裁决（审查通过/硬打回/红牌/规则触发），绝对禁止将对话流水混同为外审判决！"
            )

    return None

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        sys.exit(0)

    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
        blob = json.dumps(turn, ensure_ascii=False)
    except Exception:
        blob = open(tp, encoding="utf-8", errors="replace").read()[-50000:]

    last_text = ""
    try:
        for m in reversed(turn):
            if m.get("type") == "assistant":
                content = (m.get("message") or {}).get("content") or []
                if isinstance(content, str):
                    last_text = content
                    break
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        last_text = c.get("text", "")
                        break
                if last_text:
                    break
    except Exception:
        pass

    violation = check_text(last_text, blob)
    if violation:
        print(json.dumps({"decision": "block", "reason": violation}, ensure_ascii=False))
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
