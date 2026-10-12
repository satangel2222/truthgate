#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""交付时用了【只有我懂的词】却没当场翻译 → 拦。

⛔ 为什么必须是机器闸(2026-08-19 Frank 亲口问出来的):
  他问「挂牌价口径是什么意思?我不是有去 AI 味的 skill,为何没有自动 Invoke?」
  —— skill **在**(`renhua`),它的 description 白纸黑字写着
  「ALSO use PROACTIVELY(不等他开口)whenever handing back a chunk of substantive work」,
  还写着「a report full of identifiers, metric names and flags reads to him as literally nothing」。
  **我一次都没主动触发过它。** 我查过 ~/.claude/hooks 下 60 个钩子,没有一个管这件事 ⇒
  这个 skill 是【纸老虎】:靠"我自己想起来",而我想不起来(lessons 形状 P)。
  实际后果:我把自己发明的词「挂牌价口径」印在给他看的页面上 **8 处**,他只能回头问我。

先查现成(2026-08-19 扫六个宇宙):①本机 60 个 hook 无一管措辞;②GitHub 话题页 prose-linter
  找到 sloptrim(★161)/vale-ai-tells(★70)/no-slop(★9) —— 但它们抓的是【写得像 AI】(文风),
  我的病是【用了只有我懂的自造词】,方向不同;③eReadable/Nexotext/SciSpace 是网页版 plain-English
  checker(要把文本发出去,且 Flesch-Kincaid 对中文无效);④⑤⑥无对口。⇒ **自建**。

判据(全中才拦,宁可少拦也别制造噪音):
  ① 本轮**真的交付了东西**(Write/Edit 落过文件,或生成过 .html/.png 给他看)
  ② 最后那段回复里出现【疑似只有我懂的词】
  ③ 那个词所在的**那句话里没有任何解释**(没括注/破折号/「就是」「=」)
  ④ 本轮没走过 renhua(没 invoke,回复里也没有四问结构)
