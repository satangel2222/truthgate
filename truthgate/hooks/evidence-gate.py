#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""证据闸 —— 我说「生成了/写了/保存到 某个文件」,就去查那个文件【真的在不在】。

⛔ 为什么要它(2026-07-29,Frank「复盘别人是怎么设计怎么做的才对」→ 深搜行业做法后落地):
   实测数据(tau2-bench,arXiv 2606.09863):**「假成功」占 LLM agent 全部失败的 44~52%**
   ——agent 自信地说"完成了",而系统状态根本不是那样。
   EviBound 框架(arXiv 2511.05524)的解法一句话:
     **Claims propagate only when backed by required artifacts** —— 产物真的在,那句话才算数。

   ⭐ 而本套 Superego 的 20 道闸里,**没有一道在验「我说的东西是否真的存在」** ——
   它们全在判【我说了什么文本】(你说了"修好了"吗 / 你是不是在甩锅),
   而文本判断正是行业实测假阳性 30~60% 的那一类(pattern-based guardrail)。
   ⇒ 这道闸走另一条路:**只看客观事实,零文本猜测,因此零假阳性**。
     文件在 = 放行;文件不在 = 我确实在虚报。

判据(全中才拦,窄触发):
  ①本轮我说了「生成/写入/保存/创建/导出/落盘 + 一个具体文件路径」
  ②那个路径【在磁盘上不存在】
  ③本轮也没有任何 Write/Edit 工具调用产出过它
  = 我在说一个不存在的产物 → 拦,让我要么真做出来,要么改口。

安全:fail-open(任何异常一律放行);只读判断;不碰用户文件;留日志。
⛔ 刻意不管的:①相对路径/裸文件名(歧义太大,宁可漏拦不误伤)
  ②"将会生成/打算写入"这类未来时 ③代码块/引用里的路径(那是在讲解不是在声称)
"""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, turn_start_index, strip_doc
except Exception:
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def turn_start_index(msgs):
        return -1

    def strip_doc(t):
        return t

import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 「我做出了一个产物」的说法 + 紧跟的绝对路径。只认绝对路径:相对路径歧义太大。
# ⛔⛔ 路径【必须允许空格】—— Frank 的项目路径长这样:`d:\airbnb ai manager\lib\x.js`。
#   第一版用 `[^\s…]+` 排除空格 ⇒ 在第一个空格就断掉 ⇒ 提出 `d:\airbnb` 没有扩展名 ⇒ 永不匹配
#   ⇒ **这道闸对他的真实路径完全失效**,而我的测试全是 `d:\zznotreal\x.md`(无空格)所以 10/10 绿。
#   这是同一天第 3 次栽在"路径带空格"(audit_false_blocks 栽过两次)。
#   ⇒ 改成:锚定到【已知扩展名】为止,中间允许空格和中文;用非贪婪防吃过头。
EXT = (r"md|txt|json|jsonl|csv|xlsx?|docx?|pdf|png|jpe?g|gif|webp|svg|html?|"
       r"js|mjs|cjs|ts|tsx|py|ps1|sh|sql|ya?ml|toml|ini|log|zip|srt|mp4|mp3")
CLAIM_RE = re.compile(
    r"(?:生成(?:了|好)?|写(?:入|好|了)|保存(?:到|好|了)|创建(?:了|好)?|导出(?:到|了)?|落盘(?:到|了)?|"
    r"输出(?:到|了)|已(?:写|存|建|生成)|wrote|created|saved|generated|exported)"
    r"[^\n。;；]{0,24}?"
    # 收尾判断要同时认【中英文标点】—— 第一版只认中文 `，`,英文 `,` 直接漏掉
    r"([A-Za-z]:[\\/][^\n`'\"，。;；)）\]】]*?\.(?:" + EXT + r"))(?=[\s,，。;；:：)）\]】、]|$)",
    re.I)
# 未来时/条件式 —— 不是声称已完成,放行
FUTURE_RE = re.compile(r"将会|准备|打算|计划|接下来|要不要|如果|会生成|应该会|待会|下一步")
MADE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write_to_file", "replace_file_content"}


def turn_text_and_files(turn):
    """本轮我说的话(剥掉代码块/引用) + 本轮真正写过的文件路径集合。"""
    texts, made = [], set()
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            texts.append(content)
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and isinstance(c.get("text"), str):
                texts.append(c["text"])
            elif c.get("type") == "tool_use":
                if str(c.get("name", "")) in MADE_TOOLS:
                    fp = (c.get("input") or {}).get("file_path") or (c.get("input") or {}).get("TargetFile") or ""
                    if fp:
                        made.add(_os.path.normpath(str(fp)).lower())
    return strip_doc("\n".join(texts)), made


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
        text, made = turn_text_and_files(turn)
        if not text:
            return 0

        missing = []
        for m in CLAIM_RE.finditer(text):
            # 该句里带未来时词 → 不是声称已完成
            seg = text[max(0, m.start() - 30):m.end() + 10]
            if FUTURE_RE.search(seg):
                continue
            path = m.group(1)
            if '://' in path or path.startswith('e:/') or path.startswith('file:/'):
                import re
                path = re.sub(r'^(?:file:/*|[a-z]:/+)', '', path, flags=re.I)
                if not _os.path.isabs(path):
                    # find C: in path
                    idx = path.find(':')
                    if idx > 0 and path[idx-1].isalpha():
                        path = path[idx-1:]
            norm = _os.path.normpath(path).lower()
            if norm in made:                      # 本轮真写过 → 就算此刻被删也算做过
                continue
            try:
                if _os.path.exists(path):
                    continue
            except Exception:
                continue                          # 路径畸形 → 放行,别误伤
            if path not in missing:
                missing.append(path)

        if not missing:
            return 0
        # ⛔ 2026-09-07:触发词挪到【第三个参数】—— 拼进消息里记分板解析不到,
        #   实测这道闸 113 次开火全被记成"无证据",误伤率算不出来。
        hook_log("evidence-gate", "BLOCK(claimed-artifact-missing)", " | ".join(missing[:3]))
        print(json.dumps({
            "decision": "block",
            "reason": (
                "⛔ 证据闸:你这轮说【生成/写入/保存了】下面这些文件,但它们**在磁盘上不存在**,"
                "本轮也没有任何 Write/Edit 产出过它们:\n"
                + "\n".join("   · " + p for p in missing[:5]) + "\n"
                "这正是行业实测占 LLM agent 失败 44~52% 的【假成功】:嘴上完成、状态没变。\n"
                "二选一:①**真的把它做出来**(调 Write / 跑那个会产出它的脚本)再收尾;"
                "②这句话说错了(路径写错 / 其实没做 / 是别人的文件)——改成实话再收尾。\n"
                "⛔ 别只改措辞绕过 —— 要么产物在,要么别声称。"
            ),
        }, ensure_ascii=False))
        return 0
    except Exception:
        return 0                                   # fail-open:绝不因为这道闸挡住你干活


if __name__ == "__main__":
    sys.exit(main())
