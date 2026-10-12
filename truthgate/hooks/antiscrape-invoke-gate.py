#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""antiscrape-invoke-gate — 拦【被反爬挡住就宣布"边界"，而本机反爬工具一个没用】。

⛔ 来历（2026-09-06，Frank：「为何你遇到反爬网站，不会自动用反爬 skill?
   我有那么 skill 里自带那么多本地工具都遗失了吗?」）：
   我抓 Reddit 被挡，依次试了 r.jina.ai → playwright headless → playwright 非 headless，
   全挂，然后向他宣布「这是真边界，要人过验证码」。
   而本机躺着：anti-scraping SKILL.md(434 行)、browser-routing.md(189 行)、
   scrapling 0.4.12、cloakbrowser 0.5.8 —— **一个都没碰**。
   后来只补了 scrapling 的依赖（curl_cffi/patchright/msgspec + 内核），
   StealthyFetcher **一次就把那两个帖子的正文全抓了下来**（HTTP 200，含全部评论）。
   ⇒ 不是边界，是我没用工具。

⛔ 这是【第 3 次以上】复发：lessons 里 "反爬"出现 17 次；
   2026-08-08 Frank 原话「我不是有很多反爬…尤其可以针对 cloudflare 的工具和 skill？没用？」
   （当时记着"本机摆着 14 个对口 skill，我一个都没 invoke"）；
   2026-08-20 又记「12 天内复发」。警告写了三遍没用 ⇒ 只能上机器拦截。

⛔ 为什么已有的 browser-routing-gate 没拦住（真根因，别重复造轮子）：
   它是 **PreToolUse**，判据是【命令字符串里有没有 playwright/cloakbrowser 这类词】。
   而我把 playwright 调用**写在 .py 文件里**，命令行只有 `py -3 shot.py` ⇒ 闸看不见。
   本闸是 **Stop**，不看命令长什么样，只看【结论】和【本轮用过什么】，绕不过去。

判据（三条同时成立才拦，宁漏勿误杀）：
  ① 本轮结论里出现【被挡/放弃】类断言：被挡、403、封锁，人机验证、进不去，抓不到，真边界…
  ② 本轮全程没有任何一次【反爬工具】的痕迹（工具名出现在任何 tool_use 的入参或 name 里就算数）
  ③ 不在过去式/复述/立规矩语境
