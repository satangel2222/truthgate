#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UserPromptSubmit hook · Obsidian 知识库【自动联动】(2026-09-06)

Frank 的原话:「我发现好像靠语义是不是也太重了,其实还有更好的方法?
              **例如利用 obsidian 来当记忆库来自动联动?**」
⇒ 这个 hook 就是那个「自动」:他问问题时,自动从他 112,160 篇知识库里
   捞出最相关的几篇摆到我面前,不用我想起来去搜。

⛔ 为什么不是每轮都推(这条是设计核心,别删):
   superego-recall 召回的是【我该守哪条规则】—— 每轮都需要。
   这里召回的是【他攒的外部资料】(教程/方法论/别人的经验)——
   修 bug、改文件、跑测试时推给我全是噪音,而噪音会训练我对整个 banner 失明。
   ⇒ 双重过滤:①意图门只放行"求知类"提问 ②相似度低于阈值静默跳过。

⛔ 成本(实测,不是估的):复用已在跑的语义服务编码 1 句 1.28s
   + mmap 挂载 57 个分片 0.065s + 11 万条全量比对 0.104s ≈ 1.4s/次。
   **不新起服务、不重复加载模型** —— 那个服务 /embed 吐的就是 1024 维 Qwen3,
   和索引用的是同一个模型(2026-09-06 量过维度确认)。

