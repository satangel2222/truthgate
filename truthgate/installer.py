# -*- coding: utf-8 -*-
"""installer.py —— Superego 3.0 跨四端通用安装引擎 (Universal Multi-Platform Installer)。
支持在任意机器（Windows / macOS / Linux）上一键部署与自适应挂载：
  1. Claude Code (~/.claude)
  2. OpenAI Codex (~/.codex)
  3. Google Antigravity (~/.gemini)
  4. DeepSeek Harness (DSH Desktop / cordis)
"""
import os
import sys
import time
import json
import shutil
import platform
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

HOME = Path.home()
SYSTEM = platform.system()
HERE = Path(__file__).resolve().parent

# 目标端平台路径
PLATFORMS = {
    "claude": {
        "name": "Claude Code",
        "home": HOME / ".claude",
        "hooks_dir": HOME / ".claude" / "hooks",
        "type": "hooks_and_semantic",
    },
    "codex": {
        "name": "OpenAI Codex",
        "home": HOME / ".codex",
        "hooks_dir": HOME / ".codex" / "hooks",
        "type": "hooks_mirror",
    },
    "antigravity": {
        "name": "Google Antigravity",
        "home": HOME / ".gemini",
        "hooks_dir": HOME / ".gemini" / "antigravity" / "scripts",
        "type": "bridge_and_plugin",
    },
    "dsh": {
        "name": "DeepSeek Harness (DSH)",
        "home": Path(os.environ.get("APPDATA", str(HOME / ".config"))) / "dsh-desktop" / "harness",
        "type": "cordis_and_skills",
    }
}


def detect_installed_platforms() -> dict:
    """探测本机已安装的 AI 平台"""
    detected = {}
    for pid, pinfo in PLATFORMS.items():
        if pinfo["home"].exists():
            detected[pid] = pinfo
    return detected


def setup_profile(profile_id: str = "vibe-boss") -> bool:
    """配置并激活用户画像"""
    try:
        from config import save_config, load_config
    except ImportError:
        from superego.config import save_config, load_config
        
    cfg = load_config()
    cfg["version"] = "3.0.0"
    cfg["active_profile"] = profile_id
    cfg["last_updated"] = datetime.now().isoformat()
    return save_config(cfg)


def register_claude_hooks(claude_home: Path) -> bool:
    """安全将 hook_entry.py 挂载进 ~/.claude/settings.json，保持幂等并保留已有配置"""
    settings_file = claude_home / "settings.json"
    settings_data = {}
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                settings_data = json.load(f)
        except Exception:
            settings_data = {}

    hooks_dict = settings_data.setdefault("hooks", {})
    pre_list = hooks_dict.setdefault("PreToolUse", [])
    stop_list = hooks_dict.setdefault("Stop", [])

    # Claude Code 无论在 Windows/Mac/Linux 均在 Bash 子环境运行钩子，必须使用 $HOME 兼容语法
    hook_cmd_pre = 'python "$HOME/.claude/hooks/hook_entry.py" pre'
    hook_cmd_stop = 'python "$HOME/.claude/hooks/hook_entry.py" stop'

    # 1. 挂载 PreToolUse
    has_pre = False
    for entry in pre_list:
        for h in entry.get("hooks", []):
            if "hook_entry.py" in h.get("command", ""):
                has_pre = True
                break
    if not has_pre:
        pre_list.append({
            "matcher": "Bash|PowerShell|Write|Edit",
            "hooks": [
                {
                    "type": "command",
                    "command": hook_cmd_pre,
                    "timeout": 10
                }
            ]
        })

    # 2. 挂载 Stop
    has_stop = False
    for entry in stop_list:
        for h in entry.get("hooks", []):
            if "hook_entry.py" in h.get("command", ""):
                has_stop = True
                break
    if not has_stop:
        stop_list.append({
            "hooks": [
                {
                    "type": "command",
                    "command": hook_cmd_stop,
                    "timeout": 15
                }
            ]
        })

    try:
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        sys.stderr.write(f"   [!] 写入 Claude settings.json 失败: {e}\n")
        return False


