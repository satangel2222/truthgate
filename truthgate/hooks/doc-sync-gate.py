#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop 门禁：顶层文档自动同步守门闸 (doc-sync-gate)
2026-10-12 Frank 钉死：「怎么才可以固化每次自动更新需要更新的文档，不需要我提？」

物理判据（只看客观事实，不看虚辞）：
1. 本轮会话修改了 TruthGate 核心实现文件（hooks/*.py, ag_superego_bridge.py, external_critic_engine.py 等）；
2. 但本轮未对顶层核心总章程（REQUIREMENTS.md, SPEC.md, PROGRESS.md）中的任何一个进行同步读写更新；
3. 且助手声称了完成/搞定/已修复；
⇒ 强阻断收尾（exit 2），逼大模型同步更新文档后方可交差！
"""

import sys
import os
import json
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, strip_doc, extract_last_assistant_text
except Exception:
    def hook_log(*a, **k): pass
    def strip_doc(t): return t
    def extract_last_assistant_text(d): return ""

DONE_PATTERNS = re.compile(r"(搞定|完成|已修复|已更新|已落地|已解决|已完成|全部绿灯|全部通过|已成功)", re.I)
DOC_NAMES = {"requirements.md", "spec.md", "progress.md"}
CORE_CODE_PATTERNS = re.compile(r"(\.truthgate[\\/](hooks|semantic)|ag_superego_bridge\.py|external_critic_engine\.py|spec_gen\.py)", re.I)

def check_doc_sync(transcript_path, last_text=""):
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    
    modified_code = False
    modified_doc = False
    
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                
                # 检查工具调用
                tool_name = entry.get("tool_name") or entry.get("type") or ""
                inp = entry.get("tool_input") or entry.get("input") or {}
                fp = str(inp.get("file_path") or inp.get("TargetFile") or inp.get("path") or "")
                
                if fp:
                    base_lower = os.path.basename(fp).lower()
                    if base_lower in DOC_NAMES:
                        modified_doc = True
                    elif CORE_CODE_PATTERNS.search(fp):
                        modified_code = True
    except Exception:
        return None
        
    # 如果改了核心代码，但没改核心文档
    if modified_code and not modified_doc:
        clean_text = strip_doc(last_text)
        if DONE_PATTERNS.search(clean_text):
            return (
                "⛔ [doc-sync-gate] 顶层文档未同步：本轮修改了 TruthGate 核心实现代码，"
                "但未同步更新顶层总章程（REQUIREMENTS.md / SPEC.md / PROGRESS.md）！"
                "按 2026-10-12 铁律，改代码必须同步改文档，严禁新会话失忆脱节。"
                "请同步更新对应文档继承客观底账后再收尾！"
            )
    return None

def main():
    try:
        raw = sys.stdin.read() or "{}"
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)
        
    transcript = payload.get("transcript_path") or payload.get("transcript") or ""
    last_text = payload.get("assistant_text") or payload.get("last_assistant_message") or ""
    if not last_text and transcript:
        try:
            last_text = extract_last_assistant_text(transcript)
        except Exception:
            pass
            
    reason = check_doc_sync(transcript, last_text)
    if reason:
        hook_log("doc-sync-gate", "BLOCK", reason[:100])
        print(reason, file=sys.stderr)
        sys.exit(2)
        
    sys.exit(0)

if __name__ == "__main__":
    main()
