# -*- coding: utf-8 -*-
"""security_core.py —— Superego 3.0 统一物理硬安全与行为防御内核 (Deep Execution Security Core).

六重物理硬防御矩阵 (PreToolUse):
  1. 脚本与内联 AST 穿透 (ast_inspector.py)
  2. 拓扑诊断前置门禁 (no_diagnosis_guard.py —— 物理化 R14/R15/R18/R36)
  3. 两阶段动作契约与清单状态机 (action_contract.py —— 物理化 R7/R28/R41)
  4. 代码防劣化与偷工减料门禁 (diff_quality_guard.py)
  5. 环境与依赖防踩踏门禁 (env_safety_guard.py)
  6. 局内风暴限频与死锁熔断器 (burst_limiter.py)
"""
import os
import sys
import re
import json
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from tool_normalizer import normalize_tool_call, NormalizedToolCall
from ast_inspector import audit_command_ast, audit_python_code
from no_diagnosis_guard import check_no_diagnosis_edit
from action_contract import check_action_contract
from diff_quality_guard import check_diff_dilution
from env_safety_guard import check_env_safety
from burst_limiter import check_pre_tool_burst, record_strike, record_success

# 危险混淆与黑客外联反弹特征
_MALICIOUS_CMD_PATTERNS = [
    (re.compile(r"\b(?:powershell|pwsh)\b.*-(?:e|enc|encodedcommand)\b", re.I), "检测到 PowerShell Base64 编码隐藏执行 (EncodedCommand)，存在混淆恶意攻击风险"),
    (re.compile(r"\b(?:curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(?:bash|sh|powershell|pwsh|cmd)\b", re.I), "检测到未经审计的管道直接执行远程脚本 (curl | bash / iwr | iex)，存在供应链投毒风险"),
    (re.compile(r"\b(?:nc|netcat|ncat)\b.*-[ecl]\b", re.I), "检测到 Netcat 反弹 Shell 行为特征"),
    (re.compile(r"\b(?:eval|exec)\s*\(\s*(?:base64_decode|b64decode|atob)\b", re.I), "检测到 Eval Base64 混淆执行载荷"),
    (re.compile(r"\b(?:rmdir|rd)\s+/(?:s|q)\s+[a-zA-Z]:\\(?:\s|$)", re.I), "检测到针对系统根盘的递归强删指令"),
    (re.compile(r"\brm\s+-rf\s+/(?:\s|$)", re.I), "检测到针对 Linux 根目录的致命删除指令"),
    (re.compile(r"\b(?:format|mkfs)\s+[a-zA-Z]:", re.I), "检测到磁盘格式化指令"),
]

# 破坏性覆盖模式
_DESTRUCTIVE_OVERWRITE_PATTERNS = [
    re.compile(r"\brobocopy\b.*/mir\b", re.I),
    re.compile(r"\bcopy-item\b.*-force\b", re.I),
    re.compile(r"\bcp\s+-rf?\b.*/", re.I),
    re.compile(r"\bdrop\s+(?:database|schema|table)\b", re.I),
    re.compile(r"\btruncate\s+table\b", re.I),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
]

# 外部注入常见指令特征（当仅出现在抓取网页/工具输出中时）
_INJECTION_TOKEN_PATTERNS = re.compile(
    r"\[\[\s*SYSTEM\s*\]\]|\[SYSTEM\]|<\s*SYSTEM\s*>"
    r"|ignore\s+(?:all\s+|previous\s+|prior\s+)?instructions"
    r"|do\s+not\s+(?:tell|inform)\s+the\s+user|without\s+telling\s+the\s+user"
    r"|(?:不要|别|不)告诉用户|瞒着用户",
    re.I
)

_FILE_EXT_RE = re.compile(r"[\w][\w./\\-]*\.(?:py|js|mjs|cjs|ts|json|md|ps1|sh|txt|log|db|sqlite|env|key|pem)\b", re.I)


def extract_file_tokens(text: str) -> set:
    tokens = set()
    for match in _FILE_EXT_RE.findall(text or ""):
        base = re.split(r"[\\/]", match)[-1].lower()
        tokens.add(base)
    return tokens


def check_malicious_command(cmd: str) -> Optional[str]:
    if not cmd:
        return None
    for pat, reason in _MALICIOUS_CMD_PATTERNS:
        if pat.search(cmd):
            return f"⛔ [MALICIOUS_COMMAND_BLOCKED] 恶意代码与高危命令硬阻断：{reason}。指令：`{cmd[:100]}`"
    return None


