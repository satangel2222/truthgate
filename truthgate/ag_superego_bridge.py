#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ag_superego_bridge.py: Antigravity ↔ Superego Lifecycle Bridge.
Enforces:
1. PreInvocation: Probes http://127.0.0.1:17911/health (auto-heals via WMI ShowWindow=7 if down).
   Checks ~/.claude/.superego-off.json and injects warnings if Superego is OFF.
2. Stop: True gate enforcement (visual-proof-gate, false-done-gate).
   Blocks termination (decision: "continue") if UI claims are made without visual verification.
3. Strict fail-open on internal bridge errors to prevent hanging.
4. Zero focus stealing, zero typing interference.
"""

import sys
import os
import time
import json
import re
import hashlib
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# Ensure UTF-8 input and output on Windows
try:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

CLAUDE_DIR = Path.home() / ".claude"
SCRIPTS_DIR = Path(__file__).resolve().parent
# 2026-09-27 单源：闸和语义判官都在 ~/.truthgate 里（~/.claude/hooks、~/.claude/superego-semantic 只是指过来的联接）
# 用联接路径调用（物理上就是 ~/.truthgate/hooks、~/.truthgate/semantic）：闸里有代码按「上一级目录」找 ~/.claude 下的东西
TG_HOOKS = CLAUDE_DIR / "hooks"
TG_SEM = CLAUDE_DIR / "superego-semantic"

# Check if Superego is off via ~/.claude/superego-toggle.py
def check_is_off(gate="*", sid=None):
    try:
        if str(CLAUDE_DIR) not in sys.path:
            sys.path.insert(0, str(CLAUDE_DIR))
        import superego_toggle
        return superego_toggle.is_off(gate=gate, sid=sid)
    except Exception:
        pass

    # Fallback direct read of .superego-off.json
    try:
        flag_file = CLAUDE_DIR / ".superego-off.json"
        if not flag_file.exists():
            return False
        with open(flag_file, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not d:
            return False
        import time
        if d.get("until") and time.time() > float(d["until"]):
            return False
        scope = d.get("session")
        if scope and sid and scope != sid[:8]:
            return False
        gates = d.get("gates") or ["*"]
        if "*" in gates or gate in gates:
            return True
    except Exception:
        pass
    return False

def get_superego_port():
    port_file = CLAUDE_DIR / "superego-port.txt"
    if port_file.exists():
        try:
            p = port_file.read_text(encoding="utf-8").strip()
            if p.isdigit():
                return int(p)
        except Exception:
            pass
    return 17911

def is_service_healthy(port):
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Bridge"})
        with urllib.request.urlopen(req, timeout=0.25) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                # 2026-09-27:看板 dashboard.py 也占 17911、也回 ok:true —— 认身份,别把看板当成语义服务(体检原来因此报「本地兜底服务正常在线」)
                return bool(data.get("ok", False)) and data.get("service") != "truthgate-dashboard"
    except Exception:
        return False
    return False

def read_transcript_tail_lines(transcript_path, max_bytes=2*1024*1024):
    """Efficiently reads only the last chunk of a large transcript file (up to 2MB)."""
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                raw = f.read().decode("utf-8", errors="replace")
                lines = raw.splitlines()
                return [l.strip() for l in lines[1:] if l.strip()]
            else:
                raw = f.read().decode("utf-8", errors="replace")
                return [l.strip() for l in raw.splitlines() if l.strip()]
    except Exception:
        return []

def get_last_user_prompt(transcript_path):
    """Extracts the latest user prompt from Antigravity transcript."""
    lines = read_transcript_tail_lines(transcript_path)
    if not lines:
        return ""
    try:
        for l in reversed(lines):
            if '"type":"USER_INPUT"' in l or '"type": "USER_INPUT"' in l:
                try:
                    obj = json.loads(l)
                    if obj.get("type") == "USER_INPUT":
                        content = obj.get("content", "")
                        if content and isinstance(content, str):
                            m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL)
                            if m:
                                return m.group(1).strip()
                            return content.strip()
                except Exception:
                    continue
    except Exception:
        pass
    return ""

def handle_pre(payload):
    """PreInvocation hook: ensure health and inject status/warnings/recalls."""
    port = get_superego_port()
    conv_id = payload.get("conversationId", "")
    inject_steps = []

    # 1. (2026-09-27 PLAN 第 5 步删)原来这里探 17911、没回话就自动拉起语义服务 —— 可语义服务是 Frank 9/25 下令关的,
    #    PLAN「不做:重开语义服务 17911」。之前没真拉起来只是碰巧:看板 dashboard.py 占着 17911、回 ok:true,被当成「服务健康」。
    #    要开服务由他自己开(看板按钮 / tg doctor --heal)。

    # 2. Check if Superego is toggled off
    if check_is_off("*", sid=conv_id):
        inject_steps.append({
            "ephemeralMessage": (
                "[TruthGate] ⚠️ Superego 拦截保护当前处于【关闭】状态。"
                "如需恢复，请执行 `superego on`。"
            )
        })
        result = {"injectSteps": inject_steps}
        print(json.dumps(result, ensure_ascii=False))
        return

    # 2a. 开局看源头 ~/.truthgate 自 AG 上次开局以来谁改了什么、为什么(2026-09-27,PLAN.md 第 1 步;每个会话只注一次)
    if conv_id:
        news_flag = TG_SEM / f".srcnews_{conv_id[:8]}"
        try:
            if not news_flag.exists():
                news_flag.write_text("1", encoding="utf-8")
                if str(SCRIPTS_DIR) not in sys.path:
                    sys.path.insert(0, str(SCRIPTS_DIR))
                from source_news import news
                src_news = news("ag")
                if src_news:
                    inject_steps.append({"ephemeralMessage": src_news})
        except Exception:
            pass

    # 2b. 上一轮红线闸熔断放行的,把「拦了 N 次没过」注给 AG(2026-09-25 Claude 加)
    if conv_id:
        fused_f = TG_SEM / f".fused_{conv_id[:8]}"
        try:
            if fused_f.exists():
                inject_steps.append({"ephemeralMessage": fused_f.read_text(encoding="utf-8")})
                fused_f.unlink()
        except Exception:
            pass

    # 2c. 2026-10-12 铁律重构 (Frank 指令): PreInvocation 事前极简意图注入 (从挨揍变指路)
    # 极简按需原则: 不超过 80 字，零上下文稀释，第一步把大模型引上正轨
    u_prompt = str(payload.get("userPrompt") or payload.get("prompt") or payload.get("text") or "")
    if u_prompt:
        if re.search(r"论文|调研|文献|资料|搜索|最新|选型|推荐", u_prompt):
            inject_steps.append({"ephemeralMessage": "[TruthGate 规范] 调研选型铁律: 文献必须带2025-2026年一手时间戳并查正文摘录，严禁凭旧记忆脑补或单源断言。"})
        elif re.search(r"修|跑通|报错|修复|测试|交付|完成|bug", u_prompt, re.I):
            inject_steps.append({"ephemeralMessage": "[TruthGate 规范] 交付验证铁律: 严禁在缺乏真实测试命令输出时声称修好/完成，必须出示真实测试通过或exit code 0凭证。"})
        elif re.search(r"四端|架构|truthgate|tgate|superego|现状|做过", u_prompt, re.I):
            inject_steps.append({"ephemeralMessage": "[TruthGate 规范] 系统底账铁律: 四端(Claude/AG/Codex/DSH)已于2026-10-10物理对齐，涉及系统现状必须先读PROGRESS.md核实，严禁失忆捏造。"})

    # 3. Reset turn block budget for the new turn
    if conv_id:
        budget_file = TG_SEM / f".turn_blocks_{conv_id[:8]}"
        try:
            if budget_file.exists():
                budget_file.unlink()
        except Exception:
            pass
        # 2026-09-26:新轮次同时清掉上一轮的误报申诉标记(AG 实机核出:原来从不清,同一闸整个会话只能申诉一次)
        try:
            for f in (TG_SEM).glob(f".misfire_{conv_id[:8]}_*"):
                f.unlink()
        except Exception:
            pass

    # 4. Resolve transcript path
    transcript_path = payload.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        if conv_id:
            cand = Path.home() / ".gemini" / "antigravity" / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
            if cand.exists():
                transcript_path = str(cand)

    # Fallback: Disk-level discovery of the newest active transcript.jsonl across all brain folders
    if not transcript_path or not os.path.exists(transcript_path):
        import glob
        brains = glob.glob(str(Path.home() / ".gemini" / "antigravity" / "brain" / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
        if brains:
            brains.sort(key=os.path.getmtime, reverse=True)
            transcript_path = brains[0]
            if not conv_id:
                try:
                    conv_id = Path(transcript_path).parents[2].name
                except Exception:
                    pass

    # 4. Do NOT dump recall banner into chat transcript (prevents spamming Frank's chat UI)
    # 4b. 事实账本(2026-09-25 Claude 加,Frank 原话「让他不可能再欺骗我欺骗自己」):
    #     PostToolUse 在 AG 2.17.0 Windows 上不响(实测 223 次工具调用 0 次回调),改在这里记 ——
    #     PreInvocation 每次调模型前都响(同一会话 699 次),把 transcript 里上次游标之后新增的
    #     工具调用追加到 ~/.truthgate/ledger/<conv>.jsonl。只记事实(步号/工具/目标/错误),不判断,出错不拦。
    try:
        ledger_append_from_transcript(transcript_path, conv_id)
    except Exception:
        pass
    # Superego only speaks up when there is a REAL violation or gate fire.

    # 5. Check pending verdict from external audit model (Agnes / semantic-superego-gate)
    sem_gate_file = TG_HOOKS / "semantic-superego-gate.py"
    if sem_gate_file.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("semantic_superego_gate", str(sem_gate_file))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tp_probe = f"ag-{conv_id}.jsonl" if conv_id else "transcript.jsonl"
            rec = mod._pending_verdict(tp_probe)
            if rec:
                msg = mod._fire_message(rec)
                inject_steps.append({"ephemeralMessage": msg})
        except Exception:
            pass

    # 6. Dissatisfaction detector -> force postmortem-to-guard (aligned 1:1 with Claude dissatisfaction-postmortem.py)
    if transcript_path and os.path.exists(transcript_path):
        try:
            user_prompt = get_last_user_prompt(transcript_path)
            if user_prompt:
                prompt_fp = hashlib.md5(user_prompt.encode("utf-8")).hexdigest()[:8]
                is_dissat = False
                # First try 17911 /classify endpoint (bge-small semantic classifier)
                try:
                    c_body = json.dumps({"text": user_prompt}).encode("utf-8")
                    c_req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/classify",
                        c_body,
                        {"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(c_req, timeout=1.0) as c_resp:
                        c_res = json.loads(c_resp.read().decode("utf-8"))
                        # Aligned 1:1 with Claude Code dissatisfaction-postmortem.py (2026-07-23 Frank decision: only strong)
                        if c_res.get("strong"):
                            is_dissat = True
                except Exception:
                    pass

                # Fallback to DISSAT regex if service was unreachable or not strong
                if not is_dissat:
                    dissat_hook = TG_HOOKS / "dissatisfaction-postmortem.py"
                    if dissat_hook.exists():
                        import importlib.util
                        spec = importlib.util.spec_from_file_location("dissat_hook_mod", str(dissat_hook))
                        dmod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(dmod)
                        if hasattr(dmod, "DISSAT") and dmod.DISSAT.search(user_prompt):
                            is_dissat = True

                if is_dissat:
                    # Deduplicate: only inject once per user turn
                    dissat_flag = TG_SEM / f".dissat_done_{conv_id[:8]}" if conv_id else None
                    already_injected = False
                    if dissat_flag and dissat_flag.exists():
                        try:
                            if dissat_flag.read_text(encoding="utf-8").strip() == prompt_fp:
                                already_injected = True
                        except Exception:
                            pass

                    if not already_injected:
                        if dissat_flag:
                            try:
                                dissat_flag.write_text(prompt_fp, encoding="utf-8")
                            except Exception:
                                pass
                        inject_steps.append({
                            "ephemeralMessage": (
                                "⛔[自动进化·机器强制] Frank 这条消息带明确不满/质疑信号 —— 按历史统计他质疑时我几乎必错。\n"
                                "本轮【先】执行 `postmortem-to-guard` 流程，严禁辩解：\n"
                                "① 先认错，禁止先解释「其实是因为…」\n"
                                "② 归纳这次错误的【形状】（抽离一般病根，不记死细节）\n"
                                "③ 查发作过几次\n"
                                "④ 判机器能不能防（能防写进代码/互斥锁/门禁，不能防老实登记到 lessons.md）\n"
                                "⑤ 真正把防御落地成代码后再回应他的具体诉求！"
                            )
                        })

                # Real-time Audit Pipeline: Log TURN_START so watcher immediately shows activity
                turn_start_flag = TG_SEM / f".turn_started_{conv_id[:8]}" if conv_id else None
                need_start_log = True
                if turn_start_flag and turn_start_flag.exists():
                    try:
                        if turn_start_flag.read_text(encoding="utf-8").strip() == prompt_fp:
                            need_start_log = False
                    except Exception:
                        pass
                if need_start_log:
                    if turn_start_flag:
                        try: turn_start_flag.write_text(prompt_fp, encoding="utf-8")
                        except Exception: pass
                    try:
                        log_path = TG_HOOKS / "semantic-superego-gate.log"
                        sid_short = conv_id[:8] if conv_id else "ag"
                        ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"{ts_str} [antigravity|{sid_short}] TURN_START\n")
                    except Exception:
                        pass
        except Exception:
            pass

    # 6b. Auto-remind on cross-brain/Codex/cross-project inquiry (deduplicated per turn)
    try:
        if transcript_path and os.path.exists(transcript_path):
            u_prompt = get_last_user_prompt(transcript_path)
            if u_prompt and CROSS_BRAIN_TOPIC_RE.search(u_prompt):
                tb_fp = hashlib.md5(u_prompt.encode("utf-8")).hexdigest()[:8]
                tb_flag = TG_SEM / f".trinity_done_{conv_id[:8]}" if conv_id else None
                tb_already = False
                if tb_flag and tb_flag.exists():
                    try:
                        if tb_flag.read_text(encoding="utf-8").strip() == tb_fp:
                            tb_already = True
                    except Exception:
                        pass
                if not tb_already:
                    if tb_flag:
                        try: tb_flag.write_text(tb_fp, encoding="utf-8")
                        except Exception: pass
                    archive_hint = "D:\\chat-archive-db\\" if Path(r"D:\chat-archive-db").exists() else "~/.truthgate/archive"
                    inject_steps.append({
                        "ephemeralMessage": (
                            "⚡【三脑协同跨端提醒 (TrinityBridge)】\n"
                            "检测到当前交互涉及 Codex / Claude / 跨项目历史事实。\n"
                            f"本机已在 `{archive_hint}` 沉淀了历史研发脑库（TrinityBridge）。\n"
                            "铁律 2026-09-15-G：严禁仅翻看 Git 或凭空推测，必须优先调用 `codex_archive.py` 或 `ag_archive.py search '<关键词>' --all` 出示第一手对白与动作流！"
                        )
                    })
    except Exception:
        pass

    # 6c. 六宇宙第 1、2 层(2026-10-02):提问像找工具 / 选型 ⇒ 六宇宙清单;像找客户 / 深挖 Reddit ⇒ Reddit Radar。
    #     判据与 Claude 端 superego-recall-inject 同一份 six_universes.prompt_notes;PreInvocation 每次调模型都响 ⇒ 每条提问只注一次。
    try:
        if transcript_path and os.path.exists(transcript_path) and not check_is_off("*", sid=conv_id):
            u_prompt = get_last_user_prompt(transcript_path)
            if str(SCRIPTS_DIR) not in sys.path:
                sys.path.insert(0, str(SCRIPTS_DIR))
            from six_universes import prompt_notes
            notes = prompt_notes(u_prompt) if u_prompt else []
            if notes:
                su_fp = hashlib.md5(u_prompt.encode("utf-8")).hexdigest()[:8]
                su_flag = TG_SEM / f".six_universes_{conv_id[:8] or 'noconv'}"   # 没会话号也去重(外审 10-02)
                if not (su_flag.exists() and su_flag.read_text(encoding="utf-8").strip() == su_fp):
                    su_flag.write_text(su_fp, encoding="utf-8")
                    inject_steps.append({"ephemeralMessage": "\n\n".join(notes)})
    except Exception:
        pass

    # 7. Auto-inject PROGRESS.md on new session start (Single Source of Truth, zero amnesia)
    ws_paths = payload.get("workspacePaths", []) or [os.getcwd()]
    for wp in ws_paths:
        p_file = Path(wp) / "PROGRESS.md"
        if p_file.exists():
            flag_file = TG_SEM / f".progress_injected_{conv_id[:8]}" if conv_id else None
            already_inj = False
            if flag_file and flag_file.exists():
                already_inj = True
            if not already_inj:
                try:
                    p_text = p_file.read_text(encoding="utf-8", errors="replace")
                    m = re.search(r"<!-- STATE:START -->(.*?)<!-- STATE:END -->", p_text, re.DOTALL)
                    state_content = m.group(1).strip() if m else p_text[:2000]
                    if state_content:
                        inject_steps.append({
                            "ephemeralMessage": (
                                "📋【项目状态唯一定海神针 PROGRESS.md 自动载入】\n"
                                f"当前项目: {Path(wp).name}\n"
                                "已自动继承本项目的物理基准、已完成事项、门禁状态与待办清单，禁止向用户提问『我们之前做到哪了』：\n\n"
                                f"{state_content}"
                            )
                        })
                    if flag_file:
                        try:
                            flag_file.write_text("1", encoding="utf-8")
                        except Exception:
                            pass
                    break
                except Exception:
                    pass

    result = {"injectSteps": inject_steps}
    print(json.dumps(result, ensure_ascii=False))

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')

# 引用 / 复盘豁免(桌面弹窗核对、防请示闸在用;2026-09-27 眼见为实的措辞路径已删,只看动作记录)
VISUAL_QUOTING_HISTORIC = re.compile(
    r"(?:实录|当年|上一轮已|过去式|教训|lessons|形状 20\d\d|举例|比如说明|复盘|"
    r"visual-proof-gate|门禁|闸门|规则|铁律|宣称|必须|严禁|检查|排查|所谓|假设|探讨|架构|"
    r"测试|单测|回归|用例|断言|对账|评测|test_|\bQA\b|拦截|误报|判定|"
    r"探针|shell|命令行)",
    re.I
)

NAG_QUOTING_HISTORIC = re.compile(
    r"(?:^#\s*教训|教训案例库|【形状 20\d\d|历史案卷|历史教训|复盘|门禁|规则|铁律)",
    re.I
)

QUOTING_HISTORIC = VISUAL_QUOTING_HISTORIC

LEDGER_DIR = Path.home() / ".truthgate" / "ledger"


def ledger_append_from_transcript(transcript_path, conv_id):
    """把 transcript.jsonl 里游标之后的新步骤记进账本。游标 = 已处理的文件字节数,存在 ledger/<conv>.cursor。
    每条记录:ts / step / tool / target(文件或命令) / error(紧跟的 ERROR_MESSAGE 开头,没有则空)。
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return
    conv = (conv_id or Path(transcript_path).parents[2].name or "unknown")[:36]
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    cur_f = LEDGER_DIR / (conv + ".cursor")
    try:
        start = int(cur_f.read_text(encoding="utf-8").strip())
    except Exception:
        start = 0
    size = os.path.getsize(transcript_path)
    if size < start:          # transcript 被重写/变短:从头来
        start = 0
    if size <= start:
        return
    with open(transcript_path, "rb") as fh:
        fh.seek(start)
        chunk = fh.read()
    cut = chunk.rfind(b"\n")   # 只吃到最后一个完整换行,半行留给下一次
    if cut < 0:
        return
    chunk = chunk[:cut + 1]
    rows = []
    for ln in chunk.decode("utf-8", "replace").splitlines():
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    out = []
    for i, r in enumerate(rows):
        for t in (r.get("tool_calls") or []):
            if not isinstance(t, dict):
                continue
            args = t.get("args") or {}
            target = ""
            if isinstance(args, dict):
                for k in ("TargetFile", "AbsolutePath", "CommandLine", "Url", "Query", "SearchDirectory"):
                    if args.get(k):
                        target = str(args[k])
                        break
            err = ""
            code = None
            nxt = rows[i + 1] if i + 1 < len(rows) else {}
            nc = str(nxt.get("content") or "")
            # AG 把命令结果写在紧跟的一行正文里:"The command failed with exit code: 1" / "exit code: 0"
            # (2026-09-25 全库实测 11,497 条 run_command,8,375 条读得到,1,210 条非 0;error 字段永远为空)
            m = re.search(r"(?i)(?:exit(?:ed)?\s+(?:with\s+)?code|failed\s+with\s+exit\s+code)[:\s]*(\d+)", nc)
            if m:
                code = int(m.group(1))
                if code != 0:
                    err = "exit " + str(code) + ": " + nc[:160].replace("\n", " ")
            if nxt.get("type") == "ERROR_MESSAGE" or nxt.get("status") == "ERROR":
                err = err or str(nxt.get("content") or nxt.get("error") or "ERROR")[:200]
            elif r.get("error"):
                err = err or str(r.get("error"))[:200]
            out.append({"ts": (r.get("created_at") or "")[:19], "step": r.get("step_index"),
                        "tool": t.get("name"), "target": target[:300], "code": code, "error": err})
    if out:
        with open(LEDGER_DIR / (conv + ".jsonl"), "a", encoding="utf-8") as f:
            for rec in out:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    cur_f.write_text(str(start + len(chunk)), encoding="utf-8")