⛔ 白名单:他自己天天说的词(房号/平台名/看板/对账/入住率…)不算术语。
"""
import json
import os
import re
import sys

HOOKS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOKS)


def _logfile():
    """日志写哪儿,问【唯一出处】`log_path()` —— 它同时决定目录(认 SUPEREGO_LOG_DIR)
    和 `.test.log` 分流。自己拼路径 = 把它的规则抄一份 ⇒ **测试跑出来的开火混进生产日志**,
    而这正是 `test_log_split` 那份回归要治的病(2026-09-07 一次扫出 6 处同病)。
    guard_common 真挂了才退回本目录 —— 这里是闸的落账,不能因为日志而 fail-close。"""
    try:
        from guard_common import log_path
        return log_path("jargon-gate")
    except Exception:
        return os.path.join(HOOKS, "jargon-gate.log")

# 他自己天天在用的词:不算术语
FRANK_WORDS = {
    "airbnb", "booking", "agoda", "whatsapp", "telegram", "wise", "maybank", "grace",
    "html", "png", "pdf", "json", "csv", "url", "wifi", "chrome",
    # ⛔ 2026-09-09 补:他自己天天说这些缩写,别拿新加的"全大写"规则去误伤
    "ai", "tg", "api", "cli", "ui", "ux", "sota", "cpu", "gpu", "ram", "ssd",
    "usb", "id", "ok", "md", "ip", "rss", "seo", "vpn", "sql", "http", "https",
}

# 每条 = (正则, 说法, 命中词的最小长度)
JARGON_PAT = [
    (r'[一-龥]{2,4}口径', "我自己造的口径名", 4),
    (r'\b[a-z]+[A-Z][A-Za-z]{2,}\b', "驼峰标识符", 4),
    (r'\b(?:pace|pickup|RevPAR|ADR|OTA|SLA|TTL|CDP|WMI|HWND|regex|payload|matcher|selftest)\b', "行话", 4),
    (r'\b[a-z][a-z0-9_]*_[a-z0-9_]+\b', "下划线标识符", 4),
    # ⛔⛔ 2026-09-09 Frank 亲口:「我还是看不懂你之前做了什么对我有什么帮助」。
    #   查下来这道闸【跑了、判 clean】—— 因为它靠一张【写死的词表】+【代码长相】认行话,
    #   而我那轮砸给他的是 `NUL` / `NTFS` / `CRT` / `IPC`:既不是驼峰也不是下划线,
    #   更不在那张表里 ⇒ **我新造的行话,写死的表永远追不上**。
    #   ⇒ 换成【形态规则】:整串大写的缩写,没当场解释就算行话。不靠表,所以追得上。
    #   ⛔ 长度必须放到 3:NUL/CDP/IPC/VSS 都是 3 个字母,原来 len>=4 的硬门槛
    #     会把它们【全部漏掉】—— 这是同一个 bug 的第二层,只改词表不改长度等于没改。
    (r'\b[A-Z]{2,6}\b', "整串大写的缩写(没当场翻成人话)", 3),
]

# 这句话里有没有解释:括注 / 破折号 / 就是 / 等于 / = / 意思是
EXPLAINED = re.compile(r'[(（][^)）]{4,}[)）]|——|—|就是|也就是|意思是|等于|换句话说|=\s*\S')
RENHUA_MARK = re.compile(r'我做了什么|前后有什么区别|对你有什么帮助|还有什么没做完|说人话')
MADE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
DELIVER_EXT = {".html", ".png", ".pdf"}


def _log(m):
    try:
        with open(_logfile(), "a", encoding="utf-8") as f:
            f.write(m + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp or not os.path.exists(tp):
        return 0
    try:
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        start = turn_start_index(msgs)
    except Exception:
        return 0                      # 公共工具挂了就放行,别把闸变成故障源
    turn = msgs[start + 1:] if start >= 0 else msgs
    if not turn:
        return 0

    delivered = False
    texts = []
    for m in turn:
        msg = m.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
            continue
        for c in (content or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
            elif c.get("type") == "tool_use":
                nm = str(c.get("name", ""))
                inp = c.get("input") or {}
                if nm == "Skill" and "renhua" in str(inp.get("skill", "")):
                    _log("skip(renhua invoked)")
                    return 0
                fp = str(inp.get("file_path", ""))
                if nm in MADE_TOOLS and fp:
                    delivered = True
                if os.path.splitext(fp)[1].lower() in DELIVER_EXT:
                    delivered = True

    if not delivered:
        _log("skip(no delivery)")
        return 0
    final = texts[-1] if texts else ""
    if not final.strip() or RENHUA_MARK.search(final):
        _log("skip(renhua structure or empty)")
        return 0

    bad = []
    for sent in re.split(r'[。\n]', final):
        s = sent.strip()
        if len(s) < 10 or EXPLAINED.search(s):
            continue
        for pat, why, minlen in JARGON_PAT:
            hits = [h for h in re.findall(pat, s)
                    if isinstance(h, str) and len(h) >= minlen and h.lower() not in FRANK_WORDS]
            if hits:
                bad.append((hits[0], why, s[:56]))
                break
        if len(bad) >= 3:
            break

    if not bad:
        _log("clean")
        return 0

    lines = "\n".join("  · 「%s」(%s) —— 出现在：%s…" % b for b in bad[:3])
    sys.stderr.write(
        "⛔ 人话闸：你这轮**交付了东西**，但给 Frank 的话里有【只有你懂的词，且没当场翻译】：\n"
        + lines + "\n"
        "⛔ 实录(2026-08-19，他亲口问出来的)：我把自己发明的『挂牌价口径』印在他要看的页面上 **8 处**，\n"
        "   他只能回头问我「这是什么意思」。而 `renhua` skill 的 description 明写\n"
        "   「**不等他开口**、交付实质工作时就该主动用」，我从没主动触发过 —— 因为**没有任何东西逼我**。\n"
        "⛔ 铁律是【照写+括注】，不是删掉：术语照写，紧跟一个括号说清 ①这词是什么 ②对他干嘛用/什么后果。\n"
        "现在把上面那几处改成人话再收尾；或者 invoke skill `renhua` 走四问格式。\n")
    _log("BLOCK " + " | ".join(b[0] for b in bad[:3]))
    return 2


if __name__ == "__main__":
    sys.exit(main())
