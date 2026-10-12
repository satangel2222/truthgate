#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""deploy-dirty-tree-gate —— PreToolUse 闸:拦【从有未提交改动的目录直接部署上线】。

⛔ 为什么要它(2026-09-18 airbnb ai manager,真实事故):
  修客人入住页时,我 7 次 `npx vercel deploy --prod` 都是【直接从工作区】部署。
  工作区里躺着 Frank 本地还没提交的一整套改动 ⇒ 一起被推上了生产:
    · 他本地的「预订编号核验门禁」(说明和按钮只有中文、还露出「快捷填入测试订单」)
      —— 当天 13:06 一位真客人卡在这里,只能 WhatsApp 问「what should i put there」
    · public/ 里一份内部报告(2.78 MB)变成任何人都能打开的公开网页
    · `.env`、`.env.local.bak` 被传进部署源码;还有 `.git_old`(93 个文件)、`dev.db`、日志、78 张截图
  上线文件数从 112 变成 313。前一晚的我是特意只用 git 正式版部署的 —— 这个做法没被固化,第二天就丢了。

判据(全中才拦):
  ① 命令是部署上线类:vercel deploy / vercel --prod / fly(ctl) deploy / netlify deploy
  ② 部署目录(命令里 cd 的目标、--cwd,否则当前目录):
     · 在 git 仓库里且 `git status --porcelain` 有任何条目   ⇒ 拦(列出几条 + 危险项)
     · 或目录顶层 / public/ 里有 .env* / *.db / .git_old 这类不该上线的文件 ⇒ 拦
放行:
  · 干净目录(不在 git 里、也没有危险文件 —— 比如专门造的干净部署包)
  · 命令里带 `# DEPLOY-TREE-REVIEWED`(表示我已逐个看过这次会上传的文件清单)
安全:fail-open(判不出来就放行,但写日志);只读 git,不改任何东西。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from guard_common import hook_log
except Exception:
    def hook_log(name, msg, ctx=""):
        try:
            with open(Path(__file__).parent / f"{name}.log", "a", encoding="utf-8") as f:
                f.write(f"{msg} {ctx}\n")
        except Exception:
            pass

NAME = "deploy-dirty-tree-gate"
DEPLOY = re.compile(
    r"\bvercel\b[^\n|;&]*?\s(?:deploy|--prod|--target[= ]+production)\b"
    r"|\bfly(?:ctl)?\s+deploy\b"
    r"|\bnetlify\s+deploy\b", re.I)
READ_ONLY = re.compile(r"\bvercel\s+(?:ls|list|inspect|logs|env\s+ls|whoami)\b", re.I)
MARKER = "# DEPLOY-TREE-REVIEWED"
DANGER = re.compile(r"(^|/)(\.env(?!\.example)[^/]*|[^/]+\.db|\.git_old)(/|$)", re.I)


# 切目录:只认【命令段开头】(`curl -sL` 里的 sL、`echo "cd x"` 都不算),bash/cmd/PowerShell 写法都认。
# ⛔ 2026-09-18 两次栽:①只认 cd ⇒ PowerShell Set-Location 到脏仓库被放行;
#    ②补 sl 别名时没锚段首 ⇒ `vercel deploy; curl -sL <网址>` 把网址当部署目录、目录不存在、放行(外审抓到)。
CHDIR = re.compile(r"\s*(?:cd|chdir|Set-Location|Push-Location|pushd|sl)(?:\s+/d)?\s+"
                   r"(?:-(?:Literal)?Path(?::|\s+)\s*)?(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", re.I)


def _resolve(base, target):
    t = target.strip("\"'")
    m = re.match(r"^/([a-zA-Z])(/.*)?$", t)          # Git Bash 写法 /c/Users/... -> C:/Users/...
    if m:
        t = m.group(1) + ":" + (m.group(2) or "/")
    t = os.path.expanduser(t)
    return os.path.normpath(t if os.path.isabs(t) else os.path.join(base, t))


TOOL = re.compile(r"\b(?:vercel|fly(?:ctl)?|netlify)\b", re.I)
# 这些参数后面跟的是值(应用名/令牌/配置文件…),不是部署目录
VALUE_FLAGS = {"-a", "--app", "-c", "--config", "-t", "--token", "-S", "--scope", "-e", "--env",
               "-b", "--build-env", "-m", "--meta", "-A", "--local-config", "-Q", "--global-config",
               "--target", "-i", "--image", "--dir", "--site", "--auth", "--regions", "--archive"}