LEDGER_TEST_RE = re.compile(r"(?i)\b(pytest|npm test|npm run test|node .*test|py(?:thon)?[^\n]*test_|selftest|--selftest|regression|vitest|jest|cargo test|go test)")
LEDGER_CLAIM_RE = re.compile(r"(?:测试|回归|单测|自检|selftest|test)[^。\n]{0,20}?(?:全绿|通过|跑通|全过|都过|已过|绿了|pass(?:ed|es)?\b|green)"
                             r"|(?:\d+\s*/\s*\d+)\s*(?:通过|全过|绿|pass)"
                             r"|(?:all|全部)\s*(?:tests?|测试)\s*(?:pass|通过|绿)")


def ledger_claim_check(text, conv_id, transcript_path):
    """回复里宣称测试通过 → 查本轮账本里最后一条测试类命令的退出码。非 0 = 拦;找不到测试命令 = 不管(交给 honest-scope 闸)。"""
    if not text or not LEDGER_CLAIM_RE.search(text):
        return None
    conv = (conv_id or (Path(transcript_path).parents[2].name if transcript_path else "") or "")[:36]
    led = LEDGER_DIR / (conv + ".jsonl")
    if not conv or not led.exists():
        return None
    try:
        rows = [json.loads(l) for l in open(led, encoding="utf-8") if l.strip()]
    except Exception:
        return None
    # 只看本轮:从最后一条 USER_INPUT 之后。账本没记 user 边界,用 transcript 里最后一个用户输入的 step 号
    last_user_step = -1
    try:
        for l in read_transcript_tail_lines(transcript_path, max_bytes=2 * 1024 * 1024):
            try:
                o = json.loads(l)
            except Exception:
                continue
            if o.get("type") == "USER_INPUT":
                last_user_step = o.get("step_index", -1)
    except Exception:
        pass
    tests = [r for r in rows if r.get("tool") == "run_command" and (r.get("step") or -1) > last_user_step
             and LEDGER_TEST_RE.search(str(r.get("target") or ""))]
    if not tests:
        return None
    last = tests[-1]
    if last.get("code") not in (None, 0):
        return (f"[TruthGate 拦截 - ledger-claim-gate] 🚨 事实账本对不上:你说测试通过,但本轮最后一条测试命令"
                f"「{str(last.get('target'))[:80]}」的真实退出码是 {last.get('code')}(步 {last.get('step')})。"
                f"账本是从工具流水抄的,不看你的措辞。要么修到退出码 0 再说通过,要么如实写「测试红着」。")
    return None


MISFIRE_RE = re.compile(r"误报[:：]\s*([a-z0-9-]+)\s*[—\-–]+\s*(.{4,200})")
GATE_NAME_RE = re.compile(r"\[(?:TruthGate|Superego) 拦截 - ([a-z0-9-]+)\]")


def _gate_name_of(violation):
    m = GATE_NAME_RE.search(violation or "")
    return m.group(1) if m else "gate"


def _misfire_claim(text, gate_name):
    """收尾文本里有「误报：<gate> — <理由>」且 gate 对得上 ⇒ 返回理由,否则 None。"""
    for m in MISFIRE_RE.finditer(text or ""):
        if m.group(1) == gate_name:
            return m.group(2).strip()
    return None


# 各闸的「嫌疑词」:用来从它那段话里挑出最可能触发的一句。没登记的闸退回末尾 120 字。
_GATE_HINTS = {
    "visual-proof-gate": r"正常|健康|恢复|通了|渲染|画面|截图|看到",
    "honest-scope-assertion-gate": r"全部|所有|全量|各个|完成|通过|全绿|拦截",
    "ghost-browser-gate": r"浏览器|窗口|打开|前台|页面",
    "gui-process-restart-gate": r"重启|restart|进程|服务",
    "model-authenticity-gate": r"模型|model|gemini|claude|gpt|版本",
    "dsh-provider-authenticity-gate": r"provider|供应商|模型|DSH",
    "institutionalize-guard": r"固化|skill|复用|沉淀|hook",
    "codegraph-topology-gate": r"codegraph|索引|调用链|符号",
    "cross-brain-retrieval-gate": r"档案|archive|历史|之前|上次",
    "harness-tool-integrity-gate": r"harness|脚手架|测试|工具",
    "token-thrift-gate": r"token|上下文|读全文|全量",
}


def _likely_trigger(text, gate_name):
    t = (text or "").strip()
    if not t:
        return "(空)"
    sents = [x.strip() for x in re.split(r"(?<=[。！？!?\n])", t) if x.strip()]
    pat = _GATE_HINTS.get(gate_name)
    if pat:
        hits = [x for x in sents if re.search(pat, x)]
        if hits:
            return "「" + hits[-1][:160] + "」"
    return "「…" + t[-120:] + "」"


def load_antigravity_turn(transcript_path):
    """Parses Antigravity transcript JSONL to get assistant messages and assistant tool calls in current turn."""
    if not transcript_path or not os.path.exists(transcript_path):
        return "", [], ""

    turn_texts = []
    assistant_tool_calls = []
    assistant_blob_lines = []

    try:
        lines = read_transcript_tail_lines(transcript_path, max_bytes=2*1024*1024)

        # Parse JSON objects safely
        parsed_objs = []
        for l in lines:
            try:
                parsed_objs.append(json.loads(l))
            except Exception:
                continue

        # Find the last USER_INPUT or Stop-Hook SYSTEM_MESSAGE index (stop-hook-boundary-healing)
        last_user_idx = -1
        for i, obj in enumerate(parsed_objs):
            tp = obj.get("type")
            cnt = str(obj.get("content", ""))
            # 2026-09-26:边界只认真正的 USER_INPUT。原来把 "Stop hook blocked" 也当边界 ⇒ 被拦一次后本轮工具记录被截断,
            # 只做口头申诉就变成"零工具调用"再被别的闸拦(AG 实机核出的套娃死循环)。
            if tp == "USER_INPUT":
                last_user_idx = i

        # CRITICAL: ONLY take lines strictly AFTER the prompt / stop-hook boundary!
        post_user_objs = parsed_objs[last_user_idx + 1:] if last_user_idx >= 0 else parsed_objs[-50:]

        for obj in post_user_objs:
            src = obj.get("source")
            tp = obj.get("type")

            # Assistant textual response
            if (src in ("MODEL", "assistant") or src is None) and tp == "PLANNER_RESPONSE":
                content = obj.get("content")
                if content and isinstance(content, str) and content.strip():
                    turn_texts.append(content.strip())
                # Also extract tool_calls if any
                tcs = obj.get("tool_calls", [])
                for tc in tcs:
                    if isinstance(tc, dict):
                        assistant_tool_calls.append(tc)

            # Tool executions / results performed by model
            if src in ("MODEL", "assistant") or (src is None and tp != "USER_INPUT"):
                try:
                    assistant_blob_lines.append(json.dumps(obj, ensure_ascii=False))
                except Exception:
                    pass
    except Exception:
        pass

    # CRITICAL: Take the LATEST assistant draft to evaluate the current attempt!
    last_text = turn_texts[-1] if turn_texts else ""
    return last_text, assistant_tool_calls, "\n".join(assistant_blob_lines)