安全:全程 fail-open(任何异常静默放行,绝不挡住他发消息);只注入路径+分数,不注入正文。
"""
import os
import re
import sys
import json
import glob
import urllib.request

sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude"))
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

IDX = os.path.join("E:" + os.sep, "osidian openclaw", ".vault-semantic")
VAULT = os.path.join("E:" + os.sep, "osidian openclaw", "openclaw")
THRESH = 0.55      # 低于这个 = 不够相关,静默跳过(实测 0.7+ 很准,0.5 以下开始是噪音)
TOPK = 3
MIN_LEN = 6
KB_OFF = os.environ.get("KB_OFF_FLAG") or os.path.join(os.path.expanduser("~"), ".claude", ".kb-off")  # 环境变量只给测试用

# ① 求知类信号 —— 只有问"怎么做/有什么/哪个好"这类,外部知识才帮得上
_SEEK = re.compile(
    r"怎么|如何|怎样|有什么|有没有|哪个|哪些|什么是|是什么|为什么|为何|"
    r"方法|办法|思路|策略|工具|方案|推荐|建议|经验|教程|案例|最佳实践|"
    r"能不能|可不可以|值不值|要不要|好不好|适合|选型|对比|区别|"
    r"how |what |which |why |best |recommend",
    re.I,
)
# ② 纯操作类 —— 这些是"动手干活",外部教程帮不上,推了只会吵
_OPERATE = re.compile(
    r"^(跑|运行|执行|重启|启动|停止|杀|删|删掉|改|修|提交|推送|部署|装|安装)一?下?|"
    r"跑(一下|一次)?测试|重启服务|git |npm |pip |pm2 |继续$|好了吗|跑完了没|还没好",
    re.I,
)
# ③ ⛔ 2026-09-09 补:【个人历史类】—— 问的是"你(Frank)以前说过/给过/做过什么",
#   答案只可能在 chat-archive(他跟 Claude 的真实对话记录)里,vault 是他收藏的【外部资料】
#   (教程/文章/推文),定义上就不可能装着"他自己对 AI 说过的话"。
#   实录:查"他有没有给过 TG 机器人密钥",_SEEK 命中"有没有"就推了 vault,
#   命中的三篇全是别人的推文/教程,Frank:「你是不是白痴,知识库怎么可能有我的东西,
#   不是在查真相才是正确的第一路径?chat archiver?」——他是对的,这类问题 vault 从设计上就答不了。
_PERSONAL_HISTORY = re.compile(
    r"(我|你)(以前|之前|曾经|上次|那时候)?(说过|给过|告诉过|提过|做过|发过|配过|连过)|"
    r"记不记得|还记得|是不是给过|有没有给过|有没有告诉过|有没有说过",
)


def pick(prompt):
    """决定要不要召回。抽成函数是为了能单独测 —— 判据不该埋在 IO 里。"""
    if len(prompt) < MIN_LEN:
        return False
    if _OPERATE.search(prompt):
        return False
    if _PERSONAL_HISTORY.search(prompt):
        return False
    return bool(_SEEK.search(prompt))


def search(q, np):
    """全量比对。mmap 打开,不把 438MB 读进内存。"""
    hits = []
    for shard in sorted(glob.glob(os.path.join(IDX, "emb_*.npy"))):
        names_p = shard.replace("emb_", "idx_").replace(".npy", ".json")
        if not os.path.exists(names_p):
            continue
        mat = np.load(shard, mmap_mode="r")
        with open(names_p, encoding="utf-8") as f:
            names = json.load(f)
        sims = np.asarray(mat) @ q
        for i in np.argsort(-sims)[:TOPK]:
            if float(sims[i]) >= THRESH and i < len(names):
                hits.append((float(sims[i]), names[i]))
    hits.sort(reverse=True)
    # 索引里可能有已被删掉的笔记 —— 给出去他点进去打不开,先滤掉
    return [(s, n) for s, n in hits if os.path.exists(os.path.join(VAULT, n))][:TOPK]


def semantic_hits(prompt):
    """大库(E:\\osidian openclaw\\openclaw，11 万篇)的语义召回 —— 原有逻辑。
    任何一步失败(服务不在线/索引缺失/维度对不上)都返回 [],而不是让整个钩子静默死掉:
    2026-10-06 实测它因语义服务 9/25 下线而【整个哑了】,连自己的端到端测试都红了。"""
    try:
        if not os.path.isdir(IDX):
            return []
        import numpy as np
        from superego_port import BASE as SEM
        body = json.dumps({"text": prompt[:800]}).encode()
        req = urllib.request.Request(SEM + "/embed", body, {"Content-Type": "application/json"})
        emb = json.loads(urllib.request.urlopen(req, timeout=8).read())["embedding"]
        q = np.array(emb, dtype="float32")
        if q.shape[0] != 1024:      # 哪天服务换了模型,维度对不上就当没有,绝不给错结果
            return []
        return search(q, np)
    except Exception:
        return []


# ── 小库关键词召回(2026-10-06):不依赖语义服务 ───────────────────────────────────
# 起因:Frank 9/05~9/06 要的是「用 obsidian 当记忆库自动联动,【替代】臃肿的语义服务但不降级」,
#   而本钩子原来仍靠语义服务 /embed 给问题编码;9/25 服务按他的下线令关了 ⇒ 联动整个哑掉。
#   另外 Obsidian 当前【打开】的是 E:\superego-vault(大库 11 万篇会让客户端崩),放进去给他看的笔记
#   (如游戏角色知识包)不在大库的语义索引里 ⇒ 要把这个库也纳入召回。
# 做法:对 Knowledge/ 与 Clippings/ 用「中文二字词 + 英文词」匹配,数对上几个不同的词,
#   标题命中加分;规模小(2026-10-06 实测 6 篇),每次现读现算,不到 0.01 秒,不建索引、不起服务。
LEX_VAULT = os.path.join("E:" + os.sep, "superego-vault")
LEX_ROOTS = [os.path.join(LEX_VAULT, d) for d in ("Knowledge", "Clippings")]
LEX_MIN_MATCH = 3      # 至少对上 3 个不同的词才算相关(实测:不相关的问题最多对上 1 个)
_STOPEN = set("the and for are was were what which why how who this that these those with from have has had "
              "not but you your can will would should could does did its into than then them they there here "
              "best way any all one out use get make about more most some just".split())
_STOPCH = set("的了是吗么什怎有没个这那我你他和与或在要可能会就都也还把被对让用做来去到给为吧呢啊好很更最请帮想说看问")


def _grams(text):
    g = set()
    for s in re.findall(r"[一-鿿]+|[A-Za-z][A-Za-z0-9._-]{2,}", text):
        if re.match(r"[A-Za-z]", s):
            if s.lower() not in _STOPEN:
                g.add(s.lower())
            continue
        for i in range(len(s) - 1):
            a, b = s[i], s[i + 1]
            if a not in _STOPCH and b not in _STOPCH:
                g.add(a + b)
    return g


def lexical_hits(prompt, topk=3):
    """返回 [(分数, 绝对路径)]。任何异常 ⇒ []。"""
    try:
        q = _grams(prompt)
        if len(q) < 3:
            return []
        docs = []
        for root in LEX_ROOTS:
            for r, _, fs in os.walk(root):
                for f in fs:
                    if not f.endswith(".md"):
                        continue
                    p = os.path.join(r, f)
                    try:
                        with open(p, encoding="utf-8", errors="ignore") as fh:
                            body = fh.read(8000)
                    except OSError:
                        continue
                    docs.append((p, f[:-3].lower(), (f[:-3] + "\n" + body).lower()))
        # ponytail: 只数"对上几个不同的词"(标题里的再加 2 分),不做稀有度加权 ——
        #   2026-10-06 实测库里可召回的只有 6 篇,稀有度加权分数全挤在 0~3、分不开。
        #   笔记涨到几百篇、开始乱中时,再换成 BM25 或接回语义索引。
        scored = []
        for p, title, text in docs:
            hit = sum(1 for g in q if g in text)
            if hit >= LEX_MIN_MATCH:
                scored.append((float(hit + 2 * sum(1 for g in q if g in title)), p))
        scored.sort(reverse=True)
        return scored[:topk]
    except Exception:
        return []


def lex_lines(hits):
    out = ["📚[你的 Obsidian 库·自动召回(关键词匹配,不靠语义服务)] E:\\superego-vault 里,这几篇和你的问题最相关"
           "(含你让我存的资料和我写的笔记;要用先读原文再判断):"]
    for s, p in hits:
        out.append("  · %.1f  %s" % (s, os.path.relpath(p, LEX_VAULT).replace("\\", "/")))
    return out


def main():
    try:
        raw = sys.stdin.read()
        prompt = (json.loads(raw).get("prompt") or "").strip() if raw.strip() else ""
    except Exception:
        return 0
    # 总开关(2026-10-06 Frank 要的「切断你和知识库的联系」):py -3.12 ~/.claude/bin/cut.py kb off|on
    if os.path.exists(KB_OFF):
        sys.stdout.write("⛔[知识库已被 Frank 切断] 这一轮不许查他的 Obsidian 知识库:不跑 brainq / "
                         "openclaw_query_router / vault_semantic,不读写 E:\\osidian openclaw 和 E:\\superego-vault。"
                         "恢复:py -3.12 ~/.claude/bin/cut.py kb on")
        return 0
    if not pick(prompt):
        return 0

    kept = semantic_hits(prompt)    # 大库语义召回:服务不在线 ⇒ [](不再让整个钩子哑掉)
    lex = lexical_hits(prompt)      # 小库(Obsidian 当前打开的库)关键词召回:不依赖任何服务
    if not kept and lex:            # 只有小库命中(语义服务下线时的常态)
        sys.stdout.write("\n".join(lex_lines(lex)))
        return 0
    if not kept:
        return 0

    lines = ["📚[外部资料库·自动召回] 你收藏的教程/文章/推文里,这几篇语义最近"
             "(⚠️这是别人写的参考资料,不是你自己说过的话/给过的东西——"
             "问『我以前说过/给过什么』该查 chat-archive,不是这个;要用先读原文再判断):"]
    for s, n in kept:
        lines.append("  · %.2f  %s" % (s, n))
    lines.append('  搜更多:py -3.12 "E:/osidian openclaw/scripts/vault_semantic.py" search "<问题>"')
    if lex:
        lines += [""] + lex_lines(lex)
    sys.stdout.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)      # fail-open:绝不因为这个 hook 挡住他发消息
