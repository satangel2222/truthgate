#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
port-precheck-gate.py —— 跨项目端口资产与防撞车硬门禁 (Cross-Project Port Collision Gate)

【病根本质 (R1/R28/R42/R53)】：
守着三座跨项目会话脑库（brain.db / ag-brain.db / codex-brain.db）不查，
仅凭眼前一瞬间的 netstat 静态读数，就盲目推荐已被多个其他项目长期占用的高危端口（如 3000），
极易引发多项目并行开发时的端口踩踏与崩溃。

【机器硬拦截机制】：
1. 读取 `~/.claude/cross-project-ports.json` 跨项目历史端口档案库。
2. 捕获回复中推荐的本地端口（`localhost:(\d+)`、`127.0.0.1:(\d+)`、`端口\s*(\d+)`）。
3. 双重物理防线：
   - 防线 A（历史冲突排查）：若推荐端口已被其他项目占用或标记为高频冲突（如 3000 属于 zimagen / airbnb-ai-manager），硬打回！
   - 防线 B（实时清点证据）：若推荐新端口，必须在本轮工具调用中执行过 netstat / 探针清点，否则硬打回！
"""

import sys
import os
import re
import json
from pathlib import Path

REGISTRY_FILE = Path.home() / ".claude" / "cross-project-ports.json"
EXEMPT_PORTS = {80, 443, 22, 17911}

PORT_PATTERNS = [
    re.compile(r'localhost:(\d{2,5})', re.I),
    re.compile(r'127\.0\.0\.1:(\d{2,5})', re.I),
    re.compile(r'(?:端口|port)\s*[:：]?\s*(\d{2,5})', re.I),
]

PROBE_COMMANDS = ["netstat", "get-nettcpconnection", "test-netconnection", "socket", "lsof"]

def load_port_registry():
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def check_turn(turn_text, tool_history_text="", current_project=""):
    registry = load_port_registry()
    
    ports_found = set()
    for pat in PORT_PATTERNS:
        for p in pat.findall(turn_text):
            p_int = int(p)
            if p_int not in EXEMPT_PORTS and 1024 <= p_int <= 65535:
                ports_found.add(p_int)
                
    if not ports_found:
        return True, "No local ports suggested"
        
    for p in ports_found:
        p_str = str(p)
        # 1. 检查历史脑库冲突
        if p_str in registry or p in registry:
            used_by = registry.get(p_str) or registry.get(p) or []
            # 过滤掉属于当前项目自身的记录
            other_projects = [proj for proj in used_by if current_project.lower() not in proj.lower()]
            if other_projects:
                projs_str = ", ".join(other_projects[:4])
                return False, f"跨项目端口撞车：端口 {p} 在跨项目历史脑库中已被 [{projs_str}] 等项目分配使用！Frank 常驻并行多项目，严禁将其他项目的常驻端口随便分配给当前项目！请选用无冲突的全新独立端口并先行排查！"
                
    # 2. 检查本轮实时探针清点证据
    has_probe = any(cmd in tool_history_text.lower() for cmd in PROBE_COMMANDS)
    if not has_probe:
        ports_str = ", ".join(str(p) for p in sorted(ports_found))
        return False, f"未清点端口即妄下断言：你在回复中提及了端口（{ports_str}），但本轮工具调用未执行任何操作系统端口清点（netstat）！必须先清点确认无冲突！"
        
    return True, "Port probe and cross-project check verified"

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # 针对 3000 进行自测，应当被跨项目拦截打回
        t1, m1 = check_turn("你可以打开 http://localhost:3000 预览", tool_history_text="netstat", current_project="ecomm")
        assert not t1, f"Should block port 3000 due to cross project conflict! Got: {m1}"
        print(f"✅ 自测通过，成功拦截 3000 撞车: {m1}")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
        turn_text = data.get("turn_text", "")
        tool_text = data.get("tool_history", "")
        proj = data.get("project", "")
        ok, reason = check_turn(turn_text, tool_text, proj)
        if not ok:
            print(f"⛔ [port-precheck-gate 端口防撞车门禁] {reason}", file=sys.stderr)
            sys.exit(2)
    except Exception:
        pass
    sys.exit(0)