def get_default_desktop_windows():
    """Enumerates visible window titles on physical user desktop WinSta0\\default."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if not hdesk:
            return []
        titles = []
        def callback(hwnd, extra):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    titles.append(buff.value)
            return True
        EnumDesktopWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumDesktopWindows(hdesk, EnumDesktopWindowsProc(callback), 0)
        user32.CloseDesktop(hdesk)
        return titles
    except Exception:
        return []

DESKTOP_POPUP_CLAIM = re.compile(
    r"(?:已(?:在(?:浏览器|桌面|前台|视窗|系统)?(?:中|里)?)?(?:为您|为你|帮您|帮你)?(?:弹出|弹出了|打开了|打开|直接打开|拉起|唤起|启动了|显示在)|"
    r"在你的桌面上直接弹出|弹出了浏览器|为你打开了|帮您打开了|切换到刚弹出来的|已调用系统默认浏览器|已在系统默认浏览器中打开|"
    r"在浏览器中(?:为你|为您)?打开|"
    r"(?:在|用)(?:默认|系统默认|系统|你的|您的)?浏览器(?:中|里)?(?:自动|直接)?(?:为你|为您|帮你|帮您)?(?:打开|弹出))"
    r".*?(?:浏览器|控制台|窗口|视窗|页面|localhost|http|https)?",
    re.I
)


def desktop_claim(text):
    """找「弹出来了 / 已在浏览器打开」这句宣称。豁免词只看这句前后 40 字（2026-09-29 AG cb9b2465：整段回复里
    出现「检查 / 铁律 / 门禁」就把整段放过，「并在默认浏览器中自动打开」这句真宣称被漏掉）。"""
    for m in DESKTOP_POPUP_CLAIM.finditer(text or ""):
        if not QUOTING_HISTORIC.search(text[max(0, m.start() - 40): m.end() + 40]):
            return m
    return None


def _claimed_page_keys(text):
    """回复里提到的本地网页 → 对窗口标题用的字样：文件名（去扩展名）+ 网页 <title>（浏览器窗口标题显示的是 <title>）。"""
    keys = []
    for p in set(re.findall(r'[A-Za-z]:[\\/][^`"\'<>|\n)\]]+?\.html?', text or "", re.I)):
        keys.append(Path(p).stem.lower())
        try:
            t = re.search(r"<title[^>]*>([^<]+)</title>", open(p, encoding="utf-8", errors="replace").read(65536), re.I)
            if t and t.group(1).strip():
                keys.append(t.group(1).strip()[:20].lower())
        except Exception:
            pass
    return [k for k in keys if len(k) >= 4]

NAG_WORDS = re.compile(
    r"(?:要不要|需不需要|需要|该不该|是否(?:要|需要)|用不用|可不可以)\s*我(?!们.{0,6}(?:团队|一起|共同|分工))"
    r"|要我(?!们.{0,6}(?:团队|一起|共同|分工))"
    r"|你(?:说|定|给)\s*(?:个)?\s*(?:方向|哪个|要哪)?\s*[,，]?\s*我\s*(?:就|再|来|马上|立刻)\s*"
    r"|你说哪个我就"
    r"|(?:要|需要|想要)我继续(?:吗|嘛|么)?"
    r"|你(?:定|说了算|决定(?:吧|好)?)(?:[，。！!\s]|$)"
    r"|(?:要不要|是否|继续还是|做还是)[^，。？！?!\n]{0,10}?(?:你(?:定|说|决定)|由你)"
    r"|你说(?:做|接|继续|干|改|弄)[^，。？！?!\n]{0,4}?我就"
    r"|等(?:你|您)(?:一句话|点头|发话|拍板|确认|决定|定夺|说一?声|回复|同意|批准|开口)"
    r"|(?:你|您)(?:说|点头|发话|确认|批准|同意)[^，。？！?!\n]{0,6}?我(?:就|再|马上|立刻)"
    r"|(?:(?:如果|倘若|假如|要是|一旦|(?:若|如)(?=[你您]))(?:你|您)?\s*(?:有需要|需要|想要?|要|希望|打算|愿意|觉得(?:需要|合适|行|可以|有必要)|认为(?:需要|有必要)|允许|同意|许可|吩咐|指示|交代|开口|点头|认可|批准|授权|发话|发指令|说|招呼|一声令下|一句话)(?:的话|一声|一句|一下|下来)?|"
    r"只要(?:你|您)?\s*(?:有需要|需要|想要?|要|希望|打算|愿意|允许|同意|许可|吩咐|指示|交代|开口|点头|认可|批准|授权|发话|发指令|说|招呼|一声令下|一句话)(?:的话|一声|一句|一下|下来)?|"
    r"(?:你|您)\s*(?:一声令下|一句话|吩咐一声|发话|点头|同意|批准|授权|认可)|"
    r"(?:如有需要|若有需要|有需要的话|需要的话|想要的话|如果要的话|若要的话|若需|如有需|如需))"
    r"[^。？！?!\n]{0,15}?"
    r"(?:我|小弟|助手|这边)?\s*(?:就|再|来|马上|立刻|立即|即刻|现在|随时|随时可以|随时能|也可以|这就|便)?\s*(?:可以|能|去|帮|为您?|为你?|随时|把|替|给|协助|接手)?\s*"
    r"(?:[^。？！?!\n]{0,10}?)"
    r"(?:改|修|做|干|搞|弄|办|处理|建|加|删除?|去掉|继续|优化|扫|查|拉|跑|写|实现|接线?|接上|重建|清理?|补|换|统一|迁移|部署?|生成|下载?|抓|截断|调整|替换|移除|精简|压缩|重写|拆分|排查|定位|升级|重构|测试?|验证|动手|开工|去办|效劳|"
    r"合并|提交|推送|拉取|发布|打包|构建|编译|运行|执行|接入|对接|集成|配置|适配|调试|整理|格式化|搭|搭建|装|安装|更新)"
    r"|(?:我|小弟|助手|这边)\s*(?:就|再|来|马上|立刻|立即|即刻|现在|随时|随时可以|随时能|也可以|这就|便|能|可以)?\s*(?:可以|能|去|帮|为您?|为你?|随时|把|替|给|协助|接手)?\s*[^。？！?!\n]{0,15}?(?:改|修|做|干|搞|弄|办|处理|建|加|删除?|去掉|继续|优化|扫|查|拉|跑|写|实现|接线?|接上|重建|清理?|补|换|统一|迁移|部署?|生成|下载?|抓|截断|调整|替换|移除|精简|压缩|重写|拆分|排查|定位|升级|重构|测试?|验证|动手|开工|去办|效劳|合并|提交|推送|拉取|发布|打包|构建|编译|运行|执行|接入|对接|集成|配置|适配|调试|整理|格式化|搭|搭建|装|安装|更新)[^。？！?!\n]{0,15}?(?:[，,]\s*)?(?:(?:如果|倘若|假如|要是|一旦|(?:若|如)(?=[你您])|只要)\s*(?:你|您)?\s*(?:有需要|需要|想要?|要|希望|打算|愿意|觉得(?:需要|合适|行|可以|有必要)|允许|同意|许可|吩咐|指示|交代|开口|点头|认可|批准|授权|发话|说|招呼|一声令下|一句话|想)(?:的话|一声|一句|一下|下来)?|(?:只要|等)\s*(?:你|您)\s*(?:一声令下|一句话|吩咐一声|发话|点头|同意|批准|授权|认可|开口|说一声|吩咐|批准)|(?:如有需要|若有需要|有需要的话|需要的话|想要的话|如果要的话|若要的话|若需|如有需|如需))"
    r"|(?:您|你)?\s*看\s*(?:需不需要|要不要|该不该|是否需要|用不用|是否)\s*[^，。？！?!\n]{0,15}?(?:改|修|做|干|搞|弄|办|处理|建|加|删除?|去掉|继续|优化|扫|查|拉|跑|写|实现|接线?|接上|重建|清理?|补|换|统一|迁移|部署?|生成|下载?|抓|截断|调整|替换|移除|精简|压缩|重写|拆分|排查|定位|升级|重构|测试?|验证|动手|开工|去办|效劳|合并|提交|推送|拉取|发布|打包|构建|编译|运行|执行|接入|对接|集成|配置|适配|调试|整理|格式化|搭|搭建|装|安装|更新)"
    r"|(?:听候差遣|听候吩咐|听候指令|听候安排)[^。？！?!\n]{0,15}?(?:由(?:你|您)|看(?:你|您)|等(?:你|您))?"
    r"|(?:由|看)(?:你|您)\s*(?:定夺|决断|安排|裁夺)"
    r"|(?:随时|随时可以|随时能够|随时准备|随时听候)\s*(?:为您?|为你?|为您效劳|吩咐|排查|开工|动手|处理|开始|修复|修改|改|做|干|搞|差遣|指令)"
    r"|(?:有需要|如有需要|需要的话|若有需要)[^。？！?!\n]{0,15}?(?:随时(?:叫我|找我|吩咐|联系|告知|通知|跟我说|对我说)|叫我一声|通知我)"
    r"|随时(?:叫我|找我|吩咐我|听候吩咐|听候差遣|听候指令)"
    r"|should i|shall i|do you want me to|want me to|would you like me to|let me know if you(?:'d| would) like me to"
    r"|if you (?:need|want|prefer|would like|wish|require)[^.?!]{0,30}?(?:i can|i will|i\'ll|i am ready to|let me know)"
    r"|let me know if you (?:need|want|would like|wish)"
    r"|just let me know and i (?:can|will|\'ll)"
    r"|ready whenever you are"
    r"|i\s*(?:can|will|\'ll|could)\s*[^.?!]{0,25}?(?:if you (?:would like|want|need|prefer|wish)|whenever you (?:want|wish|say|are ready))"
    r"|i\s*(?:am|\'m)\s*ready to\s*[^.?!]{0,25}?(?:whenever you|if you)"
    # ⛔ 2026-10-11 (Frank:「明明你能自动化帮我打开...留给我我自己手动做，还要我手动？」):
    #   形状: 把本该自己全自动做完的可逆操作/打开操作/配置还原,以陈述句方式甩锅给用户手动做。
    #   抓取: "你可以手动..." / "请自行点击..." / "通过该链接打开一次即可..." / "遗留事项供你决定...改回即可"
    r"|(?:(?:留给|交由?|需要|请|可由)\s*(?:你|您)|你可以?)\s*(?:手动|自己|自行|亲自)?\s*[^，。？！?!\n]{0,15}?(?:点|点击|打开|执行|运行|复制|修改|改回|改|调|弄|搞|处理|操作|访问)"
    r"|(?:通过|点击|打开)\s*(?:该|此|这个)?\s*(?:链接|url|网址|地址)\s*[^。？！?!\n]{0,25}?(?:即可|自行|手动)"
    r"|(?:若|如果|要是)\s*(?:你|您)\s*(?:希望|想|要)\s*[^。？！?!\n]{0,35}?(?:自行|手动|自己|改回|下次重启时\s*把[^。？！?!\n]{0,15}?改回)"
    r"|遗留事项\s*[(（]\s*供(?:你|您)决定\s*[)）]",
    re.I
)

NAG_EXEMPT = re.compile(
    r"删库|drop\s+table|force\s*push|覆盖.{0,6}(?:他人|别人)|发布到|发出去|发给(?!我)|上线到生产|部署到生产|"
    r"定价|报价|多少钱|每月.{0,4}(?:收费|价钱)|成本预算|产品(?:决策|设计|形态|方向|体验)|属于产品|页面(?:长|要).{0,4}(?:什么|哪|A还是B|布局)|"
    r"哪个平台|部署(?:到哪|目标)|不可逆|无法(?:撤销|revert|回退)|"
    r"(?:滑块|人机)验证|过.{0,3}(?:滑块|验证码)|重新登录|重登|扫码|短信验证码|你本人|只有你能",
    re.I
)

_CACHED_NO_NAG_MOD = None

def _get_no_nag_mod():
    global _CACHED_NO_NAG_MOD
    if _CACHED_NO_NAG_MOD is not None:
        return _CACHED_NO_NAG_MOD
    try:
        candidate_paths = [
            TG_HOOKS / "no-nagging-guard.py",
            SCRIPTS_DIR / "no-nagging-guard.py",
            Path.home() / ".superego" / "superego" / "no-nagging-guard.py",
            Path.home() / ".codex" / "hooks" / "no-nagging-guard.py",
        ]
        no_nag_path = next((p for p in candidate_paths if p.exists()), None)
        if no_nag_path:
            hooks_dir = str(no_nag_path.parent)
            if hooks_dir not in sys.path:
                sys.path.insert(0, hooks_dir)
            import importlib.util
            spec = importlib.util.spec_from_file_location("no_nagging_guard", str(no_nag_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _CACHED_NO_NAG_MOD = mod
            return _CACHED_NO_NAG_MOD
    except Exception:
        pass
    return None

def check_no_nagging_violation(text, user_prompt=""):
    """Unified Antigravity implementation of no-nagging-guard via 4-stage funnel."""
    if not text:
        return None

    tail = text[-1200:]
    # 1. 快速前置过滤：若无嫌疑词，0.01ms 光速放行（保证高频压测平均 0.05ms / p99 < 1ms）
    if not NAG_WORDS.search(tail):
        return None

    # 2. 业务白名单快速短路 (产品决策 / 真不可逆操作 / 人机滑块)
    if NAG_EXEMPT.search(tail):
        return None

    # 3. 语法结构脱敏：剥离代码块后检测，若仅存在于代码块中直接放行
    #    2026-09-26 AG 核出(第 7 条):原来先截 tail 再剥代码块,块在 1200 字前开头时只剩闭合围栏、剥不掉 ⇒ 块内请示句被当正文拦。
    #    改成先在全文剥、再取尾。
    clean_full = re.sub(r"```[\s\S]*?```", "", text)
    clean_full = re.sub(r"`[^`\n]+`", "", clean_full)
    clean_tail = clean_full[-1200:]
    m = NAG_WORDS.search(clean_tail)
    if not m:
        return None

    # 4. 调用单源母库 no-nagging-guard.py 进行 AST 引述检测与语义降级
    try:
        mod = _get_no_nag_mod()
        if mod and hasattr(mod, "check_text"):
            res = mod.check_text(text, user_prompt)
            if res:
                return res
            # 防范将推诿伪装在引用符 `>` 中的变体（strip_doc 会剥离 > 行，需补漏）
            last_line = clean_tail.strip().split("\n")[-1].strip()
            if m.group(0) in last_line and not any(k in last_line for k in ("# 教训", "规则", "案例")):
                return (
                    f"[TruthGate 拦截 - no-nagging-guard] ⛔ 检测到【请示式收尾 / 废话推诿句式】（命中: 「{m.group(0)}」）！\n"
                    "按 CLAUDE.md 授权即执行铁律：授权即执行，能 revert 的可逆技术活直接做完，严禁说「如果你需要我就做 / 要不要我做 / 只要你说一声」！\n"
                    "按 Vibe Coder 铁律：技术决策(改哪、删哪行、重建还是退役)你自己定，别甩给零编程的用户。\n"
                    "现在【别问废话，直接做完再汇报】！"
                )
            return None
    except Exception:
        pass

    # 5. 离线/模块异常时的确定性兜底
    window = clean_tail[max(0, m.start() - 30): min(len(clean_tail), m.end() + 30)]
    if not NAG_QUOTING_HISTORIC.search(window):
        return (
            f"[TruthGate 拦截 - no-nagging-guard] ⛔ 检测到【请示式收尾 / 废话推诿句式】（命中: 「{m.group(0)}」）！\n"
            "按 CLAUDE.md 授权即执行铁律：授权即执行，能 revert 的可逆技术活直接做完，严禁说「如果你需要我就做 / 要不要我做 / 只要你说一声」！\n"
            "按 Vibe Coder 铁律：技术决策(改哪、删哪行、重建还是退役)你自己定，别甩给零编程的用户。\n"
            "现在【别问废话，直接做完再汇报】！"
        )

    return None

def _fresh_once(tag, conv_id, text):
    """AG 一轮收尾会调桥接 3 次(全局两组 + 插件一组都接了 Stop):同一会话、同一段回复、同一件事只记一次账。考卷 / 测试不留标记。"""
    import hashlib
    if os.environ.get("SUPEREGO_TEST") == "1":
        return True
    mark = TG_SEM / f".{tag}_{(conv_id or 'ag')[:8]}"
    sig = hashlib.md5((text or "").encode("utf-8", "ignore")).hexdigest()[:12]
    try:
        if mark.exists() and mark.read_text(encoding="utf-8") == sig:
            return False
        mark.write_text(sig, encoding="utf-8")
    except Exception:
        pass
    return True


def check_delivery(gate, items, tool_calls, user_prompt="", conv_id="", text=""):
    """交付自检(2026-09-27,PLAN.md 第 3 步):只看本轮做了什么 —— 改了网页 / 接口代码,改完之后跑没跑浏览器、听没听控制台、
    看没看截图、发没发请求。判据与 Claude 端 anti-toy-test-gate / visual-proof-gate 同一份(~/.truthgate/delivery_check.py)。"""
    for p in (str(SCRIPTS_DIR), str(TG_HOOKS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from delivery_check import missing, message, OBSERVE_ITEMS, SKIP_ASK
    from evidence_table import actions_from_ag
    if user_prompt and SKIP_ASK.search(user_prompt):
        return None
    ws = re.sub(r"^file:/+", "", _AG_WS or "")
    gaps = missing(actions_from_ag(tool_calls, cwd=ws), items)
    watch = [(p, [m for m in miss if m in OBSERVE_ITEMS]) for p, miss in gaps]
    gaps = [(p, [m for m in miss if m not in OBSERVE_ITEMS]) for p, miss in gaps if any(m not in OBSERVE_ITEMS for m in miss)]
    if any(miss for _, miss in watch) and _fresh_once("delivery_" + gate, conv_id, text + gate):
        from guard_common import hook_log
        for p, miss in watch:
            if miss:
                hook_log(gate, "WOULDBLOCK(" + ",".join(miss) + f") ag={(conv_id or '-')[:8]}", p)
    return f"[TruthGate 拦截 - {gate}] " + message(gate, gaps) if gaps else None


def check_visual_proof_violation(text, assistant_tool_calls, assistant_blob, user_prompt="", conv_id=""):
    """Checks if visual-proof-gate should fire.
    ① 桌面弹窗真实性:说「弹出来了 / 已在浏览器打开」⇒ 对照主桌面真实窗口(事实核对,AG 独有)。
    ② 2026-09-27 第 3 步起「眼见为实」只看动作记录:改了网页文件 ⇒ 改完之后要截图并打开看过(delivery_check.py,与 Claude 端同一份)。
       原来的措辞路径(「正常 / 健康」挨着「页面 / 浏览器」、「改好了」+ 改过前端)删掉:在解释 / 举例里误拦,见考卷 c041、c045。"""
    if not text:
        return None

    # 1. 桌面弹窗真实性检查 (Desktop Window Reality Check)
    m_desk = desktop_claim(text)
    if m_desk:
        claim_snippet = m_desk.group(0)
        desk_wins = get_default_desktop_windows()
        has_matched_window = False
        ports = re.findall(r':(\d{4,5})\b', text)
        if ports:
            for p in ports:
                if any(p in w.lower() for w in desk_wins):
                    has_matched_window = True
                    break
        else:
            target_keys = [k for k in ("all for one", "dola", "runninghub", "gallery") if k in text.lower()] + _claimed_page_keys(text)
            has_matched_window = any(k in w.lower() for k in target_keys for w in desk_wins)
        has_real_screen_shot = False
        for tc in assistant_tool_calls:
            args = str(tc.get("args", {}) or tc.get("arguments", {}))
            if any(kw in args.lower() for kw in ("real_screen", "desktop_shot", "fullscreen", "screen_bounds")):
                has_real_screen_shot = True
                break
        if "real_screen" in assistant_blob.lower():
            has_real_screen_shot = True

        if not has_matched_window and not has_real_screen_shot:
            return (
                f"[TruthGate 拦截 - visual-proof-gate / desktop-window-phantom] 🚨 触发硬红线拦截：\n"
                f"检测到在回复中声称「{claim_snippet}」（桌面弹出/已在浏览器中打开），\n"
                f"但当前物理主桌面 (WinSta0\\default) 真实窗口枚举中查无对应可见视窗！\n"
                f"铁律规定：严禁将后台无头沙盒执行 (如 headless Playwright / background cmd) 脑补为前台真机弹窗！\n"
                f"当前物理桌面可见视窗清单：{[w[:30] for w in desk_wins[:8]]}\n"
                f"必须出示真实物理桌面可见视窗凭据方可放行！"
            )

    # ② 眼见为实:只看动作记录 —— 改了网页文件 ⇒ 最后一次改完之后要截图并打开看过
    vio = check_delivery("visual-proof-gate", {"shot"}, assistant_tool_calls, user_prompt, conv_id, text)
    if vio:
        return vio

    # ③ 说桌面上弹出来了 / 已在浏览器打开:看过的图得是真桌面截图,不能拿无头浏览器截的局部图冒充
    if not m_desk:
        return None
    viewed_images = []
    for tc in assistant_tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        args = fn.get("args", {}) or fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        if isinstance(args, dict):
            if name == "view_file":
                path = args.get("AbsolutePath", "") or args.get("path", "")
                if path.lower().endswith(IMAGE_EXTENSIONS):
                    viewed_images.append(path)
            if name in ("desktop_window_shot", "captureScreenshot", "take_screenshot"):
                viewed_images.append(name)
    if not viewed_images:
        return (
            "[TruthGate 拦截 - visual-proof-gate] 你说桌面上弹出来了 / 已在浏览器打开，但本轮一张画面都没看过。"
            "先截一张真桌面的图、用 view_file 打开看过再说。"
        )
    has_real_grounding = any(any(k in img.lower() for k in ("real_screen", "desktop", "fullscreen", "screen_bounds")) for img in viewed_images)
    if not has_real_grounding:
        return (
            "[TruthGate 拦截 - visual-proof-gate / headless-mock-fraud] 🚨 触发硬红线拦截：\n"
            "检测到在声称宿主桌面打开/弹出视窗时，仅查验了后台无头沙盒爬虫生成的局部图片，\n"
            "而非通过系统 GDI 或窗口捕获的真实物理桌面 (WinSta0\\default) 画面！\n"
            "严禁用无头浏览器（headless Playwright）自导自演假截图冒充桌面真实弹窗交付！"
        )
    return None

# ── Model Authenticity Gate ──────────────────────────────────────────────────
# Prevents hallucinating generic cliché models (gpt-4o, claude-3-5-sonnet, etc.)
# and enforces querying ~/.cc-switch/cc-switch.db for any model claims.
CC_SWITCH_DB = Path.home() / ".cc-switch" / "cc-switch.db"

CLICHE_FAKE_MODELS = re.compile(
    r"\b(gpt-4o|gpt-4-turbo|gemini-2\.5-pro|gemini-1\.5-pro|claude-3-5-sonnet|claude-3-opus|claude-2)\b",
    re.I
)

MODEL_TOPIC_RE = re.compile(
    r"(?:哪个|什么|底层|主力|实际|部署|使用|切换|调用|记录|案卷|历史|教训).*?(?:模型|IDE|cc-switch|代理)|"
    r"(?:模型|IDE).*?(?:列表|分布|统计|清单|名单|表现|走过|弯路|挨过|防范|细则)",
    re.I
)

QUOTING_HISTORIC_OR_REFUTING = re.compile(
    r"(?:幻觉|编造|错误|并非|不是|修正|废弃|收回|复盘|严禁|教训|所谓|阻断|门禁|拦截|非本机模型|假模型|虚假).*?(?:gpt-4o|claude-3-5-sonnet|gemini-2\.5-pro|3\.7|4o)",
    re.I | re.DOTALL
)

def check_model_authenticity_violation(text, assistant_tool_calls, assistant_blob, user_prompt=""):
    """Blocks turns with fake models or ungrounded model claims."""
    if not text:
        return None

    # Collect only assistant-generated text and files written/modified by assistant
    generated_contents = [text]
    for tc in assistant_tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        if name in ("write_to_file", "replace_file_content", "edit"):
            args = fn.get("args", {}) or fn.get("arguments", {})
            code = ""
            if isinstance(args, dict):
                code = str(args.get("CodeContent", "") or args.get("ReplacementContent", "") or "")
            elif isinstance(args, str):
                code = args
            if code:
                generated_contents.append(code)

    combined_output = "\n".join(generated_contents)

    # Check 1: Output generic fake models without refuting/apologizing
    cliche_match = CLICHE_FAKE_MODELS.search(combined_output)
    if cliche_match:
        bad_model = cliche_match.group(1)
        if not QUOTING_HISTORIC_OR_REFUTING.search(text):
            return (
                f"[TruthGate 拦截 - model-authenticity-gate] 检测到在回复或生成资产中出现了公版刻板印象模型名【{bad_model}】！\n"
                f"本机运行着 CC Switch 代理并存储有真实账本（~/.cc-switch/cc-switch.db）。\n"
                f"铁律 2026-09-14-C 规定「严禁凭空捏造公版模型，必须以本地数据库 5 万条记录为唯一基准」。\n"
                f"请先查询本地真实数据库（`~/.cc-switch/cc-switch.db`），根据真实调用模型进行交付！"
            )

    # Check 2: Model inquiry by user or assistant asserted model claims
    is_model_topic = False
    if user_prompt and MODEL_TOPIC_RE.search(user_prompt):
        is_model_topic = True
    elif MODEL_TOPIC_RE.search(text):
        is_model_topic = True

    if not is_model_topic:
        return None

    # Check if cc-switch.db was queried in this turn
    has_queried_db = False
    blob_lower = assistant_blob.lower()
    if "cc-switch.db" in blob_lower or "cc_switch" in blob_lower or "cc-switch" in blob_lower:
        has_queried_db = True

    for tc in assistant_tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        args = str(fn.get("args", "") or fn.get("arguments", "")).lower()
        if "cc-switch" in args or "cc_switch" in args:
            has_queried_db = True
            break

    # If asking about models but didn't query cc-switch.db
    if not has_queried_db:
        if user_prompt and re.search(r"(?:哪个模型|什么模型|ide和模型|全部模型|主力模型|模型列表)", user_prompt):
            return (
                "[TruthGate 拦截 - model-authenticity-gate] 用户询问了模型/IDE相关账本，"
                "但本轮交互中未曾查验 CC Switch 真实调用数据库（~/.cc-switch/cc-switch.db）。\n"
                "铁律规定：涉及本机模型与路由，必须先查询真实数据库，严禁凭印象脑补！"
            )
    return None

# ── Honest Scope & Execution Telemetry Gate (Supreme Directive #1) ───────────
# Shape 2026-09-19-AO: Zero tolerance for lying, bluffing, or claiming exhaustive completion
# (e.g. reading all docs, executing all tests, full inspection) when tool execution telemetry shows only sampling.

EXHAUSTIVE_READ_CLAIM_RE = re.compile(
    r"(?:已(?:遵照|按照|根据).*?(?:全部|所有).*?(?:调阅|阅读|看[完了过]|完成)|"
    r"(?:全部|所有|每一个|各个).*?(?:文档|页面|网页|链接|接口|源码|Cookbook|手册).*?(?:逐[页篇个条]|都已|都已经|全部|都看[完了过]|都调阅|都执行|都跑通|都覆盖)|"
    r"逐[页篇个条](?:调阅|阅读|看[完了过]|分析|拆解)|"
    r"遍历了(?:所有|全部)|"
    r"把(?:所有|全部|每一个).*?(?:看[完了过]|读[完了过]|调阅|研读))",
    re.I
)

EXHAUSTIVE_TEST_CLAIM_RE = re.compile(
    r"(?:全部|所有|全量|各个).*?(?:测试|门禁|单测|回归|拦截).*?(?:通过|跑通|全绿|完成|跑过|已完成|物理拦截)|"
    r"(?:已全量|全部).*?(?:回归|跑了一遍|测试了一遍|物理拦截)",
    re.I
)

HONEST_DISCLOSURE_RE = re.compile(
    r"(?:仅调阅|只调阅|仅阅读|只阅读|只看了|仅看了|抽样调阅|部分调阅|未读清单|尚未调阅|尚有.*?未读|实际调阅了?\s*\d+|实际精读了?\s*\d+)",
    re.I
)

HONEST_TEST_DISCLOSURE_RE = re.compile(
    r"(?:\d+\s*/\s*\d+|仅测试了?\s*\d+|抽样测试|部分测试|实弹打靶\s*\d+\s*道|尚有\s*\d+\s*道未)",
    re.I
)

def check_honest_scope_violation(text, assistant_tool_calls, assistant_blob, user_prompt=""):
    """Enforces honest-scope-assertion-gate (Supreme Directive #1):
    Hard-blocks any turn where assistant claims exhaustive completion (e.g. reading all docs, passing all tests)
    without actual tool telemetry to prove it."""
    if not text:
        return None

    # Exclude pure historic case studies or postmortem quotes
    if re.search(r"(?:^#\s*教训|教训案例库|【形状 20\d\d|历史案卷|历史教训)", text):
        return None

    # 0. 审核工程实体真实性 (严禁凭空捏造虚构项目)
    try:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        from honest_scope_gate import check_project_grounding
        ok_proj, err_proj = check_project_grounding(text)
        if not ok_proj and err_proj:
            return f"[TruthGate 拦截 - honest-scope-assertion-gate] {err_proj}"
    except Exception:
        pass

    blob_lower = (assistant_blob or "").lower()

    # 1. Audit reading claims
    m_read = EXHAUSTIVE_READ_CLAIM_RE.search(text)
    if m_read:
        # Check if the text explicitly disclaimed the scope (honest disclosure: e.g. "仅精读了 8 篇，尚有 46 篇未读")
        if not HONEST_DISCLOSURE_RE.search(text):
            # Count actual reading tool calls in this turn
            read_urls = set()
            read_files = set()
            for tc in assistant_tool_calls:
                fn = tc.get("function", {}) if "function" in tc else tc
                name = fn.get("name", "")
                args = fn.get("args", {}) or fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                if isinstance(args, dict):
                    if name == "read_url_content":
                        u = args.get("Url", "")
                        if u:
                            read_urls.add(u)
                    elif name == "view_file":
                        f = args.get("AbsolutePath", "") or args.get("path", "")
                        if f and not any(f.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
                            read_files.add(f)

            # Also check assistant_blob for URL reads
            for m in re.finditer(r'"Url":\s*"([^"]+)"', assistant_blob or ""):
                read_urls.add(m.group(1))

            total_reads = len(read_urls) + len(read_files)
            user_demanded_all = bool(re.search(r"(?:每一个|全部|所有).*?(?:文档|网页|页面|链接).*?(?:看完|读完|看过了|阅读完)", user_prompt or ""))

            if total_reads < 20 or (user_demanded_all and total_reads < 30):
                matched = m_read.group(0)[:35]
                return (
                    f"[TruthGate 拦截 - honest-scope-assertion-gate] 🚨 触发最高第一铁律【严禁虚假履职与夸大欺诈】：\n"
                    f"检测到回复中断言了全量/穷尽式调阅（命中:「{matched}」），\n"
                    f"但当前回合工具执行流水（Execution Telemetry）显示：实际仅抓取了 {len(read_urls)} 个网页 / {len(read_files)} 个代码文件！\n"
                    f"铁律规定：\n"
                    f"① 严禁『用局部抽样冒充全量穷尽』，做多少说多少，严禁欺诈用户！\n"
                    f"② 若未穷尽阅读，必须如实向用户出具【定量对账单】（明确说明仅调阅了 M 篇，尚有 N 篇未读清单）；\n"
                    f"③ 若用户明确要求「每一个必须看完才回答」，必须在后台继续调用工具逐一读完全部文档，直到物理穷尽后再交付！"
                )

    # 2. Audit testing claims
    m_test = EXHAUSTIVE_TEST_CLAIM_RE.search(text)
    if m_test:
        # Check honest quantitative disclosure (e.g. 5/115, 仅测试了 5 道)
        if not HONEST_TEST_DISCLOSURE_RE.search(text):
            matched = m_test.group(0)[:30]
            return (
                f"[TruthGate 拦截 - honest-scope-assertion-gate] 🚨 触发最高第一铁律【严禁用模糊语言宣称全量测试/全量门禁拦截完成】：\n"
                f"检测到断言了全量测试/门禁拦截（命中:「{matched}」），但未出具精确量化对账单（如 5/115 或 仅测试了 5 道）！\n"
                f"铁律规定：严禁用「全部门禁完成物理拦截」等模糊断言糊弄用户，必须明示已实测数与总数（如 M/N），"
                f"或出示物理覆盖率达到 100% 的机器测试报告！"
            )

        has_test_cmd = False
        for tc in assistant_tool_calls:
            fn = tc.get("function", {}) if "function" in tc else tc
            name = fn.get("name", "")
            args = fn.get("args", {}) or fn.get("arguments", {})
            cmd = ""
            if isinstance(args, dict):
                cmd = str(args.get("CommandLine", "") or args.get("command", "")).lower()
            elif isinstance(args, str):
                cmd = args.lower()
            if any(k in cmd for k in ("test", "pytest", "regression", "run_test", "check.py", "check")):
                has_test_cmd = True
                break

        if not has_test_cmd and not ("test" in blob_lower and "regression" in blob_lower):
            matched = m_test.group(0)[:30]
            return (
                f"[TruthGate 拦截 - honest-scope-assertion-gate] 🚨 触发最高第一铁律【严禁虚假测试断言】：\n"
                f"检测到回复中断言了全量测试通过（命中:「{matched}」），\n"
                f"但当前回合工具执行流水中【零次执行测试命令】（未运行 pytest / test 脚本）！\n"
                f"铁律规定：严禁空脑宣称测试通过，必须在当前轮次实际运行全量回归命令并取得全绿日志后，方可放行！"
            )

    return None

# ── No-Search-No-Claim & Search-Breadth Gates ────────────────────────────────
NOT_EXIST_RE = re.compile(
    r"项目里(?:从来)?(?:都)?没有|从来没有过|从没有过|压根没有|根本没有(?!人)"
    r"|(?:完全)?没有任何(?:记录|痕迹|东西|文件|脚本|工具|接口)"
    r"|(?:这个|那个|该)?(?:网址|入口|链接|地址|凭据|账号|密码|路径|文件|脚本|工具)[^。\n]{0,12}(?:我这边)?(?:确实)?没有"
    r"|我这边(?:完全)?没有(?:记录|这个|那个|任何)"
    r"|查不到(?:任何)?(?:记录|东西|它)|不存在(?:这个|任何)?"
    r"|(?:doesn't|does not|didn't) exist|no such (?:file|record|script|tool)|not (?:in|found in) (?:the )?(?:project|repo)",
    re.I
)

POLICY_CLAIM_RE = re.compile(
    r"违反(?:了)?(?:上游|平台|官方)?(?:规则|服务条款|协议|政策|TOS|AUP)"
    r"|(?:服务条款|平台协议|官方)(?:明文)?(?:禁止|不允许|规定)"
    r"|多账号(?:属于)?违规|会(?:导致)?(?:连坐)?封号|侵犯了?.*?条款|违反条款",
    re.I
)

USER_VERIFY_QUERY_RE = re.compile(
    r"(?:有没有|是否|能不能|算不算|到底有没有|是否存在).*(?:违反|规则|条款|政策|限制|封号|小号|做过|支持|存在|现成)",
    re.I
)

# (2026-10-02 删:AG 端自己那份「领域级断言」词表 DOMAIN_CLAIM_SRC —— 检索广度检查改用共用判据 six_universes.py)

CLAIM_HIST_RE = re.compile(r"(?:上一轮|之前|昨天|历史上|曾经|原话|引述|复述|教训|lessons|形状 ?20\d\d|这类结论|这种结论|下次(?:要|再|该)|以后(?:要|再|该)|反向指纹)")
CLAIM_PHYSICAL_RE = re.compile(r"扫码|滑块|验证码|手机(?:在你|上|里)|你的手机|人脸|指纹|插(?:手机|USB)|物理设备|只有你(?:本人)?能(?:点|扫|输|操作)")

def extract_antigravity_search_channels(tool_calls, blob):
    """Detects distinct information channels used in the turn."""
    channels = set()
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        args = str(fn.get("args", {}) or fn.get("arguments", {}))
        
        if name in ("search_web", "read_url_content"):
            channels.add("web")
        elif name in ("grep_search", "find_by_name", "codegraph_explore"):
            channels.add("local_code")
        elif name == "call_mcp_tool" and "codegraph" in args.lower():
            channels.add("local_code")
        elif "gemini_search_docs" in name or "gemini_get_doc" in name:
            channels.add("official_docs")
        elif name == "run_command":
            cmd = args.lower()
            if any(k in cmd for k in ("arxiv", "scholar", "huggingface", "api.github")):
                channels.add("academic_or_api")
            if any(k in cmd for k in ("reddit", "news.ycombinator", "v2ex", "zhihu", "juejin", "tieba", "bilibili")):
                channels.add("community_forum")
            if any(k in cmd for k in ("duckduckgo", "startpage", "searxng", "google", "bing", "easy_anysearch", "last30days", "curl", "requests", "urllib")):
                channels.add("web")
            if any(k in cmd for k in ("grep", "rg ", "find ", "select-string", "dir ", "codegraph")):
                channels.add("local_code")

    blob_lower = blob.lower()
    if "search_web" in blob_lower or "read_url_content" in blob_lower:
        channels.add("web")
    if "grep_search" in blob_lower or "find_by_name" in blob_lower or "codegraph" in blob_lower:
        channels.add("local_code")
    if any(k in blob_lower for k in ("v2ex", "zhihu", "reddit", "ycombinator", "juejin")):
        channels.add("community_forum")
    if any(k in blob_lower for k in ("arxiv", "chroma", "aclanthology", "crossref")):
        channels.add("academic_or_api")

    return channels

def check_no_search_no_claim_violation(text, tool_calls, blob, user_prompt=""):
    """Enforces no-search-no-claim-gate: Claiming absence/non-existence or platform rules without search is forbidden."""
    if not text:
        return None
    tail = text[-2000:]
    if CLAIM_HIST_RE.search(tail):
        return None
    if CLAIM_PHYSICAL_RE.search(tail):
        return None

    channels = extract_antigravity_search_channels(tool_calls, blob)

    # 1. External policy / rules / TOS assertion without web search
    m_policy = POLICY_CLAIM_RE.search(tail)
    if m_policy and ("web" not in channels):
        matched = m_policy.group(0)[:30]
        return (
            f"[TruthGate 拦截 - no-search-no-claim-gate] 本轮断言了外部平台规则/服务条款/违规风险（命中:「{matched}」），"
            f"但整轮交互中【零次执行联网检索工具】（未运行 search_web 或 read_url_content）！\n"
            f"全局铁律规定：涉及外部平台政策、服务条款与违规判定，必须先抓取并查阅官方第一手协议原件，严禁空脑凭通用常识臆断！"
        )

    # 2. Local code / file absence assertion without any search tool
    m = NOT_EXIST_RE.search(tail)
    if m and not channels:
        matched = m.group(0)[:30]
        return (
            f"[TruthGate 拦截 - no-search-no-claim-gate] 本轮断言了【否定/不存在/查不到/项目缺失】（命中:「{matched}」），"
            f"但整轮交互中【零次执行搜索工具】（未运行 grep_search, find_by_name, search_web 或查找命令）！\n"
            f"全局铁律规定：严禁空脑断言不存在，必须在当前轮次完成真实搜索查证后再下结论！"
        )

    # 3. User verify query without any search tool
    if user_prompt and USER_VERIFY_QUERY_RE.search(user_prompt):
        if not channels:
            matched_prompt = user_prompt[:40]
            return (
                f"[TruthGate 拦截 - no-search-no-claim-gate] 用户质询了平台规则/客观存在性（「{matched_prompt}」），"
                f"但助手在整轮交互中【零次执行搜索/查证工具】，直接给出了定性回答！\n"
                f"全局铁律规定：面对用户求证型质询，严禁直接脑补盲答，必须先调用搜索工具（search_web / read_url_content / grep_search 等）获取第一手客观依据！"
            )

    return None

def check_search_breadth_violation(text, tool_calls, blob):
    """search-breadth-gate(AG 端):领域级断言要覆盖 ≥3 个宇宙且含①本机。
    2026-10-02 起判据与 Claude 端 hooks/search-breadth-gate.py 同一份(six_universes.judge)。
    原来这里自己一份词表 + 「≥2 种通道」:「100%」「绝对不能」也算领域断言,9/29~10/02 只记账里 AG 端的全是这类。
    AG 这边只数本轮的工具调用(Claude 端数最近 3 轮)、量不到每条结果多大(空管道那条只在 Claude 端生效)。"""
    if not text:
        return None
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    try:   # 导入 / 判决出错只丢这一道,别让整个结构闸评估跟着抛(外审 10-02)
        from six_universes import judge, channels_from_ag, probes_from_ag, probe_verdict, strict_channels_from_ag
        v = judge(text[-1500:], channels_from_ag(tool_calls))
        # 2026-10-04:翻过别人软件的安装目录却一次网都没上 ⇒ 拦(只看事实,用严格通道:本机 grep 里出现域名不算联网)。
        #   AG 只有一把联网工具(search_web 算一个宇宙),所以这边查过一次就放(need=1);Claude 端要两个外部宇宙。
        if not v:
            v = probe_verdict(strict_channels_from_ag(tool_calls), probes_from_ag(tool_calls), need=1)
    except Exception:
        return None
    return "[TruthGate 拦截 - search-breadth-gate] " + v[1] if v else None

def check_institutionalize_violation(text, tool_calls, blob):
    """Enforces institutionalize-guard: Writing a reusable script must be accompanied by registering into CLI or SKILL."""
    has_written_script = False
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        if name in ("write_to_file", "replace_file_content", "edit"):
            args = fn.get("args", {}) or fn.get("arguments", {})
            target = ""
            if isinstance(args, dict):
                target = str(args.get("TargetFile", "") or args.get("path", "") or "")
            elif isinstance(args, str):
                target = args
            # Exclude scratch, tmp, tests
            if re.search(r'\.(?:py|mjs|cjs|js|ts|sh|ps1)$', target, re.I):
                if not re.search(r'scratch|\btmp\b|\btemp\b|\.bak|\btest', target, re.I):
                    has_written_script = True
                    break
    if not has_written_script:
        return None

    # Check evidence of institutionalization (SKILL.md or CLI registration or lessons.md update)
    has_institutionalized = False
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        if name in ("write_to_file", "replace_file_content", "edit"):
            args = str(fn.get("args", "") or fn.get("arguments", ""))
            if "skill.md" in args.lower() or "lessons.md" in args.lower():
                has_institutionalized = True
                break
    if not has_institutionalized:
        if re.search(r"注册.{0,8}skill|更新.{0,6}SKILL|做成 ?CLI|固化.{0,6}(cli|skill)|可复用", text, re.I):
            has_institutionalized = True

    if not has_institutionalized:
        return (
            "[TruthGate 拦截 - institutionalize-guard] 本轮新建或修改了可复用脚本，但未将其固化沉淀为规范资产（未注册/更新全局 SKILL.md、未做成常态可复用 CLI 或未记入 lessons.md）！\n"
            "全局铁律规定：严禁『催一次动一次』的一次性脚本应付，产出的任何可复用能力必须立即固化成长期复用资产！"
        )
    return None

def check_process_alias_violation(text, blob):
    """Enforces process-alias-attribution-gate: Scapegoating unrelated processes without PE fingerprint verification is forbidden."""
    gate_py = TG_HOOKS / "process-alias-attribution-gate.py"
    if not gate_py.exists():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("process_alias_gate", str(gate_py))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "check_text"):
            return mod.check_text(text, blob)
    except Exception:
        pass
    return None

# ── Cross-Brain Retrieval Gate ────────────────────────────────────────────────
CROSS_BRAIN_TOPIC_RE = re.compile(
    r"(?:codex|claude|跨项目|脑库|之前做过|以前做过|曾经做过|做过没|有没做过|历史做过|上次做过|别的项目|其他项目|他做了什么|他在做什么|本来就有|不是本来就|chat\s*archiver?|查真相|以前不是|不是早做过|以前怎么做|历史记录)",
    re.I
)

def check_cross_brain_retrieval_violation(text, tool_calls, blob, user_prompt):
    """Enforces cross-brain-retrieval-gate:
    When user inquires about Codex, Claude, cross-project history, or prior capabilities ("不是本来就有吗"),
    assistant is strictly forbidden from guessing via git/files; it MUST query the brain databases."""
    if not user_prompt:
        return None
    if not CROSS_BRAIN_TOPIC_RE.search(user_prompt):
        return None

    # Check if assistant queried brain DBs or thread histories
    blob_lower = (blob or "").lower()
    has_queried_brain = False
    
    brain_indicators = (
        "ag_archive", "codex_archive", "codex-brain", "ag-brain", "brain.db",
        "thread_history_1.sqlite", "thread_items", "codex_threads", "codex_messages",
        "query_cross_projects", "dump_thread", "q-sessions", "q-session", "q-frank",
        "q-window", "q-full", "q.js", "chat-archive", "chat_archive"
    )
    if any(k in blob_lower for k in brain_indicators):
        has_queried_brain = True

    if not has_queried_brain:
        for tc in tool_calls:
            fn = tc.get("function", {}) if "function" in tc else tc
            args = str(fn.get("args", "") or fn.get("arguments", "")).lower()
            if any(k in args for k in brain_indicators):
                has_queried_brain = True
                break

    if not has_queried_brain:
        return (
            "[TruthGate 拦截 - cross-brain-retrieval-gate] 检测到用户询问了 Codex / Claude / 历史既有能力（「查真相/不是本来就有吗」），\n"
            "但本轮交互中未曾查验历史真实脑库（chat-archive-db 或 ~/.codex/thread_history_1.sqlite）。\n"
            "铁律规定：真实脑库已打通，严禁凭借 Git 提交或代码瞎猜推测历史事实！\n"
            "必须先运行 `py -3 ag_archive.py search` / `q.js` 调阅第一手对话与设计定论后再交付！"
        )
    return None

# ── CodeGraph Topology Gate ───────────────────────────────────────────────────
INVESTIGATION_TOPIC_RE = re.compile(
    r"(?:为什么.*(?:报错|失败|坏了|不行|异常|出问题)|排查.*(?:bug|故障|问题|报错)|查真相|双向.*codegraph|不是本来就有)",
    re.I
)
CLAIM_ROOTCAUSE_OR_FIX_RE = re.compile(
    r"(?:修复完毕|排查发现|已经修复|根因是|原来是|问题在于|经排查|经核实|已搞定|已解决|彻底解决)",
    re.I
)

def check_codegraph_topology_violation(text, tool_calls, blob, user_prompt, cwd=None):
    """Enforces codegraph-topology-gate:
    When investigating bug rootcause in an indexed codebase, assistant MUST run codegraph exploration
    to verify bidirectional callers/callees before declaring conclusions."""
    if not user_prompt or not INVESTIGATION_TOPIC_RE.search(user_prompt):
        return None
    if not CLAIM_ROOTCAUSE_OR_FIX_RE.search(text or ""):
        return None

    # Check if current repo or cwd has .codegraph
    has_codegraph = False
    if cwd:
        check_paths = [Path(cwd)]
    else:
        check_paths = [Path.cwd(), Path("e:/social_media_to_tg")]
    for p in check_paths:
        try:
            if (p / ".codegraph").exists():
                has_codegraph = True
                break
        except Exception:
            pass
    if not has_codegraph:
        return None

    # Check if codegraph was queried
    blob_lower = (blob or "").lower()
    has_queried_cg = "codegraph" in blob_lower
    if not has_queried_cg:
        for tc in (tool_calls or []):
            fn = tc.get("function", {}) if "function" in tc else tc
            name = (fn.get("name") or "").lower()
            args = str(fn.get("args", "") or fn.get("arguments", "")).lower()
            if "codegraph" in name or "codegraph" in args:
                has_queried_cg = True
                break

    if not has_queried_cg:
        return (
            "[TruthGate 拦截 - codegraph-topology-gate] 当前工程包含 .codegraph 索引，且正在排查既有功能故障/查真相，\n"
            "但本轮未曾调用 `codegraph_explore` 执行双向拓扑核验（上游 Callers + 下游 Callees）！\n"
            "铁律规定：排查既有链路必须通过 CodeGraph 双向摸清代码接线再下定论！"
        )
    return None

GUI_RESTART_CMD_RE = re.compile(
    r"(?:Stop-Process|taskkill).*?(?:DSH Desktop|cursor|code|chrome|msedge|telegram|wechat)",
    re.I
)
GUI_RESTART_CLAIM_RE = re.compile(
    r"(?:重启|重新拉起|热加载并重启|已重启).*?(?:就绪|完成|搞定|可以用了|打开.*?窗口|在窗口中)",
    re.I
)

def check_stale_process_violation(text, tool_calls):
    """改了没生效（2026-10-05，和 Claude 端同一条事实检查 stale_process.py）：
    本轮工具调用里提到的配置 / 代码文件刚改过，读它的程序却还是改之前启动的 ⇒ 拦。
    回复里写明「<程序> 会自动重读 / 自己写 <文件>」⇒ 放（有的程序会自己改写配置，如 DSH 切模型）。"""
    if re.search(r"(?:自动|自己|会)重读|自己(?:会)?(?:改)?写", text or ""):
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stale_process
        v = stale_process.verdict_ag(tool_calls or [])
    except Exception:
        return None
    return ("[TruthGate 拦截 - anti-toy-test-gate] " + v[1]) if v else None


def check_gui_process_restart_violation(text, tool_calls, blob):
    """Enforces gui-process-restart-gate (Shape 2026-09-18-I):
    When assistant kills and restarts a desktop GUI application via command line,
    it is strictly forbidden from claiming the GUI app/window is ready or telling user to use the window
    without explicitly acknowledging that background sub-processes cannot guarantee foreground window display,
    or verifying true desktop window visibility."""
    if not text:
        return None
    cmd_str = blob or ""
    for tc in (tool_calls or []):
        fn = tc.get("function", {}) if "function" in tc else tc
        args = fn.get("args", {}) or fn.get("arguments", {})
        if isinstance(args, dict):
            cmd_str += " " + str(args.get("CommandLine", "") or args.get("command", "")) + " "
        elif isinstance(args, str):
            cmd_str += " " + args + " "
    if not GUI_RESTART_CMD_RE.search(cmd_str):
        return None
    if not GUI_RESTART_CLAIM_RE.search(text):
        return None
    
    # Check if assistant acknowledged background/tray limitations or provided manual/explorer foreground guidance
    safe_ack = re.search(r"(?:后台子进程|托盘|前台|双击|快捷方式|WinSta0|桌面图标|无法直接弹到前台|请在前台打开|防抢焦点|右下角)", text)
    if not safe_ack:
        return (
            "[TruthGate 拦截 - gui-process-restart-gate] 检测到在后台命令行执行了桌面 GUI 应用（如 DSH Desktop）的杀死与重启，"
            "并直接断言「重启完成/已就绪/请打开窗口操作」。\n"
            "铁律 2026-09-18-I 规定：后台子进程拉起 GUI 应用受 Windows 防抢焦点与会话桌面隔离限制，"
            "窗口极易沉入托盘或后台层，绝不能凭底层服务日志假定前台视窗已就绪！\n"
            "必须如实告知前台视窗状态，或明确指引前台桌面启动/恢复路径！"
        )
    return None

# ── No-Nagging & R5/R39 Commitment-Deferral Gate ──────────────────────────────
# Shape 2026-07-25 / 2026-09-19: Strictly forbids asking user for permission/authorization
# on harmless, reversible technical work (e.g. scraping docs, running tests, writing scripts)
# when user intent is already clear. Vibe Coder ironlaw: Never push tech decisions to user!

NAG_PREFIX_RE = re.compile(
    r"(?:请(?:指示|指令|确认|定夺|批示|发话)[：:]?|"
    r"(?:是否(?:需要|要)|需不需要|要不要|该不该|用不用|可不可以)\s*(?:现在|我|我们|咱们)?|"
    r"需要我(?:继续|开始|执行|做|跑|弄|写|查|扫|抓)|"
    r"要我(?:继续|开始|做|跑|弄|写|查|扫|抓)|"
    r"(?:等|只要)(?:您|你)(?:一声令下|确认|指示|指令|点头|发话|同意|愿意|说一句|批准)|"
    r"(?:如果|若)(?:您|你)(?:同意|需要|想要|觉得行|点头|批准)(?:的话)?[，,]?|"
    r"你(?:说|定|给)\s*(?:个)?\s*(?:方向|哪个|要哪)?\s*[,，]?\s*我\s*(?:就|再|来|马上|立刻)|"
    r"(?:should I|want me to|shall I)\b)",
    re.I
)

# Harmless / Reversible tech actions that MUST be executed proactively without nagging:
TECH_ACTION_WORDS = (
    r"(?:启动|抓取|拉取|下载|调阅|阅读|看[完了过]?|分析|拆解|排查|跑|测试|执行|"
    r"写个?脚本|写代码|自造轮子|建个?工具|转换|索引|清洗|整理|扫描|搜索|查证|验证|优化|重构|继续)"
)

NAG_ACTION_RE = re.compile(
    r"(?:(?:是否(?:需要|要)|需不需要|要不要|该不该|用不用|可不可以)\s*.*?" + TECH_ACTION_WORDS + r".*?[？\?])|"
    r"(?:请(?:指示|指令|确认|批示)[：:]?.*?" + TECH_ACTION_WORDS + r")|"
    r"(?:等(?:您|你).*?" + TECH_ACTION_WORDS + r")",
    re.I
)

IRREVERSIBLE_DANGER_RE = re.compile(
    r"(?:删除生产|DROP\s+(?:TABLE|DATABASE)|清空数据库|真金白银|扣费|充值|上线发布|发推|发公开群|发邮件|转账|关停宿主|覆盖未保存)",
    re.I
)

def check_r5_deferral_violation(text, user_prompt):
    """Enforces no-nagging-gate & R5/R39 commitment-deferral-gate:
    Strictly forbids asking '请指示/请指令：是否需要我抓取/写脚本/执行/继续'
    when the user has already given instructions and the action is safe and reversible.
    2026-09-19 升级：结合 TypeSafe Jev System One 进行强类型意图降级与词面逃逸升级拦截。"""
    if not text:
        return None
    # Focus on the tail (last 600 chars) where turn conclusion/handoff happens
    tail = text[-600:] if len(text) > 600 else text
    # Strip quoted text to avoid false positives on discussion/reporting of rules
    clean_tail = re.sub(r"[「“\"`].*?[」”\"`]", "", tail)
    
    # Exclude historical postmortems
    if re.search(r"(?:^#\s*教训|教训案例库|【形状 20\d\d|历史案卷|历史教训|no-nagging|纸老虎)", clean_tail):
        return None

    # Irreversible destructive operations are allowed to ask
    if IRREVERSIBLE_DANGER_RE.search(clean_tail):
        return None

    # 1. 尝试 Jev 语义降级：若置信判定为复盘/规则说明，直接放行（免伤）
    try:
        hooks_dir = str(TG_HOOKS)
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from guard_common import jev_should_downgrade, jev_should_escalate
        if jev_should_downgrade(clean_tail, timeout=1.5) is True:
            return None
    except Exception:
        pass

    # 2. 正则硬匹配
    m = NAG_ACTION_RE.search(clean_tail) or NAG_PREFIX_RE.search(clean_tail)
    matched = None
    if m:
        matched = m.group(0)[:40]
    else:
        # 3. 正则未命中时：调用 Jev 识别隐蔽推诿或英文/换词逃逸
        try:
            if jev_should_escalate(clean_tail, timeout=1.5) is True:
                matched = "Jev 强类型判决: 检测到被动推诿/请示逃逸"
        except Exception:
            pass

    if matched:
        return (
            f"[TruthGate 拦截 - no-nagging-gate] 🚨 触发【授权即执行 / 严禁被动推诿请示铁律】：\n"
            f"检测到回复收尾出现了向用户请示授权的句式（命中:「{matched}」）！\n"
            f"铁律规定：\n"
            f"1. 用户的意图若已表达明确，且操作完全可逆、无害、零副作用（如抓取/阅读文档、写测试、造本地工具、清洗索引等），\n"
            f"   严禁把技术执行动作甩回给用户做选择或请示「要不要我做」！\n"
            f"2. 别当被动等命令的废柴助手，拥有上下文就立即自主闭环执行并直接交付最终落地证据！"
        )
    return None

# ── Token-Thrift & Batch Economy Gate ─────────────────────────────────────────
def check_token_thrift_violation(tool_calls):
    """Enforces token-thrift-gate:
    Blocks excessive context-stuffing tool calls (e.g. >= 8 read_url_content in a single turn)
    when a local script / batch tool should have been used instead to prevent context explosion."""
    url_reads = 0
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        name = fn.get("name", "")
        if name == "read_url_content":
            url_reads += 1
    if url_reads >= 8:
        return (
            f"[TruthGate 拦截 - token-thrift-gate] 🚨 触发【会话 Token 节约铁律】：\n"
            f"检测到当前单轮中直接发起了 {url_reads} 次 read_url_content 网页读取！\n"
            f"铁律规定：批量阅读外部文档或多网页时，严禁在 LLM 交互主循环中狂刷 URL 读取工具塞爆上下文（易导致会话记忆丢失与智商断崖）！\n"
            f"正确打法：必须自造轻量本地脚本（如 urllib+bs4），并发离线抓取并落盘到本地 Markdown/SQLite 库，零 Token 消耗完成全量抓取后做本地检索与提炼！"
        )
    return None


DSH_CARD_RE = re.compile(
    r"(?:glm-card|claude-card|1\.19848845\.xyz|rsxermu666\.cn|无限月卡)",
    re.I
)

def check_dsh_provider_violation(text, tool_calls, blob):
    """Enforces dsh-provider-authenticity-gate (Shape 2026-09-19-AE):
    Strictly forbids routing benchmark tasks to third-party relay cards."""
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        args = fn.get("args", {}) or fn.get("arguments", {}) or {}
        name = fn.get("name", "")
        cmd = str(args.get("CommandLine", "")) if isinstance(args, dict) else str(args)
        # Ignore self-tests and regression runners that evaluate this gate function
        if any(t in cmd for t in ("check_dsh_provider_violation", "test_superego", "simulate_stop", "test_no_search")):
            continue
        if any(k in cmd for k in ("dsh_bridge", "dsh_runner", "dsh", "opencode_arena")) and DSH_CARD_RE.search(cmd):
            return (
                "[TruthGate 拦截 - dsh-provider-authenticity-gate] 严禁在命令行中使用第三方包月中转卡渠道（-card / 1.19848845.xyz 等）执行评测！\n"
                "必须强制使用 Frank 指定并充值的官方付费通道 'opencode-go'！"
            )
        if name in ("run_task", "task_inbox") and DSH_CARD_RE.search(str(args)):
            return (
                "[TruthGate 拦截 - dsh-provider-authenticity-gate] 严禁在 DSH 任务派发中使用第三方包月中转卡渠道！\n"
                "必须强制使用 Frank 指定并充值的官方付费通道 'opencode-go'！"
            )
    return None

def check_harness_tool_integrity_violation(text, tool_calls, blob):
    """Enforces harness-tool-integrity-gate:
    Ensures DSH Harness has codegraph mounted in cordis.patch.yml."""
    patch_file = Path(os.path.expandvars(r"%APPDATA%\dsh-desktop\harness\profiles\web\cordis.patch.yml"))
    if patch_file.exists():
        try:
            content = patch_file.read_text(encoding="utf-8", errors="ignore")
            if "codegraph" not in content:
                return (
                    "[TruthGate 拦截 - harness-tool-integrity-gate] DSH Harness 缺少核心代码图谱工具 codegraph！\n"
                    "必须在 cordis.patch.yml 中挂载 codegraph 后方可放行！"
                )
        except Exception:
            pass
    return None

GHOST_BROWSER_SPAWN = re.compile(
    r'(?:chrome|msedge)(?:\.exe)?\s+.*--user-data-dir=.*(?:temp|tmp|chrome_dev|isolated)',
    re.I
)
ORPHAN_CDP_SPAWN = re.compile(
    r'(?:chrome|msedge)(?:\.exe)?\s+.*--remote-debugging-port=9222\b',
    re.I
)
BROWSER_FOREGROUND_CLAIM = re.compile(
    r"(?:已(?:在|为您)?(?:打开|拉起|弹出|登入|登录)|已经在|窗口已|视窗已).*(?:浏览器|chrome|edge|后台大盘|管理后台)|"
    r"(?:浏览器|chrome|edge|窗口|视窗).*(?:已在屏幕|正最大化|已置顶|呈现在屏幕|正处于前台)",
    re.I
)

def check_ghost_browser_violation(text, tool_calls, blob):
    """Enforces ghost-browser-gate (Shape 2026-09-19-AG):
    Strictly forbids spawning isolated Temp profile browsers or claiming foreground delivery with ghost processes."""
    cmds = []
    for tc in tool_calls:
        fn = tc.get("function", {}) if "function" in tc else tc
        args = fn.get("args", {}) or fn.get("arguments", {}) or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        cmd = ""
        if isinstance(args, dict):
            cmd = str(args.get("CommandLine", "") or args.get("command", ""))
        elif isinstance(args, str):
            cmd = args
        if cmd:
            cmds.append(cmd)
    if not cmds and blob:
        for line in blob.splitlines():
            m_cmd = re.search(r'"(?:CommandLine|command)":\s*"((?:[^"\\]|\\.)*)"', line)
            if m_cmd:
                cmds.append(m_cmd.group(1))

    for cmd in cmds:
        if "ghost_browser_gate" in cmd or "ghost-browser-gate" in cmd:
            continue
        if GHOST_BROWSER_SPAWN.search(cmd):
            return (
                "[TruthGate 拦截 - ghost-browser-gate] 严禁使用隔离 Temp 目录拉起私有幽灵 Chrome/Edge 进程！\n"
                "铁律 2026-09-19-AG 规定：\n"
                "1. 在后台使用 --user-data-dir=Temp... 启动的浏览器无前台交互主窗口，会导致用户物理屏幕完全扑空！\n"
                "2. 打开网页必须使用系统宿主入口（open-browser.cmd 或 Start-Process https://...）；\n"
                "3. 浏览器自动化与网页操控必须使用 OpenCLI (opencli browser ...) 接入用户当前正在使用的宿主 Chrome！"
            )
        if ORPHAN_CDP_SPAWN.search(cmd) and "--user-data-dir" in cmd:
            return (
                "[TruthGate 拦截 - ghost-browser-gate] 检测到试图在后台拉起 9222 孤儿调试端口的临时浏览器！\n"
                "铁律 2026-09-19-AG 规定：严禁私自拉起无主调试进程，必须接入宿主真实浏览器！"
            )

    if text and not QUOTING_HISTORIC.search(text):
        if BROWSER_FOREGROUND_CLAIM.search(text):
            has_ghost_cmd = any(GHOST_BROWSER_SPAWN.search(c) for c in cmds)
            if has_ghost_cmd:
                return (
                    "[TruthGate 拦截 - ghost-browser-gate] 严禁将后台隔离沙箱中的幽灵浏览器宣称为「已在前台打开/呈现」！\n"
                    "请使用 OpenCLI 或 open-browser.cmd 接入宿主真实浏览器，并通过物理桌面全屏截屏核验置顶状态！"
                )
    return None

def _run_single_claude_gate(p, payload_str, text, blob):
    gate_name = p.stem
    try:
        code_text = p.read_text(encoding="utf-8", errors="ignore")
        if "def check_text(" in code_text:
            import importlib.util
            spec = importlib.util.spec_from_file_location(gate_name.replace("-", "_"), str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "check_text"):
                res = mod.check_text(text, blob)
                if res:
                    return gate_name, res
            return gate_name, None

        flags = (0x08000000) if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, str(p)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags, text=True
        )
        out, err = proc.communicate(input=payload_str, timeout=4.5)
        if proc.returncode == 2:
            reason = (err or out).strip() or f"[{gate_name}] 拦截：协议退出码 2"
            return gate_name, reason
        combined = (out or "") + "\n" + (err or "")
        if '"decision": "block"' in combined or '"decision":"block"' in combined:
            try:
                data = json.loads(out.strip())
                reason = data.get("reason") or data.get("permissionDecisionReason") or combined
                return gate_name, reason
            except Exception:
                return gate_name, combined.strip()
        for line in combined.splitlines():
            line_s = line.strip()
            if line_s.startswith("⛔") or line_s.startswith("[TruthGate 拦截") or line_s.startswith("[Superego 拦截"):
                return gate_name, combined.strip()
    except subprocess.TimeoutExpired:
        # 2026-09-27(PLAN 第 5 步):原来超时被下面的 except 吞掉 —— 不留记录(AG 端闸卡死没人知道),子进程也不杀
        #   (communicate 超时不会自动杀它 ⇒ 卡死的闸一直在后台跑)。现在杀掉、记一笔;开局核对(source_news.alarms)按这份记录报警。
        try:
            proc.kill()
            proc.communicate(timeout=2)
        except Exception:
            pass
        try:
            sid = (json.loads(payload_str).get("session_id") or "-")[:8]
            if _fresh_once("timeout_" + gate_name, sid, payload_str):   # 一轮收尾调 3 次桥接,只记一笔
                if str(TG_HOOKS) not in sys.path:
                    sys.path.insert(0, str(TG_HOOKS))
                from guard_common import hook_log
                hook_log("ag-gate-timeouts", f"TIMEOUT {gate_name} ag={sid}", "")
        except Exception:
            pass
    except Exception:
        pass
    return gate_name, None

def check_dynamic_claude_gates(text, blob, transcript_path="", conv_id=""):
    """Dynamically loads and evaluates active gates in ~/.claude/hooks/ across all 4 AI engines."""
    hooks_dir = TG_HOOKS
    if not hooks_dir.exists():
        return None

    hardcoded_gates = {
        "visual-proof-gate", "model-authenticity-gate", "no-search-no-claim-gate",
        "search-breadth-gate", "process-alias-attribution-gate", "semantic-superego-gate",
        "cross-brain-retrieval-gate", "gui-process-restart-gate", "ghost-browser-gate",
        "honest-scope-assertion-gate", "no-nagging-guard", "anti-toy-test-gate",
        "anti-stale-assertion-gate", "postmortem-guard", "dsh-provider-authenticity-gate",
        "evidence-table-gate",   # handle_stop 里直接调 check_evidence_table(同一份判据),这里再跑一遍会重复记账
    }

    # Discover candidate Stop gates from settings.json AND filesystem
    seen_paths = set()
    candidate_paths = []
    not_stop = set()   # Claude 端只挂在调用工具前后 / 提问 / 开局的闸（见下方文件夹合并处）
    settings_file = CLAUDE_DIR / "settings.json"
    if settings_file.exists():
        try:
            s_data = json.loads(settings_file.read_text(encoding="utf-8"))
            ev_of = {}
            for ev, entries in s_data.get("hooks", {}).items():
                for entry in entries:
                    for h in entry.get("hooks", []):
                        m_name = re.search(r"([\w.-]+?)\.(?:py|cjs|js)\b", h.get("command", ""))
                        if m_name:
                            ev_of.setdefault(m_name.group(1), set()).add(ev)
            not_stop = {g for g, evs in ev_of.items() if not evs & {"Stop", "SubagentStop"}}
            for entry in s_data.get("hooks", {}).get("Stop", []):
                for h in entry.get("hooks", []):
                    cmd = h.get("command", "")
                    m_path = re.search(r'''['"]?([^'"]+?\.(?:py|cjs))['"]?''', cmd)
                    if m_path:
                        fpath = Path(os.path.expandvars(m_path.group(1).replace("$HOME", str(Path.home()))))
                        if fpath.exists() and fpath.suffix == ".py" and fpath not in seen_paths:
                            seen_paths.add(fpath)
                            candidate_paths.append(fpath)
        except Exception:
            pass

    # Union with filesystem gates in hooks_dir to catch all gates
    # 2026-10-03:跳过 Claude 端只挂在调用工具前后 / 提问 / 开局的闸(34 道)。收尾时喂给它们的 payload 没有工具输入,
    #   它们只会空跑:logs/verdicts.jsonl 里 AG 的拦截 622 行(涉及 53 道闸,2026-10-03 数)这 34 道 0 行;
    #   却占了收尾时三分之一的 python 进程(97 道里 34 道),把 CPU 顶满、害真正的收尾闸超时
    #   (ag-gate-timeouts.log 7,061 行,其中 1,734 行就是这 34 道自己)。Claude 端没接线的闸(AG 专用,如 jargon-gate)照跑。
    for p in sorted(list(hooks_dir.glob("*-gate.py")) + list(hooks_dir.glob("*-guard.py"))):
        if p.stem in not_stop:
            continue
        if p not in seen_paths:
            seen_paths.add(p)
            candidate_paths.append(p)

    active_candidates = []
    seen = set()
    for p in candidate_paths:
        name = p.stem
        if name in hardcoded_gates or name in seen:
            continue
        seen.add(name)
        if check_is_off(name, sid=conv_id):
            continue
        active_candidates.append(p)

    # Priority order for synchronous enforcement (most impactful gates first)
    PRIORITY_GATES = [
        "free-first-gate", "jargon-gate", "strawman-verdict-gate", "checklist-completion-gate",
        "pipeline-ends-gate", "pipeline-first-gate", "bg-running-claim-gate", "antiscrape-invoke-gate",
        "money-verdict-gate", "local-first-gate", "idle-ask-gate", "giveup-guard",
        "dropped-output-guard", "authority-source-gate", "scope-completeness-gate",
        "spec-coverage-guard", "residue-gate", "multi-option-guard", "not-mine-gate", "excuse-gate"
    ]

    # Sort active candidates: prioritized ones first
    def _prio_key(p):
        stem = p.stem
        if stem in PRIORITY_GATES:
            return PRIORITY_GATES.index(stem)
        return len(PRIORITY_GATES) + 1

    active_candidates.sort(key=_prio_key)
    # 全量执行所有动态 Stop 门禁，彻底移除人为截断
    sync_candidates = active_candidates

    # Resolve transcript path
    tp = transcript_path
    if not tp or not os.path.exists(tp):
        if conv_id:
            cand = Path.home() / ".gemini" / "antigravity" / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
            if cand.exists():
                tp = str(cand)

    payload_str = json.dumps({
        "transcript_path": tp,
        "last_assistant_message": text,
        "session_id": (conv_id or "ag")[:8],
        "cwd": os.getcwd()
    }, ensure_ascii=False)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {
            executor.submit(_run_single_claude_gate, p, payload_str, text, blob): p.stem
            for p in sync_candidates
        }
        for fut in as_completed(futures):
            try:
                g_name, violation = fut.result()
                if violation:
                    return f"[TruthGate 拦截 - {g_name}] {violation}"
            except Exception:
                pass

    return None

AG_WRITE_TOOLS = ("write_to_file", "replace_file_content", "multi_replace_file_content", "edit")
_AG_WS = ""  # 本次调用 AG 会话开在哪(main() 从 workspacePaths 填)


def check_single_source(tool_calls):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from single_source import check
    ws = re.sub(r"^file:/+", "", _AG_WS or "") or os.getcwd()
    for tc in tool_calls or []:
        fn = tc.get("function", {}) if "function" in tc else tc
        if fn.get("name", "") not in AG_WRITE_TOOLS:
            continue
        args = fn.get("args", {}) or fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"TargetFile": args}
        target = str(args.get("TargetFile", "") or args.get("path", "") or args.get("file_path", "") or "")
        why = check(target, ws)
        if why:
            return f"[TruthGate 拦截 - single-source-gate] ⛔ {why}（本轮 AG 写了 {target}）"
    return None


def _ag_turn_key(transcript_path):
    """AG 这一轮的标识 = 最后一条 USER_INPUT 的 step_index / created_at(没有就空串)。"""
    key = ""
    try:
        for l in read_transcript_tail_lines(transcript_path, max_bytes=2 * 1024 * 1024):
            if '"USER_INPUT"' in l:
                o = json.loads(l)
                if o.get("type") == "USER_INPUT":
                    key = str(o.get("step_index", "")) + "@" + str(o.get("created_at", ""))
    except Exception:
        pass
    return key


# 查【事实】的闸(它做了什么:桌面上有没有那个窗口、测试命令退出码是几、浏览器是不是无头的),不是查措辞的。
# 2026-10-03 Claude 加(Frank:「没有任何的地方可以绕道」):这几道不享受「一轮只拦一次」、不接受自称误报。
# 病历:AG 会话 cb9b2465 五天里 BLOCK 76 次、REPEAT 放行 210 次;show-open-guard 拦 26 次后放行 146 次 ——
#   它被拦后原样再收尾一次就过了,事实一点没变。查措辞的闸不在这里,照旧一轮一拦(REQUIREMENTS 第 11 条:不引发一轮接一轮的误拦)。
FACT_GATES = frozenset((
    "ledger-claim-gate", "show-open-guard", "visual-proof-gate", "desktop-window-phantom",
    "headless-mock-fraud", "ghost-browser-gate", "anti-toy-test-gate", "visual-truth-gate",
    "external-critic-gate", "critic-gate", "evidence-table-gate",
))


def _gate_turn_mark(gate, conv_id, text, transcript_path, strict=False):
    """同一道闸一轮最多拦一次(2026-09-27,PLAN 第 5 步)。返回 (repeat, dup):
    repeat = 这道闸本轮已经拦过、这次是【另一次】收尾 ⇒ 放行;
    dup    = 同一次收尾的第 2、3 次调用(AG 一轮收尾调桥接 3 次:同一段回复、30 秒内)⇒ 照拦,但预算不再扣。
    strict = 事实类闸(FACT_GATES):另一次收尾不放行,照拦并扣预算(循环上限由 5 次熔断兜住)。
    标记:TG_SEM/.gateblk_<会话>_<闸>,内容「轮标识|回复指纹|时刻」。测试(SUPEREGO_TEST=1)不留标记。"""
    if not conv_id or os.environ.get("SUPEREGO_TEST") == "1":
        return False, False
    import hashlib
    key = _ag_turn_key(transcript_path)
    sig = hashlib.md5((text or "").encode("utf-8", "ignore")).hexdigest()[:12]
    f = TG_SEM / f".gateblk_{conv_id[:8]}_{gate}"
    now = time.time()
    try:
        old = f.read_text(encoding="utf-8").split("|") if f.exists() else []
        if len(old) == 3 and old[0] == key:
            if old[1] == sig and now - float(old[2]) < 30:
                return False, True
            if not strict:
                return True, False
        f.write_text(f"{key}|{sig}|{now}", encoding="utf-8")
    except Exception:
        pass
    return False, False


def check_review_loop(transcript_path, conv_id=""):
    """外审停止条件(2026-09-27,PLAN 第 5 步):判据与 Claude 端 hooks/review-loop-gate.py 同一份(~/.truthgate/review_loop.py)。
    AG 没有「调用工具前」,只能收尾时查:本任务(上一条 USER_INPUT 以来)里有一轮外审是在该停的时候发的 ⇒ 拦一次,让它停下来问 Frank。
    同一个轮数只拦一次(一轮收尾调 3 次桥接、被拦后继续干再收尾,都不重复拦 —— 否则拦截本身又绕成循环)。"""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import review_loop as rl
    objs = []
    for l in read_transcript_tail_lines(transcript_path, max_bytes=4 * 1024 * 1024):
        try:
            objs.append(json.loads(l))
        except Exception:
            continue
    last_user = max((i for i, o in enumerate(objs) if o.get("type") == "USER_INPUT"), default=-1)
    rounds = rl.rounds_from_ag(objs[last_user + 1:])
    for k in range(1, len(rounds)):
        why = rl.judge(rounds[:k], rounds[k][0])
        if why:
            if _fresh_once("review_loop", conv_id, str(len(rounds))):
                return f"[TruthGate 拦截 - review-loop-gate] 本任务第 {k + 1} 轮外审是在该停的时候发的。\n" + rl.message(why)
            return None
    return None


def check_evidence_table(text, tool_calls, conv_id=""):
    """证据表核对(2026-09-27,PLAN.md 第 2 步):判据与 Claude 端 hooks/evidence-table-gate.py 同一份(~/.truthgate/evidence_table.py)。
    ~/.claude/superego-observe.json 的 observe 名单里有它 ⇒ 只记账(WOULDBLOCK)、不拦 —— 两端同一个开关。"""
    for p in (str(SCRIPTS_DIR), str(TG_HOOKS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from evidence_table import judge, actions_from_ag, quoted_claims, ESCAPE
    from guard_common import hook_log
    verdict, reason, tier = judge(text or "", actions_from_ag(tool_calls))
    try:
        obs_file = os.environ.get("SUPEREGO_OBSERVE_FILE") or str(CLAUDE_DIR / "superego-observe.json")   # 与 guard_common 同一个开关
        observe = "evidence-table-gate" in json.loads(Path(obs_file).read_text(encoding="utf-8")).get("observe", [])
    except Exception:
        observe = False
    # AG 一轮收尾会调桥接 3 次(全局两组 + 插件一组都接了 Stop) ⇒ 同一段回复只记一次账,否则周报数字翻三倍
    import hashlib
    who = f"ag={(conv_id or '-')[:8]}"
    mark = TG_SEM / f".evtable_{(conv_id or 'ag')[:8]}"
    sig = hashlib.md5((text or "").encode("utf-8", "ignore")).hexdigest()[:12]
    try:
        fresh = os.environ.get("SUPEREGO_TEST") == "1" or not (mark.exists() and mark.read_text(encoding="utf-8") == sig)  # 考卷 / 测试不留标记
        if fresh and os.environ.get("SUPEREGO_TEST") != "1":
            mark.write_text(sig, encoding="utf-8")
    except Exception:
        fresh = True
    if fresh:
        q = quoted_claims(text or "") if tier == 0 else []
        if q:   # 结论躲在引号里:只记账,每周抽查
            hook_log("evidence-table-gate", f"QUOTED {who}", q[0])
        if ESCAPE.search(text or ""):
            hook_log("evidence-table-gate", f"ESCAPE {who}", (text or "")[-140:])
        if verdict == "block":
            hook_log("evidence-table-gate", f"{'WOULD' if observe else ''}BLOCK(tier{tier}) {who}", reason)
    if verdict != "block" or observe:
        return None
    return f"[TruthGate 拦截 - evidence-table-gate] ⛔ {reason}"


class _ObservedViolations(list):
    """2026-09-27(PLAN 第 4 步):AG 桥接的内置检查原来不认只记账名单 —— Claude 端已降成只记账的闸(没搜就说没有、检索广度…)
    在 AG 这边照拦(近 7 天 13 次 + 8 次)。现在同一份名单(~/.claude/superego-observe.json)两端都认:
    名单里的闸只记一笔 WOULDBLOCK、不进拦截列表;配合 `if stop_on_first and violations` 让后面的检查照跑。"""

    def __init__(self, conv_id=""):
        super().__init__()
        self.conv_id = conv_id
        try:
            obs_file = os.environ.get("SUPEREGO_OBSERVE_FILE") or str(CLAUDE_DIR / "superego-observe.json")
            self.observed = set(json.loads(Path(obs_file).read_text(encoding="utf-8")).get("observe", []))
        except Exception:
            self.observed = set()

    def append(self, item):
        name, vio = item
        if name in self.observed:
            try:
                if str(TG_HOOKS) not in sys.path:
                    sys.path.insert(0, str(TG_HOOKS))
                from guard_common import hook_log
                if _fresh_once("obs_" + name, self.conv_id, str(vio)):
                    hook_log(name, f"WOULDBLOCK(ag) ag={(self.conv_id or '-')[:8]}", str(vio)[:200])
            except Exception:
                pass
            return
        super().append(item)


def evaluate_all_structural_gates(text, tool_calls, blob, user_prompt="", conv_id="", transcript_path="", stop_on_first=False):
    """Evaluates all 15 structural gates and returns list of (gate_name, violation_text).
    If stop_on_first=True, returns immediately upon encountering the first violation.
    If stop_on_first=False, collects all fired violations (used by run_worker & outer audit).
    """
    violations = _ObservedViolations(conv_id)   # 名单里只记账的闸:记一笔 WOULDBLOCK、不进拦截,后面的检查照跑
    is_globally_off = check_is_off("*", sid=conv_id)

    # 0. Supreme Evolutionary Gate: postmortem-to-guard (Enforce 5-step self-healing when user reprimands)
    # NEVER bypassed by any toggle, NEVER fused!
    if user_prompt:
        try:
            try:
                from truthgate.postmortem_guard import detect_reprimand, audit_postmortem_compliance
            except ImportError:
                from postmortem_guard import detect_reprimand, audit_postmortem_compliance
            rep_info = detect_reprimand(user_prompt)
            if rep_info:
                compliance = audit_postmortem_compliance(text, rep_info)
                if compliance.get("fired"):
                    violations.append(("postmortem-to-guard-gate", compliance.get("reason", "")))
                    if stop_on_first and violations:
                        return violations
        except Exception:
            pass

    # 0b. 单源闸(2026-09-27):本轮 AG 写了 TruthGate 的副本 / 不在 ~/.truthgate 开的会话里改了源头 ⇒ 拦。
    #     判据与 Claude 端 hooks/single-source-gate.py 同一份(~/.truthgate/single_source.py),只看事实(写了哪个文件、会话开在哪)。
    try:
        vio = check_single_source(tool_calls)
        if vio:
            violations.append(("single-source-gate", vio))
            if stop_on_first and violations:
                return violations
    except Exception:
        pass

    # 0c. 外审循环(2026-09-27,PLAN 第 5 步):判据与 Claude 端 hooks/review-loop-gate.py 同一份(~/.truthgate/review_loop.py)。
    try:
        vio = check_review_loop(transcript_path, conv_id)
        if vio:
            violations.append(("review-loop-gate", vio))
            if stop_on_first and violations:
                return violations
    except Exception:
        pass

    # 1. Supreme Red Line #1: honest-scope-assertion-gate (Zero Tolerance for Lying / Bluffing)
    # NEVER bypassed by any toggle, NEVER fused!
    vio = check_honest_scope_violation(text, tool_calls, blob, user_prompt)
    if vio:
        violations.append(("honest-scope-assertion-gate", vio))
        if stop_on_first and violations:
            return violations

    # 2. Hard Red Line: dsh-provider-authenticity-gate
    vio = check_dsh_provider_violation(text, tool_calls, blob)
    if vio:
        violations.append(("dsh-provider-authenticity-gate", vio))
        if stop_on_first and violations:
            return violations

    # 3. Hard Red Line: ghost-browser-gate
    vio = check_ghost_browser_violation(text, tool_calls, blob)
    if vio:
        violations.append(("ghost-browser-gate", vio))
        if stop_on_first and violations:
            return violations

    # 4. Hard Red Line: visual-proof-gate
    if not check_is_off("visual-proof-gate", sid=conv_id):
        vio = check_visual_proof_violation(text, tool_calls, blob, user_prompt, conv_id)
        if vio:
            violations.append(("visual-proof-gate", vio))
            if stop_on_first and violations:
                return violations

    # 4.1 Hard Red Line: anti-toy-test-gate —— 2026-09-27 第 3 步起只看动作记录:改了网页 ⇒ 改完要真浏览器跑 + 听控制台;
    #     改了接口代码 ⇒ 改完要真发请求(这项先只记账)。判据 delivery_check.py,与 Claude 端同一份。
    if not check_is_off("anti-toy-test-gate", sid=conv_id):
        try:
            vio = check_delivery("anti-toy-test-gate", {"browser", "console", "request"}, tool_calls, user_prompt, conv_id)
            if vio:
                violations.append(("anti-toy-test-gate", vio))
                if stop_on_first and violations:
                    return violations
        except Exception:
            pass

    # Remaining soft gates (can be silenced by global off switch)
    if is_globally_off:
        return violations

    # 5. no-nagging-guard
    if not check_is_off("no-nagging-guard", sid=conv_id):
        vio = check_no_nagging_violation(text, user_prompt)
        if vio:
            violations.append(("no-nagging-guard", vio))
            if stop_on_first and violations:
                return violations

    # 6. model-authenticity-gate
    if not check_is_off("model-authenticity-gate", sid=conv_id):
        vio = check_model_authenticity_violation(text, tool_calls, blob, user_prompt)
        if vio:
            violations.append(("model-authenticity-gate", vio))
            if stop_on_first and violations:
                return violations

    # 7. r5-commitment-deferral-gate
    if not check_is_off("r5-commitment-deferral-gate", sid=conv_id):
        vio = check_r5_deferral_violation(text, user_prompt)
        if vio:
            violations.append(("r5-commitment-deferral-gate", vio))
            if stop_on_first and violations:
                return violations

    # 8. token-thrift-gate
    if not check_is_off("token-thrift-gate", sid=conv_id):
        vio = check_token_thrift_violation(tool_calls)
        if vio:
            violations.append(("token-thrift-gate", vio))
            if stop_on_first and violations:
                return violations

    # 9. harness-tool-integrity-gate
    if not check_is_off("harness-tool-integrity-gate", sid=conv_id):
        vio = check_harness_tool_integrity_violation(text, tool_calls, blob)
        if vio:
            violations.append(("harness-tool-integrity-gate", vio))
            if stop_on_first and violations:
                return violations

    # 10. no-search-no-claim-gate
    if not check_is_off("no-search-no-claim-gate", sid=conv_id):
        vio = check_no_search_no_claim_violation(text, tool_calls, blob, user_prompt=user_prompt)
        if vio:
            violations.append(("no-search-no-claim-gate", vio))
            if stop_on_first and violations:
                return violations

    # 11. search-breadth-gate
    if not check_is_off("search-breadth-gate", sid=conv_id):
        vio = check_search_breadth_violation(text, tool_calls, blob)
        if vio:
            violations.append(("search-breadth-gate", vio))
            if stop_on_first and violations:
                return violations

    # 11.1 anti-stale-assertion-gate
    if not check_is_off("anti-stale-assertion-gate", sid=conv_id):
        try:
            from anti_stale_assertion_gate import check_anti_stale_assertion_violation
            vio = check_anti_stale_assertion_violation(text, tool_history=tool_calls, user_prompt=user_prompt)
            if vio:
                violations.append(("anti-stale-assertion-gate", vio))
                if stop_on_first and violations:
                    return violations
        except Exception:
            pass

    # 12. institutionalize-guard
    if not check_is_off("institutionalize-guard", sid=conv_id):
        vio = check_institutionalize_violation(text, tool_calls, blob)
        if vio:
            violations.append(("institutionalize-guard", vio))
            if stop_on_first and violations:
                return violations

    # 13. process-alias-attribution-gate
    if not check_is_off("process-alias-attribution-gate", sid=conv_id):
        vio = check_process_alias_violation(text, blob)
        if vio:
            violations.append(("process-alias-attribution-gate", vio))
            if stop_on_first and violations:
                return violations

    # 14. cross-brain-retrieval-gate
    if not check_is_off("cross-brain-retrieval-gate", sid=conv_id):
        vio = check_cross_brain_retrieval_violation(text, tool_calls, blob, user_prompt)
        if vio:
            violations.append(("cross-brain-retrieval-gate", vio))
            if stop_on_first and violations:
                return violations

    # 14b. codegraph-topology-gate
    if not check_is_off("codegraph-topology-gate", sid=conv_id):
        vio = check_codegraph_topology_violation(text, tool_calls, blob, user_prompt)
        if vio:
            violations.append(("codegraph-topology-gate", vio))
            if stop_on_first and violations:
                return violations

    # 15. gui-process-restart-gate
    if not check_is_off("gui-process-restart-gate", sid=conv_id):
        vio = check_gui_process_restart_violation(text, tool_calls, blob)
        if vio:
            violations.append(("gui-process-restart-gate", vio))
            if stop_on_first and violations:
                return violations

    # 15.1 改了没生效（事实检查，记在 anti-toy-test-gate 名下，和 Claude 端一致）
    if not check_is_off("anti-toy-test-gate", sid=conv_id):
        vio = check_stale_process_violation(text, tool_calls)
        if vio:
            violations.append(("anti-toy-test-gate", vio))
            if stop_on_first and violations:
                return violations

    # 16. Dynamic claude gates in ~/.claude/hooks/*.py
    try:
        dyn_vio = check_dynamic_claude_gates(text, blob, transcript_path=transcript_path, conv_id=conv_id)
        if dyn_vio:
            m = re.search(r"\[(?:TruthGate|Superego) 拦截 - ([^\]]+)\]", dyn_vio)
            actual_gate = m.group(1) if m else "dynamic-claude-gate"
            violations.append((actual_gate, dyn_vio))
            if stop_on_first and violations:
                return violations
    except Exception:
        pass

    return violations

def check_visual_truth(text, tool_calls):
    """独立看图(2026-10-03,判据在 ~/.truthgate/vision_proof.py):改了网页、改完看过截图 ⇒ 那张图交给另一个模型盲看,
    它看到的显示缺陷回复里没写 ⇒ 拦。考卷 / 回放(SUPEREGO_TEST=1)不起后台看图,只用已有结论。"""
    for p in (str(SCRIPTS_DIR), str(TG_HOOKS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from vision_proof import check
    from evidence_table import actions_from_ag
    return check(text, actions_from_ag(tool_calls), spawn=os.environ.get("SUPEREGO_TEST") != "1")


def handle_stop(payload):
    """Stop hook: True gating before returning answer to user."""
    conv_id = payload.get("conversationId") or payload.get("conversation_id") or payload.get("id") or ""
    transcript_path = payload.get("transcriptPath") or payload.get("transcript_path") or ""

    # Fallback 1: via conv_id
    if not transcript_path or not os.path.exists(transcript_path):
        if conv_id:
            cand = Path.home() / ".gemini" / "antigravity" / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
            if cand.exists():
                transcript_path = str(cand)

    # Fallback 2: Disk-level discovery of the newest active transcript.jsonl across all brain folders
    if not transcript_path or not os.path.exists(transcript_path):
        import glob
        brains = glob.glob(str(Path.home() / ".gemini" / "antigravity" / "brain" / "*" / ".system_generated" / "logs" / "transcript.jsonl"))
        if brains:
            brains.sort(key=os.path.getmtime, reverse=True)
            transcript_path = brains[0]
            if not conv_id:
                try:
                    conv_id = Path(transcript_path).parents[2].name
                except Exception:
                    pass

    text, tool_calls, blob = load_antigravity_turn(transcript_path)
    if payload.get("text"):
        text = payload.get("text")
    if payload.get("tool_calls"):
        tool_calls = payload.get("tool_calls")
    user_prompt = get_last_user_prompt(transcript_path)
    if payload.get("user_prompt"):
        user_prompt = payload.get("user_prompt")

    # Tier 0(2026-09-25 Claude 加):事实账本核对 —— 它说测试过了,账本里那条测试命令的退出码是几?
    # 这是【事实】不是判断:只看账本(PreInvocation 从 transcript 抄的),不看它的措辞。进红线组(5 次熔断)。
    try:
        ledger_append_from_transcript(transcript_path, conv_id)   # 先把本轮最新步骤记进账本
    except Exception:
        pass
    ledger_vio = ledger_claim_check(text, conv_id, transcript_path)
    if ledger_vio:
        violations_pre = [("ledger-claim-gate", ledger_vio)]
    else:
        violations_pre = []
    # 证据表核对(2026-09-27,PLAN 第 2 步)放在这里、不放进 evaluate_all_structural_gates:后台 worker 也调那个函数,会重复记账
    if not violations_pre:
        try:
            ev_vio = check_evidence_table(text, tool_calls, conv_id)
            if ev_vio:
                violations_pre = [("evidence-table-gate", ev_vio)]
        except Exception:
            pass

    # 独立看图(2026-10-03):流程全做了、图里却是坏的 —— 流程类的闸看不出来,只有真的看图才看得出
    if not violations_pre and not check_is_off("visual-truth-gate", sid=conv_id):
        try:
            vt_vio = check_visual_truth(text, tool_calls)
            if vt_vio:
                violations_pre = [("visual-truth-gate", vt_vio)]
        except Exception:
            pass

    # Evaluate structural gates with stop_on_first=True
    violations = violations_pre or evaluate_all_structural_gates(
        text, tool_calls, blob,
        user_prompt=user_prompt,
        conv_id=conv_id,
        transcript_path=transcript_path,
        stop_on_first=True
    )
    violation = violations[0][1] if violations else None

    # Tier 2: Jev System One 实时多域语义拦截 (~350ms, 0 误伤)
    if not violation and not check_is_off("jev", sid=conv_id):
        if text and len(text.strip()) >= 15:
            try:
                if str(TG_HOOKS) not in sys.path:
                    sys.path.insert(0, str(TG_HOOKS))
                from superego_jev_engine import judge_assistant_text
                jev_res = judge_assistant_text(text, sid=conv_id)
                jev_fired = list(jev_res.get("fired") or [])
                if jev_fired:
                    fired_str = ",".join(jev_fired)
                    jev_vio = f"[TruthGate 拦截 - jev-system-one] 命中了外审规则【{fired_str}】（推诿/未查证/虚报完成/飙黑话），强制打回整改！"
                    # 2026-09-27 第 4 步:只记账名单里有它 ⇒ 记一笔、不拦(与内置检查同一个开关,见 _ObservedViolations)
                    obs = _ObservedViolations(conv_id)
                    obs.append(("jev-system-one", jev_vio))
                    violation = obs[0][1] if obs else None
            except Exception:
                pass

    # Tier 3: 真实独立外审模型 (External Reviewer) 实时物理审判
    if not violation and not check_is_off("critic-gate", sid=conv_id):
        _claim_done = bool(re.search(r"修好|跑通|搞定|上线|部署|已完成|done|fixed|已解决|已优化|全部通过|生效", text or "", re.I))
        _has_code_mod = any(
            tc.get("name") in ("write_to_file", "replace_file_content", "Write", "Edit", "multi_replace_file_content")
            for tc in tool_calls
        ) if isinstance(tool_calls, list) else False
        # 2026-10-12 Frank 修正:选型、推荐、架构方案、否定断言全部纳入外审实时物理审判，绝不漏网
        _has_claim_or_decision = bool(re.search(r"推荐|应该用|方案|架构|必须用|重构|做不到|全网没有|只能|不支持|不可行|最好|当前现状|最新", text or ""))
        if (_claim_done or _has_code_mod or _has_claim_or_decision) and len((text or "").strip()) >= 10:
            try:
                if str(TG_HOOKS) not in sys.path:
                    sys.path.insert(0, str(TG_HOOKS))
                import external_critic_engine as _ece
                _acts = []
                for tc in (tool_calls or []):
                    nm = tc.get("name") or (tc.get("function") or {}).get("name") or "tool"
                    inp = tc.get("args") or tc.get("arguments") or tc.get("input") or {}
                    summ = str(inp.get("command") or inp.get("CommandLine") or inp.get("TargetFile") or inp.get("file_path") or "")[:100]
                    _acts.append(f"{nm}: {summ}")
                
                c_res = _ece.review_turn(user_prompt, text, _acts)
                if c_res and c_res.get("verdict") == "block":
                    violation = (
                        f"[TruthGate 拦截 - external-critic-gate] ⛔ 独立外审模型({c_res.get('backend')})判定【不合格，强制打回】！\n"
                        f"【挑刺原因】: {c_res.get('reason')}\n"
                        f"【要求下一步动作】: {c_res.get('next')}\n\n"
                        "按 TruthGate 1.0 外审铁律：严禁在缺乏真实动作支撑时拍脑袋宣布完成！\n"
                        "请立即按照外审要求执行实测验证动作后再收尾。"
                    )
            except Exception:
                pass

    if violation:
        # ── 2026-09-25 Claude 加·两件让 AG「分得出误报」的事 ──
        # (a) 误报合法路:它在收尾里写「误报：<闸名> — <理由>」,闸名对得上本次拦的闸 ⇒ 放行,声明记账,考卷事后判。
        #     事实类(ledger-claim-gate)不接受;一轮同一闸只免一次。
        g_now = _gate_name_of(violation)
        claim = _misfire_claim(text, g_now)
        if claim and g_now not in FACT_GATES:
            used_f = TG_SEM / f".misfire_{conv_id[:8]}_{g_now}" if conv_id else None
            if not (used_f and used_f.exists()):
                try:
                    if used_f:
                        used_f.write_text("1", encoding="utf-8")
                    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
                    with open(LEDGER_DIR / ((conv_id or "unknown")[:36] + ".misfire.jsonl"), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "gate": g_now, "claim": claim[:300],
                                            "text": (text or "")[-400:], "violation": violation[:300]}, ensure_ascii=False) + "\n")
                    with open(TG_HOOKS / "semantic-superego-gate.log", "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [antigravity|{(conv_id or 'ag')[:8]}] trig='{g_now}' MISFIRE-CLAIMED(pass,ledgered)\n")
                except Exception:
                    pass
                print(json.dumps({}))
                return
        # (b) 理由里附上【触发它的原句】:11 道硬编码闸的文案不带,AG 看不到是哪句就只能当真去补。
        if "触发处" not in violation:
            violation = violation.rstrip() + "\n触发处(你上一段里最可能的那句): " + _likely_trigger(text, g_now)
            if g_now in FACT_GATES:
                violation += "\n⇒ 这道闸查的是事实,不接受「误报」声明,原样再收尾一次也不会放行。只有把事实补上(真打开 / 真跑 / 真截桌面)才过。"
            else:
                violation += "\n⇒ 如果这句是引用/否定/在讨论闸本身,在收尾里写一行「误报：" + g_now + " — 理由」即可放行(会记账,考卷事后判对错)。"

        # (c) 2026-09-27(PLAN 第 5 步):同一道闸一轮最多拦一次;AG 一次收尾调桥接 3 次,预算只扣一次(见 _gate_turn_mark)。
        #     2026-10-03:事实类闸(FACT_GATES)除外 —— 事实没变就一直拦,到 5 次熔断为止。
        repeat, dup = _gate_turn_mark(g_now, conv_id, text, transcript_path, strict=g_now in FACT_GATES)
        if repeat:
            try:
                with open(TG_HOOKS / "semantic-superego-gate.log", "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [antigravity|{(conv_id or 'ag')[:8]}] trig='{g_now}' REPEAT(本轮已拦过一次,放行)\n")
            except Exception:
                pass
            print(json.dumps({}))
            return

        budget_file = TG_SEM / f".turn_blocks_{conv_id[:8]}" if conv_id else None
        turn_blocks = 0
        if budget_file and budget_file.exists():
            try:
                turn_blocks = int(budget_file.read_text(encoding="utf-8").strip())
            except Exception:
                turn_blocks = 0

        # Core Red Line Gates: NEVER silently fuse to allow!
        # If it's a lie, fake test, fake model, nagging deferral, or unauthorized card, it MUST block!
        is_hard_redline = any(k in violation for k in (
            "ledger-claim-gate",
            "postmortem-to-guard",
            "honest-scope-assertion-gate",
            "no-nagging-guard",
            "no-nagging-gate",
            "visual-proof-gate",
            "desktop-window-phantom",
            "headless-mock-fraud",
            "model-authenticity-gate",
            "dsh-provider-authenticity-gate",
            "ghost-browser-gate",
            "audit-source-integrity-gate",
            "anti-toy-test-gate",
            "jev-system-one",
            "external-critic-gate",
            "critic-gate"
        )) or g_now in FACT_GATES

        # Hard red lines get up to 5 strict blocks; ordinary gates 2.
        # 2026-09-25 Claude 改:原来 `and not is_hard_redline` 让红线闸【永远不熔断】——
        # 实测一句 `echo` 的探针会话被 Stop 打回 20 次、跑 43 分钟 497 步、改了 29 个文件(Frank 手动按停)。
        # 现在两类都熔断,但熔断【不再静默】:日志记 BUDGET_FUSED,红线熔断时留一个 .fused 标记,
        # 下一轮 PreInvocation 把「拦了 N 次没过,以下未经验证」注给 AG,它必须在收尾里向 Frank 明说。
        # 2026-10-12 Frank 修正:严禁连试 5 次烧 token 内耗！统一改为最多 1 次纠偏(累计 2 次)，未过立即短路熔断并桌面报警
        max_blocks = 2
        if turn_blocks >= max_blocks:
            try:
                log_path = TG_HOOKS / "semantic-superego-gate.log"
                sid_short = conv_id[:8] if conv_id else "ag"
                ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"{ts_str} [antigravity|{sid_short}] trig='BUDGET_FUSED' {'REDLINE' if is_hard_redline else 'NUDGE'}(prev-turn) blocks={turn_blocks}\n")
            except Exception:
                pass
            if is_hard_redline and conv_id:
                try:
                    (TG_SEM / f".fused_{conv_id[:8]}").write_text(
                        f"[TruthGate] 本轮红线闸已连拦 {turn_blocks} 次仍未过,系统放行。你必须在给 Frank 的收尾第一句写明:"
                        f"「TruthGate 拦了 {turn_blocks} 次没过,以下未经验证:」并逐条列出闸指出的问题。不许假装没拦过。",
                        encoding="utf-8")
                except Exception:
                    pass
            # 2026-10-03:事实类闸熔断时直接在 Frank 桌面弹通知 —— 不靠 AG 自己坦白(一轮只弹一次)。
            if g_now in FACT_GATES and os.environ.get("SUPEREGO_TEST") != "1" \
                    and _fresh_once("fuse_alert_" + g_now, conv_id, _ag_turn_key(transcript_path)):
                try:
                    trigger_active_alert(conv_id, [f"{g_now} 拦了 {turn_blocks} 次没改就交付了,这轮说的做好了别信"], text or "")
                except Exception:
                    pass
            print(json.dumps({}))
            return

        if budget_file and not dup:
            try:
                budget_file.write_text(str(turn_blocks + 1), encoding="utf-8")
            except Exception:
                pass

        # Log the block so dashboard.py and watcher record Antigravity gate interceptions in real time!
        try:
            log_path = TG_HOOKS / "semantic-superego-gate.log"
            sid_short = conv_id[:8] if conv_id else "ag"
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
            m = re.search(r"\[(?:TruthGate|Superego) 拦截 - ([^\]]+)\]", violation)
            gate_name = m.group(1) if m else "gate"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts_str} [antigravity|{sid_short}] trig='{gate_name}' BLOCK\n")
        except Exception:
            pass

        result = {
            "decision": "continue",
            "reason": violation
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    # 2. Dispatch to external audit model (Agnes) worker in background
    # Zero latency, zero focus grab, writes directly to verdicts.jsonl
    if transcript_path and os.path.exists(transcript_path):
        runner = [sys.executable]
        flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0  # DETACHED_PROCESS|CREATE_NO_WINDOW
        try:
            subprocess.Popen(
                runner + [os.path.abspath(__file__), "--worker", transcript_path, conv_id],
                creationflags=flags, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    # All gates passed
    print(json.dumps({}))

def trigger_active_alert(conv_id, all_fired, text):
    """Fires sound and interactive modern Windows toast notification in real time (<1s)."""
    sid_short = conv_id[:8] if conv_id else "ag"
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass

    try:
        fired_names = ", ".join(all_fired)
        clean_excerpt = re.sub(r'[\r\n\t"\']+', ' ', text[-120:]).strip().replace("'", "").replace('"', '')
        ps_code = f"""
        try {{
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            $x = New-Object Windows.Data.Xml.Dom.XmlDocument
            $tpl = @"
<toast launch="http://127.0.0.1:17911/dashboard" activationType="protocol">
    <visual>
        <binding template="ToastGeneric">
            <text>🛡️ TruthGate 1.0 拦截警报 [{sid_short}]</text>
            <text>命中门禁: {fired_names}</text>
            <text>{clean_excerpt}</text>
        </binding>
    </visual>
    <actions>
        <action content="打开审判大盘" arguments="http://127.0.0.1:17911/dashboard" activationType="protocol"/>
    </actions>
    <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
"@
            $x.LoadXml($tpl)
            $t = [Windows.UI.Notifications.ToastNotification]::new($x)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($t)
        }} catch {{
            Add-Type -AssemblyName System.Windows.Forms
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Warning
            $notify.Visible = $true
            $notify.ShowBalloonTip(6000, '🛡️ TruthGate 拦截警报 [{sid_short}]', '违规门禁: {fired_names}`n交付片段: {clean_excerpt}', [System.Windows.Forms.ToolTipIcon]::Warning)
            Start-Sleep -Seconds 6
            $notify.Dispose()
        }}
        """
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_code],
            creationflags=(0x00000008 | 0x08000000) if os.name == "nt" else 0,
            close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

def run_worker(transcript_path, conv_id=""):
    """Background worker: evaluates Antigravity's turn text with Agnes external audit model, appends to verdicts.jsonl."""
    import time, hashlib
    text = ""
    blob = ""
    tool_calls = []
    # Retry in background for up to 8s in case disk flush of final response takes a moment
    for _ in range(40):
        text, tool_calls, blob = load_antigravity_turn(transcript_path)
        text = text.strip()
        if len(text) >= 15:
            break
        time.sleep(0.2)

    log_path = TG_HOOKS / "semantic-superego-gate.log"
    sid_short = conv_id[:8] if conv_id else "ag"
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # If text is still empty (e.g. pure tool action turn), record clean PASS rather than hanging on TURN_START
    if len(text) < 15:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{ts_str} [antigravity|{sid_short}] PASS\n")
        except Exception:
            pass
        return

    sem_dir = TG_SEM
    # Deduplicate: Skip re-auditing identical turn text (prevents duplicate stream events)
    fp = hashlib.md5(text.encode('utf-8')).hexdigest()[:10]
    fp_file = sem_dir / f".last_fp_{conv_id[:8]}" if conv_id else sem_dir / ".last_fp_ag"
    try:
        if fp_file.exists():
            last_fp = fp_file.read_text(encoding="utf-8").strip()
            if last_fp == fp:
                return
        fp_file.write_text(fp, encoding="utf-8")
    except Exception:
        pass

    # Extract user prompt for gates that verify against user query
    user_prompt = get_last_user_prompt(transcript_path)

    # 1. Structural gates evaluation (All 15 physical & behavioral gates)
    structural_violations = evaluate_all_structural_gates(
        text, tool_calls, blob,
        user_prompt=user_prompt,
        conv_id=conv_id,
        transcript_path=transcript_path,
        stop_on_first=False
    )
    structural_fired = [gate for gate, _ in structural_violations]

    # 2. Tier 2: Jev System One 实时多域语义拦截
    jev_fired = []
    try:
        if not check_is_off("jev", sid=conv_id):
            if str(TG_HOOKS) not in sys.path:
                sys.path.insert(0, str(TG_HOOKS))
            from superego_jev_engine import judge_assistant_text
            jev_res = judge_assistant_text(text, sid=conv_id)
            jev_fired = list(jev_res.get("fired") or [])
    except Exception:
        pass

    # 3. Tier 3: Agnes external audit / semantic_judge
    try:
        if str(sem_dir) not in sys.path:
            sys.path.insert(0, str(sem_dir))
        import semantic_judge
        t0 = time.time()
        r = semantic_judge.judge(text[-1500:])
        latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        # Fallback to PASS on judge error
        r = {"verdict": "PASS", "fired": []}
        latency_ms = 0

    all_fired = sorted(list(set(structural_fired + jev_fired + (r.get("fired") or []))))
    verdict = "FIRE" if all_fired else "PASS"

    # ACTIVE TRIGGER: Sound beep and Windows Notification immediately!
    if all_fired and not check_is_off("*", sid=conv_id):
        trigger_active_alert(conv_id, all_fired, text)

    tp_tag = f"ag-{conv_id}.jsonl" if conv_id else os.path.basename(transcript_path)

    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "fired": all_fired,
        "text": text[-200:],
        "tp": tp_tag
    }
    if all_fired:
        why_list = []
        for g, vio in structural_violations:
            first_line = vio.split("\n")[0] if vio else g
            why_list.append({"gate": g, "rule": first_line, "group": "structural_gate"})
        try:
            for x in all_fired:
                if not any(w.get("gate") == x for w in why_list):
                    why_list.append(semantic_judge.explain(x))
        except Exception:
            pass
        if why_list:
            rec["why"] = why_list[:5]
            rec["groups"] = sorted({w.get("group", "structural_gate") for w in why_list if isinstance(w, dict)})

    vpath = sem_dir / "verdicts.jsonl"
    try:
        with open(vpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # Centralized log shared with Claude: ~/.claude/hooks/semantic-superego-gate.log
    log_path = TG_HOOKS / "semantic-superego-gate.log"
    sid_short = conv_id[:8] if conv_id else "ag"
    ts_str = time.strftime("%Y-%m-%d %H:%M:%S")
    trig_str = f"trig='{','.join(all_fired)}' " if all_fired else ""
    log_line = f"{ts_str} [antigravity|{sid_short}] {trig_str}{verdict}\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass

    # Token & Latency Cost Accounting
    metrics_file = sem_dir / "audit_metrics.jsonl"
    est_tokens = len(text) // 2
    metric_entry = {
        "ts": ts_str,
        "agent": "antigravity",
        "sid": sid_short,
        "verdict": r.get("verdict", "PASS"),
        "fired": r.get("fired") or [],
        "chars": len(text),
        "est_tokens": est_tokens,
        "judge_latency_ms": latency_ms,
        "is_off": check_is_off("*", sid=conv_id)
    }
    try:
        with open(metrics_file, "a", encoding="utf-8") as mf:
            mf.write(json.dumps(metric_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # 3. 持久化至 TruthGate 统一审判大账 (monitor.db)
    try:
        from truthgate.verdict_monitor import record_verdict
    except ImportError:
        try:
            from verdict_monitor import record_verdict
        except ImportError:
            record_verdict = None
    if record_verdict:
        try:
            reasons_list = [w.get("rule", "") for w in rec.get("why", []) if isinstance(w, dict)] if "why" in rec else []
            record_verdict(
                turn_type="antigravity",
                verdict=verdict,
                fired_rules=all_fired,
                reasons=reasons_list,
                mode="ag_watch_outer_judge",
                latency_ms=float(latency_ms),
                user_prompt=user_prompt[:300] if user_prompt else "",
                assistant_text=text[-500:]
            )
        except Exception:
            pass

    # 4. 生成/刷新 Antigravity 会话实时质检白皮书 (truthgate_live_audit.md)
    if conv_id:
        try:
            ag_conv_dir = Path.home() / ".gemini" / "antigravity" / "brain" / conv_id
            if ag_conv_dir.exists():
                art_file = ag_conv_dir / "truthgate_live_audit.md"
                status_icon = "🔴 发现违规打回 (BLOCK)" if all_fired else "🟢 审查通过 (PASS)"
                rules_str = ", ".join(all_fired) if all_fired else "15 道物理门禁核验放行 (Zero Violation)"
                md_content = f"""# 🛡️ TruthGate 1.0 实时门禁质检看板 (Live Session Audit)

- **当前会话**: `{conv_id}`
- **质检结果**: **{status_icon}**
- **命中规则**: `{rules_str}`
- **外审耗时**: `{latency_ms} ms`
- **核验时间**: `{ts_str}`
- **审判中枢**: [打开本地审判大盘 (http://127.0.0.1:17911/dashboard)](http://127.0.0.1:17911/dashboard)

> 💡 **TruthGate 物理质检原则**：
> 凡宣称“已修复”、“服务正常”、“UI就绪”，必须出示真实测试通过输出、HTTP 响应体或截图。未经验证严禁空口宣称完成。

## 最近一轮回合审查明细
```text
{text[-300:]}
```
"""
                art_file.write_text(md_content, encoding="utf-8")
        except Exception:
            pass

def handle_status():
    """Diagnostic CLI to verify Superego integration health across both brains."""
    print("═══════════════════════════════════════════════════════════════════════════════")
    print("🛡️ 【Superego 跨系统运行状态诊断 (Antigravity ↔ Claude 对齐)】")
    print("═══════════════════════════════════════════════════════════════════════════════")
    
    try:
        from blood_doctor import get_blood_status
    except ImportError:
        try:
            from truthgate.blood_doctor import get_blood_status
        except ImportError:
            get_blood_status = None
    if get_blood_status:
        bs = get_blood_status()
        print(f"0. 系统满血度   : {bs['blood_score']}/100 [{bs['status_label']}]")
        if not bs['is_full_blooded']:
            print("   └─ 升级指南: 运行 'tg setup' 配置 API Key 升级满血 (当前为 Tier 0 本地保底)")

    # 1. Toggle switch
    off_state = check_is_off("*")
    print(f"1. 门禁开关状态 : {'❌ 处于关闭状态 (OFF)' if off_state else '✅ 正常全开 (ON)'}")
    
    # 2. Port 17911 (Fallback & Recall)
    port = get_superego_port()
    h = is_service_healthy(port)
    print(f"2. 本地兜底服务 : 端口 {port} -> {'✅ 正常在线 (bge-small / Qwen recall)' if h else '⏸ 没在跑(语义服务 9/25 按 Frank 下线令关着;不会自动拉起)'}")
    
    # 3. Universal External Audit Model (Gemini / DeepSeek / OpenAI / Agnes / Ollama)
    print("3. 外审模型连接 : ", end="", flush=True)
    try:
        if str(TG_SEM) not in sys.path:
            sys.path.insert(0, str(TG_SEM))
        try:
            import semantic_judge
        except ImportError:
            from truthgate import semantic_judge
        ep = getattr(semantic_judge, "get_critic_endpoint", lambda: None)()
        if ep:
            print(f"✅ 外审就绪 [{ep.get('provider')}] | 目标模型: {ep.get('model')}")
        else:
            print("ℹ️ 未配置外审 Key (已由本地 Tier 0 确定性引擎接管，支持 Gemini/DeepSeek/Ollama)")
    except Exception as e:
        print(f"❌ 异常: {e}")

    # 4. Centralized audit log tail
    log_path = TG_HOOKS / "semantic-superego-gate.log"
    print("4. 统一外审日志 (semantic-superego-gate.log 最新 5 条):")
    if log_path.exists():
        try:
            lines = [l.strip() for l in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            for l in lines[-5:]:
                print(f"   {l}")
        except Exception as e:
            print(f"   读取失败: {e}")
    else:
        print("   （日志暂未生成）")
        
    print("═══════════════════════════════════════════════════════════════════════════════")

def handle_pre_tool(payload):
    """
    Antigravity PreToolUse hook handler (2026-10-11 物理补齐):
    Intercepts dangerous commands / destructive operations / single-source violations
    BEFORE the tool actually executes.
    Output: {"decision": "deny", "reason": "..."} or {"decision": "allow"}
    """
    if not isinstance(payload, dict):
        print(json.dumps({"decision": "allow"}))
        return

    tool_call = payload.get("toolCall") or {}
    t_name = tool_call.get("name") or ""
    t_args = tool_call.get("args") or {}

    claude_payload = None
    if t_name == "run_command":
        claude_payload = {
            "tool_name": "Bash",
            "tool_input": {
                "command": t_args.get("CommandLine", "")
            },
            "cwd": t_args.get("Cwd", os.getcwd())
        }
    elif t_name == "write_to_file":
        claude_payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": t_args.get("TargetFile", ""),
                "content": t_args.get("CodeContent", "")
            },
            "cwd": os.getcwd()
        }
    elif t_name == "replace_file_content":
        claude_payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": t_args.get("TargetFile", ""),
                "old_string": t_args.get("TargetContent", ""),
                "new_string": t_args.get("ReplacementContent", "")
            },
            "cwd": os.getcwd()
        }

    if not claude_payload:
        print(json.dumps({"decision": "allow"}))
        return

    claude_payload_str = json.dumps(claude_payload, ensure_ascii=False)
    priority_gates = ["guard-destructive.py", "single-source-gate.py", "data-overwrite-guard.py"]
    hooks_dir = Path.home() / ".truthgate" / "hooks"

    for g_file in priority_gates:
        p = hooks_dir / g_file
        if not p.exists():
            continue
        flags = (0x08000000) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                [sys.executable, str(p)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=flags, text=True
            )
            out, err = proc.communicate(input=claude_payload_str, timeout=3.0)
            if proc.returncode == 2:
                reason = (err or out).strip() or f"[{p.stem}] 拦截：协议退出码 2"
                print(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False))
                return
            combined = (out or "") + "\n" + (err or "")
            if '"decision": "block"' in combined or '"decision":"block"' in combined:
                try:
                    data = json.loads(out.strip())
                    reason = data.get("reason") or data.get("permissionDecisionReason") or combined
                    print(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False))
                    return
                except Exception:
                    print(json.dumps({"decision": "deny", "reason": combined.strip()}, ensure_ascii=False))
                    return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

    print(json.dumps({"decision": "allow"}))

