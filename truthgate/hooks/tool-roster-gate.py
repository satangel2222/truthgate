#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop gate: 我给 Frank 列【工具路由表/能力清单】时，漏掉 CLAUDE.md 那张现成表里的条目 ⇒ 拦。

⛔ 为什么必须是【机器拦】而不是又一条警告（2026-09-05，Frank 第 3 次问同一件事）:
   实录：他问「我是不是有 x-tweet-fetcher 这个 skill，为何你没提？」
   —— 那张「本机搜索/联网工具全表」**就写在我每轮都加载的 CLAUDE.md 里、12 行**，
   我列表时只写了 6 个，漏掉 x-tweet-fetcher / last30days / obsidian-brain /
   chat-archive / codegraph / web-access **整整一半**。
   他 2026-08-26 问过一模一样的话：「我本地和 skill 是不是也有同类的工具你没有全部列出来」。
   lessons 里「全表」出现 9 次、「没有全部列出来」2 次 ⇒ **这是高频复发形状**。

⛔ 病根不是"我不知道"，是**我列表时凭「刚才用过什么」回忆，而不是去查那张现成的表**。
   表就在上下文里，我却当它不存在 —— 所以「记住要列全」这类警告没有用：
   在"我没意识到自己漏了"的那一刻，警告一个字都进不去。
   ⇒ 唯一有效的：**把我写的表和 CLAUDE.md 那张表做集合差，少了就 deny。**

判据（要同时成立才拦，避免误伤日常对话）:
  ① 本轮我确实在给他【列表/路由表】(输出里有 markdown 表格或多个 `工具名` 并列)
  ② 话题落在那张表覆盖的领域(搜索/联网/抓取)
  ③ CLAUDE.md 那张表里的条目，我漏了 >= MISS_MIN 个