# 备份 / 快照 / 临时目的地：写入这些位置不销毁源数据，属防损毁的正确做法。
# 判定只看命令里是否出现备份类动词 + 备份类目的地，避免被无关路径误伤。
_BACKUP_DEST_TOKENS = (
    "backup", "bak", "snapshot", "archive", "restore", "rollback",
    "tg-fix", "temp", "tmp", ".trash", "quarantine",
)
_BACKUP_CMD_NAMES = (
    "copy-item", "cp", "robocopy", "xcopy", "copy",
)
_TIMESTAMP_DIR_RE = re.compile(r"(?:19|20)\d{6}|(?:19|20)\d{2}-\d{2}-\d{2}|\b1[6-9]\d{8}\b")


def _is_backup_destination(cmd: str) -> bool:
    r"""命令是否在往「备份/临时」位置写。

    保守到底（宁可漏报，绝不误报）：必须【同时】满足
      ① 出现备份类动词（copy-item / cp / robocopy / xcopy / copy）；
      ② 出现备份类目的地 token，或带时间戳的目录名。
    只出现其一不豁免 —— 例如 `Copy-Item -Force C:\data\x D:\data\x` 仍会被拦。
    """
    if not cmd:
        return False
    low = cmd.lower()
    if not any(name in low for name in _BACKUP_CMD_NAMES):
        return False
    if any(tok in low for tok in _BACKUP_DEST_TOKENS):
        return True
    if _TIMESTAMP_DIR_RE.search(cmd):
        return True
    return False

def check_destructive_overwrite(cmd: str, recent_history_text: str) -> Optional[str]:
    if not cmd:
        return None
    for pat in _DESTRUCTIVE_OVERWRITE_PATTERNS:
        if pat.search(cmd):
            # 豁免：往备份/临时位置写不销毁源数据（防损毁的正确做法）。
            # 修复 2026-10-11 实测误杀：Copy-Item -Force 到 backup 目录被判成破坏性覆写。
            if _is_backup_destination(cmd):
                return None
            # 如果是 git reset --hard，必须检查工作区是否有未暂存修改
            if "git" in cmd.lower() and "reset" in cmd.lower() and "--hard" in cmd.lower():
                return (
                    f"⛔ [GIT_HARD_RESET_BLOCKED] 严禁盲目执行 `git reset --hard` 破坏工作区！\n"
                    f"按防代码损毁铁律：若需撤销变更，必须先执行 `git stash push -m 'backup'` 安全落盘备份，"
                    f"或只撤销具体单个文件！"
                )
            has_count_check = bool(re.search(r"\b(?:count|Measure-Object|du\b|wc\s+-l|select\s+count|dir\s+/s)\b", recent_history_text, re.I))
            if not has_count_check:
                return (
                    f"⛔ [DATA_OVERWRITE_BLOCKED] 破坏性数据覆写拦截：即将执行覆盖或清空操作 `{cmd[:80]}`，"
                    "但未发现对两边源数据与目标数据的行数/体积进行事前对比核验（如 count/Measure-Object/du）。"
                    "按防数据损毁铁律，必须先出示两边数据量对比证据，严禁盲目覆盖！"
                )
    return None