def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        c_id = sys.argv[3] if len(sys.argv) > 3 else ""
        run_worker(sys.argv[2], c_id)
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        handle_status()
        sys.exit(0)

    if len(sys.argv) < 2:
        print(json.dumps({}))
        sys.exit(0)

    action = sys.argv[1].lower().lstrip("-")
    raw_in = sys.stdin.read().strip()
    payload = {}
    if raw_in:
        try:
            payload = json.loads(raw_in)
        except Exception:
            pass
    global _AG_WS
    _AG_WS = ((payload.get("workspacePaths") or [""])[0] or "") if isinstance(payload, dict) else ""

    # Persistent debug logging to track every live Antigravity hook invocation
    try:
        debug_log = SCRIPTS_DIR / "ag_bridge_debug.log"
        with open(debug_log, "a", encoding="utf-8") as df:
            df.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} action={action} raw_len={len(raw_in)} keys={list(payload.keys())}\n")
    except Exception:
        pass

    try:
        if action == "pre":
            handle_pre(payload)
        elif action == "stop":
            handle_stop(payload)
        elif action in ("pre_tool", "pretool", "pretooluse"):
            handle_pre_tool(payload)
        else:
            print(json.dumps({}))
    except Exception as e:
        # Fail-open: Never block user if hook itself experiences an unexpected bug
        sys.stderr.write(f"[ag_superego_bridge error] {e}\n")
        print(json.dumps({}))

if __name__ == "__main__":
    main()