安全: fail-open —— 任何异常/找不到表/读不到 transcript 一律放行(rc=0)。
"""
import io
import json
import os
import re
import sys

MISS_MIN = 3          # 漏 3 个及以上才拦(漏 1~2 个可能是话题确实窄，不当错)
CLAUDE_MD = os.path.expanduser(r"~\.claude\CLAUDE.md")
TABLE_ANCHOR = "本机搜索/联网工具全表"


def die_ok():
    sys.exit(0)


def roster_from_claude_md():
    """从 CLAUDE.md 那张表里抠出【工具标识】。返回 {显示名: [别名...]}。"""
    try:
        t = io.open(CLAUDE_MD, encoding="utf-8", errors="replace").read()
    except Exception:
        return {}
    i = t.find(TABLE_ANCHOR)
    if i < 0:
        return {}
    seg = t[i:i + 3000]
    out = {}
    for ln in seg.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "---" in s or "要干什么" in s:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # 第二列是"用哪个"，从里面抠出反引号里的标识或 skill 名
        ids = re.findall(r"`([^`]+)`", cells[1])
        ids += re.findall(r"skill\s+([\w-]+)", cells[1])
        names = set()
        # ⛔ 别名必须是【能唯一指认这个工具】的词。第一版直接切路径末段,抠出了
        #   `claude`(来自 ~/.claude/web.py)、`api`(来自 gh api)、`"词"`、`<url>` 这种
        #   —— 前两个太通用会恒真放行(假保护),后两个是占位符永远匹配不到(恒假误拦)。
        #   实测:补全后的表仍被拦,就是因为 `"词"` / `<url>` 这类永远命中不了。
        #   第二版又踩一个:`~/.claude/web.py search` 切完只剩 `.claude`(目录名),
        #   三个不同条目的别名全成了 `.claude` ⇒ 互相混淆。⇒ 显式剔除路径成分,
        #   并且**保留带扩展名的脚本名**(web.py→web,search.py→search 太通用则丢弃)。
        NOISE = {"claude", ".claude", "api", "py", "node", "python", "skill", "npx",
                 "run", "get", "search", "add", "the", "and", "for", "skills",
                 "scripts", "home", "users"}
        for x in ids:
            x = x.strip()
            if x.startswith("<") or x.startswith('"') or x.startswith("'"):
                continue                       # 占位符 <url> / "词" —— 不是工具名
            for tok in re.split(r"[\s/\\]+", x):
                tok = tok.strip().strip("\"'<>`~").lower()
                stem = tok.replace(".py", "").replace(".js", "").replace(".mjs", "")
                if len(stem) >= 4 and stem not in NOISE and not stem.startswith("-"):
                    names.add(stem)
        # 仍然一个别名都抠不出来(整格全是路径/占位符)⇒ 用"要干什么"那列的关键词兜底,
        # 免得这一条变成【永远匹配不到 = 恒误拦】。
        if not names:
            for kw in re.findall(r"[A-Za-z][\w.-]{3,}", cells[0]):
                if kw.lower() not in NOISE:
                    names.add(kw.lower())
        if names:
            key = re.sub(r"[*`]", "", cells[0])[:24]
            out[key] = sorted(names)
    return out


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        die_ok()

    tp = data.get("transcript_path") or ""

    # 2026-09-06 防无限 loop:本轮被 Stop 闸拽回次数到上限就让开。

    #   实测 55 道 Stop 闸只有 64% 受回合预算管,自己读 transcript 的 12 道全绕过,

    #   本闸就在那 12 道里(Frank:「触发了无限Loop的bug…think twice 然后阻塞」)。

    #   安全类闸在 _BUDGET_NEVER 里永不熔断;逃生阀 SUPEREGO_NO_BUDGET=1。

    try:

        from guard_common import turn_budget_ok as _tbo

        if tp and not _tbo(tp):

            return

    except Exception:

        pass
    if not tp or not os.path.exists(tp):
        die_ok()

    # 取本轮我最后一条给他的话
    said = ""
    try:
        with io.open(tp, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-160:]
        for ln in reversed(lines):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            for c in (o.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "text":
                    said = c.get("text") or ""
                    break
            if said:
                break
    except Exception:
        die_ok()

    if not said:
        die_ok()

    low = said.lower()

    # ① 是不是在列表/路由表(有 markdown 表格,或 3 个以上反引号标识并列)
    is_table = said.count("|") >= 12 or len(re.findall(r"`[\w./-]{3,}`", said)) >= 4
    if not is_table:
        die_ok()

    # ② 话题在"搜索/联网/抓取"这张表覆盖的领域
    topical = re.search(r"搜索|检索|联网|抓取|抓网页|websearch|webfetch|搜网页|查资料", low)
    if not topical:
        die_ok()

    # ⛔ 2026-09-05 第一天就误伤一次:我在讲 chat-archive 的同步状态(表格是
    #   「你的印象 / 实测」的核对表),只因文中出现"搜索""抓取"就被判成在列工具表。
    #   ⇒ 加一条:必须真的在【推荐/罗列可用工具】,判据是同一段里出现
    #     「用什么 / 用哪个 / 路由 / 我会用 / 走哪条」这类**选型语义**,
    #     而不只是碰巧提到搜索这个词。缺了它就放行,宁可漏拦也别天天误伤 ——
    #     一个天天误伤的闸,我很快就会学会无视它(那才是真正的失效)。
    picking = re.search(
        r"用什么|用哪个|用哪条|走哪条|我会用|路由|优先用|该用|选型|工具表|全表|清单",
        low)
    if not picking:
        die_ok()

    # ⛔⛔ 2026-09-06 收窄:这道闸一天误伤 4 次(4/4 全错),而它自己【从没进过 hook-stats】——
    #   于是我既看不到它开火多凶,也没意识到它已经是最该修的那道。
    #   三次误伤的现场:①我在列【闸的名字】(guard-destructive / cross-scope-guard…)回答
    #   "superego 为何没拦住" ②我在列【Obsidian 插件】(7,323 个里筛语义类)
    #   ③我在列【这轮装了哪些 Python 包】。三次都碰到了"搜索/工具/清单"这些词,但
    #   **一次都不是在列他那张搜索工具全表**。
    #   ⇒ 一个天天误伤的闸,我很快学会无视它 —— 那比没有闸更糟(banner 失明)。
    #   判据:同一段里明显在讲【别的清单】时放行。宁可漏拦,别天天喊狼来了。
    other_roster = re.search(
        r"闸|hook|guard|gate|插件|plugin|下载量|回归|测试|故障注入|"
        r"pip install|npm install|装(回来|上|好)了|包(装|没装)|依赖",
        low)
    if other_roster:
        die_ok()

    roster = roster_from_claude_md()
    if len(roster) < 6:          # 表读不出来就别拦(可能 CLAUDE.md 改版了)
        die_ok()

    missing = []
    for label, aliases in roster.items():
        if not any(a in low for a in aliases):
            missing.append((label, aliases[0]))

    if len(missing) < MISS_MIN:
        die_ok()

    msg = ["⛔ 工具全表闸:你在给 Frank 列【搜索/联网工具】,但 CLAUDE.md 那张现成的全表里,",
           "   有 %d 个条目你一个字没提:" % len(missing)]
    for label, a in missing[:10]:
        msg.append("     · %-22s (%s)" % (label, a))
    msg += [
        "",
        "⛔ 实录(2026-09-05,他第 3 次问同一件事):他问「我是不是有 x-tweet-fetcher 这个 skill,为何你没提?」",
        "   —— 那张表 12 行,我只列了 6 个。2026-08-26 他问过一模一样的话。",
        "   lessons 里「全表」出现 9 次 ⇒ 这是高频复发形状,不是偶然。",
        "⛔ 病根:我列表时凭【刚才用过什么】回忆,而不是去查那张现成的表 —— 表就在我上下文里。",
        "⇒ 现在回去把漏掉的补进你那张表(或明说为什么这次不适用),再收尾。",
    ]
    sys.stderr.write("\n".join(msg) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        die_ok()
