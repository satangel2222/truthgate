#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse 守卫：拦【定频轮询远程服务】的等待循环。

由来(2026-08-20 形状-P)：Kaggle 手机验证要 Frank 本人操作，我却写脚本每 10 秒问一次
服务器"好了没"，写了三遍，最后一个还每次 new_page() 开新标签。合计约 280 次请求，
把他账号刷出 "You've sent too many requests"。他问「你一直 sent 了多少次？是不是
现在还没停？」——问的时候它确实还在跑，我毫不知情。

病根：等【人】的动作，服务器根本不需要被问，正确成本是 0 次请求。

先查现成(2026-08-20)：GitHub `rate limit guard polling AI agent` /
`prevent excessive requests hook agent` 两查零结果；本机 hooks 无同类 ⇒ 自建。

拦：循环 + sleep + 对【外部域名】发请求。
放行：只碰 localhost/127.0.0.1/::1；没循环或没 sleep；显式 `# poll-ok`。
加重：循环体里出现 new_page/new_context（比刷新重得多）。
fail-open：自己出错一律放行，绝不卡住正常工作。
"""
# ⛔ 2026-09-10 接进账本(Frank:「为何 superego 没拦你还是没开火?」):本闸此前从没 import guard_common,
#   于是它每次开火 hook-stats.jsonl 里都是 0 条 ⇒ 记分板看不见它、nudge-escalation-gate 也数不到它
#   (同日扫出 10 道同病,ui-edit-guard 一天响 8 次账本 0 条)。guard_common 一 import 就自动观测 stdout、
#   退出时按内容判 nudge/block/allow,本闸逻辑一字不改。自包含写法:不依赖本文件已有的 import。
try:
    import os as _gc_os, sys as _gc_sys
    _gc_sys.path.insert(0, _gc_os.path.dirname(_gc_os.path.abspath(__file__)))
    import guard_common  # noqa: F401  接线即记账;失败不影响本闸(fail-open)
except Exception:
    pass

import json
import os
import re
import sys

# ⛔ 2026-08-20 故障注入抓出来的漏洞：原来写死 `for \w+ in range`，
# 于是 shell 的 `for i in $(seq 100); do sleep 10; curl https://...; done`
# 完全匹配不上 —— 而那正是我最可能写出来的轮询形式。改成通用的 `for X in`。
LOOP = re.compile(r"\b(for\s+\w+\s+in\b|while\s+True|while\s+\w|while\s*\[|"
                  r"until\s+\w|foreach\s*\(|for\s*\()")
SLEEP = re.compile(r"(time\.sleep|asyncio\.sleep|wait_for_timeout|Start-Sleep|\bsleep\s+\d)")
# ⛔ curl/wget 后面几乎总有参数（`curl -s https://…`），原来写 `curl\s+http` 漏掉了。
# 允许中间夹最多 60 个非换行字符再出现 http。
NET = re.compile(r"(\.goto\(|requests\.(get|post)|urlopen|urllib\.request|httpx\."
                 r"|fetch\(|(curl|wget)[^\n]{0,60}https?://"
                 r"|Invoke-WebRequest|Invoke-RestMethod|page\.reload)")
NEWPAGE = re.compile(r"(new_page\(|newPage\(|new_context\(|newContext\()")
EXTERNAL_URL = re.compile(
    r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])[\w.-]+", re.I)
SCRIPT_PATH = re.compile(r"[\w./\\:-]+\.(?:py|js|mjs|cjs|ts|ps1|sh)\b")

REASON_TMPL = """🚫 远程轮询闸拦截 [{src}]：{hit}

⛔ 2026-08-20 形状-P：我用「每 10 秒问一次服务器」等 Frank 做手机验证，三个脚本
   合计约 280 次请求，把他 Kaggle 账号刷出 'You've sent too many requests'。
   他问「你一直 sent 了多少次」时，它还在跑，而我毫不知情。

先答这三问，答不出就别启动它：
  ① 我在等【人】还是【机器】？
     等人（输密码/收验证码/点确认/审批/线下操作）→ ⛔ 绝不轮询远程服务，
     改成「他做完说一声我再动」—— 正确成本是 0 次请求。
  ② 这个循环总共会发多少次请求？（时长 ÷ 间隔）写不出这个数就不许跑。
  ③ 谁的额度在被消耗？用他的账号 = 花他的信誉。

