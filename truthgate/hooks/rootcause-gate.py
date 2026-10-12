#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Stop 闸:【说"修好了"但没交代根因】→ 拦。治「头疼医头」。

⛔ 起因(2026-08-26 Frank 原话):
   「**防止头疼医头,彻底根治这个是我最在乎的铁律之一**,这个方法论尤其重要通用性最好的。
     我还怀疑你每次帮我找的工具**是不是只是给头疼药,而不是完整彻底方案优先**…
     **全局没有写吗?还是控制不住?还是 superego 没有这道 gate?**」

⛔ 当天实测他那三个猜测,答案是第三个:
   ① 全局【写了】—— CLAUDE.md 第 318 行「症状≠根因,问 why 到触底」、326 行「一个症状可叠多层根因」
   ② skill【有】—— `rootcause`(六问)、`postmortem-to-guard`,但**要我主动 invoke,而我当天一次没 invoke**
   ③ **自动闸:没有。** 84 道闸里没有一道叫 root/cause/symptom;
      grep 到的 8 处「根治」全是【注释里提到这个词】,不是判据。
   ⇒ 规则写了、工具有、**但没有任何东西逼我用** —— 和 `renhua` skill 那次一模一样。

⛔ 当天他亲自抓到的两次(都是"停在能跑了,不是不会再犯"):
   · 推荐 scrapling(本地·第二名)说「够用」⇒ 实测 firecrawl 快 3.3 倍、内容多 3.6 倍
   · 语义服务挂了,我**换个端口就说修好了** ⇒ 真根因是「服务用成功码报告失败 +
     看守分不清『还没起来』和『起不来』」—— 换端口治不了,下次换个端口再撞保留区一模一样

⛔ 判据(全中才拦,窄):
   ① 本轮真改了【代码/配置】(纯 .md/PROGRESS/lessons 不算)
   ② 本轮说了【修复类完成】(修好了/解决了/修复了/不会再…/搞定了)
   ③ 整轮**没有任何一处交代根因**(没出现 根因/病根/根本原因/root cause/为什么会发生/这次为什么不会再犯…)
   ⇒ 三条同时成立 = 我在报"能跑了",没报"不会再犯"。

⛔ 防死循环(Frank 同日亲口提醒「硬拦也有副作用,agent 完全什么都不做,或者 think loop」):
   照抄现成两条 —— `self_blocked_this_turn`(自己不连拦两次)+ MAX_BLOCKS(拦满就闭嘴)。
   **宁可漏拦,绝不锁死。**
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from guard_common import hook_log, self_blocked_this_turn, strip_doc, turn_start_index
except Exception:
    def hook_log(*a, **k):
        pass

    def self_blocked_this_turn(*a, **k):
        return True

    def strip_doc(t):
        return t or ""

    def turn_start_index(m):
        return -1

SELF = "rootcause-gate"
MAX_BLOCKS = 2          # 本闸每会话最多拦这么多次,之后闭嘴。宁可漏拦,绝不锁死。

# ① 改了代码/配置(纯文档不算 —— 写 lessons 不是修 bug)
CODE_EXT = re.compile(r"\.(py|js|cjs|mjs|ts|tsx|json|ya?ml|toml|ini|cfg|sh|ps1|bat|sql|env)\b", re.I)
# ② 修复类完成 claim(和 critic-gate 的 DONE 词表不同:那条管"交付",这条专管"修 bug")
FIXED = re.compile(
    r"修好了|已修好|修复了|已修复|解决了|已解决|搞定了|治好了|不再(会)?(出现|发生|复现)"
    r"|问题(已)?(排除|消失|没了)|根治了|已根治|fixed|resolved", re.I)
# ③ 有没有交代根因(任何一处都算 —— 判据要宽,免得逼我说套话)
ROOTCAUSE = re.compile(
    r"根因|病根|根本原因|真凶|root\s*cause|为什么会(发生|出现|这样)"
    r"|(这次|以后)?(为什么|凭什么)?不会再(犯|出现|发生|来)"
    r"|换个形式.{0,8}(还会|不会)|同形|一类|扫全身|修一处扫"
    r"|治标|头疼医头|绕过(而已|不是根治)|不是根治|只是绕过", re.I)


# ④ 2026-09-11 补的洞:「诚实交代」被当成放行证。
#   实录:我承认"这是一类、还剩 ~20 处",紧接着写「没顺手改」「下次用到它们时一起改」——
#   ROOTCAUSE 看到"一类"就放行。Frank:「有根源问题没有改,还要留下次?为何 superego 没拦你」。
#   ⇒ 本轮改了代码,又把已知残留【推到以后】,而【同一句里】给不出真约束(花钱/不可逆/要他本人/
#     凭证验证码/够不到)⇒ 拦。便宜的残留 = 当场修,不许拿"我说了"当交付。
DEFER = re.compile(
    r"下次(再|用到|一起)|以后再(改|修|弄|处理|说)|留(到|给)(下次|以后)|没顺手"
    r"|先不(改|修|动)(?!动)|暂(时)?不(改|修)|回头再(改|修)|有空再|坏着放"
    r"|等(下次|以后|用到).{0,8}(再|时)(改|修|一起)"
    # 外审补的同义说法:之后再/后续/留待/后面再/另开/暂缓
    r"|之后再(改|修|弄|处理|说)|后续(再)?(改|修|处理|清理)|留待|后面再|另开.{0,4}(任务|处理)|暂缓")
# ⛔ 外审高-3:原来含 token/手机/权限/物理/force/凭证/密钥 这类【单独出现就放行】的宽词,
#   「残留先不动,force 一下也行」「没顺手改,手机上也用不到」全被放过。只留带动作结构的真约束。
REAL_BLOCKER = re.compile(
    r"花钱|付费|扣费|不可逆|删数据|force\s*push|对外(发布|发)|只有你|你本人|要你(亲自|去|点|登)|需要你"
    r"|验证码|扫码|够不到|你拍板|你决定|你定", re.I)