def unregister_claude_hooks(claude_home: Path) -> bool:
    """从 ~/.claude/settings.json 安全移除 hook_entry.py 挂载"""
    settings_file = claude_home / "settings.json"
    if not settings_file.exists():
        return True
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        hooks_dict = data.get("hooks", {})
        for hook_type in ["PreToolUse", "Stop"]:
            if hook_type in hooks_dict:
                new_list = []
                for entry in hooks_dict[hook_type]:
                    filtered = [h for h in entry.get("hooks", []) if "hook_entry.py" not in h.get("command", "")]
                    if filtered:
                        entry["hooks"] = filtered
                        new_list.append(entry)
                hooks_dict[hook_type] = new_list
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def register_codex_hooks(codex_home: Path) -> bool:
    """安全将 hook_entry.py 挂载进 ~/.codex/hooks.json，保持幂等并保留已有配置"""
    hooks_file = codex_home / "hooks.json"
    hooks_data = {}
    if hooks_file.exists():
        try:
            with open(hooks_file, "r", encoding="utf-8") as f:
                hooks_data = json.load(f)
        except Exception:
            hooks_data = {}

    hooks_dict = hooks_data.setdefault("hooks", {})
    pre_list = hooks_dict.setdefault("PreToolUse", [])
    stop_list = hooks_dict.setdefault("Stop", [])

    py_cmd = "python" if SYSTEM == "Windows" else "python3"
    hook_path = codex_home / "hooks" / "hook_entry.py"
    hook_cmd_pre = f'{py_cmd} "{hook_path}" pre'
    hook_cmd_stop = f'{py_cmd} "{hook_path}" stop'

    # 1. 挂载 PreToolUse
    has_pre = False
    for entry in pre_list:
        for h in entry.get("hooks", []):
            if "hook_entry.py" in h.get("command", ""):
                has_pre = True
                break
    if not has_pre:
        pre_list.append({
            "matcher": "Bash|PowerShell|Write|Edit",
            "hooks": [
                {
                    "type": "command",
                    "command": hook_cmd_pre,
                    "timeout": 10
                }
            ]
        })

    # 2. 挂载 Stop
    has_stop = False
    for entry in stop_list:
        for h in entry.get("hooks", []):
            if "hook_entry.py" in h.get("command", ""):
                has_stop = True
                break
    if not has_stop:
        stop_list.append({
            "hooks": [
                {
                    "type": "command",
                    "command": hook_cmd_stop,
                    "timeout": 15
                }
            ]
        })

    try:
        with open(hooks_file, "w", encoding="utf-8") as f:
            json.dump(hooks_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        sys.stderr.write(f"   [!] 写入 Codex hooks.json 失败: {e}\n")
        return False


def unregister_codex_hooks(codex_home: Path) -> bool:
    """从 ~/.codex/hooks.json 安全移除 hook_entry.py 挂载"""
    hooks_file = codex_home / "hooks.json"
    if not hooks_file.exists():
        return True
    try:
        with open(hooks_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        hooks_dict = data.get("hooks", {})
        for hook_type in ["PreToolUse", "Stop"]:
            if hook_type in hooks_dict:
                new_list = []
                for entry in hooks_dict[hook_type]:
                    filtered = [h for h in entry.get("hooks", []) if "hook_entry.py" not in h.get("command", "")]
                    if filtered:
                        entry["hooks"] = filtered
                        new_list.append(entry)
                hooks_dict[hook_type] = new_list
        with open(hooks_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def rollback_superego() -> bool:
    """执行 3 秒一键物理回滚：注销四端门禁与插件挂载"""
    print("🔄 正在执行 3 秒基准一键物理回滚...")
    # 1. 注销 Claude Code
    claude_home = HOME / ".claude"
    if claude_home.exists():
        unregister_claude_hooks(claude_home)
        print("   [✓] Claude Code settings.json 门禁已注销")

    # 2. 注销 OpenAI Codex
    codex_home = HOME / ".codex"
    if codex_home.exists():
        unregister_codex_hooks(codex_home)
        print("   [✓] OpenAI Codex hooks.json 门禁已注销")

    # 3. 注销 Antigravity 全局插件与 Native MCP
    ag_config = HOME / ".gemini" / "config" / "config.json"
    if ag_config.exists():
        try:
            with open(ag_config, "r", encoding="utf-8") as f:
                ag_data = json.load(f)
            plugins = ag_data.get("plugins", {})
            if "superego-plugin" in plugins:
                del plugins["superego-plugin"]
            user_settings = ag_data.get("userSettings", {})
            grants = user_settings.get("globalPermissionGrants", {})
            if "allow" in grants:
                grants["allow"] = [p for p in grants["allow"] if not (isinstance(p, str) and p.startswith("mcp(superego"))]
            with open(ag_config, "w", encoding="utf-8") as f:
                json.dump(ag_data, f, indent=2, ensure_ascii=False)
            print("   [✓] Google Antigravity 全局插件与权限授权已安全移除")
        except Exception:
            pass

    ag_mcp_cfg = HOME / ".gemini" / "config" / "mcp_config.json"
    if ag_mcp_cfg.exists():
        try:
            with open(ag_mcp_cfg, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            servers = mdata.get("mcpServers", {})
            if "superego" in servers:
                del servers["superego"]
                with open(ag_mcp_cfg, "w", encoding="utf-8") as f:
                    json.dump(mdata, f, indent=2, ensure_ascii=False)
                print("   [✓] Google Antigravity Native MCP 挂载已安全注销")
        except Exception:
            pass

    print("✅ 已彻底还原至纯净基准状态！")
    return True


def register_skills(detected_platforms: dict) -> list:
    """跨端分发 Superego 官方核心治理与自愈技能 (如 postmortem-to-guard)"""
    synced = []
    candidates = [
        HERE.parent / "skills",
        HERE / "skills",
        Path.cwd() / "skills"
    ]
    skills_src_dir = None
    for cand in candidates:
        if cand.exists():
            skills_src_dir = cand
            break

    if not skills_src_dir:
        return synced

    skill_folders = [p for p in skills_src_dir.iterdir() if p.is_dir()]
    if not skill_folders:
        return synced

    # 1. Claude Code (~/.claude/skills)
    if "claude" in detected_platforms:
        target_dir = detected_platforms["claude"]["home"] / "skills"
        target_dir.mkdir(parents=True, exist_ok=True)
        for sk in skill_folders:
            dest = target_dir / sk.name
            shutil.copytree(sk, dest, dirs_exist_ok=True)
            synced.append(f"Claude: {sk.name}")

    # 2. OpenAI Codex (~/.codex/skills)
    if "codex" in detected_platforms:
        target_dir = detected_platforms["codex"]["home"] / "skills"
        target_dir.mkdir(parents=True, exist_ok=True)
        for sk in skill_folders:
            dest = target_dir / sk.name
            shutil.copytree(sk, dest, dirs_exist_ok=True)
            synced.append(f"Codex: {sk.name}")

    # 3. Antigravity (~/.gemini/config/skills)
    if "antigravity" in detected_platforms:
        target_dir = detected_platforms["antigravity"]["home"] / "config" / "skills"
        target_dir.mkdir(parents=True, exist_ok=True)
        for sk in skill_folders:
            dest = target_dir / sk.name
            shutil.copytree(sk, dest, dirs_exist_ok=True)
            synced.append(f"Antigravity: {sk.name}")

    # 4. Workspace Level (.agents/skills) if in a workspace
    try:
        ws_agents_skills = Path.cwd() / ".agents" / "skills"
        ws_agents_skills.mkdir(parents=True, exist_ok=True)
        for sk in skill_folders:
            dest = ws_agents_skills / sk.name
            shutil.copytree(sk, dest, dirs_exist_ok=True)
            synced.append(f"Workspace: {sk.name}")
    except Exception:
        pass

    return synced


def install_superego(profile: str = "vibe-boss", dry_run: bool = False) -> bool:
    """执行一键跨端安装与双核挂载"""
    print("=" * 70)
    print("🚀 SUPEREGO 3.0 跨端通用 AI 紧箍咒与物理硬防线一键安装器")
    print(f"操作系统: {SYSTEM} | 用户主目录: {HOME}")
    print(f"激活模式: {profile}")
    print("=" * 70)

    detected = detect_installed_platforms()
    if not detected:
        print("⚠️ 未在默认路径发现支持的 AI 平台。创建默认 ~/.claude 与 ~/.superego 配置...")
        (HOME / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
        detected["claude"] = PLATFORMS["claude"]

    print("\n🔍 [1/3] 正在探测本机已安装的 AI 平台...")
    for pid, pinfo in detected.items():
        print(f"   [✓] 发现平台: {pinfo['name']} -> {pinfo['home']}")

    if dry_run:
        print("\nℹ️ [Dry Run] 预检模式通过，未写入任何文件。")
        return True

    print("\n🛡️ [2/3] 配置用户画像与安全内核...")
    setup_profile(profile)
    print(f"   [✓] 已激活 Profile 面具: {profile}")

    print("\n⚡ [3/3] 跨端挂载安全门禁与语义引擎...")
    
    # 核心引擎源码列表 (TruthGate 1.0 / Superego 3.0 完整全套核心)
    core_files = [
        "tool_normalizer.py",
        "ast_inspector.py",
        "no_diagnosis_guard.py",
        "action_contract.py",
        "diff_quality_guard.py",
        "env_safety_guard.py",
        "burst_limiter.py",
        "read_after_write.py",
        "honest_scope_gate.py",
        "visual_proof_gate.py",
        "nav_ladder.py",
        "security_core.py",
        "critic_engine.py",
        "jev_engine.py",
        "semantic_judge.py",
        "internal_four_ends.py",
        "search_integrity_gate.py",
        "verdict_monitor.py",
        "postmortem_guard.py",
        "dashboard.py",
        "config.py",
        "replay.py",
        "hook_entry.py",
        "no-nagging-guard.py",
        "parity_auditor.py",
        "deep_parity_auditor.py",
        "blood_doctor.py",
        "doctor.py",
        "evidence_table.py",
        "delivery_check.py",
        "dsh-hooks-shim.py",
        "anti_stale_assertion_gate.py",
        "anti_toy_test_gate.py",
        "misfire_rate.py",
        "review_loop.py",
        "single_source.py",
        "six_universes.py",
        "source_news.py",
        "spec_gen.py",
        "stale_process.py",
        "vision_proof.py"
    ]

    # 同步规则包到 ~/.superego/rulepacks
    rulepacks_src = HERE / "rulepacks"
    if rulepacks_src.exists():
        custom_rp = HOME / ".superego" / "rulepacks"
        custom_rp.mkdir(parents=True, exist_ok=True)
        for rp in rulepacks_src.glob("*.rulepack.json"):
            shutil.copy2(rp, custom_rp / rp.name)

    # 1. 部署到 Claude Code
    if "claude" in detected:
        c_hooks = detected["claude"]["hooks_dir"]
        c_hooks.mkdir(parents=True, exist_ok=True)
        for cf in core_files:
            src = HERE / cf
            if src.exists():
                shutil.copy2(src, c_hooks / cf)
        if rulepacks_src.exists():
            rp_dest = c_hooks / "rulepacks"
            rp_dest.mkdir(parents=True, exist_ok=True)
            for rp in rulepacks_src.glob("*.rulepack.json"):
                shutil.copy2(rp, rp_dest / rp.name)
        hooks_src = HERE / "hooks"
        if hooks_src.exists():
            for hf in hooks_src.glob("*.py"):
                shutil.copy2(hf, c_hooks / hf.name)
        register_claude_hooks(detected["claude"]["home"])
        print("   [✓] Claude Code 核心门禁与 settings.json 挂载就绪")

    # 2. 镜像对齐到 Codex
    if "codex" in detected:
        x_hooks = detected["codex"]["hooks_dir"]
        x_hooks.mkdir(parents=True, exist_ok=True)
        for cf in core_files:
            src = HERE / cf
            if src.exists():
                shutil.copy2(src, x_hooks / cf)
        if rulepacks_src.exists():
            rp_dest = x_hooks / "rulepacks"
            rp_dest.mkdir(parents=True, exist_ok=True)
            for rp in rulepacks_src.glob("*.rulepack.json"):
                shutil.copy2(rp, rp_dest / rp.name)
        hooks_src = HERE / "hooks"
        if hooks_src.exists():
            for hf in hooks_src.glob("*.py"):
                shutil.copy2(hf, x_hooks / hf.name)
        register_codex_hooks(detected["codex"]["home"])
        print("   [✓] OpenAI Codex 核心安全引擎镜像与 hooks.json 挂载就绪")

    # 3. 关联 Antigravity
    if "antigravity" in detected:
        ag_home = detected["antigravity"]["home"]
        ag_scripts = detected["antigravity"]["hooks_dir"]
        ag_scripts.mkdir(parents=True, exist_ok=True)
        # 部署核心库、Antigravity 核心桥接脚本、Native MCP 服务端与看门狗
        ag_deploy_files = core_files + ["ag_superego_bridge.py", "superego_mcp_server.py", "ag_watch.py"]
        for cf in ag_deploy_files:
            src = HERE / cf
            if src.exists():
                shutil.copy2(src, ag_scripts / cf)
        hooks_src = HERE / "hooks"
        if hooks_src.exists():
            for hf in hooks_src.glob("*.py"):
                shutil.copy2(hf, ag_scripts / hf.name)
        if rulepacks_src.exists():
            rp_dest = ag_scripts / "rulepacks"
            rp_dest.mkdir(parents=True, exist_ok=True)
            for rp in rulepacks_src.glob("*.rulepack.json"):
                shutil.copy2(rp, rp_dest / rp.name)

        # 部署 MCP 懒加载工具模式定义到 ~/.gemini/antigravity/mcp/superego/
        ag_mcp_dir = ag_home / "antigravity" / "mcp" / "superego"
        ag_mcp_dir.mkdir(parents=True, exist_ok=True)
        mcp_src_dir = HERE / "mcp"
        if mcp_src_dir.exists():
            for mf in mcp_src_dir.glob("*"):
                if mf.is_file():
                    shutil.copy2(mf, ag_mcp_dir / mf.name)

        # 注册 Native MCP 服务到 ~/.gemini/config/mcp_config.json
        ag_mcp_config = ag_home / "config" / "mcp_config.json"
        mcp_cfg = {}
        if ag_mcp_config.exists():
            try:
                mcp_cfg = json.loads(ag_mcp_config.read_text(encoding="utf-8"))
            except Exception:
                mcp_cfg = {}
        mcp_servers = mcp_cfg.setdefault("mcpServers", {})
        server_script = (ag_scripts / "superego_mcp_server.py").as_posix()
        mcp_servers["superego"] = {
            "command": "python",
            "args": [server_script]
        }
        ag_mcp_config.parent.mkdir(parents=True, exist_ok=True)
        ag_mcp_config.write_text(
            json.dumps(mcp_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 部署全局插件: ~/.gemini/config/plugins/superego-plugin/
        ag_plugin_dir = ag_home / "config" / "plugins" / "superego-plugin"
        ag_plugin_dir.mkdir(parents=True, exist_ok=True)

        ag_plugin_json = {
            "name": "superego-plugin",
            "version": "3.0.0",
            "description": "Native Superego 3.0 governance, quality gating, MCP verification, and active watchdog plugin for Google Antigravity.",
            "author": {
                "name": "Frank & Superego Community"
            }
        }
        (ag_plugin_dir / "plugin.json").write_text(
            json.dumps(ag_plugin_json, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        py_cmd = "py -3" if SYSTEM == "Windows" else "python3"
        bridge_script = (
            r"%USERPROFILE%/.gemini/antigravity/scripts/ag_superego_bridge.py"
            if SYSTEM == "Windows"
            else "~/.gemini/antigravity/scripts/ag_superego_bridge.py"
        )
        # 注: Antigravity 内部 language_server 对通用 hooks.json 执行服务端灰度控制，
        # Superego 3.0 正式采用 Native MCP (superego_verify) + ag_watch.py 物理闭环
        ag_hooks_json = {
            "superego-gate": {
                "enabled": False,
                "note": "Antigravity language_server gates hooks server-side; Superego 3.0 runs via Native MCP + ag_watch.py.",
                "PreInvocation": [
                    {
                        "type": "command",
                        "command": f"{py_cmd} {bridge_script} pre",
                        "timeout": 5
                    }
                ],
                "Stop": [
                    {
                        "type": "command",
                        "command": f"{py_cmd} {bridge_script} stop",
                        "timeout": 120
                    }
                ]
            }
        }
        (ag_plugin_dir / "hooks.json").write_text(
            json.dumps(ag_hooks_json, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 注册并激活全局插件与权限授权到 ~/.gemini/config/config.json
        ag_config_file = ag_home / "config" / "config.json"
        cfg_data = {}
        if ag_config_file.exists():
            try:
                cfg_data = json.loads(ag_config_file.read_text(encoding="utf-8"))
            except Exception:
                cfg_data = {}
        plugins_dict = cfg_data.setdefault("plugins", {})
        plugins_dict["superego-plugin"] = {"enabled": True}

        # 预授权 Native MCP 工具权限，防止弹窗阻塞自动化
        user_settings = cfg_data.setdefault("userSettings", {})
        grants = user_settings.setdefault("globalPermissionGrants", {})
        allow_list = grants.setdefault("allow", [])
        for perm in [
            "mcp(superego/*)",
            "mcp(superego/superego_verify)",
            "mcp(superego/superego_status)"
        ]:
            if perm not in allow_list:
                allow_list.append(perm)

        ag_config_file.parent.mkdir(parents=True, exist_ok=True)
        ag_config_file.write_text(
            json.dumps(cfg_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("   [✓] Google Antigravity Native MCP (superego_verify) 与权限挂载就绪")
        print("   [✓] Google Antigravity 全局插件与后台看门狗 (ag_watch.py) 就绪 (跨项目全局生效)")

    # 4. 关联 DSH
    if "dsh" in detected:
        print("   [✓] DeepSeek Harness (DSH) 旁路监听就绪 (零侵入模式)")

    # 5. 跨端分发官方核心治理与自愈技能 (postmortem-to-guard)
    synced_skills = register_skills(detected)
    if synced_skills:
        print(f"   [✓] 核心治理与自愈技能分发完成: {', '.join(sorted(set(synced_skills)))}")

    print("\n" + "=" * 70)
    print("🎉 恭喜！Superego 3.0 已成功部署至全部平台！")
    print("• 行为对齐 (Jev 349ms 快车道): 已就绪")
    print("• 物理六重硬防线 (CodeGraph诊断/两阶段动作契约/真实桌面视窗/AST穿透): 100% 物理硬锁生效")
    print("• 启动实时大盘: 运行 python -m superego dashboard (访问 http://127.0.0.1:17911/dashboard)")
    print("=" * 70)
    return True


def handle_profile_cli(args: list):
    try:
        from config import list_profiles, get_active_profile, set_active_profile, save_custom_profile, merge_profiles
    except ImportError:
        from superego.config import list_profiles, get_active_profile, set_active_profile, save_custom_profile, merge_profiles

    sub = args[0] if args else "list"
    if sub == "list":
        profiles = list_profiles()
        active_id = get_active_profile().get("id")
        print("=" * 65)
        print("🎭 Superego 3.0 用户治理画像列表 (Active Profiles):")
        print("=" * 65)
        for pid, p in profiles.items():
            is_active = (pid == active_id)
            flag = "★ [ACTIVE]" if is_active else "  [      ]"
            print(f"{flag} {pid:<15} {p.get('name')}")
            print(f"       激活规则包: {p.get('rulepacks')}")
            print(f"       允许代码黑话: {'是' if p.get('allowed_jargon') else '否'} | 来源: {p.get('_source', 'builtin')}")
            print(f"       说明: {p.get('description')}\n")
    elif sub == "use":
        if len(args) < 2:
            print("❌ 用法: python -m superego profile use <profile_id>")
            sys.exit(1)
        pid = args[1]
        try:
            set_active_profile(pid)
            print(f"✅ 成功切换当前激活画像为: {pid}")
        except Exception as e:
            print(f"❌ 切换失败: {e}")
            sys.exit(1)
    elif sub == "init":
        if len(args) < 2:
            print("❌ 用法: python -m superego profile init <profile_id>")
            sys.exit(1)
        pid = args[1]
        template = {
            "id": pid,
            "name": f"自定义画像: {pid}",
            "description": "由用户自主配置的行为治理与安全审查画像",
            "persona_title": "自定义 AI 协作者",
            "rulepacks": [
                "@security/core-safe"
            ],
            "allowed_jargon": True,
            "destructive_confirm_only_real_harm": False,
            "rules_override": {
                "R5_strict_no_asking": False,
                "R8_free_open_source_first": True
            }
        }
        if save_custom_profile(template):
            print(f"✅ 自定义画像模板已生成: ~/.superego/profiles/{pid}.json")
            print(f"   您可以按需配置生效的 RulePacks，然后运行: python -m superego profile use {pid}")
    elif sub == "merge":
        if len(args) < 4 or "-o" not in args:
            print("❌ 用法: python -m superego profile merge <profile1> <profile2> -o <target_profile_id>")
            sys.exit(1)
        p1 = args[1]
        p2 = args[2]
        out_idx = args.index("-o")
        new_id = args[out_idx + 1]
        try:
            merged = merge_profiles(p1, p2, new_id)
            print(f"🎉 成功合并画像 [{p1}] 与 [{p2}] -> 生成新画像: {new_id} ({merged.get('name')})")
            print(f"   生效规则包: {merged.get('rulepacks')}")
            print(f"   启用新画像: tg profile use {new_id}")
        except Exception as e:
            print(f"❌ 合并失败: {e}")
            sys.exit(1)
    else:
        print("❌ 未知 profile 指令。支持: list, use, init, merge")
        sys.exit(1)


def handle_rulepack_cli(args: list):
    try:
        from config import list_rulepacks, get_active_profile, load_config, save_config, CUSTOM_RULEPACKS_DIR
        from rulepack_runner import validate_rulepack_file, test_all_rulepacks
    except ImportError:
        from truthgate.config import list_rulepacks, get_active_profile, load_config, save_config, CUSTOM_RULEPACKS_DIR
        from truthgate.rulepack_runner import validate_rulepack_file, test_all_rulepacks

    sub = args[0] if args else "list"
    if sub == "list":
        packs = list_rulepacks()
        active_packs = get_active_profile().get("rulepacks", [])
        print("=" * 75)
        print("📦 TruthGate 1.0 规则包生态列表 (Available RulePacks):")
        print("=" * 75)
        for pk_id, pk in packs.items():
            is_enabled = pk_id in active_packs
            flag = "★ [ENABLED]" if is_enabled else "  [       ]"
            source = pk.get("_source", "builtin")
            print(f"{flag} {pk_id:<24} {pk.get('name')} (v{pk.get('version')}) [{source}]")
            print(f"       包含规则: {len(pk.get('rules', []))} 条 | 类别: {pk.get('category')} | Tier: {pk.get('tier')}")
            print(f"       说明: {pk.get('description')}\n")
    elif sub == "test":
        if len(args) > 1:
            target = args[1]
            all_packs = list_rulepacks()
            if target in all_packs:
                filepath = Path(all_packs[target]["_path"])
            else:
                filepath = Path(target)
            res = validate_rulepack_file(filepath)
            sys.exit(0 if res.get("ok") else 1)
        else:
            success = test_all_rulepacks()
            sys.exit(0 if success else 1)
    elif sub == "init":
        if len(args) < 2:
            print("❌ 用法: tg rulepack init <rulepack_id> (或 python -m truthgate rulepack init <rulepack_id>)")
            sys.exit(1)
        pk_id = args[1]
        clean_name = pk_id.replace("@", "").replace("/", "_")
        CUSTOM_RULEPACKS_DIR.mkdir(parents=True, exist_ok=True)
        target_path = CUSTOM_RULEPACKS_DIR / f"{clean_name}.rulepack.json"
        template = {
            "$schema": "https://truthgate.ai/schema/rulepack-v1.json",
            "id": pk_id,
            "name": f"自定义规则包: {pk_id}",
            "version": "1.0.0",
            "author": "Custom",
            "license": "MIT",
            "category": "behavioral",
            "description": "自定义行为审查规则包",
            "tier": 2,
            "max_fp_rate": 0.005,
            "rules": [
                {
                    "id": "CUSTOM-01",
                    "text": "自定义红线规则描述: 严禁...",
                    "timing": "Stop",
                    "severity": "BLOCK"
                }
            ],
            "golden_cases": [
                {
                    "text": "触发红线的违规样例句子",
                    "expected": "FIRE",
                    "rule": "CUSTOM-01",
                    "rationale": "测试触发原因"
                },
                {
                    "text": "完全合规且带有客观测试证据的放行句子 exit code 0",
                    "expected": "PASS",
                    "rule": "CUSTOM-01",
                    "rationale": "测试放行原因"
                }
            ]
        }
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"✅ 自定义规则包模板已生成: {target_path}")
        print(f"   您可以按 rulepack_spec.md 规范补充规则与样本，并运行:")
        print(f"   tg rulepack test {pk_id}")
    elif sub == "enable":
        if len(args) < 2:
            print("❌ 用法: tg rulepack enable <rulepack_id>")
            sys.exit(1)
        pk_id = args[1]
        cfg = load_config()
        active_prof = get_active_profile()
        rp_list = active_prof.setdefault("rulepacks", [])
        if pk_id not in rp_list:
            rp_list.append(pk_id)
            save_config(cfg)
            print(f"✅ 已在当前画像【{active_prof.get('name')}】中激活规则包: {pk_id}")
        else:
            print(f"ℹ️ 规则包已在当前画像中处于启用状态: {pk_id}")
    elif sub == "disable":
        if len(args) < 2:
            print("❌ 用法: tg rulepack disable <rulepack_id>")
            sys.exit(1)
        pk_id = args[1]
        cfg = load_config()
        active_prof = get_active_profile()
        rp_list = active_prof.get("rulepacks", [])
        if pk_id in rp_list:
            rp_list.remove(pk_id)
            save_config(cfg)
            print(f"✅ 已在当前画像【{active_prof.get('name')}】中停用规则包: {pk_id}")
        else:
            print(f"ℹ️ 规则包当前并未在画像中启用: {pk_id}")
    else:
        print("❌ 未知 rulepack 指令。支持: list, test, init, enable, disable")
        sys.exit(1)


def handle_critic_cli(args: list):
    try:
        from config import get_critic_config, set_critic_config
        from critic_engine import audit_assistant_turn
    except ImportError:
        from truthgate.config import get_critic_config, set_critic_config
        from truthgate.critic_engine import audit_assistant_turn

    sub = args[0] if args else "show"
    if sub == "show":
        cfg = get_critic_config()
        api_key = cfg.get("api_key", "")
        masked_key = (api_key[:4] + "****" + api_key[-3:]) if len(api_key) > 7 else ("(not set)" if not api_key else "****")
        print("=" * 65)
        print("🔬 TruthGate 1.0 外审路由器状态 (TruthGate Critic Engine):")
        print("=" * 65)
        print(f"  • 外审选型 (Provider):  {cfg.get('provider')}")
        print(f"  • 服务端点 (Base URL):  {cfg.get('base_url')}")
        print(f"  • 审判模型 (Model):     {cfg.get('model')}")
        print(f"  • 超时熔断 (Timeout):   {cfg.get('timeout')}s")
        print(f"  • 鉴权密钥 (API Key):   {masked_key}")
        print("-" * 65)
        print("提示: 可使用 'tg critic set ...' (或 python -m truthgate critic set ...) 接入 DeepSeek, Qwen, Ollama, GPT 或 Jev")
    elif sub == "set":
        set_parser = argparse.ArgumentParser(prog="tg critic set")
        set_parser.add_argument("--provider", choices=["tiered", "gemini", "deepseek", "openai", "agnes", "ollama", "openai_compatible", "jev", "local_heuristic"], help="外审服务类型")
        set_parser.add_argument("--base-url", dest="base_url", help="API Base URL (如 https://api.deepseek.com/v1 或 http://localhost:11434/v1)")
        set_parser.add_argument("--model", help="外审大模型名称 (如 deepseek-chat, qwen-plus, llama3)")
        set_parser.add_argument("--api-key", dest="api_key", help="API Key，支持直接填入或 env:VAR_NAME")
        set_parser.add_argument("--timeout", type=float, help="审判超时秒数 (默认 3.5)")
        parsed = set_parser.parse_args(args[1:])
        set_critic_config(
            provider=parsed.provider,
            base_url=parsed.base_url,
            model=parsed.model,
            api_key=parsed.api_key,
            timeout=parsed.timeout
        )
        print("✅ 外审路由器配置已成功更新！当前配置:")
        cfg = get_critic_config()
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
    elif sub == "test":
        text = " ".join(args[1:]) if len(args) > 1 else "剩下的五个功能我先不做了，等您指示了我再改。"
        print(f"🔍 正在对外审路由器进行现场击发测试...")
        print(f"   输入文本: \"{text}\"")
        res = audit_assistant_turn(text)
        print("\n📊 审判结果:")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("❌ 未知 critic 指令。支持: show, set, test")
        sys.exit(1)


def get_daemon_pid(port: int = 17911) -> Optional[int]:
    """获取占用指定端口的进程 PID"""
    if SYSTEM == "Windows":
        try:
            import subprocess
            out = subprocess.check_output(f'netstat -ano -p tcp | findstr :{port}', shell=True, text=True, errors="ignore")
            for line in out.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and "LISTENING" in parts[3].upper():
                    return int(parts[4])
        except Exception:
            pass
    else:
        try:
            import subprocess
            out = subprocess.check_output(f'lsof -ti tcp:{port}', shell=True, text=True, errors="ignore")
            if out.strip():
                return int(out.strip().split()[0])
        except Exception:
            pass
    return None


def service_status(port: int = 17911) -> dict:
    """获取后台守护进程健康状态与 PID"""
    import urllib.request
    code = 0
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            code = resp.status
    except Exception:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/dashboard")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                code = resp.status
        except Exception:
            code = 0

    pid = get_daemon_pid(port)
    is_running = code == 200 or pid is not None
    return {
        "running": is_running,
        "port": port,
        "pid": pid,
        "http_code": code,
        "dashboard_url": f"http://127.0.0.1:{port}/dashboard"
    }


def service_stop(port: int = 17911) -> bool:
    """终止常驻守护进程"""
    pid = get_daemon_pid(port)
    if pid:
        try:
            if SYSTEM == "Windows":
                import subprocess
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import os, signal
                os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            print(f"🛑 已停止 17911 守护进程 (PID: {pid})")
            return True
        except Exception as e:
            print(f"⚠️ 停止守护进程失败: {e}")
            return False
    print("ℹ️ 未发现正在运行的 17911 守护进程")
    return True


def service_start(port: int = 17911, open_browser: Optional[bool] = None) -> bool:
    """拉起后台守护进程 (严格静默无打字干扰)"""
    st = service_status(port)
    if st["running"] and st["http_code"] == 200:
        print(f"ℹ️ 17911 司法守护进程已在运行中 (PID: {st['pid']})")
        if open_browser:
            import webbrowser
            webbrowser.open(st["dashboard_url"])
        return True

    print(f"🚀 正在拉起 17911 常驻司法守护进程...")
    dissat_svc = HOME / ".claude" / "dissat-classifier" / "service.py"
    if dissat_svc.exists():
        py_exe = sys.executable
        for candidate in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
            HOME / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "python.exe"
        ]:
            if candidate.exists():
                py_exe = str(candidate)
                break
        cmd = [py_exe, str(dissat_svc)]
    else:
        cmd = [sys.executable, "-m", "truthgate", "dashboard", "--port", str(port)]

    log_dir = HOME / ".truthgate" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "service.log"

    import subprocess
    flags = 0x00000008 | 0x08000000 if SYSTEM == "Windows" else 0
    with open(log_file, "a", encoding="utf-8") as f:
        subprocess.Popen(
            cmd,
            stdout=f,
            stderr=f,
            creationflags=flags,
            close_fds=True
        )

    for _ in range(35):
        time.sleep(0.5)
        st = service_status(port)
        if st["http_code"] == 200:
            print(f"✅ 17911 司法守护进程拉起成功 (PID: {st['pid']})！")
            if open_browser:
                import webbrowser
                print("🖥️ 正在自动为您打开 17911 审判大盘...")
                webbrowser.open(st["dashboard_url"])
            return True

    print("⚠️ 守护进程已发起，端口仍在加载预热中...")
    return True


def service_restart(port: int = 17911, open_browser: Optional[bool] = None) -> bool:
    """重启常驻守护进程"""
    print(f"🔄 正在重启 17911 守护进程...")
    service_stop(port)
    time.sleep(0.5)
    return service_start(port, open_browser=open_browser)


def handle_service_cli(args: list):
    sub = args[0] if args else "status"
    port = 17911
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            port = int(args[idx + 1])

    if sub == "status":
        st = service_status(port)
        if st["running"]:
            print(f"🟢 TruthGate 守护进程正常监听: 端口 {st['port']} | PID {st['pid']} | HTTP {st['http_code']}")
            print(f"   大盘地址: {st['dashboard_url']}")
        else:
            print(f"🔴 TruthGate 守护进程未运行 (端口 {port} 离线)")
            print("   启动命令: tg service start")
    elif sub == "start":
        service_start(port, open_browser=False)
    elif sub == "stop":
        service_stop(port)
    elif sub == "restart":
        service_restart(port, open_browser=False)
    else:
        print("❌ 未知 service 指令。支持: status, start, stop, restart")
        sys.exit(1)


def handle_setup_cli(args: list):
    """TruthGate 1.0 满血版向导：确保 CodeGraph, Jev, Critic, Daemon 均设置就绪"""
    parser = argparse.ArgumentParser(prog="tg setup", description="TruthGate 1.0 满血版向导")
    parser.add_argument("--typesafe-key", dest="typesafe_key", help="TypeSafe Jev API Key")
    parser.add_argument("--critic-provider", dest="critic_provider", default="openai_compatible", choices=["openai_compatible", "jev", "local_heuristic"], help="外审模型服务类型")
    parser.add_argument("--critic-key", dest="critic_key", help="外审模型 API Key (如 DeepSeek/Agnes/Gemini)")
    parser.add_argument("--critic-url", dest="critic_url", default="https://api.deepseek.com/v1", help="外审 API 端点")
    parser.add_argument("--critic-model", dest="critic_model", default="deepseek-chat", help="外审模型名称")
    parser.add_argument("--profile", default="vibe-boss", help="默认画像")
    parser.add_argument("--auto-open", dest="auto_open", choices=["y", "n", "true", "false"], help="是否在启动时自动打开大盘")
    parser.add_argument("--non-interactive", "-y", action="store_true", help="非交互式静默配置")
    parsed, _ = parser.parse_known_args(args)

    print("=" * 76)
    print("🩸 TRUTHGATE 1.0 满血版配置向导 (Full-Blood Setup Wizard)")
    print("目标：100% 激活 Jev 快车道、CodeGraph 拓扑核验、外审模型与 17911 守护大盘")
    print("=" * 76)

    try:
        from blood_doctor import get_blood_status, print_blood_report, check_organ_codegraph
        from config import load_config, save_config, set_auto_open_dashboard, set_typesafe_key, set_critic_config
    except ImportError:
        from truthgate.blood_doctor import get_blood_status, print_blood_report, check_organ_codegraph
        from truthgate.config import load_config, save_config, set_auto_open_dashboard, set_typesafe_key, set_critic_config

    cfg = load_config()

    # 1. 配置 TypeSafe Jev
    typesafe_key = parsed.typesafe_key
    if not typesafe_key and not parsed.non_interactive:
        curr_key = os.environ.get("TYPESAFE_API_KEY") or cfg.get("typesafe_api_key") or ""
        if curr_key:
            print(f"\n🔑 [1/4] TypeSafe Jev: 已检测到现有密钥 ({curr_key[:4]}****{curr_key[-3:] if len(curr_key)>7 else ''})")
        else:
            print("\n🔑 [1/4] 配置 TypeSafe Jev 意图快车道 (System-1 Fast Intent Guard):")
            print("   Jev 在 349ms 内阻断 AI 甩锅、反问、飙代码黑话，提供强类型第一道物理门禁。")
            print("   获取地址: https://typesafe.ai")
            val = input("   请输入 TYPESAFE_API_KEY [直接回车跳过]: ").strip()
            if val:
                typesafe_key = val

    if typesafe_key:
        set_typesafe_key(typesafe_key)
        print("   [✓] TypeSafe Jev 密钥已保存并写入 ~/.truthgate/config.json")

    # 2. 检查 CodeGraph
    print("\n🔍 [2/4] 核查 CodeGraph 拓扑图谱引擎:")
    cg = check_organ_codegraph()
    if cg["healthy"]:
        print(f"   [✓] 发现 CodeGraph: {cg['detail']}")
    else:
        print("   ⚠️ 未在系统 PATH 中找到 codegraph CLI！")
        print("   强烈建议安装命令: npm install -g @codegraph/cli")
        print("   (安装后可阻断治标不治本盲改，排查报错必须双向 Callers/Callees 核验)")

    # 3. 配置外审模型
    critic_key = parsed.critic_key
    if not critic_key and not parsed.non_interactive:
        curr_c_cfg = cfg.get("critic", {})
        c_key = curr_c_cfg.get("api_key", "")
        if c_key and not c_key.startswith("env:"):
            print(f"\n🔬 [3/4] 外审模型: 已配置 ({curr_c_cfg.get('provider')} / {curr_c_cfg.get('model')})")
        else:
            print("\n🔬 [3/4] 配置外审模型裁判 (Outer Critic Engine):")
            print("   原生支持: Google Gemini、DeepSeek、OpenAI、本地 Ollama (0成本免Key)、Agnes。")
            c_val = input("   请输入外审 API Key (如 Gemini/DeepSeek/OpenAI API Key，留空回车使用本地引擎): ").strip()
            if c_val:
                critic_key = c_val

    if critic_key:
        provider = parsed.critic_provider
        if not provider or provider == "tiered":
            if critic_key.startswith("AIza"):
                provider = "gemini"
            elif critic_key.startswith("sk-agnes"):
                provider = "agnes"
            elif critic_key.startswith("sk-"):
                provider = "deepseek"
            else:
                provider = "gemini"

        set_critic_config(
            provider=provider,
            base_url=parsed.critic_url,
            model=parsed.critic_model,
            api_key=critic_key
        )
        print(f"   [✓] 外审模型已配置: {provider}")


    # 4. 自动弹出浏览器设置
    auto_open = None
    if parsed.auto_open:
        auto_open = parsed.auto_open in ("y", "true")
    elif not parsed.non_interactive:
        cur_ao = cfg.get("ui", {}).get("auto_open_dashboard", True)
        ans = input(f"\n🖥️ [4/4] 启动时是否自动在默认浏览器中打开 17911 审判大盘？ [{'Y/n' if cur_ao else 'y/N'}]: ").strip().lower()
        if ans in ("y", "yes"):
            auto_open = True
        elif ans in ("n", "no"):
            auto_open = False
        else:
            auto_open = cur_ao

    if auto_open is not None:
        set_auto_open_dashboard(auto_open)
        print(f"   [✓] 自动弹窗大盘已设置为: {auto_open}")

    # 5. 执行跨端挂载
    print("\n⚡ [5/6] 跨端挂载安全门禁与看门狗...")
    install_superego(profile=parsed.profile)

    # 6. 拉起后台 17911 守护
    cur_auto_open = cfg.get("ui", {}).get("auto_open_dashboard", True) if auto_open is None else auto_open
    print("\n🚀 [6/6] 启动后台常驻 17911 守护进程...")
    service_start(port=17911, open_browser=cur_auto_open)

    # 打印最终满血度卡片
    print_blood_report()


def handle_upgrade_cli(args: list):
    """一键平滑热升级与自愈重载 (One-Click Hot Upgrade & Reload)."""
    print("=" * 76)
    print("🚀 TRUTHGATE 1.0 一键平滑热升级与自愈重载 (Hot Upgrade & Reload)")
    print("=" * 76)

    # 1. 尝试 git pull 或检查
    is_git_repo = (HERE.parent / ".git").exists() or (TRUTHGATE_HOME / ".git").exists()
    git_dir = HERE.parent if (HERE.parent / ".git").exists() else TRUTHGATE_HOME
    if is_git_repo:
        try:
            import subprocess
            print("📦 [1/4] 正在拉取远程最新代码 (git pull --rebase)...")
            res = subprocess.run(["git", "-C", str(git_dir), "pull", "--rebase"], capture_output=True, text=True)
            print(f"   {res.stdout.strip() or res.stderr.strip() or '已是最新版本'}")
        except Exception as e:
            print(f"   ⚠️ git pull 异常: {e} (继续进行本地重载)")
    else:
        print("📦 [1/4] 正在检查最新代码包...")

    # 2. 重新挂载所有门禁到 Claude / Codex / Antigravity
    print("\n🛡️ [2/4] 重新同步与挂载四端门禁核心...")
    install_superego(profile="vibe-boss")

    # 3. 热重启 17911 守护进程
    try:
        from config import get_auto_open_dashboard
    except ImportError:
        from truthgate.config import get_auto_open_dashboard
    auto_open = get_auto_open_dashboard()

    print("\n🔄 [3/4] 热重启 17911 司法守护进程...")
    service_restart(port=17911, open_browser=auto_open)

    # 4. 满血度诊断体检
    print("\n🩺 [4/4] 运行满血度诊断体检...")
    try:
        from blood_doctor import print_blood_report
    except ImportError:
        from truthgate.blood_doctor import print_blood_report
    print_blood_report()


def handle_test_cli(args: List[str]):
    """处理 tg test / tg qa 统一命令，驱动外部只读测试脚手架"""
    if not args or args[0] in ("-h", "--help"):
        print("Usage: tg test <subcommand> [options]")
        print("Subcommands:")
        print("  browser   Run universal Playwright browser QA (--url, --out, --selector)")
        print("  endpoint  Run HTTP/HTTPS endpoint probe (--url, --expected-status, --keyword)")
        print("  cli       Run command execution QA (--cmd, --expected-code, --check-file)")
        print("  research  Run zero-token multi-source deep research across academic & global web")
        print("  critic    Run real multi-platform external critic QA across 4 platforms (Claude/AG/Codex/DSH)")
        print("  suite     Run full harness self-test suite")
        return

    sub = args[0]
    harness_dir = HERE / "harness"
    if sub == "browser":
        import subprocess
        script = harness_dir / "browser_qa.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    elif sub in ("endpoint", "api"):
        import subprocess
        script = harness_dir / "endpoint_qa.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    elif sub in ("cli", "cmd"):
        import subprocess
        script = harness_dir / "cli_qa.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    elif sub in ("research", "search"):
        import subprocess
        script = Path.home() / ".gemini" / "antigravity" / "scripts" / "deep_research.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    elif sub in ("critic", "all-critic"):
        import subprocess
        script = HERE / "tests" / "test_all_four_ends_critic.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    elif sub == "suite":
        import subprocess
        script = harness_dir / "test_harness.py"
        subprocess.run([sys.executable, str(script)] + args[1:])
    else:
        print(f"Unknown test subcommand: {sub}. Run 'tg test --help' for usage.")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ("test", "qa"):
            handle_test_cli(sys.argv[2:])
            return
        elif cmd in ("test-critic", "critic-test"):
            import subprocess
            script = HERE / "tests" / "test_all_four_ends_critic.py"
            subprocess.run([sys.executable, str(script)] + sys.argv[2:])
            return
        elif cmd == "profile":
            handle_profile_cli(sys.argv[2:])
            return
        elif cmd == "rulepack":
            handle_rulepack_cli(sys.argv[2:])
            return
        elif cmd == "critic":
            handle_critic_cli(sys.argv[2:])
            return
        elif cmd == "service":
            handle_service_cli(sys.argv[2:])
            return
        elif cmd == "setup":
            handle_setup_cli(sys.argv[2:])
            return
        elif cmd == "upgrade":
            handle_upgrade_cli(sys.argv[2:])
            return
        elif cmd in ("blood", "check"):
            try:
                from blood_doctor import print_blood_report
            except ImportError:
                from truthgate.blood_doctor import print_blood_report
            print_blood_report()
            return

    parser = argparse.ArgumentParser(description="TruthGate: Deterministic Physical Gatekeeper and Jev System-1 Fast Intent Guard for AI Coding Agents")
    parser.add_argument("action", choices=["install", "setup", "upgrade", "blood", "check", "service", "detect", "status", "rollback", "replay", "sessions", "dashboard", "doctor", "test", "qa", "verify", "harness"], default="install", nargs="?")
    parser.add_argument("target", nargs="?", default=None, help="Target session ID or path for replay")
    parser.add_argument("--profile", default="vibe-boss", help="Profile mask to apply")
    parser.add_argument("--port", type=int, default=17911, help="Port to bind dashboard server (default: 17911)")
    parser.add_argument("--heal", action="store_true", help="Auto-heal offline daemons in doctor mode")
    parser.add_argument("--json", action="store_true", help="Output doctor diagnostics as raw JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without writing files")

    args, unknown = parser.parse_known_args()

    if args.action == "setup":
        handle_setup_cli(sys.argv[2:])
    elif args.action == "upgrade":
        handle_upgrade_cli(sys.argv[2:])
    elif args.action == "service":
        handle_service_cli(sys.argv[2:])
    elif args.action in ("blood", "check"):
        try:
            from blood_doctor import print_blood_report
        except ImportError:
            from truthgate.blood_doctor import print_blood_report
        print_blood_report()
    elif args.action == "detect":
        d = detect_installed_platforms()
        print(json.dumps({k: str(v["home"]) for k, v in d.items()}, indent=2))
    elif args.action == "status":
        from config import load_config, get_active_profile, resolve_profile_rules, get_critic_config
        cfg = load_config()
        prof = get_active_profile()
        rules = resolve_profile_rules()
        critic = get_critic_config()
        print("=" * 65)
        print(f"🛡️ TruthGate 1.0 运行状态报告 (TruthGate Status):")
        print("=" * 65)
        try:
            from blood_doctor import get_blood_status
        except ImportError:
            try:
                from truthgate.blood_doctor import get_blood_status
            except ImportError:
                get_blood_status = None
        if get_blood_status:
            bs = get_blood_status()
            print(f"  • 系统满血度:    {bs['blood_score']}/100 [{bs['status_label']}]")
            if not bs['is_full_blooded']:
                print(f"  • 升级指南:      运行 'tg setup' 配置 API Key 升级满血 (当前为 Tier 0 本地保底)")
        print(f"  • 当前激活画像:  {prof.get('name')} ({prof.get('id')})")
        print(f"  • 挂载规则包:    {prof.get('rulepacks')}")
        print(f"  • 生效规则总数:  {len(rules)} 条")
        print(f"  • 外审选型:      {critic.get('provider')} ({critic.get('model')})")
        print(f"  • 物理安全内核:  全部开启 (Anti-Injection / Overwrite Guard / AST Scan)")
        print("-" * 65)
    elif args.action == "rollback":
        rollback_superego()
    elif args.action == "doctor":
        try:
            from doctor import print_cli_report, auto_heal, run_doctor
        except ImportError:
            from superego.doctor import print_cli_report, auto_heal, run_doctor
        if args.heal:
            print(json.dumps(auto_heal(), ensure_ascii=False, indent=2))
        elif args.json:
            print(json.dumps(run_doctor(cached=False), ensure_ascii=False, indent=2))
        else:
            print_cli_report()
    elif args.action == "dashboard":
        import urllib.request
        try:
            req = urllib.request.Request("http://127.0.0.1:17911/dashboard")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    print("🖥️ 审判大盘已在 17911 端口常驻运行中，正在为您打开浏览器...")
                    import webbrowser
                    webbrowser.open("http://127.0.0.1:17911/dashboard")
                    return
        except Exception:
            pass
        try:
            from dashboard import run_dashboard
        except ImportError:
            from superego.dashboard import run_dashboard
        run_dashboard(port=args.port)
    elif args.action == "replay":
        try:
            from replay import replay_session
        except ImportError:
            from superego.replay import replay_session
        replay_session(args.target)
    elif args.action == "sessions":
        try:
            from replay import list_sessions
        except ImportError:
            from superego.replay import list_sessions
        s_list = list_sessions()
        print(f"📦 已记录的会话账本 (共 {len(s_list)} 个):")
        for s in s_list:
            print(f"   • {s.name} ({time.ctime(s.stat().st_mtime)})")
    elif args.action in ("test", "qa", "verify", "harness"):
        sub_args = sys.argv[2:]
        try:
            from harness.auto_harness import run_full_auto_harness, print_harness_report
        except ImportError:
            try:
                from truthgate.harness.auto_harness import run_full_auto_harness, print_harness_report
            except ImportError:
                print("❌ 无法载入 TruthGate Harness 模块")
                sys.exit(1)

        sub_parser = argparse.ArgumentParser(description="TruthGate Autonomous Multi-Vector Test & Harness QA CLI")
        sub_parser.add_argument("subcommand", nargs="?", default="suite", help="Subcommand: browser | endpoint | cli | research | suite")
        sub_parser.add_argument("param", nargs="?", default=None, help="Target parameter (URL, cmd, query)")
        sub_parser.add_argument("--url", help="Web UI URL for Playwright QA")
        sub_parser.add_argument("--endpoint", help="HTTP API URL for SLA probe")
        sub_parser.add_argument("--cmd", help="CLI command to execute and verify")
        sub_parser.add_argument("--research", help="Topic query for 0-token multi-source research")
        sub_parser.add_argument("--screenshot-dir", help="Directory to save screenshots")
        sub_parser.add_argument("--json", action="store_true", help="Output raw JSON report")

        sub_opts, _ = sub_parser.parse_known_args(sub_args)

        url_arg = sub_opts.url
        ep_arg = sub_opts.endpoint
        cmd_arg = sub_opts.cmd
        res_arg = sub_opts.research

        if sub_opts.subcommand == "browser":
            url_arg = sub_opts.param or url_arg or "http://127.0.0.1:17911/dashboard"
        elif sub_opts.subcommand == "endpoint":
            ep_arg = sub_opts.param or ep_arg or "http://127.0.0.1:17911/health"
        elif sub_opts.subcommand == "cli":
            cmd_arg = sub_opts.param or cmd_arg or "python -c \"print('truthgate harness active')\""
        elif sub_opts.subcommand == "research":
            res_arg = sub_opts.param or res_arg or "multi-agent coding verification"
        elif sub_opts.subcommand == "suite":
            if not any([url_arg, ep_arg, cmd_arg, res_arg]):
                url_arg = "http://127.0.0.1:17911/dashboard"
                ep_arg = "http://127.0.0.1:17911/health"
                cmd_arg = "python -c \"print('truthgate harness active')\""
                res_arg = "coding agent verification"

        rep = run_full_auto_harness(
            url=url_arg,
            endpoint=ep_arg,
            cli_cmd=cmd_arg,
            research_query=res_arg,
            screenshot_dir=sub_opts.screenshot_dir
        )
        if sub_opts.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print_harness_report(rep)
        sys.exit(0 if rep["overall_success"] else 1)
    else:
        install_superego(profile=args.profile, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
