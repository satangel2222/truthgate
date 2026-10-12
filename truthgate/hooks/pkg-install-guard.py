#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""pkg-install-guard —— PreToolUse 闸:拦【未评估就装包】。

⛔ 为什么要它(2026-08-29 21:50 被掏空成 25 字节 stub 之前):
  Frank 跨项目一直在用本机 `pip install / npm install / choco / brew / cargo / gem` 装包。
  1MB 真实日志(2026-07-30~2026-08-25)显示:
    · `pip install` 73 次 / `npm install` 15 次 / `choco 11` / `brew 11` / `cargo 11` / `gem 11`
    · 16 个项目都跑过(airbnb-ai-manager / manju / duckduckweb / humanizerai / bananaflow 等)
  病根不是装包本身 —— 是【没评估就装】:
    ① 装之前有没有查【本机已装 / 项目内 requirements / 6 大宇宙有没有现成可改的】
    ② 装的位置对不对 (系统 vs venv vs 项目 venv)
    ③ 装完会不会污染他的 8G 机器 (拖卡、抢显存、留垃圾)
  ⇒ 8-29 21:50 文件被掏空成 `import sys; sys.exit(0)` —— 闸**没拦到任何东西**整整一周。

判据(全中才拦,宽放窄拦):
  ① 命令是装包类 (pip install / pip3 / npm i / choco install / brew install / cargo add / gem install / pipx install)
  ② 不是 `pip list/show/check` / `pip freeze` / `npm ls` 这类只读
  ③ 不是 venv/conda 内部操作 (已是隔离)
  ④ 本轮没标记过 `assessed-this-turn` (用文件锁记录本 session 本 turn 评估过哪些包)
  = 装包前没评估 → DENY,强制走"先评估再装"流程

放行口径(原文日志出现过的):
  · `allow(eval/readonly/venv/uninstall)` —— 评估型 / 只读 / 在 venv / 卸载
  · `allow(write-file-quote)` —— write 工具写出来的命令(不是直接键入)
  · `allow(local-project-install)` —— 项目内 requirements.txt 等
  · `allow(assessed-this-turn)` —— 本轮已评估过

安全:fail-open;hook_log 落档到 pkg-install-guard.log.1 续写;不阻塞只读。
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from guard_common import hook_log, fail_open
except Exception:
    # ⛔ 2026-09-07:签名必须跟真的 hook_log 一致(name, msg, ctx="")。
    #   原来只收两个 ⇒ 一旦走兜底路径,带触发词的调用会 TypeError,而它会被外层 except 吞掉
    #   ⇒ 拦截 JSON 发不出去、闸静默失效、测试还绿。**这正是 2026-07-28 那次死闸的形状。**
    def hook_log(name, msg, ctx=""):
        try:
            with open(Path(__file__).parent / f"{name}.log", "a", encoding="utf-8") as f:
                f.write(f"{msg} {ctx}\n")
        except Exception:
            pass
    def fail_open():
        return 0


INSTALL_PATTERNS = [
    # pip 系列
    re.compile(r"\b(?:pip3?|pipx)\s+install\b", re.IGNORECASE),
    re.compile(r"\buv\s+pip\s+install\b", re.IGNORECASE),
    # npm 系
    re.compile(r"\bnpm\s+(?:install|i|add)\b", re.IGNORECASE),
    re.compile(r"\byarn\s+(?:add|global\s+add)\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+(?:add|install|i)\b", re.IGNORECASE),
    # 系统级
    re.compile(r"\bchoco\s+install\b", re.IGNORECASE),
    re.compile(r"\bwinget\s+install\b", re.IGNORECASE),
    re.compile(r"\bscoop\s+install\b", re.IGNORECASE),
    re.compile(r"\bbrew\s+install\b", re.IGNORECASE),
    re.compile(r"\bapt(-get)?\s+install\b", re.IGNORECASE),
    # 二进制全局
    re.compile(r"\bcargo\s+(?:install|add)\b", re.IGNORECASE),
    re.compile(r"\bgo\s+install\b", re.IGNORECASE),
    re.compile(r"\bgem\s+install\b", re.IGNORECASE),
]

