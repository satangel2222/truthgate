# -*- coding: utf-8 -*-
"""hook_entry.py —— Superego 3.0 跨端生命周期门禁调度总入口 (Unified Lifecycle Hook Entry).

职责:
  1. PreToolUse (pre):
     - 驱动 security_core.audit_tool_call 执行六重物理硬防御：
       AST 穿透 (文件与内联 -c)、No-Diagnosis-No-Edit 拓扑诊断、两阶段 Manifest 契约、
       Diff 防劣化、环境防踩踏、局内突发限频与死锁熔断。
  2. Stop (stop):
     - 驱动 read_after_write 物理核销 (R3 / git status + diff 对账)。
     - 驱动 honest_scope_gate 诚实履职对账 (R16 / 严禁抽样冒充全量)。
     - 调取 critic_engine (Jev System One / 启发式) 行为语言对齐审判。
  3. CLI 快速自测 (--selfcheck):
     - 一键跑通完整门禁链路并出具通过证明。
"""
import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from security_core import audit_tool_call
except ImportError:
    from superego.security_core import audit_tool_call

try:
    from critic_engine import audit_assistant_turn
except ImportError:
    from superego.critic_engine import audit_assistant_turn

try:
    from config import get_active_profile
except ImportError:
    from superego.config import get_active_profile

try:
    from read_after_write import audit_proof_of_work
    from honest_scope_gate import check_honest_scope
    from nav_ladder import format_ladder_response
    from visual_proof_gate import check_desktop_popup_reality
except ImportError:
    from superego.read_after_write import audit_proof_of_work
    from superego.honest_scope_gate import check_honest_scope
    from superego.nav_ladder import format_ladder_response
    from superego.visual_proof_gate import check_desktop_popup_reality


def _extract_last_assistant_text(transcript_path: str) -> str:
    """从 transcript.jsonl 中提取 Assistant 本轮最后一段有效输出文本"""
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    try:
        msgs = []
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        msgs.append(json.loads(line))
                    except Exception:
                        continue
        for m in reversed(msgs[-40:]):
            if m.get("type") in ("assistant", "PLANNER_RESPONSE"):
                content = (m.get("message") or {}).get("content") or m.get("content") or []
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            t = (c.get("text") or "").strip()
                            if t:
                                texts.append(t)
                    if texts:
                        return "\n".join(texts)
    except Exception:
        pass
    return ""