def check_anti_prompt_injection(cmd: str, transcript_messages: List[Dict[str, Any]]) -> Optional[str]:
    if not cmd or not transcript_messages:
        return None

    # 1. 只读探索与信息查阅类命令天然免疫注入执行，绝对放行
    _READONLY_CMD_RE = re.compile(
        r"^(?:head|tail|cat|grep|rg|find|which|type|more|less|bat|ls|dir|git\s+(?:status|log|diff|show)|echo|pwd)\b",
        re.I
    )
    first_cmd = cmd.strip().split("|")[0].strip()
    if _READONLY_CMD_RE.search(first_cmd) or _READONLY_CMD_RE.search(cmd.strip()):
        # 只要不包含黑客外联反弹特征，只读命令绝对放行
        if not re.search(r"\b(?:nc|netcat|bash\s+-i|Invoke-WebRequest|curl.*\|\s*bash)\b", cmd, re.I):
            return None

    cmd_tokens = extract_file_tokens(cmd)
    if not cmd_tokens:
        return None

    user_tokens = set()
    poisoned_tool_tokens = set()

    for m in transcript_messages:
        mtype = m.get("type", "")
        if mtype == "user":
            content = (m.get("message") or {}).get("content")
            if isinstance(content, str):
                user_tokens |= extract_file_tokens(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            user_tokens |= extract_file_tokens(item.get("text", ""))
                        elif item.get("type") == "tool_result":
                            tc = str(item.get("content") or "")
                            # 核心第一性原理：只有当工具返回的内容中确实包含恶意注入指令特征时，
                            # 从该内容中解析出的新文件/目标才被标记为受毒害的嫌疑目标！
                            if _INJECTION_TOKEN_PATTERNS.search(tc):
                                poisoned_tool_tokens |= extract_file_tokens(tc)
        elif mtype == "assistant":
            content = (m.get("message") or {}).get("content")
            if isinstance(content, str):
                user_tokens |= extract_file_tokens(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        user_tokens |= extract_file_tokens(item.get("text", ""))

    suspect = (cmd_tokens & poisoned_tool_tokens) - user_tokens
    if suspect:
        return (
            f"⛔ [PROMPT_INJECTION_BLOCKED] 反向提示词注入与越权防御：即将执行的命令中涉及的文件/目标 {sorted(suspect)} "
            "源自包含未授权注入特征的外部抓取内容或工具返回，用户从没有在对话中提出或授权过该操作。"
            "系统已强行阻断外部文档越权操控 AI 执行本地命令的行为！"
        )
    return None


def audit_tool_call(
    tool_name: str,
    tool_input: dict,
    transcript_messages: List[Dict[str, Any]] = None,
    conv_id: str = "global",
    cwd: Optional[Path] = None
) -> Tuple[bool, Optional[str]]:
    """全局统一工具调用安检接口 (PreToolUse Gate) —— 接入六重物理硬防御矩阵"""
    norm: NormalizedToolCall = normalize_tool_call(tool_name, tool_input)

    # 1. 局内突发工具调用风暴限频检查
    burst_ok, burst_err = check_pre_tool_burst(conv_id)
    if not burst_ok:
        record_strike(conv_id, "BURST_LIMIT")
        return False, burst_err

    # ════════════════════════════════════════════════════════════
    # 分支 A: 命令行执行类 (Command Execution)
    # ════════════════════════════════════════════════════════════
    if norm.kind == "command":
        cmd = norm.command
        if not cmd:
            return True, None

        # 1. 混淆木马与远程管道拦截
        malicious = check_malicious_command(cmd)
        if malicious:
            record_strike(conv_id, "MALICIOUS_CMD")
            return False, malicious

        # 2. 破坏性数据覆写与 git hard reset 拦截
        recent_history = ""
        if transcript_messages:
            recent_history = json.dumps(transcript_messages[-5:], ensure_ascii=False)
        overwrite = check_destructive_overwrite(cmd, recent_history)
        if overwrite:
            record_strike(conv_id, "DESTRUCTIVE_OVERWRITE")
            return False, overwrite

        # 3. 环境与依赖防踩踏 (lockfile 保护 / 全局 pip 拦截)
        env_ok, env_err = check_env_safety(cmd)
        if not env_ok:
            record_strike(conv_id, "ENV_SAFETY")
            return False, env_err

        # 4. 两阶段动作契约 (Manifest) 拦截
        contract_ok, contract_err = check_action_contract(cmd, cwd)
        if not contract_ok:
            record_strike(conv_id, "ACTION_CONTRACT")
            return False, contract_err

        # 5. 脚本文件与内联 python -c / node -e 语法树穿透 (AST)
        ast_ok, ast_err = audit_command_ast(cmd, cwd)
        if not ast_ok:
            record_strike(conv_id, "AST_PAYLOAD")
            return False, ast_err

        # 6. 反向提示词注入防御
        if transcript_messages:
            injection = check_anti_prompt_injection(cmd, transcript_messages)
            if injection:
                record_strike(conv_id, "PROMPT_INJECTION")
                return False, injection

        record_success(conv_id)
        return True, None

    # ════════════════════════════════════════════════════════════
    # 分支 B: 代码修改与文件写入类 (File Write / Edit)
    # ════════════════════════════════════════════════════════════
    elif norm.kind in ("file_write", "file_edit"):
        file_path = norm.file_path
        if not file_path:
            return True, None

        # 1. No-Diagnosis-No-Edit 拓扑诊断门禁 (物理化 R14/R15/R18/R36)
        diag_ok, diag_err = check_no_diagnosis_edit(
            file_path,
            is_new_file=norm.is_new_file,
            transcript_messages=transcript_messages,
            cwd=cwd
        )
        if not diag_ok:
            record_strike(conv_id, "NO_DIAGNOSIS")
            return False, diag_err

        # 2. 代码防劣化与偷工减料审查
        if norm.kind == "file_edit" and norm.old_content:
            diff_ok, diff_err = check_diff_dilution(file_path, norm.old_content, norm.content)
            if not diff_ok:
                record_strike(conv_id, "DIFF_DILUTION")
                return False, diff_err

        # 3. 写入内容 AST 静态高危语法审查 (针对 Python 文件)
        if file_path.lower().endswith(".py"):
            ast_ok, ast_err = audit_python_code(norm.content, source_label=f"待写入文件 `{Path(file_path).name}`")
            if not ast_ok:
                record_strike(conv_id, "AST_FILE_PAYLOAD")
                return False, ast_err

        record_success(conv_id)
        return True, None

    return True, None