# 描述正常行为 / 转述别人的话,不是我在推后
DESCRIPTIVE = re.compile(r"(会|能)自动|(他|她|用户|Frank)说")


# ⛔ 上线当轮就误伤我自己:「根源问题不该留到下次」是在【否定】推后,却被当成推后拦了。
NEGATED = re.compile(r"(不该|不应|不能|不许|不会|别)再?\s*(留|等|拖|推|下次|以后)|不会(炸|坏|出错|失效)")


def deferral(text):
    """返回【把残留推到以后、且同一句里没有真约束】的那一句,否则 None。"""
    # ⛔ 外审高-3:引用≠断言。strip_doc 已剥代码块/行内代码/表格/引用块,但剥不到中文引号 ——
    #   「」“” 里是在【转述原话】(汇报里常见"我上次写了「没顺手改」"),不是我在推后。
    t = re.sub(r"「[^」]*」|“[^”]*”", "", strip_doc(text))
    for sent in re.split(r"[。;；!！?？\n]", t):
        if (DEFER.search(sent) and not REAL_BLOCKER.search(sent)
                and not NEGATED.search(sent) and not DESCRIPTIVE.search(sent)):
            return sent.strip()
    return None


def turn_facts(msgs):
    """返回 (本轮改过代码吗, 本轮文本)。只看本轮。"""
    i = turn_start_index(msgs)
    turn = msgs[i + 1:] if i >= 0 else msgs
    touched, texts = False, []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        c = (m.get("message") or {}).get("content") or []
        if isinstance(c, str):
            texts.append(c)
            continue
        for x in c:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "text":
                texts.append(x.get("text") or "")
            elif x.get("type") == "tool_use":
                n = str(x.get("name") or "")
                blob = json.dumps(x.get("input") or {}, ensure_ascii=False)
                if n in ("Write", "Edit", "MultiEdit", "NotebookEdit") and CODE_EXT.search(blob):
                    touched = True
    return touched, "\n".join(texts)


def verdict(touched, text):
    """三条全中才拦。返回命中的那句话(拦)或 None(放行)。"""
    if not touched:
        return None
    d = deferral(text)
    if d:
        return "DEFER:" + d
    clean = strip_doc(text)          # 剥代码块/引用:在文档里【描述】这条规则不算我在犯
    m = FIXED.search(clean)
    if not m:
        return None
    if ROOTCAUSE.search(clean):      # 交代过根因/明说过是绕过 ⇒ 放行
        return None
    s = max(0, m.start() - 60)
    return clean[s:m.end() + 60]


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn(SELF, turn_start=True)
    elif self_blocked_this_turn(SELF):
        hook_log(SELF, "skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        return
    msgs = []
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)
    except Exception:
        try:
            for ln in open(tp, encoding="utf-8", errors="replace").read().splitlines():
                try:
                    msgs.append(json.loads(ln))
                except Exception:
                    continue
        except Exception:
            return
    touched, text = turn_facts(msgs)
    win = verdict(touched, text)
    if not win:
        hook_log(SELF, "allow(touched=%s)" % touched)
        return
    # 防锁死:本闸拦满 MAX_BLOCKS 次就彻底闭嘴
    sid = (os.environ.get("CLAUDE_CODE_SESSION_ID") or data.get("session_id") or "-")[:8]
    d = os.environ.get("SUPEREGO_LOG_DIR") or HERE
    cp = os.path.join(d, ".rootcause-count-%s" % sid)
    try:
        cnt = int(open(cp, encoding="utf-8").read().strip() or "0")
    except Exception:
        cnt = 0
    if cnt >= MAX_BLOCKS:
        hook_log(SELF, "allow(max-blocks-%d)" % MAX_BLOCKS)
        return
    try:
        with open(cp, "w") as f:
            f.write(str(cnt + 1))
    except Exception:
        pass
    # ⛔ 2026-09-07:触发词挪到第三个参数(拼进消息里记分板解析不到 ⇒ 记成"无证据")。
    hook_log(SELF, "BLOCK(fixed-without-rootcause)", win[:140])
    print(json.dumps({"decision": "block", "reason": (
        "⛔ 根治闸:你这轮改了代码并说了「修好了」,但**整轮没有一处交代根因**。\n"
        "   触发处:…%s…\n"
        "⛔ Frank 2026-08-26:「**防止头疼医头,彻底根治这个是我最在乎的铁律之一**」。\n"
        "   当天他亲自抓到我两次:①推荐本地第二名说「够用」(实测第一名快 3.3 倍) "
        "②语义服务挂了我**换个端口就说修好了**(真根因是「服务用成功码报告失败 + "
        "看守分不清『还没起来』和『起不来』」——换端口治不了它)。\n"
        "⇒ 收尾前答这两句(答完就放行,不用长篇):\n"
        "   ① **换个形式,它还会回来吗?** 会 = 你修的是症状,继续往下问 why。\n"
        "   ② **这是一个实例,还是一类?** 同一个形状,项目里还有几处没扫?\n"
        "⇒ 要走完整六问 → invoke skill `rootcause`。\n"
        "⇒ 若这次**确实只能绕过**(受限于外部/成本/不可逆),那就**明说「这是绕过不是根治」**"
        "并写清代价 —— 说了就放行。**诚实的绕过可以,假装根治不行。**"
    ) % win[:120].replace("\n", " ")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            hook_log(SELF, "error(fail-open):%s" % str(e)[:100])
        except Exception:
            pass
