#!/usr/bin/env python3
"""pipe-truncation-guard.py -- PreToolUse hook

Prevents Bash pipelines from early-terminating long-running processes.
Example: python train.py | head -20 cuts off a multi-hour training job.
Criteria: pipe + head/tail on right + long-running keyword on left -> deny
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

import json, re, sys

TRUNCATE_RE = re.compile(r"^\s*(head|tail)\s", re.IGNORECASE)
LONG_RUN_RE = re.compile(
    r"(?:^|[\s_/.()-])(train|fit|optim|learning|model|epoch|batch|gradient|"
    r"build|compile|install|scrape|crawl|fetch|download|export|dump|migrate|seed|"
    # ⛔ 2026-09-07 补:词表里没有【回归跑器】这一类,于是我自己那条
    #   `py -3.12 .../run_all.py 2>&1 | tail -8` 被判 `short-cmd` 放行 ——
    #   8 分钟的全量回归跑完,保存下来的却是某个测试的输出尾巴,**汇总被截没了,整轮白跑**。
    #   (我 lessons 里明写着「|tail 截掉日志毁证据」,这次是闸也没兜住。)
    r"run_all|regression|regress|sweep|suite|"
    r"worker|daemon|server|serve|watch|dev|test|benchmark|process|job|task)"
    r"(?:[\s_/.()-]|$)",
    re.IGNORECASE,
)

# ⛔ 2026-09-05 修死闸: 下面 4 个正则被 verdict() 使用却【从未定义】-> NameError,
#   这道闸每次跑都崩 = 彻底失效。按各自注释的语义补齐。
# `grep -m N` / `grep --max-count=N`: 拿到 N 条就退出, 同样会关掉管道把左边写死。
GREP_EARLY_EXIT_RE = re.compile(r"\bgrep\b[^|]*(?:\s-m\s*\d+|--max-count[=\s]*\d+)", re.IGNORECASE)
# `tee` 在管道中间 = 全量已落盘, 右边再截断只影响屏幕显示, 数据没丢 -> 不该拦。
TEE_RE = re.compile(r"(?:^|\|)\s*tee\b", re.IGNORECASE)
# 查询/列举类秒回命令: 截断无害, 拦了就是噪音。
QUERY_RE = re.compile(
    # ⛔ 必须锚定【命令分段的开头】(^ 或 ; && || & 之后的首词) —— 原版任意位置匹配导致:
    #   `cd "$SP" && timeout 1800 python train.py` 因中间词误判成 query 而漏拦(危险);
    #   而 `powershell -Command "Get-Process python"` 因 python 命中 LONG_RUN 被误拦。
    r"(?:^|[;&]{1,2}\s*|\|\|\s*)\s*"
    # 包装器前缀(timeout N / nohup / env X=Y / stdbuf -oL)后面才是真命令 ——
    #   `timeout 600 tail -F app.log` 的开头是 timeout, 不跳过它就够不到 tail。
    r"(?:(?:timeout\s+(?:/t\s*)?\d+|nohup|stdbuf(?:\s+-\w+)*|env(?:\s+\w+=\S+)*)\s+)*"
    r"(?:ls|dir|cat|type|echo|printf|ps|tasklist|netstat|wc|sort|uniq|"
    # tail -F/-f = 跟随日志等一个信号(不是长跑被截断) -> 放行;
    #   裸 tail 是截断符, 归 TRUNCATE_RE, 所以 `python train.py | tail -5` 照样拦。
    r"tail\s+-[Ff]\b[^|]*|"
    r"git\s+(?:log|status|diff|branch|show)|"
    r"pip\s+(?:list|show|freeze)|npm\s+(?:ls|list)|winget\s+list|"
    r"powershell[^|]*?Get-\w+|pwsh[^|]*?Get-\w+|Get-\w+)\b",
    re.IGNORECASE,
)

# 被 timeout/长跑时限包着的外部命令: 即使名字不在 LONG_RUN 词表里也算长跑。
TIMEOUT_LONG_RE = re.compile(r"\btimeout\s+\d+|\btimeout\s+/t\s*\d+", re.IGNORECASE)

# 2026-09-05 抽出 verdict(Frank 授权彻查 superego 时补):
#   判据原本长在 hook 外壳 check(tool_name, tool_input) 里,而回归测试要的是
#   verdict(cmd, bg) -> (bool, why) ⇒ 测试整份跑不起来(AttributeError: no attribute 'verdict'),
#   这道闸等于零回归覆盖,里面的正则改成什么样都没人知道。
#   ⇒ 判据抽成纯函数(字符串进、判定出,不碰 stdin/不碰 JSON),外壳只做 IO ——
#   与本仓库 douyin_retry.py / douyin_alert.py 抽模块同理:让尺子量得到东西。
def verdict(cmd, bg=False):
    """纯判据:这条命令会不会把一个长跑进程截断掉。返回 (要拦吗, 为什么)。
    bg = 是否后台运行。保留这个入参是因为回归用例带它;判定与前台一致 ——
    后台跑同样会因为 head 关掉管道而让左边写 stdout 堵死。"""
    if "|" not in (cmd or ""):
        return False, "no-pipe"
    parts = [p.strip() for p in cmd.split("|")]
    if not parts:
        return False, "no-parts"
    last = parts[-1]
    # ⛔ 截断不只有 head/tail:`grep -m N` 拿到 N 条就退出,同样会关掉管道把左边写死。
    if not (TRUNCATE_RE.search(last) or GREP_EARLY_EXIT_RE.search(last)):
        return False, "no-trunc"
    # ⛔ `tee` 在中间 = 全量已落盘,右边再截断只影响【屏幕显示】,数据没丢 ⇒ 不该拦。
    if TEE_RE.search(cmd):
        return False, "tee-saves-all"
    left = "|".join(parts[:-1])
    # ⛔ 左边是【查询/列举】这类秒回命令(Get-Process/ps/ls/git log…),截断无害 ⇒ 不该拦。
    #   否则 `powershell "Get-Process python" | head -8` 这种日常也被拦 = 噪音。
    if QUERY_RE.search(left):
        return False, "query-cmd"
    if LONG_RUN_RE.search(left):
        return True, "longrun+trunc"
    # ⛔ 有 timeout/长跑时限包着的外部命令,即使名字不在 LONG_RUN 词表里也算长跑
    #   (实录:jianying-subtitle 转录 10 分钟音频,名字里一个关键词都不占)。
    if TIMEOUT_LONG_RE.search(left):
        return True, "timeout-longrun+trunc"
    return False, "short-cmd"


def check(tn, ti):
    if tn != "Bash":
        return "allow", ""
    cmd = ti.get("command", "")
    bad, _why = verdict(cmd, bool(ti.get("run_in_background")))
    if not bad:
        return "allow", ""
    parts = [p.strip() for p in cmd.split("|")]
    left, last = "|".join(parts[:-1]), parts[-1]
    reason = ("Pipeline terminated a potentially long-running process.\n"
              "Left: %s\nTruncation: %s\n"
              "If left takes longer than a few seconds, data will be lost." % (left[:80], last))
    return "deny", reason

def main():
    data = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
    except:
        sys.exit(0)
    tn = data.get("tool_name", "")
    ti = data.get("tool_input", {})
    d, r = check(tn, ti)
    if d == "deny":
        sys.stderr.write(r)
        sys.stdout.write(json.dumps({"permissionDecision": "deny",
            "permissionDecisionReason": r,
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": r}},
            ensure_ascii=False))
    else:
        sys.stdout.write(json.dumps({"permissionDecision": "allow"}, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()