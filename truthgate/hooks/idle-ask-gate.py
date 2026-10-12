#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""空转请示闸 —— 我列出【我自己能做的活】然后问「要不要做」,而这一轮我【一个工具都没调】。

⛔ 病(Frank 2026-07-29 截图当场抓到,跨项目复发):
   另一个 chat 里我写:「剩下4个(日历/财务/快照/写回)**要不要现在接**?…你说够了我就停在订单这儿。」
   —— 活是我能做的、可逆的、他早就授权的方向,我却停下来问他。
   他的原话:「你看一直问我要不要继续做这种废话,而不开干要怎么彻底防治?」

⛔ 为什么已有的 no-nagging-guard 治不好(它拦了 213 次/7天,病照犯):
   它判【话像不像请示】—— 是**文本判断**。我把「要不要我做X?」改成「我建议做X」,
   措辞过关了,**手还是没动** ⇒ 拦了个寂寞。行业实测这类 pattern-based 判断假阳性 30~60%,
   而且**可以靠改措辞绕过 = 等于没有**。

⇒ 本闸换一条路:**触发看文本,判定看行为**。
   判据(全中才拦):
     ①本轮我的话里出现「要不要 / 需不需要 / 要我…吗 / 你说…我就 / 说一声我就 / 要做的话」
       这类【把动手的决定权交回去】的说法
     ②本轮**一个产出型工具都没调**(没有 Write/Edit,也没有真执行东西的 Bash)
       —— 纯说话 = 我在空转,不是在干活
   ⇒ 两条同时成立 = 我在拿"请示"代替"动手"。**改措辞绕不过去,因为第②条看的是有没有干活。**

   ⛔ 刻意不拦的:①本轮真干了活(哪怕也问了一句)—— 那是正常汇报
     ②问的是【只有人能做】的事(密码/扫码/手机/物理设备/花钱/对外发布)—— 那时该问
     ③纯查资料/纯问答(没提到"我能做的活")

安全:fail-open;只读;留日志。
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, strip_doc, trig
except Exception:
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def strip_doc(t):
        return t

    def trig(s, n=120):
        return str(s)[:n]

import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ① 把动手的决定权交回去的说法
ASK_RE = re.compile(
    r"要不要(?:我)?(?:现在|先|继续|接着|顺便)?[^\n。?？]{0,12}(?:做|接|改|修|建|加|跑|试|上|补|删|清)"
    r"|需不需要(?:我)?"
    r"|要我(?:现在|先|继续)?[^\n。?？]{0,10}(?:吗|么)[?？]"
    r"|你说(?:做|要|加|改|修)?[^\n。?？]{0,8}我(?:就|再|才)(?:做|干|加|改|修|上|接)"
    r"|说一声我(?:就|再)"
    r"|(?:要|想)(?:做|加|改|修|接)的话(?:就)?(?:说|告诉|吱)"
    r"|你(?:决定|拍板|说了算)(?:吧|吧。)?$"
    r"|等你(?:一句话|点头|确认)(?:再|才)"
    , re.M)
# ② 只有人能做的事 —— 这时候问是【对的】,不拦
HUMAN_ONLY = re.compile(
    r"密码|口令|验证码|扫码|扫一扫|二维码|手机|短信|指纹|人脸|滑块|人机验证"
    r"|你的账号|登录一下|物理|插上|插线|重启路由|花钱|付费|订阅|充值|买"
    r"|发布|上线到|发给客人|发到群|对外|公开|推送给", re.I)
# 产出型工具:调了 = 我真干活了
MADE = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_to_file", "replace_file_content"}
SHELL = {"Bash", "PowerShell", "run_command"}
# 真执行了东西的 shell(照 critic-gate 的思路:纯查询不算干活)
EXEC_BIN = {
    "python", "python3", "py", "node", "npm", "npx", "pytest", "cargo", "go", "make",
    "curl", "wget", "gh", "opencli", "docker", "pm2", "netstat", "taskkill", "schtasks",
    "ruff", "eslint", "tsc", "jest", "pip", "uv", "git", "powershell", "pwsh", "bash", "sh",
}
SEG = re.compile(r"\|\||&&|[|;\n]")


def did_work(turn):
    """本轮有没有「真的动手」。纯 ls/cat/grep 这类查询不算。"""
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in (m.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name = str(c.get("name", ""))
            if name in MADE:
                return True
            if name in SHELL:
                cmd = str((c.get("input") or {}).get("command") or (c.get("input") or {}).get("CommandLine") or "")
                for seg in SEG.split(cmd):
                    toks = seg.strip().split()
                    if toks and toks[0].lower().lstrip("./\\").split("\\")[-1].split("/")[-1] in EXEC_BIN:
                        return True
            elif name in ("Agent", "Task", "invoke_subagent"):
                return True          # 派了子任务 = 推进了
    return False


def my_text(turn):
    out = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            out.append(content)
        else:
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                    out.append(c["text"])
    return strip_doc("\n".join(out))


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        msgs = load_transcript_tail(data.get("transcript_path")) or []
        last = turn_start_index(msgs)
        turn = msgs[last + 1:] if last >= 0 else msgs
        text = my_text(turn)
        if not text:
            return 0
        m = ASK_RE.search(text)
        if not m:
            return 0
        # 问的是只有人能做的事 → 该问,放行
        seg = text[max(0, m.start() - 60):m.end() + 60]
        if HUMAN_ONLY.search(seg):
            return 0
        # ⭐ 决定性的一条:本轮真干活了 → 放行(哪怕也问了一句,那是正常汇报)
        if did_work(turn):
            return 0

        hook_log("idle-ask-gate", "BLOCK(ask-without-acting) " + trig(m.group(0), 60))
        print(json.dumps({
            "decision": "block",
            "reason": (
                "⛔ 空转请示闸:你这轮**一个工具都没调**(没写文件、没跑东西、没派任务),"
                "却在问 Frank「" + m.group(0)[:40] + "…」。\n"
                "他 2026-07-29 当场点破:「你看一直问我要不要继续做这种废话,而不开干」。\n"
                "⛔ 别靠改措辞过关 —— 本闸看的不是你怎么说,是**你这轮有没有动手**。\n"
                "二选一:①**现在就去做**(那些活是可逆的、他早授权的方向)再来汇报;"
                "②这活真的只有他能做(密码/扫码/手机/花钱/对外发布)——那就把【为什么只有他能做】写清楚。"
            ),
        }, ensure_ascii=False))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
