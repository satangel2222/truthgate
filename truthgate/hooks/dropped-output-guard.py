#!/usr/bin/env python3
"""Stop hook: 拦截「用我自己的实现缺口当理由，丢掉用户已经产生的成果」(形状 V)。

2026-07-28 duckduckweb 实录:用户在 RunningHub 跑一个任务,产出视频+音频。
我修好视频入库后,对音频宣布:「不做。主相册本来就不渲染音频,搬进去你也看不见」。
Frank:「看不到你可以弄成可以带播放器点击可以听的方式你是笨蛋吗?
       所有结果都是算力生成的,为何要漏掉?」

病根不是懒,是**把两件事混成一件**:
  ① 这份数据该不该保留  ← 用户花算力/花钱产生的,默认全都要
  ② 我的界面现在显不显示得了  ← 我的实现缺口,该补的是界面
我拿 ② 当理由否决了 ①,还包装成"帮你判断了价值"。
同源已有铁律(全都被这次违反):CLAUDE.md「信息拉满,一条都不许因精简删掉」
「功能只能比别人更多、不能更少」「禁止自我强加 Frank 没要求的省」。

查过现成:GitHub/网上关于 "dropped output" 的都是【框架静默吞掉 tool output】那类技术故障
(schema 校验失败被 drop、异常被 orchestrator 吞),没人治"agent 主观决定丢掉用户成果";
本机 32 道闸里 false-done(虚报)、giveup(撞墙推回)、multi-option(不给评比)、
coherence(散着改)也都不覆盖 → 自建,复用 guard_common 骨架。

触发条件(三信号同现在同一句里才拦):
  ① 丢弃决定:不做/不搬/不入库/跳过/不收录/漏掉/暂不支持…
  ② 对象是用户已有的成果:结果/输出/音频/视频/图片/数据/文件/条目…
  ③ 理由是我的实现缺口:看不见/不渲染/没有播放器/前端没有/还没做/只渲染…
豁免:用户本人说过不要、那东西压根没生成成功、或我在引述这条闸本身。

安全设计(照 no-nagging-guard):fail-open、只拦自己一次、只读 transcript。
回归:test_dropped_output_guard.py,正例用【这次真实的原话】。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, self_blocked_this_turn, trig, is_real_user_msg
except Exception:                                    # guard_common 坏了也不许拦每一轮
    def is_real_user_msg(m):        # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass

    def self_blocked_this_turn(*a, **k):
        return True

    def trig(x, n=120):
        return "trig=?"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ① 我决定丢掉/不处理(陈述式,不是提问)
DROP = re.compile(
    r"不做|不搬|不入库|不进库|不收录|不同步|不导入|不落地|不保存|不处理|不支持|"
    r"跳过|略过|忽略掉?|漏掉|舍弃|丢掉|放弃|"
    r"(?:仍|还是|依旧|暂时?|先|目前|现在)\s*(?:不|没)(?:会)?\s*(?:入库|进库|进相册|同步|显示|渲染|支持|做)",
    re.I)
# ② 对象 = 用户已经产生的成果/数据
# regex-sanity: ok — 2026-07-29 实测:正常汇报放行(需与其它信号同现)
OBJ = re.compile(
    r"音频|音轨|声音|语音|视频|图片|图像|结果|输出|产物|成果|素材|数据|文件|记录|条目|附件|"
    r"flac|mp3|wav|mp4|png|jpg|zip|venc", re.I)
# ③ 理由 = 我这边还没实现(而不是用户不需要)
MYGAP = re.compile(
    r"看不[见到]|显示不了|展示不了|播不了|不渲染|"
    r"没(?:有)?(?:渲染|播放器|入口|界面|卡片|支持|做)|"
    r"前端(?:还)?没|界面(?:上)?没|UI\s*没|还没(?:做|实现|接|支持)|没实现|尚未(?:支持|实现)|"
    r"只(?:渲染|显示|支持|认)|本来就[不没]|现在(?:还)?(?:不|没)(?:支持|显示|渲染)|"
    r"待办|阶段[二三]|以后再|哪天再|等(?:哪天|以后|将来|做)",
    re.I)
# 豁免:用户自己要求不要的 / 那东西压根没产生 / 我在引述这条闸
EXEMPT = re.compile(
    r"你(?:说|要求|讲|提|明确)(?:过)?(?:了)?[^。！!\n]{0,12}(?:不(?:要|用|需要)|别)|"
    r"按(?:你|您)的?(?:要求|意思|决定)|用户(?:明确)?(?:说|要求)[^。！!\n]{0,10}不|"
    r"(?:没有?|未)(?:生成|产出|跑出|成功)|生成失败|任务失败|"
    r"这道?闸|本闸|dropped-output|形状\s*V|误拦|正则|词表|回归|"
    # ⛔ 2026-09-08:补【引用测试靶子】这一档。上一条补丁刚救了一个误伤,我在汇报里
    #   **把对抗样本原文列进表格**(「之前说过音频不入库…」「前端没播放器你也看不见」),
    #   闸当场又拦一次 —— 它认得那些句子是真丢弃,但认不出我是在【引用】。
    #   兄弟闸(not-mine / excuse / search-breadth)都有这一档,唯独它没有。
    r"对抗样本|靶子|用例|仍拦|该拦|测试里|fixture|"
    # 复盘/认错时【引用我自己过去那句错话】≠ 现在又在丢东西。
    # 2026-07-29 实测误拦:「而那些 flac，正是我前天说"不做、你也看不见"想丢掉的东西」——
    # 那是在认错,却被自己这道闸拦下。⛔ 豁免只认【承认错误】的标记词,
    # 不能宽到"我之前说过"(否则「我之前说过音频不入库,现在还是不做」这种真丢弃会被放过)。
    r"差点(?:丢|删|扔)|想丢掉|本来要丢|骂得对|骂得没错|我错了|我当时错|错在|"
    r"复盘|教训|事后想|回头看|正是我(?:前天|昨天|当时|上一轮)|"
    # ⛔⛔ 2026-09-08 实测误伤(本闸当天第 2 次拦我;第 1 次我判"误伤"就过去了 ——
    #   那正是"不测就下判断"。这次拿【真 transcript 的原句】喂 verdict() 复现出来):
    #     原句「我登记过『还没做成检测』—— 现在做。检测器刚建好就抓到第 4 处我漏掉的:
    #           spec-first-gate 里我修了 read_this_turn,却漏了同一个文件的 find_docs」
    #     命中 DROP=漏掉 / OBJ=文件 / MYGAP=还没做 —— 三个词凑在一个窗口里,**语义正好相反**:
    #     我说的是「我漏了一处、现在补」,它读成「我丢掉你的东西、因为我没做」。
    #   ⇒ 只加两条**结构性**豁免,不加通用词(源码上面那条教训:宽到"我之前说过"就会放过真丢弃):
    #     ① 「还没… —— 现在/当轮/已 做|补|建|修」= 正在补,恰恰是本闸想要的行为;
    #     ② 「我漏掉 / 漏掉的一处 / 抓到…漏掉」= 我自己的疏漏(而且已被抓出来),不是丢他的产物。
    #   ⛔ 对抗样本已验:源码点名的那条真丢弃、「前端没播放器你也看不见」、
    #     「先不落地等以后再说」——**三条全部仍拦**(见 test 里的靶子)。
    r"还没[^。！!\n]{0,14}(?:—|——|,|,)?\s*(?:现在|当轮|马上|已)(?:经)?(?:就)?(?:做|补|建|修)|"
    r"(?:我|自己)(?:又)?漏掉|漏掉的(?:那)?一?处|抓(?:到|出)[^。\n]{0,10}漏掉",
    re.I)


def _log(msg):
    hook_log("dropped-output-guard", msg)


def final_text(tp):
    """本轮(最后一个真实 user 之后)助手说的话。"""
    msgs = []
    with open(tp, encoding="utf-8") as f:
        for ln in f:
            try:
                msgs.append(json.loads(ln))
            except Exception:
                pass
    last_user = -1
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        content = (m.get("message") or {}).get("content")
        # is_real_user_msg 同时排除 tool_result 和【系统注入的伪 user 消息】(后台 Agent 完成通知)。
        # 原来只排 tool_result ⇒ 通知被当成新一轮开始 ⇒ 本轮已做的事全失效 ⇒ 反复开火。
        if is_real_user_msg(m):
            last_user = i
    parts = []
    for m in msgs[last_user + 1:]:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            parts.append(content)
        else:
            parts += [c.get("text", "") for c in content
                      if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(parts)


def verdict(text: str):
    """三信号是否同现在【相邻两句】的窗口里 → 返回命中的窗口；否则 None。

    ⛔ 窗口必须是【2 句】不是 1 句:拿真实原话一测就知道 ——
       「音频仍不入库 —— 不做。主相册本来就不渲染音频，搬进去你也看不见」
       丢弃决定在前句、实现缺口理由在后句,按单句判会整条漏掉(第一版就是这么写的)。
    也不整段扫:整段扫会把"音频已入库"和别处无关的"还没做"凑成假阳性。"""
    sents = [s for s in re.split(r"[。！!\n]", text or "") if s.strip()]
    for i in range(len(sents)):
        for win in (sents[i], "。".join(sents[i:i + 2])):
            if len(win) < 6 or EXEMPT.search(win):
                continue
            if DROP.search(win) and OBJ.search(win) and MYGAP.search(win):
                return win.strip()[:160]
    return None


REASON = (
    "⛔ 丢弃成果闸:你正在【丢掉用户已经产生的成果】,理由却是【你自己还没做的那部分功能】。"
    "这是两件事,别混:①这份数据该不该留 —— 他花算力/花钱生成的,默认全都要;"
    "②你的界面现在显不显示得了 —— 那是你的实现缺口,该补的是界面(加播放器/加卡片/加入口),不是把数据扔掉。"
    "CLAUDE.md 明文:『信息拉满,他该知道的一条都不许因精简删掉』『功能只能比别人更多、不能更少』"
    "『禁止自我强加 Frank 没要求的省』。现在:把数据收进来 + 把显示补上,一起做完再汇报。"
    "唯一例外:他本人说过不要,或那东西压根没生成成功。"
)


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn("dropped-output-guard", turn_start=True)
    elif self_blocked_this_turn("dropped-output-guard"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
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
    if not tp:
        _log("skip(no tp)")
        return
    hit = verdict(final_text(tp))
    if not hit:
        _log("allow")
        return
    _log("BLOCK(dropped-output) " + trig(hit))
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