"""
import json
import re
import sys
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "antiscrape-invoke-gate.log"

# ① 「被挡 / 我放弃了」类断言
BLOCKED_CLAIM = re.compile(
    r"(被(挡|拦|封|阻)|挡住|拦住|封锁|封杀|屏蔽"
    r"|人机验证|验证码|滑块|challenge|cloudflare|反爬|anti-?bot"
    r"|(拿|抓|读|取)不到(正文|内容|数据|页面)?"
    r"|进不去|访问不了|打不开|读不了"
    r"|真(的)?(是)?边界|能力边界|做不到|无法(获取|访问|抓取)"
    r"|需要(你|人|用户)(去|来)?(登录|过|点|验证)"
    r"|403|429)", re.I)

# ② 本机反爬/取数工具的痕迹（出现任一即视为"用过工具"）
TOOL_TRACE = re.compile(
    r"(scrapling|StealthyFetcher|StealthySession|Camoufox|cloakbrowser|CloakBrowser"
    r"|browser-?act|stealth-?extract|anti-?scraping|browser-routing"
    r"|patchright|camoufox|opencli|web-access|x-tweet-fetcher"
    r"|solve_cloudflare|humanize\s*=|grab\s*\(|fetch\s*\(|curl_cffi"
    r"|jina\.ai|jn\.ai|r\.jina)", re.I)

# ③ 过去式 / 复述 / 立规矩 —— 不是"我现在放弃了"
PAST_CTX = re.compile(
    r"(上一轮|之前|昨天|历史上|曾经|原话|引述|复述|教训|lessons|形状 ?20"
    r"|这类结论|下次(要|再|该)|以后(要|再|该)|反向指纹|来历|案发"
    r"|我(今天|这轮|刚才|本轮)的?错|我犯的|我错在|认错|复盘|归因"
    r"|拿错(了)?(数字|对象)|误伤|误判|纸老虎|为何没拦|没拦住"
    # ⛔ 2026-09-12 新增：我在纠正自己的说法，而不是在"被挡就宣布放弃"
    #   特征：说了"实际上/其实/纠正/修正" + 描述了工具及其返回内容
    r"|实际上|其实(是)?|纠正了|修正了|重新试|重新用|又用了|补上了)")

GATE_SUBJECT = re.compile(
    r"(闸|gate|hook|superego|守卫|guard)[^。;;\n]{0,20}(拦|挡|阻|blocked|开火|误伤|误报|误判|搞错|弄反|搞反|判错|拦错)"
    r"|(拦|挡|阻|误伤|误报|误判|搞错|弄反|搞反|判错|拦错)[^。;;\n]{0,20}(闸|gate|hook|superego|守卫|guard)",
    re.I)

LOCAL_TARGET = re.compile(
    r"(obsidian|electron|客户端|桌面|窗口|白屏|渲染进程|vault|本地(程序|文件|库)"
    r"|进程崩|崩溃|闪退|加载不出|开不起来|启动失败"
    r"|\.exe|\.db|\.json|\.md\b|文件夹|目录)", re.I)


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not Path(tp).exists():
        _log("skip(no transcript)")
        return 0

    sys.path.insert(0, str(Path.home() / ".claude" / "hooks"))
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
        turn = msgs[start:] if start >= 0 else msgs
    except Exception:
        try:
            msgs = [json.loads(l) for l in open(tp, encoding="utf-8") if l.strip()]
        except Exception:
            return 0
        turn = msgs[-40:]

    used_tool = False
    tool_results = []  # 记工具名
    last_text = ""
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            last_text = content
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                last_text = c.get("text") or ""
            elif c.get("type") == "tool_use":
                blob = json.dumps(c.get("input") or {}, ensure_ascii=False)
                tool_name = c.get("name") or ""
                if TOOL_TRACE.search(blob) or TOOL_TRACE.search(tool_name):
                    used_tool = True
                    tool_results.append(tool_name)

    tail = last_text[-1800:]
    hit = BLOCKED_CLAIM.search(tail)
    if not hit:
        _log("pass(no blocked-claim)")
        return 0
    # 工具用了但结论仍有"拿不到"——这才是真正的危险信号
    if used_tool and hit and tool_results:
        _log(f"TOOL_USED_BUT_FAILED: tools={tool_results} claim={hit.group(0)}")
        # 只打日志不过拦——这说明工具返回了空内容，不是反爬闸该管的
        return 0

    if used_tool:
        _log("pass(tool used)")
        return 0
    if PAST_CTX.search(tail):
        _log("pass(past ctx)")
        return 0
    around = tail[max(0, hit.start() - 160): hit.end() + 160]
    if LOCAL_TARGET.search(around):
        _log("pass(local target, not a website)")
        return 0
    if GATE_SUBJECT.search(around):
        _log("pass(gate blocked me, not a website)")
        return 0

    msg = (
        "⛔ 反爬工具没用闸：你这轮说了【被挡/拿不到/是边界】(命中: "
        + (hit.group(0) or "")
        + ")，但整轮【没有任何一次反爬工具的痕迹】。\n"
        "⛔ 这个形状已复发 3 次以上（lessons 里「反爬」17 次；2026-08-08 Frank 原话\n"
        "   「我不是有很多反爬…尤其可以针对 cloudflare 的工具和 skill？没用？」；08-20 记过「12 天内复发」）。\n"
        "⛔ 2026-09-06 实录：我抓 Reddit 被挡，试完 r.jina.ai / playwright(headless 与非 headless) 就宣布「真边界」；\n"
        "   补齐 scrapling 依赖后，StealthyFetcher **一次就把全文含评论抓了下来**。不是边界，是我没用工具。\n"
        "现在按 ~/.claude/browser-routing.md 选一个再下结论：\n"
        "  · 反爬硬页面 / 无登录 / 一次性 → browser-act stealth-extract\n"
        "  · 要量 / 抗改版 / 代理轮换   → scrapling StealthyFetcher(py -3，solve_cloudflare=True)\n"
        "  · 要登录 ＋ 会弹滑块         → CloakBrowser 优先(pip 包，py -3)，opencli 作降级\n"
        "  · X/Twitter                  → x-tweet-fetcher(免登录免 key)\n"
        "⛔ 依赖缺了就补(curl_cffi / patchright / msgspec + `py -3 -m patchright install chromium`)，\n"
        "   『import 失败』不是『工具没有』。真试过全挂，再说边界并贴出每条通道的失败证据。"
    )
    _log("BLOCK: " + (hit.group(0) or ""))
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