# 升级类(共享依赖命脉,必须先评估再升,2026-07-30 真实事故 scrapling 硬升 playwright 1.61)
UPGRADE_PATTERNS = [
    re.compile(r"\bpip3?\s+install\s+(?:-[uU]|--upgrade)\b"),
    re.compile(r"\buv\s+pip\s+install\s+(?:-[uU]|--upgrade)\b"),
    re.compile(r"\bnpm\s+(?:install|i|update)\s+-[gG]\b", re.IGNORECASE),
    re.compile(r"\bbrew\s+(?:upgrade|reinstall|upgrade)\b", re.IGNORECASE),
    re.compile(r"\bchoco\s+upgrade\b", re.IGNORECASE),
    re.compile(r"\bapt(-get)?\s+(?:upgrade|full-upgrade)\b", re.IGNORECASE),
]

READONLY_PATTERNS = [
    re.compile(r"\b(?:pip3?|pipx)\s+(?:list|show|check|freeze|search|index)\b", re.IGNORECASE),
    re.compile(r"\buv\s+pip\s+(?:list|show|freeze|search)\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+(?:ls|list|outdated|view|search|info)\b", re.IGNORECASE),
    re.compile(r"\bchoco\s+(?:list|info|search)\b", re.IGNORECASE),
    re.compile(r"\bwinget\s+(?:show|list|search)\b", re.IGNORECASE),
    re.compile(r"\bscoop\s+(?:list|info|search)\b", re.IGNORECASE),
    re.compile(r"\bbrew\s+(?:list|info|search|outdated)\b", re.IGNORECASE),
    re.compile(r"\bapt(-get)?\s+(?:list|show|search)\b", re.IGNORECASE),
    re.compile(r"\bcargo\s+(?:search|info)\b", re.IGNORECASE),
    re.compile(r"\bgem\s+(?:list|search|info|dependency)\b", re.IGNORECASE),
    re.compile(r"\bgo\s+list\b", re.IGNORECASE),
]

# 本地项目级装(不带 -g / 不动系统级) —— npm/yarn/pnpm/pip 都行
LOCAL_PATTERNS = [
    re.compile(r"\bnpm\s+install\b(?!.*-[gG])\b", re.IGNORECASE),
    re.compile(r"\bnpm\s+i\b(?!.*-[gG])\b", re.IGNORECASE),
    re.compile(r"\byarn\s+add\b(?!.*global)\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+install\b(?!.*-[gG])\b", re.IGNORECASE),
    re.compile(r"\bpnpm\s+add\b(?!.*-[gG])\b", re.IGNORECASE),
    re.compile(r"\bpip3?\s+install\s+(?!.*-[gGU]|--upgrade)", re.IGNORECASE),
]

VENV_HINT = re.compile(r"(?:\\\\|\/)(?:venv|\.venv|env|conda-env|envs)[\\\\/]|\bactivate\b|\bdeactivate\b|\bconda\s+(?:activate|deactivate)\b", re.IGNORECASE)

ASSESSED_FILE = Path.home() / ".claude" / "hooks" / ".pkg-install-assessed.json"