等【机器】（编译/CI/任务队列）才可轮询，且必须：指数退避(10→20→40s) + 硬上限，
不许定频长跑；⛔ 循环体里绝对不许 new_page()/new_context()。
只碰 localhost / 127.0.0.1 的轮询不受本闸限制。
（他明确要求这样轮询时，在命令里加 `# poll-ok`。）"""


def _looks_indent_lang(text):
    """缩进型语言(python/js/ts)的特征;shell 的 for...do...done 不算。"""
    if re.search(r";\s*do\b|\bdone\b|\bfi\b", text):
        return False
    return bool(re.search(r"^\s*(def |import |from |const |let |await |async )", text, re.M))


def _line_in_loop(lines, i):
    """第 i 行是否处在某个 for/while 循环体内(靠缩进回溯)。"""
    indent = len(lines[i]) - len(lines[i].lstrip())
    if indent == 0:
        return False
    for j in range(i - 1, -1, -1):
        ln = lines[j]
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind < indent:
            if LOOP.search(ln):
                return True
            indent = ind
            if ind == 0:
                return False
    return False


def analyze(text):
    """命中返回理由字符串，否则 None"""
    if not text or re.search(r"#\s*poll-ok", text, re.I):
        return None
    if not (LOOP.search(text) and SLEEP.search(text)):
        return None

    # ⛔ 2026-08-20 修误伤：原来"全文有网络调用 + 全文有外部网址"就拦，
    # 于是一个只轮询 127.0.0.1 等自己进程起来、但文件里另有一行
    # `URL = "https://www.kaggle.com/..."` 的脚本被误拦。
    # 改判据：只认【同一行里既发请求、又指向外部域名】的行。
    # 已知漏洞（诚实登记）：`U="https://外部"` + 另一行 `goto(U)` 这种变量绕行会漏，
    # 宁可漏拦也不误伤——误伤会让我养成加 `# poll-ok` 绕过的坏习惯。
    lines = text.splitlines()
    bad = [ln for ln in lines if NET.search(ln) and EXTERNAL_URL.search(ln)]
    if not bad:
        return None

    # ⛔ 2026-09-09 第二次修误伤(Frank 正等着 IG 修好,这道闸连拦 3 次全是误报):
    # 上面只验证了「全文存在循环」和「某一行发外部请求」,**没验证那一行是否【在】循环里**。
    # 实际被误拦的脚本:一次性 `page.goto(外部)` 在顶层,而文件别处有个
    # `for s, v in zip(sels, [...]): s.select_option(v)`(纯 DOM 操作,零请求)
    # ⇒ 判成「定频轮询」。真轮询的判据必须是【请求行本身在循环体内】。
    # 只对缩进型语言(py/js)收紧;shell 的 `for ...; do curl; done` 无缩进,保留原判据不削弱。
    if _looks_indent_lang(text):
        if not any(_line_in_loop(lines, i) for i, ln in enumerate(lines)
                   if NET.search(ln) and EXTERNAL_URL.search(ln)):
            return None
    # ⛔ 2026-10-05 第三次修误伤：轮询 = 反复问【同一个地址】等它变；而
    # `for n in range(1, 41): get(base + f"&page={n}")`、`for t in 星辰变 仙逆; do curl ".../$t"; done`
    # 是【逐个处理一份有限清单】，每次地址都不同、跑完就停，不是轮询。当天实录：我要把一个小说站的
    # 搜索结果翻完核对「星辰变到底有没有」，被拦，于是没核对就写了「没配到」。
    # 判据（看事实）：全文没有 while 循环，且某个 `for X in` 的循环变量 X 被拼进了字符串
    # （`{X}` / `$X` / `+ X` / `% X` / `quote(X`）。`for i in $(seq 100); do sleep 10; curl 固定地址` 不满足，照拦。
    # 已知漏洞（诚实登记）：`for i in range(999): get(f"固定地址?try={i}")` 会漏。宁可漏拦也不误伤。
    if not re.search(r"\bwhile\b", text):
        for v in set(re.findall(r"\bfor\s+(\w+)\s+in\b", text)):
            ev = re.escape(v)
            if re.search(r"(\{\s*%s\b|\$\{?%s\b|[+%%]\s*%s\b|quote\(\s*%s\b)" % (ev, ev, ev, ev), text):
                return None
    ext = [m for ln in bad for m in EXTERNAL_URL.findall(ln)]
    hosts = sorted(set(ext))[:3]
    if NEWPAGE.search(text):
        return f"循环里开新页面/新上下文 + 轮询外部域名 {hosts}"
    return f"定频轮询外部域名 {hosts}"


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        sys.exit(0)
    cmd = str((data.get("tool_input") or {}).get("command") or "")
    if not cmd:
        sys.exit(0)

    hit, src = analyze(cmd), "命令本身"
    if not hit:                            # 命令里执行的脚本文件也要看
        # ⛔ 2026-09-10:只看【被执行】的脚本。`sed -n 1,5p rh_studio.py` / `grep def rh_studio.py` /
        #   `Get-Item rh_studio.py` 是在【读】它,不是在【跑】它 —— 一天误拦 3 次(Frank「误伤误拦不修?」)。
        #   判据在 guard_common.path_is_only_read:看这段命令的动词。拿不到共享层就退回旧行为(全看,保守)。
        try:
            from guard_common import path_is_only_read as _only_read
        except Exception:
            def _only_read(_c, _p):
                return False
        for path in SCRIPT_PATH.findall(cmd):
            if _only_read(cmd, path):
                continue
            try:
                if os.path.isfile(path) and os.path.getsize(path) < 400_000:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        hit = analyze(f.read())
                    if hit:
                        src = f"脚本 {path}"
                        break
            except Exception:
                continue
    if not hit:
        sys.exit(0)

    reason = REASON_TMPL.format(src=src, hit=hit)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.stderr.write(reason + "\n")
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)                        # fail-open
