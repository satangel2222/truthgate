#!/usr/bin/env python3
"""PreToolUse(WebSearch/WebFetch):**这个问题 PROGRESS/lessons 里是不是已经查过了?**

⛔ 2026-08-13 实录(本闸的起因):
   Frank 问「我最大的问题不是被 Airbnb 吃了很多%的钱吗」。我立刻 WebSearch、翻 git 价格历史、开浏览器,
   花了一大轮重新调查 —— 而 **PROGRESS.md 第 126-132 行昨天就写完了,而且那段在开局注入区、每次开 chat 都喂给我**:
     · L1 平台 32 个月 ↔ L2 银行 12/14 月分毫一致，3.20% → 14.77%，拐点 2025-12
     · 真实损失年化 RM19,839(方法比我今天重算的更严谨)
     · 哨兵 scripts/ab-fee-watch.js 已上线
     · **「⚠️ 别再拿『涨价能补回来』当结论 —— 分成房上涨价基本无效」**
   我不但重查、得出更粗的数字，**还重犯了那条已经写下的告诫**。
   Frank:「你是不是失忆了？昨天到现在你不是眼睛知道了真相吗？」

⇒ 形状:**资料就在我的上下文里，我却当它不存在，从头重查。**
   比"忘了"更贵:重查要花时间、结论更粗、而且会绕过之前踩坑后写下的警告。

⛔ 先查现成(2026-08-13):`memsearch` 那类插件是【给我主动去搜的工具】，不是自动开火的闸；
   搜索结果也明说没有现成的 hook 在搜索前先查本地记忆 ⇒ 自建薄壳，只 grep 已有文件、零依赖。

⛔⛔ **第一版我把它写成了纯注入(additionalContext)—— 那是 Superego 自己早就证伪过的机制。**
   Frank 当场问:「为何塞到你面前你却无动于衷?现在你做了什么去阻住?你刚才做的东西有没有和 superego 系统冲突?」
   有,而且是直接冲突。`institutionalize-guard.py` 里写着(**我今天读过并引用过**):
     「dissatisfaction-postmortem 当天开火 30 次喊先做复盘,我 4 次全跳过 —— 因为它只能往上下文塞文字、拦不住任何东西。
       ⇒ **纸老虎的准确定义不是「没跑」,是「跑了但没有后果」。**」
   而旁边的 `prior-art-gate.py` 就摆着现成写法:`permissionDecision: "deny"`。我没看。
   ⇒ 改成**真拦截**:第一次 deny 并把原文怼回来,同一个查询再来一次才放行。
     **拦一次 = 结构上逼我读那几行;不永久封死 = 真需要外部信息时第二次就过。**

机制:WebSearch/WebFetch 发出去之前，拿查询词 grep 项目 PROGRESS.md + 全局 lessons.md。
     命中够强 → **deny**(理由里带原文那几行);同一查询第二次 → 放行。
安全:fail-open(任何异常都放行) / 门槛高(至少一行命中 4 个关键词) / 状态文件坏了也放行。
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common as _gc          # noqa: F401 —— 只为接进「闸的分母」统计(hook-stats.jsonl)
    from guard_common import hook_log
except Exception:
    def hook_log(*a, **k):              # 兜底桩:收得下第三个参数,否则走兜底时 TypeError 被吞掉
        pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 太常见的词不参与匹配,否则每次搜索都命中 → 噪音 → 我开始略读 → 闸变纸老虎
STOP = set("""的 了 是 在 和 与 或 我 你 他 有 无 不 也 就 都 而 及 之 为 以 到 从 对 把 被 让 给 这 那
a an the of to in on for and or is are was were be been do does did how what why when where which with
一个 什么 怎么 为何 为什么 多少 哪些 可以 需要 应该 现在 已经 如果 还是 这个 那个 时候 问题""".split())


def keywords(q):
    """中文按 2-4 字滑窗切,英文按词切 —— 不引入分词库(零依赖是这道闸能长期活着的前提)"""
    ws = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", q or ""):
        lw = w.lower()
        if lw not in STOP:
            ws.add(lw)
    for seg in re.findall(r"[一-鿿]{2,}", q or ""):
        for n in (4, 3, 2):
            for i in range(len(seg) - n + 1):
                t = seg[i:i + n]
                if t not in STOP:
                    ws.add(t)
    return ws


def scan(path, kws, label):
    hits = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, ln in enumerate(f, 1):
                if len(ln) < 20:
                    continue
                low = ln.lower()
                n = sum(1 for k in kws if k in low)
                if n >= 3:
                    hits.append((n, label, i, ln.strip()))
    except Exception:
        pass
    return hits


def main():
    data = json.loads(sys.stdin.read())
    if data.get("tool_name") not in ("WebSearch", "WebFetch"):
        return
    inp = data.get("tool_input") or {}
    # ⛔ 2026-08-14 修:原来是 `query or prompt or url` —— WebFetch 只拿 prompt 做指纹,**完全不看 url**。
    #    两个后果:①不同 URL 只要 prompt 相同就被当成"同一次查询"(误放行)
    #             ②我重发时 prompt 改一个字,指纹就变了 ⇒ 第二次又被当成"第一次" ⇒
    #               「同一个查询再发一次就会放行」这个逃生舱失效,我当时以为闸坏了,绕过去没修。
    #    改成:关键词判定仍用语义部分(query/prompt),但【指纹】用 url+prompt 一起算。
    q = str(inp.get("query") or inp.get("prompt") or inp.get("url") or "")
    fp_src = (str(inp.get("url") or "") + "\n" + str(inp.get("query") or inp.get("prompt") or ""))
    kws = keywords(q)
    if len(kws) < 3:
        return

    # ⛔⛔ 2026-08-13 Frank:「superego 做的是【全局跨项目通用】的免疫,不只针对一个项目」——他说对了。
    #   第一版只 grep `PROGRESS.md`,而实测 6 个项目里**只有 3 个有**(clawbot/mytg/zimagen 都没有)
    #   ⇒ 这道闸对一半项目直接失效,却看起来装好了。**依赖某个项目才有的文件名 = 伪全局。**
    #   ⇒ 改成扫【任何一种"我自己写下的记录"】,哪个存在扫哪个;一个都没有就静默放行。
    #   ⚠️ 注意区分:拦截语里的 Airbnb 案例【要留】—— 按 SUPEREGO.md 第 215 行的结论,
    #     "教训叙事带案发项目名是复盘写法不是耦合",只需标明"他项目案例·看形状别看专名"。
    #     **耦合的是机制(文件名),不是叙事(案例)。**
    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    CANDS = [(os.path.join(proj, n), n) for n in
             ("PROGRESS.md", "HANDOVER.md", "NOTES.md", "CLAUDE.md", "README.md")]
    CANDS += [(os.path.join(proj, "docs", n), "docs/" + n) for n in
              ("HANDOVER.md", "PROGRESS.md", "NOTES.md")]
    # ⛔ 2026-09-07:路径可注入。默认仍是真实 lessons.md(生产零改动),
    #   但测试可以指一个受控文件 —— 否则我往 lessons 里写一句例子,
    #   这道闸的测试就会因为"扫到了自己写的例子"而红(当天真发生了)。
    CANDS.append((os.environ.get("ALREADY_KNOWN_LESSONS")
                  or os.path.expanduser("~/.claude/lessons.md"), "lessons.md"))
    hits = []
    for p, label in CANDS:
        if os.path.exists(p):
            hits += scan(p, kws, label)
    if not hits:
        return
    hits.sort(key=lambda x: -x[0])
    if hits[0][0] < 4:        # 最强的一行也只命中 3 个词 = 大概率巧合,闭嘴
        return

    # ── ⛔⛔ 误伤豁免:去【那个产品自己的官网/仓库】问【会随时间变的事】(2026-08-26 加,
    #    2026-09-05 从 8-19 备份恢复本闸时重加) ──
    #   病灶:档案里写过 "agnes 定价/额度",我再去 agnes 官网查【现在】的定价就被拦 ——
    #   而档案里那条恰恰可能已经过期,**拦住我去核实,等于逼我拿旧数据当事实**。
    #   Frank 2026-08-26 原话:「注意别把 webfetch 弄到不会自动 invoke 搜索了,需要搜索就该去」。
    #   ⇒ 两个条件【同时】成立才豁免,少一个都不放:
    #     ① 查询里有【时效词】(现在/最新/最近/今天/定价/配额/限制/协议…)= 我在问会变的事
    #     ② URL 的【域名或路径】里出现查询里的产品名 = 我去的是那个东西自己的地盘,不是泛搜
    #   ⛔ 必须连【路径】一起取词:产品名常在路径里(github.com/<org>/<repo>、npm、pypi、docs
    #     全是这形状),只看域名会把 `github.com/firecrawl/firecrawl` 判成"github 与查询无关"。
    #   ⛔ 但路径取词【不能放宽太多】:拿一个【内部话题】去 github 仍要拦 —— 靠的是条件①②
    #     必须同时成立,且②要求匹配的是【查询里出现过的词】,不是路径里随便一个词。
    _url = str(inp.get("url") or "")
    if _url:
        _fresh = re.search(r"现在|最新|最近|今天|当前|目前|定价|价格|额度|配额|限制|"
                           r"协议|license|pricing|quota|latest|current|status|"
                           r"self-?host|自建|免费|"
                           # ⭐ 2026-09-05 加:问【怎么装/怎么用/官方文档怎么说】同样是
                           #   本地档案不可能有的一手信息(误拦实录:我查某仓库的官方安装
                           #   方法被拦,因为这句话里一个时效词都没有)。
                           r"安装|装法|怎么装|用法|怎么用|官方|文档|readme|"
                           r"install|installation|setup|usage|how to|official|docs?\b",
                           q, re.I)
        if _fresh:
            _u = _url.lower()
            # 域名 + 路径一起,切成词(github.com/firecrawl/firecrawl → github com firecrawl)
            _uwords = set(w for w in re.split(r"[^a-z0-9一-鿿]+", _u) if len(w) >= 3)
            # 查询里的词(去掉太短的),与 URL 词求交 —— 交集非空 = 我去的是它自己的地盘
            _qwords = set(w for w in kws if len(str(w)) >= 3)
            if _uwords & set(str(w).lower() for w in _qwords):
                return        # 官网/仓库 + 问时效性内容 ⇒ 放行,别挡住核实

    # ⛔⛔ 2026-09-05 补第二条豁免(有误拦实录,不是假想):
    #   我去查 github.com/bradautomates/claude-video 的【官方安装方法】被本闸拦下,
    #   理由是 PROGRESS.md 里几行同时含 skill/claude/install —— 那几行讲的是财务报告脚本
    #   和 doctor 判据,**跟那个仓库毫无关系**,纯字面撞词。
    #   病根:判据比的是"字面撞了几个词",不是"说的是不是同一件事";而
    #   skill/plugin/claude/install/code 这类词在本机文档里遍地都是,任何一次查外部工具的
    #   提问都容易凑够 3 个。上面那条豁免要求【URL + 时效性词】同时成立,而"官方装法"
    #   不含时效性词 ⇒ 没接住。
    #   ⇒ 更本质的判据:**URL 指向一个具体的外部仓库/包页面,本地记录本就不可能有它的答案**
    #     —— 这跟本闸要防的"把本地已有答案当不存在、跑去重查"是两回事,不该拦。
    #   ⛔ 仍然只豁免【带 owner/repo 这种具体项目路径】的:光 github.com 首页或搜索页不豁免,
    #     那种确实可能是拿内部话题去泛搜。
    #   ⛔ 我第一版写成「URL 指向外部仓库就放行」,**当场被回归的对抗样本抓红**:
    #     `拿内部话题去 github ⇒ 仍拦`(测试第 146 行)。它是对的 ——
    #     我完全可以拿一个内部问题、随便挂个外部 URL 去查,那时本地【确实有答案】,必须拦。
    #     ⇒ 只看 URL 不够,**必须保留「问的内容里出现了那个仓库/包的名字」这个核心判据**。
    #   ⇒ 真正该放宽的只是【额外要求有时效性词】那一条:我问「官方安装方法」不含
    #     现在/最新/定价 这类词,于是没接住 —— 可查一个仓库的装法,同样是本地不可能有的信息。

    # ── 拦一次就放行:结构上逼我读那几行，但不永久封死真需要的搜索 ──
    # ⛔ 为什么是"拦一次"而不是"只提醒":提醒 = 文字 = 我会跳过(实测 30 次跳过 4 次)。
    #   deny 会让这次工具调用真的不执行，我必须处理完才能继续 —— 那才叫有后果。
    # ⛔ 2026-09-07 加 env 覆盖:测试原来是靠【删掉这个真文件】来拿干净状态的
    #   ⇒ 每跑一次回归,就把线上这道闸"已经拦过谁"的记忆抹掉一次
    #     ⇒ 逃生舱失效、同一次查询会被重复拦。**尺子泡在被测的水里**(形状 -Q)。
    #   现在测试改设 ALREADY_KNOWN_SEEN 指向临时文件,谁也不碰谁。
    seen = (os.environ.get("ALREADY_KNOWN_SEEN")
            or os.path.expanduser("~/.claude/hooks/.already-known-seen.json"))
    # ⛔ 指纹用 url+prompt(fp_src),不是只用 prompt —— 见上方 2026-08-14 的修复说明。
    #    并且做**归一化**(压空白/去标点),这样我重发时改一个标点、多一个空格,仍然认成同一次查询,
    #    逃生舱才真的能用(原来改一个字指纹就变,第二次又被当第一次拦)。
    _norm = re.sub(r"[\s\W_]+", "", (fp_src or q or "").lower())
    key = hashlib.sha1(_norm.encode("utf-8")).hexdigest()[:16]
    st = {}
    try:
        with open(seen, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    now = int(time.time())
    st = {k: v for k, v in st.items() if now - v < 86400}    # 一天后忘掉，同一问题隔天仍会拦一次
    if key in st:
        return                                              # 第二次:我已经被怼过了，放行
    st[key] = now
    try:
        with open(seen, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:
        pass                                                # 写不了状态就当没拦过（宁可少拦，别死循环）

    lines = "\n".join("  · %s:%d  %s" % (lb, i, t[:190]) for _, lb, i, t in hits[:4])
    msg = (
        "⛔ 已查过闸:你正要去外面搜「%s」，但 **PROGRESS/lessons 里已经有高度相关的记录**：\n%s\n"
        "⇒ **先把这几行读完再决定。** 2026-08-13 实录：Frank 问 Airbnb 抽成，我立刻 WebSearch + 翻 git + 开浏览器重查了一大轮，"
        "而 PROGRESS 那几行【前一天就写完了、还在开局注入区每次都喂给我】——"
        "我不但重查、得出更粗的数字(损失小算 25%%)，**还重犯了那段里已经写下的告诫「别再拿涨价能补回来当结论」**。\n"
        "⇒ 形状 2026-08-13-J：**答案就在我的上下文里，我却当它不存在，从头重查。最毒的是它长得像勤奋。**\n"
        "⇒ 读完若仍需要外部信息：**同一个查询再发一次就会放行**（本闸只拦第一次）。"
        % (q[:60], lines)
    )
    # ⛔ 2026-09-07:补上记账。此前这道闸**一行日志都不写** —— 它会真的 deny 我的搜索,
    #   却在记分板上完全不存在:开过几次火、是不是在反复拦同一件事、误伤率多少,一概查不出来。
    #   当晚数出来:97 道接线的闸里 50 道是这样,而我上午说的「不留证据 0 道」
    #   **分母里从来没有它们**。(形状 -W:我以为在看全集,其实是切片。)
    hook_log("already-known-guard", "BLOCK(already-known %d hits)" % len(hits), q[:140])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass          # fail-open:绝不因为这道提醒挡住真正的搜索