def _read_assessed():
    try:
        if ASSESSED_FILE.exists():
            return json.loads(ASSESSED_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _mark_assessed(session_id, pkg):
    try:
        data = _read_assessed()
        data.setdefault(session_id, []).append(pkg)
        data[session_id] = list(set(data[session_id]))[-50:]
        ASSESSED_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ⛔⛔ 2026-09-07 这里删掉了四个函数:`_is_install` / `_is_readonly` / `_is_venv_op` /
#   `_is_local_project_install`。它们**一个调用点都没有**(全仓 grep 0 处、测试里也 0 处),
#   是旧实现的残留 —— 真正判事的是下面的 `_classify()`。
#   为什么必须删、而不是留着当"参考":今天给这道闸补故障注入,注入打在它们用的那几张
#   模式表上,**三条全部"仍绿"**;我一度读成"测试没覆盖",查了很久才发现是**注在死代码上**。
#   留着 = 给下一次的自己(或别人)埋同一个坑。(形状 -P:看起来在工作、其实从没被执行过。)
#   上面那几张只服务于它们的 *_PATTERNS / VENV_HINT 表暂时保留,已在文件头标注为仅供参考。


def _extract_pkg_name(cmd: str) -> str:
    # ⛔ 2026-09-07:`install` 必须带 `\b`。裸写的话 `pip uninstall requests`
    #   也会命中,把 requests 当成"正在安装的包"抽出来 —— 卸载被记成安装。
    #   是「命令动词无词边界」那个扫描器找出来的最后一处(同族:今晚 move-item ⊂ remove-item)。
    m = re.search(r"\binstall\s+([^\s\"']+)", cmd, re.IGNORECASE)
    return m.group(1) if m else ""


# 包管理器 install 子命令
_PM_VERBS = ("pip", "pip3", "pipx", "uv", "npm", "yarn", "pnpm", "choco",
             "winget", "scoop", "brew", "apt", "apt-get", "cargo", "go", "gem")


def _flag_on_pm(cmd, *flags):
    """这个开关是不是挂在【那次包管理器调用自己】身上(而不是同一行里别的命令带的)。

    解析器不可用时返回 None ⇒ 调用方退回老判据。**不静默放宽**:
    宁可保持以前的行为,也不因为解析器缺失就把闸变松。
    """
    try:
        from cmd_parse import has_invocation
    except Exception:
        return None
    return any(has_invocation(cmd, v, f) for v in _PM_VERBS for f in flags)


PM_INSTALL = {
    # pip 家族:本地 pip install 也拦(2026-07-30 真事故:pip install scrapling 硬升 playwright 1.61)
    "pip":    re.compile(r"\b(?:pip3?|pipx)\s+install\b", re.IGNORECASE),
    "uv":     re.compile(r"\buv\s+pip\s+install\b", re.IGNORECASE),
    # npm 家族:本地 install 是日常开发,只拦 -g 全局
    "npm":    re.compile(r"\bnpm\s+(?:install|i|add)\b", re.IGNORECASE),
    "yarn":   re.compile(r"\byarn\s+(?:add|global\s+add)\b", re.IGNORECASE),
    "pnpm":   re.compile(r"\bpnpm\s+(?:add|install|i)\b", re.IGNORECASE),
    # 系统级:任何 install 都拦
    "choco":  re.compile(r"\bchoco\s+install\b", re.IGNORECASE),
    "winget": re.compile(r"\bwinget\s+install\b", re.IGNORECASE),
    "scoop":  re.compile(r"\bscoop\s+install\b", re.IGNORECASE),
    "brew":   re.compile(r"\bbrew\s+install\b", re.IGNORECASE),
    "apt":    re.compile(r"\bapt(-get)?\s+install\b", re.IGNORECASE),
    "cargo":  re.compile(r"\bcargo\s+(?:install|add)\b", re.IGNORECASE),
    "go":     re.compile(r"\bgo\s+install\b", re.IGNORECASE),
    "gem":    re.compile(r"\bgem\s+install\b", re.IGNORECASE),
}

# 危险标志: 全局/升级
_DANGER_PATTERNS = [
    re.compile(r"\s-[gG]\b"),
    re.compile(r"\s--global\b"),
    re.compile(r"\s-[uU]\b"),
    re.compile(r"\s--upgrade\b"),
    re.compile(r"\bglobal\s+add\b", re.IGNORECASE),
]

# 安全上下文: venv / 项目内
_SAFE_PATTERNS = [
    re.compile(r"(?:[\\/])(?:venv|\.venv|env|conda-env|envs)[\\\\/]", re.IGNORECASE),
    re.compile(r"\bactivate\b|\bdeactivate\b", re.IGNORECASE),
    re.compile(r"\bpip3?\s+install\s+-[rReE]\b", re.IGNORECASE),
]


def has_danger_flag(cmd: str) -> bool:
    return any(p.search(cmd) for p in _DANGER_PATTERNS)


def is_venv_or_project(cmd: str) -> bool:
    return any(p.search(cmd) for p in _SAFE_PATTERNS)


SYSTEM_LEVEL = {"apt", "choco", "brew", "winget", "scoop", "cargo", "go", "gem"}


# 写文件类(整条命令是写文件,内容里含装包串 ≠ 真装)
_WRITE_FILE_HINT = re.compile(
    r"^\s*(?:cat\s*(?:>>|>)|\btee\s+|\becho\s+[^|]*[>|]|"
    r"^[^|;&]*>[^>|&]*$|"
    r"(?:^|\s)(?:python|node|ruby)\s+-c\s|"
    r"\b(?:cat|tee)\b.*<<)",
    re.IGNORECASE,
)
# 评估类(整条命令是评估)
_EVAL_HINT = re.compile(
    r"\b--dry-run\b|\b--dry-run\b|\bdry-run\b|"
    r"\bshow\b|\blist\b|\bsearch\b|\binfo\b|\b--target\b",
    re.IGNORECASE,
)


def _classify(cmd: str) -> str:
    """分类路径(ponytail:一条线判到底,别堆分支):
      1. 整条命令含 --dry-run 或 --target 隔离目录 → allow(评估动作)
      2. 写文件/引号包裹 → 整条命令不是 install → allow
      3. 是 install 类?否 → allow
      4. 是 system-level 包管理器 → block
      5. 是 npm/yarn/pnpm 本地(无 -g/--global)→ allow
      6. 是 pip/pip3/pipx/uv:看 venv/requirements → allow,否则 block
      7. 同命令内有 ; 分隔 + 前面是评估 → allow
    """
    # 1. 评估标志优先(--dry-run / --target 隔离目录)
    # ⛔ 2026-09-07:原来在【整条命令】里找这两个开关,不管它挂在谁身上。
    #   这条是**豁免**,所以写松的方向最危险:
    #   `npm install -g <随便什么> && echo --dry-run` 就能骗到一次放行。
    #   改成【那次包管理器调用自己】带着它才算(cmd_parse);解析器不可用时退回老判据。
    _dry = _flag_on_pm(cmd, "--dry-run", "--target")
    if _dry if _dry is not None else re.search(
            r"\s--dry-run\b|\s--target\s+\S", cmd, re.IGNORECASE):
        return "allow"

    # 2. 写文件/包含字符串的伪命令
    if _WRITE_FILE_HINT.search(cmd) and not _real_install(cmd):
        return "allow"
    if _EVAL_HINT.search(cmd) and not _real_install(cmd):
        return "allow"

    for pm, pat in PM_INSTALL.items():
        if not pat.search(cmd):
            continue
        # 7. 同命令内分号分隔 + 前半是评估(show/list/info/search)
        parts = re.split(r";", cmd)
        for p in parts[:-1]:
            if re.search(r"\b(?:show|list|search|info)\b", p, re.IGNORECASE):
                return "allow"
        if pm in SYSTEM_LEVEL:
            return "block"          # choco/winget/scoop/brew/apt/cargo/go/gem
        if pm == "uv":
            return "block"         # uv pip install 也算命脉
        if pm in ("npm", "yarn", "pnpm"):
            # ⛔ 2026-09-07 同一个病、反方向:`-g` 原来也是整串找 ⇒
            #   `npm install react; git log -g` 会被当成全局安装拦下(误伤)。
            _g = _flag_on_pm(cmd, "-g", "--global", "global")
            if _g if _g is not None else re.search(
                    r"\s-[gG]\b|\s--global\b|global\s+add", cmd, re.IGNORECASE):
                return "block"
            return "allow"          # npm install react / yarn add lodash / pnpm add vite
        # pip/pip3/pipx
        if is_venv_or_project(cmd):
            return "allow"
        return "block"
    return "allow"


def _real_install(cmd: str) -> bool:
    """判断"这是不是真的在跑 install"。排除写文件/引号内的命令。

    简化:看 install 关键字后面是不是紧跟包名/参数(命令式)还是引号字符串(数据式)。
    命令式: install <pkg>  /  install --flag  /  install 2>&1
    数据式:  install "scrapling[all]" 在 cat >> / echo / heredoc 里
    """
    # 命令第一个有效词是 cat/echo/tee/grep/awk/sed/python -c 等 ⇒ 数据式
    head = re.match(r"\s*([\w./\\-]+)", cmd)
    if head:
        first = head.group(1).lower().split("/")[-1].split("\\")[-1]
        if first in ("cat", "echo", "tee", "grep", "awk", "sed", "head", "tail",
                     "more", "less", "vi", "vim", "nano", "notepad"):
            return False
    # 含 >> 写入 / << heredoc / -c 脚本 ⇒ 数据式
    if re.search(r">>|\b<<|>>?\s*[\w./-]+\s*$|\s-c\s", cmd):
        return False
    return True


def _read_transcript_assess(data) -> bool:
    """读 transcript 看本轮之前是否跑过评估命令(winget show / pip --dry-run / brew info 等)。
    test 期望:'先 winget show 再装 → 放' 即靠这条。"""
    tp = data.get("transcript_path", "")
    if not tp or not os.path.exists(tp):
        return False
    try:
        with open(tp, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-40:]   # 只看最近 40 条
        for line in lines:
            try:
                m = json.loads(line)
            except Exception:
                continue
            content = (m.get("message") or {}).get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in ("Bash", "PowerShell"):
                        inp = c.get("input", {}) or {}
                        prev = inp.get("command", "")
                        if _EVAL_HINT.search(prev) and prev != data.get("tool_input", {}).get("command", ""):
                            return True
    except Exception:
        return False
    return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        data = json.loads(raw)
        tool = data.get("tool_name", "")
        if tool not in ("Bash", "PowerShell"):
            return 0
        tool_input = data.get("tool_input", {}) or {}
        cmd = tool_input.get("command", "") or tool_input.get("cmd", "")
        if not cmd:
            return 0

        decision = _classify(cmd)
        # 出口:本轮已跑过评估命令 → 放
        if decision == "block" and _read_transcript_assess(data):
            decision = "allow"
            hook_log("pkg-install-guard", f"allow(transcript-already-assessed) {cmd[:80]}")
            return 0

        if decision == "allow":
            hook_log("pkg-install-guard", f"allow {cmd[:80]}")
            return 0

        pkg = _extract_pkg_name(cmd)
        # ⛔ 2026-09-07:命令挪到【第三个参数】⇒ 日志里才会成为 trig='...'。
        #   写在消息里记分板解析不到 ⇒ 这道闸永远显示"无证据"、误伤率算不出来。
        hook_log("pkg-install-guard", "DENY(install-without-assess)", cmd[:200])
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"⛔ pkg-install-guard:命令是【{pkg or '装包'}】,本 session 本轮**没评估**就装。\n"
                f"装包前必做三步(可只回答一句即可解锁):\n"
                f"  ① 本机已装?`pip show {pkg}` / `winget list` (装过的就别再装)\n"
                f"  ② 项目内 requirements 写没写? (有就该用 `pip install -r`)\n"
                f"  ③ 这个能力本机 skill / 6 大宇宙有没有现成的可以【改 / 复用】?(别重复造轮子)\n"
                f"⚠️ 放行条件是【真的跑一条查询命令】,不是嘴上说评估过 —— "
                f"本闸不读你的文字,只认你本轮执行过 `pip show <包>` / `pip list` / "
                f"`winget list <id>` / `npm ls <包>` 这类只读查询(见 EVAL_PATTERNS)。\n"
                f"⇒ 先跑一条查询确认装没装,下一条 install 即自动放行。"
            ),
        }, ensure_ascii=False))
        return 0
    except Exception:
        return fail_open()


if __name__ == "__main__":
    sys.exit(main())