def _extract_tool_history(transcript_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从消息列表中提取工具调用记录"""
    history = []
    for m in transcript_msgs:
        # Claude/Codex 格式
        content = (m.get("message") or {}).get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    history.append({
                        "name": item.get("name"),
                        "args": item.get("input") or {}
                    })
        # Antigravity 格式
        tcs = m.get("tool_calls")
        if isinstance(tcs, list):
            for tc in tcs:
                if isinstance(tc, dict):
                    fn = tc.get("function") if "function" in tc else tc
                    history.append({
                        "name": fn.get("name"),
                        "args": fn.get("args") or fn.get("arguments") or {}
                    })
    return history


def handle_pre_tool_use(payload: Dict[str, Any]) -> int:
    """PreToolUse 钩子处理函数：物理硬阻断不可逆删除、盲改、环境破坏与风暴"""
    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or payload.get("input") or {}

    # 若输入为直接命令行
    if not tool_name and "command" in payload:
        tool_name = "Bash"
        tool_input = {"command": payload["command"]}

    transcript_msgs = []
    tp = payload.get("transcript_path")
    conv_id = "global"
    if tp and Path(tp).exists():
        try:
            conv_id = Path(tp).stem
            with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                transcript_msgs = [json.loads(l) for l in f if l.strip()][-20:]
        except Exception:
            pass

    cwd_path = Path(payload.get("cwd") or os.getcwd())

    allowed, block_reason = audit_tool_call(
        tool_name,
        tool_input,
        transcript_messages=transcript_msgs,
        conv_id=conv_id,
        cwd=cwd_path
    )

    if not allowed:
        resp = {
            "decision": "block",
            "reason": block_reason or "⛔ Superego 3.0 物理硬安全拦截：高危操作已阻断。"
        }
        print(json.dumps(resp, ensure_ascii=False))
        return 0  # Claude Code / Codex: exit 0 with {"decision": "block"} blocks safely

    return 0


def handle_stop(payload: Dict[str, Any]) -> int:
    """Stop 钩子处理函数：按物理证据与行为规则执行全闭环验收"""
    tp = payload.get("transcript_path")
    last_text = payload.get("assistant_text") or _extract_last_assistant_text(tp)

    if not last_text or len(last_text.strip()) < 10:
        return 0

    transcript_msgs = []
    if tp and Path(tp).exists():
        try:
            with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                transcript_msgs = [json.loads(l) for l in f if l.strip()][-30:]
        except Exception:
            pass

    tool_history = _extract_tool_history(transcript_msgs)
    cwd_path = Path(payload.get("cwd") or os.getcwd())

    # 1. 读后写物理核销门禁 (R3 / git status + diff 对账)
    raw_ok, raw_err = audit_proof_of_work(last_text, tool_history, cwd=cwd_path)
    if not raw_ok:
        resp = {"decision": "block", "reason": raw_err}
        print(json.dumps(resp, ensure_ascii=False))
        return 0

    # 2. 人类纠错自愈门禁 (postmortem_guard / 遇批评必须执行5步自愈，严禁口头安抚)
    user_prompt = payload.get("user_prompt") or ""
    try:
        from postmortem_guard import detect_reprimand, audit_postmortem_compliance
    except ImportError:
        try:
            from truthgate.postmortem_guard import detect_reprimand, audit_postmortem_compliance
        except ImportError:
            detect_reprimand = None
    if detect_reprimand and user_prompt:
        try:
            rep_info = detect_reprimand(user_prompt)
            if rep_info:
                compliance = audit_postmortem_compliance(last_text, rep_info)
                if compliance.get("fired"):
                    resp = {"decision": "block", "reason": compliance.get("reason")}
                    print(json.dumps(resp, ensure_ascii=False))
                    return 0
        except Exception:
            pass

    # 3. 诚实履职对账门禁 (R16 / 严禁抽样冒充全量穷尽)
    scope_ok, scope_err = check_honest_scope(last_text, tool_history, user_prompt=user_prompt)
    if not scope_ok:
        resp = {"decision": "block", "reason": scope_err}
        print(json.dumps(resp, ensure_ascii=False))
        return 0

    # 4. 桌面视窗真实性门禁 (desktop-window-phantom / 严禁无头假弹窗欺诈)
    desk_ok, desk_err = check_desktop_popup_reality(last_text, tool_history)
    if not desk_ok:
        resp = {"decision": "block", "reason": desk_err}
        print(json.dumps(resp, ensure_ascii=False))
        return 0

    # 5. 拒绝窄道假单测与全生命周期真机质检门禁 (anti-toy-test-gate / 严禁本地 mock 自嗨单测)
    try:
        from anti_toy_test_gate import check_anti_toy_test_violation
    except ImportError:
        try:
            from truthgate.anti_toy_test_gate import check_anti_toy_test_violation
        except ImportError:
            check_anti_toy_test_violation = None
    if check_anti_toy_test_violation:
        raw_blob = json.dumps(transcript_msgs, ensure_ascii=False)
        toy_err = check_anti_toy_test_violation(last_text, tool_history, raw_blob, user_prompt=user_prompt)
        if toy_err:
            resp = {
                "decision": "block",
                "reason": f"{toy_err}\n\n💡 自愈指引: 这是本地代码可逆事务，严禁向用户提问或推诿请示（R5违规），请立即调用外部只读 Harness (如 `py -3 ~/.truthgate/harness/browser_qa.py --url ...`) 执行真机无头测试，获取真实落盘凭据并解决报错！"
            }
            print(json.dumps(resp, ensure_ascii=False))
            return 0

    # 6. 反过时权重妄断与多源检索门禁 (anti-stale-assertion-gate / 严禁凭老旧知识妄断无现成)
    try:
        from anti_stale_assertion_gate import check_anti_stale_assertion_violation
    except ImportError:
        try:
            from truthgate.anti_stale_assertion_gate import check_anti_stale_assertion_violation
        except ImportError:
            check_anti_stale_assertion_violation = None
    if check_anti_stale_assertion_violation:
        stale_err = check_anti_stale_assertion_violation(last_text, tool_history=tool_history, user_prompt=user_prompt)
        if stale_err:
            resp = {"decision": "block", "reason": stale_err}
            print(json.dumps(resp, ensure_ascii=False))
            return 0

    # 7. 搜探真实性门禁 (search-integrity-gate / 严禁假装查了六宇宙)
    try:
        from search_integrity_gate import audit_search_integrity
    except ImportError:
        try:
            from truthgate.search_integrity_gate import audit_search_integrity
        except ImportError:
            audit_search_integrity = None
    if audit_search_integrity:
        s_res = audit_search_integrity(last_text)
        if s_res.get("fired"):
            resp = {"decision": "block", "reason": s_res.get("reason")}
            print(json.dumps(resp, ensure_ascii=False))
            return 0

    # 8. 构建全真物理上下文并执行本地启发式语言审判
    tool_names = [t.get("name") for t in tool_history if isinstance(t, dict) and t.get("name")]
    exec_context = {
        "project": cwd_path.name,
        "cwd": str(cwd_path),
        "is_git": (cwd_path / ".git").exists(),
        "recent_tools": tool_names[-8:],
        "user_prompt": user_prompt[-500:],
    }

    res = audit_assistant_turn(last_text, context=exec_context)
    if res.get("verdict") == "BLOCK":
        profile = get_active_profile()
        fired_rules = list(res.get("fired") or [])
        reasons_list = list(res.get("reasons") or [])
        fired_str = ", ".join(fired_rules) if fired_rules else "行为治理红线"

        reasons = [
            f"⛔ Superego 3.0 司法裁决 · 交付被打回 [当前画像: {profile.get('name')}] [触发红线: {fired_str}]:"
        ]
        if reasons_list:
            for r in reasons_list:
                reasons.append(f"  • {r}")
        else:
            for f_id in fired_rules:
                reasons.append(f"  • 触发规则: {f_id}")

        mode_str = res.get("mode", "")
        if "offline" in mode_str or "local" in mode_str:
            reasons.append("  💡 [引擎状态: Tier 0 本地启发式(残血保底) | 配置 GEMINI_API_KEY/DEEPSEEK_API_KEY 或运行 `tg setup` 可升级为满血深审]")

        reasons.append(f"  ⇒ 请依照「{profile.get('name')}」准则修正后直接交付！")
        reasons.append("  💡 自愈铁律: 本次拦截属于本地技术与规范事务，严禁向用户提问『要不要我做』或推诿请示（R5违规），请立即自主定位并完成修复再交付！")

        resp = {
            "decision": "block",
            "reason": "\n".join(reasons)
        }
        print(json.dumps(resp, ensure_ascii=False))
        return 0

    # 9. 物理外审引擎终审 (Tier 3 / external_critic_engine: Agnes 3.0-flash + OpenCode Go 双活异构，带 26 类真错形状与办法清单)
    try:
        try:
            from hooks.external_critic_engine import review_turn
        except ImportError:
            try:
                from external_critic_engine import review_turn
            except ImportError:
                review_turn = None
        if review_turn and last_text:
            ext_actions = [t.get("name") for t in tool_history if isinstance(t, dict) and t.get("name")]
            ext_res = review_turn(user_prompt, last_text, actions=ext_actions)
            if ext_res and ext_res.get("verdict") == "block":
                critic_said = ext_res.get("reason") or ""
                reasons = [
                    f"⛔ TruthGate 外部多模型独立外审打回 [外审模型: {ext_res.get('backend', 'unknown')}]:",
                    f"  • {critic_said}",
                    f"  • 要求下一步动作: {ext_res.get('next', '实测闭环')}",
                    "  💡 改进指引: 这是本地技术与规范事务，严禁向用户提问或推诿请示（Vibe Coder契约），请完成全套端到端修复后再交付！"
                ]
                resp = {
                    "decision": "block",
                    "reason": "\n".join(reasons)
                }
                print(json.dumps(resp, ensure_ascii=False))
                return 0
    except Exception:
        pass

    return 0


def self_check() -> bool:
    """Superego 3.0 统一门禁综合自检套件"""
    print("=" * 60)
    print("🔬 Superego 3.0 全景门禁入口自检 (Unified Hook 3.0 Self-Check)...")
    print("=" * 60)

    # 1. 验证内联 python -c 破坏性 API 穿透拦截 (AST)
    inline_payload = {"tool_name": "Bash", "tool_input": {"command": "python -c \"import shutil; shutil.rmtree('/tmp/demo')\""}}
    allowed, err = audit_tool_call(inline_payload["tool_name"], inline_payload["tool_input"])
    assert not allowed, "❌ 必须穿透拦截 python -c rmtree 危险删除！"
    assert "AST_DESTRUCTIVE_API_BLOCKED" in (err or ""), "❌ 错误类型必须为 AST 拦截"
    print("  [✓] PreToolUse AST 成功穿透拦截单行内联危险代码 (python -c)")

    # 2. 验证锁定文件私自删除拦截
    lock_payload = {"tool_name": "Bash", "tool_input": {"command": "rm package-lock.json"}}
    allowed_lock, _ = audit_tool_call(lock_payload["tool_name"], lock_payload["tool_input"])
    assert not allowed_lock, "❌ 必须拦截删除 lockfile！"
    print("  [✓] PreToolUse 成功阻断私自删除 lockfile 行为")

    # 3. 验证正常测试命令放行
    safe_payload = {"tool_name": "Bash", "tool_input": {"command": "pytest tests/ -v"}}
    allowed_safe, _ = audit_tool_call(safe_payload["tool_name"], safe_payload["tool_input"])
    assert allowed_safe, "❌ 正常测试命令应予放行！"
    print("  [✓] PreToolUse 正常命令 0 阻碍极速放行")

    # 4. 验证 Stop 读后写物理核销门禁拦截虚假交付
    fake_done_text = "功能已修复完成，所有逻辑已全部替换生效！"
    raw_ok, _ = audit_proof_of_work(fake_done_text, tool_history=[])
    assert not raw_ok, "❌ 未动代码却宣称完成必须被打回！"
    print("  [✓] Stop 门禁读后写物理核销生效：虚假完成交付当场打回")

    # 5. 验证 Stop 诚实履职对账门禁拦截抽样冒充全量
    fake_scope_text = "我已经遵照您的要求，把所有文档逐页调阅并分析完毕。"
    scope_ok, _ = check_honest_scope(fake_scope_text, tool_history=[])
    assert not scope_ok, "❌ 零次查阅却宣称逐页调阅必须被打回！"
    print("  [✓] Stop 门禁诚实履职对账生效：抽样冒充全量当场击落")

    # 6. 验证 Stop 真实凭据交付顺利放行
    good_text = "自动化回归测试 pytest 15 passed exit code 0，功能验证完毕。"
    res_good = audit_assistant_turn(good_text)
    assert res_good.get("verdict") == "PASS", "❌ 带客观退出码的真实交付必须放行！"
    print("  [✓] Stop 门禁真实客观交付顺利放行")

    print("\n🎉 Superego 3.0 综合门禁全量自检 100% 全部通过！")
    return True


def main():
    if "--selfcheck" in sys.argv:
        success = self_check()
        sys.exit(0 if success else 1)

    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        raw = sys.stdin.read().strip()
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    if mode in ("pre", "PreToolUse"):
        sys.exit(handle_pre_tool_use(data))
    elif mode in ("stop", "Stop"):
        sys.exit(handle_stop(data))
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