def _deploy_target(seg, d):
    """部署那一段里显式给出的目录:`--cwd X`,或位置参数 `vercel [目录]` / `fly deploy [目录]`。"""
    toks = re.findall(r"\"[^\"]+\"|'[^']+'|\S+", seg[TOOL.search(seg).end():])
    out, i = d, 0
    while i < len(toks):
        t = toks[i]
        flag, eq, val = t.partition("=")
        if flag == "--cwd" or flag in VALUE_FLAGS:
            if not eq:
                val = toks[i + 1] if i + 1 < len(toks) else ""
                i += 1
            if flag == "--cwd" and val:
                out = _resolve(d, val)
        elif not t.startswith("-") and t.lower() != "deploy" and os.path.isdir(_resolve(d, t)):
            out = _resolve(d, t)
        i += 1
    return out


def deploy_dir(cmd, cwd):
    """部署发生在哪个目录。只算部署那一段【之前】的切目录,相对路径接着上一个目录算。
    解析不出(变量 $w / 目录不存在)返回 None —— 调用方按【拦】处理:看不清上传什么就不许上线。"""
    d = cwd or os.getcwd()
    for seg in re.split(r"&&|\|\||[;|\n]", cmd):
        if DEPLOY.search(seg):
            d = _deploy_target(seg, d)
            break
        c = CHDIR.match(seg)
        if c:
            d = _resolve(d, c.group(1))
    return d if os.path.isdir(d) else None


def git_dirty(d):
    """返回 (是否在 git 里, porcelain 条目列表)。只看这个目录子树。"""
    try:
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=15)
        if top.returncode != 0:
            return False, []
        st = subprocess.run(["git", "-C", d, "status", "--porcelain", "--untracked-files=all", "--", "."],
                            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="ignore")
        return True, [l for l in st.stdout.splitlines() if l.strip()]
    except Exception:
        return False, []


def danger_files(d):
    out = []
    p = Path(d)
    for base in (p, p / "public"):
        try:
            for x in base.iterdir():
                rel = x.relative_to(p).as_posix()
                if DANGER.search(rel):
                    out.append(rel)
        except Exception:
            pass
    return out


def verdict(cmd, cwd):
    if not DEPLOY.search(cmd) or READ_ONLY.search(cmd) or MARKER in cmd:
        return None
    d = deploy_dir(cmd, cwd)
    if d is None:
        return None, [], []
    in_git, entries = git_dirty(d)
    danger = danger_files(d)
    if in_git and entries:
        return d, entries, danger
    if danger:
        return d, [], danger
    return None


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
        if data.get("tool_name") not in ("Bash", "PowerShell"):
            return
        cmd = (data.get("tool_input") or {}).get("command", "") or ""
        res = verdict(cmd, data.get("cwd"))
        if not res:
            hook_log(NAME, "allow", cmd[:160])
            return
        d, entries, danger = res
        if d is None:
            hook_log(NAME, "BLOCK unresolved-dir", cmd[:200])
            print(json.dumps({"decision": "block", "reason": (
                "⛔ 部署闸:这条部署命令【解析不出是从哪个目录上线】(切目录用了变量,或那个目录不存在)。\n"
                "看不清会上传什么就上线 = 2026-09-18 出事的同一个形状。\n"
                "✅ 改成字面路径:`--cwd \"<干净部署目录的完整路径>\"`;"
                "或逐个核过这次会上传的清单后,在命令末尾加 `# DEPLOY-TREE-REVIEWED`。"
            )}, ensure_ascii=False))
            return
        risky =[e for e in entries if DANGER.search(e[3:].replace("\\", "/")) or e[3:].startswith("public/")]
        hook_log(NAME, f"BLOCK dir={d} dirty={len(entries)} danger={len(danger)}", cmd[:200])
        lines = "\n".join("    " + e for e in (risky or entries)[:12])
        print(json.dumps({"decision": "block", "reason": (
            f"⛔ 部署闸:你要从【{d}】直接上线,但这个目录不干净 —— 它会把下面这些一起推到生产:\n"
            f"  未提交/未跟踪的改动: {len(entries)} 条"
            + (f"(其中危险项 {len(risky)} 条)" if risky else "") + "\n"
            + (lines + "\n" if lines else "")
            + (f"  不该上线的文件: {danger}\n" if danger else "")
            + "2026-09-18 实录:就是这样把 Frank 本地没做完的「预订编号核验门禁」(只有中文+测试订单按钮)、"
              "一份内部报告(变成公开网页)、.env 备份一起推上了线,真客人当天就卡住了。\n"
              "✅ 正确做法:造一个干净的部署目录 = 上一次已验证的线上版本 + 只叠你这次要改的文件,"
              "逐个看差异,再从那个目录部署。\n"
              "（已逐个核过这次会上传的清单、确实都该上线:命令末尾加 `# DEPLOY-TREE-REVIEWED`）"
        )}, ensure_ascii=False))
    except Exception as e:
        hook_log(NAME, f"error(fail-open): {e}")


if __name__ == "__main__":
    main()
