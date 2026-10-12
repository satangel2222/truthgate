# -*- coding: utf-8 -*-
"""递归扫描闸 —— 拦【对已知超大目录跑递归统计】。

⛔ 治的是 lessons 形状 2026-08-20-R【观察者效应：用消耗 X 的动作去测量 X】的窄子集。

实录（2026-08-20 19:2x）：Frank 报"很卡"，我实测出 C 盘读延迟 182ms（正常 0.3ms）。
为了统计"我这轮往 npm-cache 砸了多少 MB"，我跑了
    Get-ChildItem npm-cache -Recurse -File | Measure-Object Length -Sum
它**自己超时 300 秒没跑完** —— 我正在用一个猛读几十万个小文件的操作，
去诊断"读小文件很慢"，而且在他已经很卡的时候又加了一轮压力。

先查现成（2026-08-20）：①本机 hooks/ 下 60+ 个闸，同构的纯语法判据闸已有 15+
（pipe-truncation-guard / launch-bound-guard / shell-writes-code-gate …），
但**没有一个管递归扫描**；host-machine-archive-first 只注入定论、不拦动作。
②-⑥ 外部不会有：这类闸绑定我自己的 lessons 和这台机器。⇒ **改造复用本机骨架，判据自建。**

判据（三条同时成立才拦，避免误伤）：
  ① 命令里有【递归遍历】动作
  ② 目标命中【已知超大目录】（node_modules / npm-cache / site-packages / .venv ...）
  ③ 做的是【统计/求和/计数】而不是找一个具体文件

放行：带 -Filter/-Include/-name 的精确查找、-Depth/-maxdepth 浅扫、
      删除清理操作、明确写了 SCAN-OK 的。
"""
import json
import re
import sys

RECURSE = re.compile(
    r"(-Recurse\b|Get-ChildItem\s+-r\b|\bfind\s+\S+\s|\bdu\s+-\w*s|\bdu\s+-\w*h"
    r"|\bls\s+-R\b|EnumerateFiles|os\.walk)", re.I)

BIG = re.compile(
    r"(node_modules|npm-cache|_npx|site-packages|\.venv\b|pnpm-store|pnpm-cache"
    r"|pip[\\/]Cache|\.cargo|\.gradle|\.nuget|AppData[\\/]Local[\\/]Temp(?![\\/]claude[\\/])"   # 会话自己的 scratchpad(Temp/claude/…)很小
    r"|Program Files|[\\/]Windows[\\/]System32)", re.I)

AGG = re.compile(
    r"(Measure-Object|\|\s*wc\b|\bwc\s+-[lc]\b|Length\s*-Sum|-Sum\b|--total"
    r"|\bdu\s+-|Sort-Object\s+Length|\bcount\b)", re.I)

OK = re.compile(
    r"(SCAN-OK|-Filter\s+\S|-Include\s+\S|\s-name\s+\S|-maxdepth\s+[1-3]\b"
    r"|-Depth\s+[1-3]\b|Remove-Item|\brm\s+-rf|--delete|-mtime|-Newer)", re.I)

MSG = u"""⛔ 递归扫描闸：你要对一个【已知超大目录】做递归统计。
命中：{hit}

⛔ 2026-08-20 实录：Frank 报「很卡」，我测出 C 盘读延迟 182ms（正常 0.3ms），
   然后为了统计 npm-cache 有多大而跑了递归扫描 —— **它自己超时 300 秒没跑完**，
   等于用【猛读几十万个小文件】去诊断【读小文件很慢】，还给他又加了一轮压力。
   （lessons 形状 2026-08-20-R：观察者效应 —— 用消耗 X 的动作去测量 X）

✅ 换成不压盘的路子：
  · 包缓存大小 → `npm cache ls` / `pnpm store path` 等包管理器自带的元数据命令
  · 目录大小   → `Get-Item` 看单层，或 `-Depth 1` 浅扫，或看磁盘剩余空间的差值
  · 真要全量数 → 等机器空闲再量，别在他报卡的时候量

（确需扫描：命令里加 `# SCAN-OK` 即放行；带 -Filter/-name 的精确查找、
 -Depth 1~3 浅扫、删除清理操作都不受此限。）
"""


def check(cmd):
    """返回命中的超大目录名，或 None 表示放行。抽出来供回归测试直接调用。"""
    if not cmd or len(cmd) > 20000:
        return None
    if OK.search(cmd):
        return None
    # 2026-09-27(考卷 c053):三样要在【同一条语句】里(管道连着的算一条),原来整条命令里各处凑齐就拦 ——
    #   `py <scratchpad>/x.py && … && du -sh archive/*` 里,大目录字样在第一条、递归统计在最后一条,毫不相干
    for st in re.split(r"&&|\|\||;|\n", cmd):
        if RECURSE.search(st) and BIG.search(st) and AGG.search(st):
            return BIG.search(st).group(0)
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    hit = check(cmd)
    if not hit:
        sys.exit(0)
    sys.stderr.write(MSG.format(hit=hit))
    sys.exit(2)


if __name__ == "__main__":
    main()
