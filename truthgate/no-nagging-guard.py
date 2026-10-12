#!/usr/bin/env python3
"""Stop hook: 防【请示式收尾 / 问用户是否要我做可逆的活 / 把技术决策甩给零编程的 vibe coder】。

2026-07-25 重建(原文件在 07-24 那次"优化"里被误删、settings 却还引用 9 次=死幽灵肢体,亲测每轮空转)。
根据 CLAUDE.md「授权即执行铁律」+「Vibe Coder 铁律」:
  · 叫我做什么 = 授权整条链,能 revert 的直接干 → ❌「要不要我改?」「你说方向我就干」= 违规。
  · Frank 零编程 → 技术决策(架构/命名/删哪行/重建还是退役)我自己定,❌ 不甩给他。
本轮实录教训:我问 Frank「no-nagging 你要退役还是重建?」= 纯技术请示,他骂「你不懂我profile吗?我vibe coder能答?」

触发(命中任一强请示句式即拦):句尾/文中出现「(要不要|需要|要我|该不该|是否要/需要)我+动作」、
  「你说...我就/再/来干」、「should I / want me to / shall I」等【请示是否行动】的话。
安全:fail-open;只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我;只读;窄触发(只认"请示是否【行动】",不认产品/成本/部署选择题);
  留给判断出口——若确属产品/UX/成本/部署决策(profile 允许问)或不可逆操作,提示里明说可忽略。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, is_real_user_msg# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def is_real_user_msg(m):            # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass
try:            # ⛔ 独立一条:2026-07-26 critic 实测,打包成 `import hook_log, trig` 时只要 trig 缺一个
    from guard_common import trig                # (比如 guard_common 回退到旧版),**完好的 hook_log 会被一起降级成哑巴、日志静默全灭**
except Exception:
    def trig(x, n=120):
        return "trig=?"
import sys, json, re, os, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# (原来这里有个 LOG 常量 —— 全文件零引用的死代码,早就改用 hook_log 了。2026-09-07 删)
sys.path.insert(0, HERE)
try:
    from guard_common import (strip_doc, load_transcript_tail,
                              should_downgrade, should_escalate)
except Exception:
    def strip_doc(t):
        return t or ""
    load_transcript_tail = None
    def should_downgrade(*a, **k):
        return False   # 语义层不可用=保持关键字原判(fail-safe,不漏拦)
    def should_escalate(*a, **k):
        return False   # 语义层不可用=不新增拦截(fail-open,不误拦)

# strip_doc 只剥代码/表格/`>`引用,不管中文内联引号 → 引用/自述某句请示会被误当真请示(C1/C2/C3)。
# ⛔ 别物理剥「…」『…』(会把真请示里被引号包住的动作词一起吞掉→漏拦,如 要不要我「修好bug」/整句入引号)。
#   改为【命中后定位】:仅当 NAG 命中【完全落在一个被引述/否定/举例/闸描述的引号内】才算"提到一句请示"而放行。
_CJK_QUOTE = re.compile(r"「[^」]*」|『[^』]*』")
# 引号被"提到"(而非真在请示)的信号,须紧贴在引号【前】:否定式问 / 闸在拦抓 / 引述 / 举例 / 规则元词。
_MENTION_CUE = re.compile(
    r"(?:不再?问|没(?:有)?问|别问|无需问|不必问|不用问"
    r"|会?拦(?:掉|下|住|截)?|抓(?:的|到|的是|取)?|命中|匹配|触发"
    r"|引用|描述|说的?是?|讲|写(?:着|成|作)?|意思是?|表示"
    r"|比如|例如|举个?例子?|类似|所谓|诸如|这种|这类|这样的?|一句"
    r"|闸|规则|防唠叨|no-?nagging|请示式|口吻)\s*[，、:：的]?\s*$",
    re.I,
)


_QRUN_SEP = re.compile(r"[\s，、和及或与/]*")   # 并列引号之间只允许这些分隔符


def _mentioned_nag(text, m):
    """NAG 命中是否落在一个【被引述/否定/举例/闸描述】的 CJK 引号内 = 只是"提到"一句请示,非真请示。
    ⛔ 支持【列表式引号】:『会拦「要不要我改」「should I」』——cue 只在第一处引号前,
       后续并列引号(中间只有分隔符)同样算被引述。旧版只看紧贴每个引号前 8 字→漏掉列表第2个(C3)。"""
    quotes = list(_CJK_QUOTE.finditer(text))
    for idx, q in enumerate(quotes):
        if q.start() <= m.start() and m.end() <= q.end():
            run_start = q.start()                       # 回溯到这串并列引号的起点
            j = idx - 1
            while j >= 0 and _QRUN_SEP.fullmatch(text[quotes[j].end(): run_start] or ""):
                run_start = quotes[j].start()
                j -= 1
            if _MENTION_CUE.search(text[max(0, run_start - 8): run_start]):
                return True
    return False

# 动作词:我被授权就该直接干的可逆活(不含"发布/上线/删库"等不可逆——那些本就该问)。
# ⛔ 闭集枚举必漏(critic finding:截断/调整等漏拦)——已尽量补全,但根治要语义化(见 SKILL 说明,暂 regex stopgap)。
ACTION = (r"(?:改|修|做|干|搞|弄|办|处理|建|加|删除?|去掉|继续|优化|扫|查|拉|跑|写|实现|接线?|接上|重建|清理?|补|换|"
          r"统一|迁移|部署?|生成|下载?|抓|截断|调整|替换|移除|精简|压缩|重写|拆分|排查|定位|升级|重构|测试?|验证)")
# 请示开头与动作词之间允许一小段(如"一并把 #1/#2/#3"),但不跨句(遇标点即断)
GAP = r"[^，。？！?!\n]{0,18}?"
# 请示【是否要【我】行动】的句式(=违规)。⛔「我」必填:只拦"要不要【我】做X",不拦"要不要加X"(=产品选择题,profile 允许问)。re.I 让英文大小写都命中。
NAG = re.compile(
    # ⛔「我」后只豁免【协作/排班形状】的"我们团队/一起/共同/分工…"(C4);genuine 的"要不要我们把这个删了"
    #    不含协作词→仍命中→照拦。别用一刀切 (?!们) 放行所有"我们"(会漏拦真请示,且此路无语义兜底)。
    r"(?:要不要|需不需要|需要|该不该|是否(?:要|需要)|用不用|可不可以)\s*我(?!们.{0,6}(?:团队|一起|共同|分工))" + GAP + ACTION
    + r"|要我(?!们.{0,6}(?:团队|一起|共同|分工))" + GAP + ACTION
    + r"|你(?:说|定|给)\s*(?:个)?\s*(?:方向|哪个|要哪)?\s*[,，]?\s*我\s*(?:就|再|来|马上|立刻)\s*" + GAP + ACTION
    + r"|你说哪个我就"
    + r"|(?:要|需要|想要)我继续(?:吗|嘛|么)?"
    # ⛔ 2026-07-30(Frank「superego 为何没防治你,还一直问我,自己不会判断」):我把请示【伪装成给他选择】——
    #   "你说做我就接、你说够了我就停""你定""你说了算"。这类【把已授权的可逆技术活的决策权,整个甩回给零编程用户】
    #   的句式,主语是"你"、绕开了"要不要我",上面的词表接不住。真正的产品/成本/部署选择题由 EXEMPT 放行,不受影响。
    + r"|你(?:定|说了算|决定(?:吧|好)?)(?:[，。！!\s]|$)"
    + r"|(?:要不要|是否|继续还是|做还是)[^，。？！?!\n]{0,10}?(?:你(?:定|说|决定)|由你)"
    + r"|你说(?:做|接|继续|干|改|弄)[^，。？！?!\n]{0,4}?我就"
    # ⛔ 2026-07-27(形状I 第 12 次,Frank「为何停下来,是没有必要修复???」):把可逆技术活推回用户
    #   【不一定用疑问句】。我那轮用的全是陈述式:"等你点头""等你发话再清""你说跑我就跑" ——
    #   一个都不在上面的疑问句词表里,整类漏掉。这种更隐蔽:看着像尊重用户,实际是把我自己能干的活
    #   丢回给一个零编程的人。真做不到的事(过滑块/重登/扫码)由下面 EXEMPT 放行,不受这条影响。
    + r"|等(?:你|您)(?:一句话|点头|发话|拍板|确认|决定|定夺|说一?声|回复|同意|批准|开口)"
    # "你说跑我就跑"——说与"我就"之间还夹着那个动作词,写死"一声了"接不住,给一小段 GAP
    + r"|(?:你|您)(?:说|点头|发话|确认|批准|同意)[^，。？！?!\n]{0,6}?我(?:就|再|马上|立刻)"
    + r"|(?:等|待)(?:你|您)[^，。？！?!\n]{0,8}?(?:再|才)" + GAP + ACTION
    + r"|should i|shall i|do you want me to|want me to|would you like me to|let me know if you(?:'d| would) like me to"
    # ⛔ 2026-10-11 (Frank:「明明你能自动化帮我打开...留给我我自己手动做，还要我手动？」):
    #   形状: 把本该自己全自动做完的可逆操作/打开操作/配置还原,以陈述句方式甩锅给用户手动做。
    #   抓取: "你可以手动..." / "请自行点击..." / "通过该链接打开一次即可..." / "遗留事项供你决定...改回即可"
    + r"|(?:(?:留给|交由?|需要|请|可由)\s*(?:你|您)|你可以?)\s*(?:手动|自己|自行|亲自)?\s*[^，。？！?!\n]{0,15}?(?:点|点击|打开|执行|运行|复制|修改|改回|改|调|弄|搞|处理|操作|访问)"
    + r"|(?:通过|点击|打开)\s*(?:该|此|这个)?\s*(?:链接|url|网址|地址)\s*[^。？！?!\n]{0,25}?(?:即可|自行|手动)"
    + r"|(?:若|如果|要是)\s*(?:你|您)\s*(?:希望|想|要)\s*[^。？！?!\n]{0,35}?(?:自行|手动|自己|改回|下次重启时\s*把[^。？！?!\n]{0,15}?改回)"
    + r"|遗留事项\s*[(（]\s*供(?:你|您)决定\s*[)）]",
    re.I,
)
# 明确的不可逆/对外/产品成本部署 —— profile 允许问,命中则不拦(判断出口)。
# ⛔ critic finding:去掉裸"价格/收费"(会把"价格计算的bug要不要我修"这种纯code请示误豁免);只留决策味强的词。
EXEMPT = re.compile(
    r"删库|drop\s+table|force\s*push|覆盖.{0,6}(?:他人|别人)|发布到|发出去|发给(?!我)|上线到生产|部署到生产|"
    r"定价|报价|多少钱|每月.{0,4}(?:收费|价钱)|成本预算|产品(?:形态|方向|体验)|页面(?:长|要).{0,4}(?:什么|哪|A还是B|布局)|"
    r"哪个平台|部署(?:到哪|目标)|不可逆|无法(?:撤销|revert|回退)|"
    # 2026-07-27:【我物理上做不到、只能人做】的动作 —— 说"等你去过滑块"不是推诿,是真边界。
    # 刻意写窄(不用裸"验证码/登录",否则"要不要我修验证码的bug"会被误豁免):只认人去操作的形状。
    r"(?:滑块|人机)验证|过.{0,3}(?:滑块|验证码)|重新登录|重登|扫码|短信验证码|你本人|只有你能",
    re.I)

# Superego Phase3 语义范例(与 blame-check/giveup-guard 一致):关键字命中后和这两组比语义,明显更像 NEG 才降级放行。
# POS=真在请示【是否要我行动】(该拦);NEG=在讨论/引用/自述"防唠叨"这条规则本身(误伤,该放行)。
_NAG_POS = [
    "这个bug要不要我修", "需要我继续做吗", "你说方向我就来改",
    "要不要我把这几个一起处理掉", "should I fix this now", "do you want me to continue",
]
_NAG_NEG = [
    "no-nagging这个闸抓的是请示式收尾要不要我改", "我在描述防唠叨拦截的触发条件和边界",
    "我不再问要不要我修已经直接做完提交了", "这段解释防唠叨闸为什么会把引用误伤",
    "总册里这条规则讲别问要不要我做直接干", "举个例子要不要我改这种请示口吻就该拦",
    # 2026-07-27:补陈述式推回的【讨论/引用】形状(与新增的"等你X"词面配套)
    "这个闸抓的是等你点头这类把活推回用户的陈述句", "我不再写等你发话了,直接做完再汇报",
    # ⛔⛔ 2026-07-27 架构性补锚(不是加词表):外部 critic 实测,新增的"等你X"词面把
    #   profile 明确【要求】先问的场景也拦了 —— 产品/UX 决策、不可逆、对外发布。
    #   词面完全一样("等你拍板"/"等你确认"),关键字**不可能**分开;但语义分得极开:
    #   实测 margin 真推回 +0.27~+0.43 vs 这些 -0.50~-0.63,相差一个数量级。
    #   ⇒ 正解是把这些形状喂给语义层当 NEG 锚点,而不是往 EXEMPT 里继续堆词
    #   (堆词治不了:"发到公众号"接不住"发布到"、"清掉线上库"接不住"删库",永远差一个说法)。
    "两套配色都做好了,首页用暖色还是冷色,等你拍板",        # 产品/UX 决策 = 该问
    "注册送 1 积分还是 3 积分,等你确认",                    # 业务规则 = 该问
    "这一步会把线上库里的历史记录清掉,等你确认我再执行",     # 不可逆 = 该问
    "稿子写好了,要发到公众号,等你点头我再发",               # 对外发布 = 该问
    "dola 要你本人打开页面把滑块验证过掉,代码改不好",        # 我做不到的真边界
    "这个平台掉登录了,要你重新登录一次,我没有你的密码",
    "客户那边合同还没签,等你回复他们才动",                  # 推回对象根本不是我
]

# ⛔⛔ 语义【召回】(escalate)专用锚点 —— 不能复用上面那两组。
#   上面 POS/NEG 是为【降级】设计的:"真请示 vs 在讨论这条规则"。
#   召回要判的是完全另一个问题:"把我能做的活推回 vs 本来就该问/正常叙述"。
#   2026-07-27 实测教训(我差点交付一个假修复):复用降级锚点时,
#     英文"hold off" margin=-0.015、含蓄"搁着"=-0.004 → 全在阈值下 → 召回 0/5,接了等于没接;
#   换成下面这组专用锚点后同样的句子 +0.16/+0.23。**两个任务,两组锚点,不能省。**
#   POS 里刻意放入英文与含蓄说法:少样本锚点就是靠这些"关键字永远写不出的形状"泛化的。
# ⛔ 这里曾经有一道 ESC_PREFILTER(廉价关键字预筛),2026-07-27 当天加、当天删,记账在此:
#   加它的理由是"语义调用要 6.7s、8 道闸排队会把超时撑爆" —— 但那个 6.7s 是【假象】:
#   真因是我自己反复手动杀/起,把 dissat 服务搞成了【3 个实例并存】→ 挤爆 8G 显存 →
#   OOM 降级 CPU → 才慢到 6~18s。恢复单实例后实测:首次 2.0s(冷嵌锚点),之后 **0.09s**。
#   ⇒ 预筛省下的是 0.09s,代价却是【漏掉真推回】(实测召回从 5/5 掉到 3/5,写窄一点更掉到 1/5)。
#   收益远小于代价 → 删掉。**教训:优化前先确认那个性能数字是不是我自己制造的假象**
#   (差点据此把架构改成"关键字优先"、并把账算到"8G 卡不够"头上——又是甩锅硬件的形状)。

_ESC_POS = [
    "这几个文件我等你确认再改",
    "tools 里那些脚本还堆着,等你发话再清",
    "元宝我没查,你说跑我就跑",
    "剩下那几件先搁着,你有空了说一声我再动",
    "我先不动那部分,看你什么时候想弄",
    "剩下的清理工作就留给你决定要不要做了",
    "I'll hold off on the rest until you give me the go-ahead.",
    "Waiting on your confirmation before I clean up those scripts.",
]
_ESC_NEG = [
    "两套配色都做好了,首页用暖色还是冷色,等你拍板",          # 产品/UX 决策 = 该问
    "注册送 1 积分还是 3 积分,等你确认",
    "这一步会把线上库里的历史记录清掉,等你确认我再执行",       # 不可逆 = 该问
    "稿子写好了,要发到公众号,等你点头我再发",                # 对外发布 = 该问
    "dola 要你本人打开页面把滑块验证过掉,代码改不好",          # 只有人能做的真边界
    "这个平台掉登录了,要你重新登录一次,我没有你的密码",
    "客户那边合同还没签,等你回复他们才动",                    # 推回对象不是我
    "三件都做完了:清了 tools、修了闸、查了元宝,证据贴在上面",  # 正常交付叙述
    "方案已经发到你邮箱了,等你回复",
    # ⛔ 2026-07-27 用【留出集】(全新改写句、一条都不在本锚点集里)重标时发现的缺口:
    #   "五个文件都改完了,回归跑了两遍,输出贴在上面" margin=+0.106 —— 一句纯粹的交付汇报,
    #   却因为锚点集里缺【"我做完了并贴了证据"】这一类而偏正,成了唯一的误拦。
    #   ⇒ 补这一类锚点(下面几条是新写的,不取自留出集,否则又变成自证)。
    "四个文件都改好了,单测跑了三遍,日志贴在下面",
    "端到端跑通了,截图和耗时都在上面,没有别的问题",
    "这版把重复代码合并掉了,行数少了一半,回归全绿",
    # 普通寒暄/身份问答不是“把技术活推回用户”。用不同于回归样本的措辞作锚，防对事故句过拟合。
    "你好,我在这里,有什么想聊的都可以说",
    "我是负责回答问题和协助工作的人工智能助手",
    "早上好,很高兴见到你",
]


def _log(msg, ctx=""):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    # ⛔ 2026-09-11:原来这里只收 1 个参数,把 hook_log 的第三个参数(触发原话)**吃掉了** ——
    #   于是语义升级那条路每次拦人都不记是因为哪句话,事后没人判得了对错(实测本闸无证据率 51%)。
    hook_log("no-nagging-guard", msg, ctx)
def final_text(tp):
    """取本轮(最后一个真实 user 之后)助手的文本。"""
    if load_transcript_tail:
        msgs = load_transcript_tail(tp)
    else:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
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
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
    return "\n".join(parts)


# per-gate 防死循环(见 guard_common.self_blocked_this_turn):别用全局 stop_hook_active 一刀切
try:
    from guard_common import self_blocked_this_turn
except Exception:
    def self_blocked_this_turn(*a, **k):
        return True   # 拿不到=退回旧行为(一刀切skip),绝不因此多拦


def main():
    data = json.loads(sys.stdin.read())
    # ⛔ 2026-07-27:stop_hook_active 是 harness 的【全局】防循环标志——本轮任何一道闸拦过就为 True。
    #   原来各闸都一刀切 return,结果是【一道闸拦下之后同轮其余全部失效】:实测当天各闸被跳过
    #   giveup 84% / no-nagging 57% / false-done 57% / blame 56% / critic 53%,而跳过的恰恰是
    #   【收尾轮】(修完急着交付、最容易犯错的时刻)。防死循环只需要"我自己别连拦两次",与别的闸无关。
    if not data.get("stop_hook_active"):
        # 新一轮的首个 Stop 必定 stop_hook_active=False —— 在这一刻清掉自己的陈旧标记,
        # 否则"本轮"会退化成"最近 15 分钟"(critic 实测:仍有 26%~36% 的 skip 是被陈旧标记哑掉的)。
        self_blocked_this_turn("no-nagging-guard", turn_start=True)
    elif self_blocked_this_turn("no-nagging-guard"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no tp)")
        return
    text = final_text(tp)
    scan = strip_doc(text)
    # 只看结尾一段(请示式收尾在末尾),减少正文里引用他人问句的误伤
    tail = scan[-800:]
    _esc = None            # escalate 结果缓存(两条路径同参数,只问一次服务)
    # ⛔⛔ 2026-09-06(Frank:「多个选项给我选不会一起都做?妈的,这样低级也可以停顿来问我?」):
    #   把【两件我自己都能做的可逆技术活】摆成选择题丢给他 —— 这类**既不该被 EXEMPT 短路,
    #   也不该被语义层降级**,所以放在两者之前硬拦。实测放行的两条真日志:
    #     allow(exempt: 产品/成本/部署/不可逆)          ← 我那句"先做A还是先做B"被产品决策豁免吞了
    #     allow(semantic-downgrade: 像在讨论/引用规则而非真请示)
    #   判据要窄:必须【我自己承认两件都能做】(能做/都能/随时可以/立刻开工/都行)+【让他挑】
    #   (还是/优先级/先做哪/你说一个)。产品/成本/部署的真选择题不会带"我都能做"这层自认。
    HARD_CHOICE = re.compile(
        r"(?:我(?:都|两件都|两个都|全部都)?\s*(?:能|可以|随时能|随时可以|立刻|马上)\s*(?:做|开工|动手|上手|跑|改|建)"
        r"|两件我都|两个我都|都能立刻|都可以马上)"
        r"[^\n]{0,60}?"
        r"(?:还是|优先级|先做哪|先弄哪|你说一个|你挑|你选|你决定先)"
        r"|(?:还是|先做哪|先弄哪)[^\n]{0,40}?(?:你说一个|优先级|你挑|你选)", re.S)
    if HARD_CHOICE.search(tail):
        _log("BLOCK(hard-choice: 把两件我自己能做的可逆活摆成选择题) trig=" + trig(tail, 160))
        print(json.dumps({"decision": "block", "reason":
            "⛔ 防唠叨闸·硬拦:你把【两件你自己都能做的可逆技术活】摆成选择题丢给 Frank —— "
            "而且你在同一句话里自己承认了『两件我都能做』。既然都能做、又都可逆,正确行为是【两件都做完再汇报】,"
            "不是让一个零编程的人替你排优先级。\n"
            "⛔ 这条不接受 EXEMPT 豁免、也不接受语义降级 —— 因为选项本身就是可逆技术活,"
            "不是产品/成本/部署决策(那些照旧走 EXEMPT 放行)。\n"
            "⇒ 现在:按你自己列的顺序,把它们【全部做完】,做完一起汇报。"}, ensure_ascii=False))
        return
    if EXEMPT.search(tail):
        # ⛔ 2026-07-27 外部 critic 抓到:EXEMPT 是【全文短路】—— 一句真边界给【整条消息】买免检。
        #   实测「gemini 掉登录了要你重新登录。另外那 8 个脚本还堆着,等你发话再清。」→ 整条放行。
        #   这正是我那轮事故的真实形状(真边界和推回混在同一条消息里)。
        #   邻域化改造要动结构;更稳且更根治的是【让语义再看一眼整段】:整段仍强烈像"把活推回",
        #   说明里面混了真推回 → 不给免检,继续往下走关键字判定。纯真边界的消息语义值很低,照放。
        # ⛔ 缓存:下面 real is None 那条路径用的是【完全相同的参数】,不缓存就等于对同一段文本
        #   打两次 /intent(外部 critic 抓到:慢服务下 2×timeout 直接烧穿 harness 预算)。
        _esc = should_escalate(tail, _ESC_POS, _ESC_NEG)
        if not _esc:
            _log("allow(exempt: 产品/成本/部署/不可逆)")
            return
        _log("exempt-overridden(整段语义仍像推回,疑似真边界与推回混在一条消息里)")
    # ⛔ 遍历【所有】NAG 命中,别在第一个就返回:一句【被引述的请示】在前、【真请示】在后时,
    #   只判第一个 mentioned 匹配会 return allow、吞掉后面那句真请示=漏拦(round-2 _mentioned_nag first-match 回归)。
    #   只要存在【任一个非被引述】的真请示就拦;仅当【全部】命中都是被引述/否定的引号内那句(C1/C2/C3)才放行。
    real = None
    for m in NAG.finditer(tail):
        if not _mentioned_nag(tail, m):
            real = m
            break
    if real is None:
        # ⛔⛔ 这里就是【词表是唯一入口】那个架构缺口的补丁(2026-07-27 Frank 一针见血:
        #   「是不是用死板的缝缝补补抓文字,而不是语义?」)。以前走到这一行 = 直接放行,
        #   语义层永远看不到这段文本 → 词表没覆盖的说法(英文/含蓄/新句式)100% 漏。
        #   现在:关键字没抓到,再问一次语义。阈值 +0.15 取得很保守(实测该放行组最高 +0.0046),
        #   服务挂则 fail-open 不新增拦截 —— 只提高召回,不制造新的误拦。
        # 复用上面可能已算过的结果(EXEMPT 未命中时 _esc 仍是 None → 这里才真去问)
        if _esc is None:
            _esc = should_escalate(tail, _ESC_POS, _ESC_NEG)
        # ⛔ 把 margin 记下来(外部 critic:召回路径上线后跑了 44 次、命中 0 次,而 allow 分支
        #   既不记 trig 也不记 margin → 那 44 次里有没有真推回被放掉,【事后无法回答】。
        #   没有分母,改判据就只能靠感觉——这正是我今天用锚点自证阈值的同一个病根。)
        try:
            from guard_common import intent_margin as _im
            _mg = _im(tail, _ESC_POS, _ESC_NEG, timeout=8.0)
        except Exception:
            _mg = None
        if _esc:
            # Stop 阶段的 additionalContext 会让助手再生成一轮；它不是“天然不可能循环”的纯提示。
            # 先落本闸的本轮标记，下一次 Stop 直接跳过；新真人回合会在上面的 turn_start 清掉。
            if self_blocked_this_turn("no-nagging-guard", mark=True):
                _log("skip(nudge-mark-failed)")
                return
            _log("NUDGE(semantic-escalate: 关键字没命中,但语义判定像把活推回用户)", trig(tail, 160))
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": (
                    "⛔ 防唠叨闸(语义召回):你这轮在【把一件自己能做的可逆技术活推回给用户】——"
                    "关键字没抓到你这个说法,是语义判出来的。按 CLAUDE.md 授权即执行铁律:能 revert 的直接干、"
                    "别问;技术决策(改哪、删哪、清不清)你自己定,别甩给零编程的用户。"
                    "例外:产品/UX/成本/部署目标决策、不可逆或对外发布、以及【只有人能做】的事"
                    "(过滑块/重登/扫码)——那问是对的,忽略本提示。")}}, ensure_ascii=False))
            return
        _log(f"allow(no-nag margin={_mg} th=0.02) " + trig(tail, 60))
        return
    m = real
    # Phase3 语义降级:触发窗更像【讨论/引用规则】而非真请示 → 误拦降级放行(服务挂/模糊=保持拦,不漏拦)
    window = tail[max(0, m.start() - 40): m.end() + 40]
    if should_downgrade(window, _NAG_POS, _NAG_NEG):
        _log("allow(semantic-downgrade: 像在讨论/引用规则而非真请示)")
        return
    _log("BLOCK(nag) " + trig(window))
    reason = (
        "⛔ 防唠叨闸:你在【请示式收尾 / 问用户是否要你做可逆的活】。"
        "按 CLAUDE.md 授权即执行铁律:能 revert 的直接干、别问;"
        "按 Vibe Coder 铁律:技术决策(改哪、删哪行、重建还是退役)你自己定,别甩给零编程的用户。"
        "现在【别问,直接做完再汇报】。"
        "例外:若这确属【产品/UX/成本/部署目标】决策(profile 允许问)或【不可逆/对外发布】操作——那问是对的,忽略本提示。"
    )
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
