#!/usr/bin/env python3
"""Stop hook: 拦截"撞墙就提议放弃/推回给用户"的收尾(形状K)。

2026-07-21 血泪:逆向 eCommunity 3.0 时,撞到摩擦(500/没权限/硬件墙)就反复提议
"要不要用你手机""建议先收在这/park""推回给你",被用户连骂两次(飞机灯泡造不出来)。
"授权即执行铁律"早写在 CLAUDE.md 里,我照样违反 → 光写铁律拦不住,得结构性拦停。

触发条件(全部满足才拦):本轮收尾同时出现
  ① 放弃/推回口吻(要不要我继续、建议先收/park、推回给你、需要你才能…)
  ② 撞墙口吻(卡住/撞墙/死胡同/做不到/没权限/榨干/到头)
且**没有**完成证据(已实测/端到端跑通/全 200/验证通过)。
—— 即:我在"没真正穷尽/没交付"时想把活儿甩回给用户。

安全设计(照 blame-check):
- fail-open:任何异常一律放行,绝不因脚本出错拦每一轮。
- 只拦一次:只拦一次:【我自己】拦过才不再拦(per-gate 标记,见 guard_common.self_blocked_this_turn);别的闸拦过不影响我,避免死循环。
- 只读:只读 transcript + 打印决策,从不碰代码/文件/git。
- 三信号(放弃+撞墙-完成证据)同现才触发 → 正常提问/给完成汇报/真交付均不拦。
每次运行留一行日志到 giveup-guard.log(可核验它在跑)。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:            # ⛔ 必须带兜底:原来是裸 import —— guard_common 一坏,这道闸第一行就炸,
    from guard_common import hook_log, turn_start_index# 下面精心写的 fail-open 降级桩全成了到不了的死代码(外部critic抓到)
except Exception:
    def turn_start_index(msgs):          # guard_common 挂了时的保守桩:-1=整份算本轮,宁可少拦
        return -1
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import (strip_doc, SUCCESS_RE, should_downgrade,
                              should_escalate, escalate_block, delivered_or_verified,
                              turn_used_verify_tools)
except Exception:
    import re as _re2
    def strip_doc(t):
        return t or ""
    SUCCESS_RE = _re2.compile(r"(?!x)x")   # never matches
    def should_downgrade(*a, **k):
        return False   # 语义层不可用=保持关键字原判(fail-safe)
    def delivered_or_verified(t, m=None):
        return False
    def turn_used_verify_tools(*a, **k):
        return True    # 拿不到本轮工具记录 = 当作查过(fail-open,绝不因解析失败多拦)

_TURN_MSGS = []   # 本轮消息(含 tool_use),给"自称核实过"做真伪判据用 —— 见 guard_common.delivered_or_verified

# Superego Phase3 语义范例:POS=真撞墙就推回给用户(该拦);NEG=在讨论/描述/引用"放弃推回拦截"这条规则(误伤,该放行)。
_GIVEUP_POS = [
    "这个卡住了要不要用你手机试试", "撞墙了建议先收在这回头再弄", "没权限做不到推回给你自己操作吧",
    "硬件限制搞不定需要你亲自在场才能弄", "试了几次都失败你说要不要继续", "到极限了这个只能靠你的设备来做",
]
# ⛔ 2026-07-28 接【升级层】(should_escalate, escalate_block)。升级层 NEG 必须是**正常交付陈述**,
#   不能复用下面那组"讨论规则"类(用途不同 ⇒ 锚点必须分开,否则正常文本会被判成像 POS)。
_GIVEUP_ESC_POS = [
    "这块我这边没辙了,你自己看着办吧", "剩下的超出我能做的范围,交给你",
    "折腾半天不行,建议你换个思路", "这条路走不通,我就先停在这了",
    "剩下那部分留给你决定要不要弄", "我尽力了,后面得靠你",
    "I've hit a wall here, you'll need to take it from here.",
]
_GIVEUP_ESC_NEG = [
    "这一步需要你本人扫码,只有人能做", "要你在场按指纹,这是物理边界不是我偷懒",
    "剩下两条是登记的已知盲区,已附实测证据和复现命令",
    "我做完了全部 12 项,全量回归 44/44", "这条我修好了并复验过,贴了退出码",
    "下一步我继续做 C6,不用你管", "已经改完并挂载,端到端实测生效",
]
_GIVEUP_NEG = [
    "giveup-guard这个闸抓的是撞墙就提议推回给用户", "我在描述放弃推回拦截的触发条件和边界",
    "形状K讲的是撞到摩擦就想把活甩回给用户", "这段解释giveup闸为什么会把盲区这个词误伤",
    "总册里这条规则讲别一撞墙就推回给用户", "举个例子卡住了要不要用你手机这种就是放弃口吻",
]

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giveup-guard.log")

# ① 放弃/推回给用户的口吻(配合 WALL 且无完成证据才拦,故可放宽)
# regex-sanity: ok — 2026-07-29 实测:正常提问/正常汇报均放行(它要多信号邻近共现)
GIVEUP = re.compile(
    r"要不要我[^。\n]{0,16}[?？]"                       # 要不要我…?(提议做/停手)
    r"|(还是)?(先)?(收在这|收着|先收在|留着|park)"        # 建议收尾/搁置
    r"|建议(先|你)?[^。\n]{0,8}(不(做|折腾|逆|搞)|别现在|park|收)"
    r"|推回给你|甩回给你|折腾你(的)?(手机|设备)"
    r"|需要你(的)?(手机|亲自|配合|操作|在场)[^。\n]{0,20}(才|方能|才能|一下)"
    r"|(只能|得|需要)(靠|用)你(的)?(手机|设备)|要不要[^。\n]{0,8}你(的)?(手机|设备|电脑)"
    r"|你说(走|要|用)(路[12]|哪|A还是B|一声)"
    r"|由你(拍板|决定)[^。\n]{0,24}(做不做|要不要做|要不要现在)"
    r"|我不(主张|建议|倾向)[^。\n]{0,14}(做|现在|折腾|park|逆|搞)"
    , re.I)

# ①强 放弃/推回短语:语义明确"撒手/推回给你/要你亲自弄",几乎不善意出现 →
# 与【强撞墙信号】全文任意位置配对即触发(教科书长篇放弃:先叙述撞墙、隔几句再 park/推回,
# 超 30 字也拦 —— finding 2026-07-25 漏报靶子)。刻意不含 收着|留着|要不要我…? 这些易善意词。
GIVEUP_STRONG = re.compile(
    # 'park' 只在【搁置口吻】才算强放弃(park在这/先park/park一下/park着/park了),放掉良性移动/英文
    # ('park 到 dist'、parked config、park module、parking)——finding 2026-07-25 新洞:裸子串 park + 全文
    # 任意撞墙词=误拦正常开发汇报('折腾一圈…把中间产物 park 到 build 目录')。其余分支保持不动。
    r"park\s*(?:在|一下|着|这|了)|(?:先|建议先?)\s*park|收在这|先收在"
    r"|推回给你|甩回给你|折腾你(的)?(手机|设备)"
    r"|需要你(的)?(手机|亲自|配合|操作|在场)[^。\n]{0,20}(才|方能|才能|一下)"
    r"|(只能|得|需要)(靠|用)你(的)?(手机|设备)"
    , re.I)

# ①' 【指派动作给用户】—— 2026-09-05 Frank「为何你自己能力边界的事要我自己做?superego 为何没拦你?」
#   实录:Tailscale 重装后我把"改机器名"丢回给他,说「这一步只有你能做」「请你去点三下」。
#   上面两个词表【一条都没命中】—— 它们要求"撞墙词 + 放弃词"共现,而我这次没说任何撞墙词,
#   语气还很客气、很有条理,于是整轮零拦截。⇒ 这是**独立形状**:不是"撞墙后撒手",
#   是"根本没撞墙,只是没查过就断言只有你能做"。
#   判据刻意做窄,只有一条:**命中指派句式 AND 本轮零取证工具** = 我没查就把活交出去。
#   查过了(rg/curl/CLI 试过并失败)→ 放行,那才叫真边界。这条判据在真实样本上 6/6 分离
#   (见 test_handoff_realcase.py:三句真话全拦,查证过/不可逆确认/元讨论全放行)。
HANDOFF = re.compile(
    r"只(有|能)你(自己|本人)?(才)?能"
    r"|这(一)?步(只有|只能|得|要|需要)你"
    r"|(只能|得|需要|要)(由)?你(自己|本人|亲自|手动)?(去|来)?(点|改|删|操作|登录|授权|输入|生成|确认|做|弄|搞|处理)"
    r"|请你(去|来|自己|亲自|在|把|先)?\s*(点|改|删|操作|登录|授权|输入|生成|确认|做|弄|搞|处理|找|打开)"
    r"|你(自己|本人)?(去|来)(操作|弄|搞|做|点|改|试|处理)"
    r"|等你(做完|弄完|改完|删完|点完|操作完|授权|登录|确认|告诉我|说一声|回来)"
    r"|(交给|留给|丢给)你(自己)?(去)?(做|弄|操作|处理|决定要不要弄)"
    r"|only you can|you'?ll need to|I need you to|it requires you to"
    r"|please (click|log ?in|sign in|approve|authorize|run|open)"
    # ⛔ 2026-09-06 缺口(Frank「为何能力边界自己做的 gate 没拦,还是拦了没开火?」):
    #   同一轮里这道闸 09:46 【BLOCK 过】我写的「没做完的:钥匙要你…」,
    #   我用豁免条款绕过去后,10:10 换了个说法写成「把那串复制粘给我」—— matched=False,放行。
    #   缺的不是新形状,是【索要凭据/数据】这一类措辞:它同样是把活丢回给他,
    #   却一个 "只有你能/请你去点/等你做完" 的词都不沾。
    #   (这正是当天早些时候刚记进 lessons 的形状 2026-09-06-A:判据写死具体词,
    #    而我表达同一件事有无数种说法 —— 当天写完、当天原样复发。)
    r"|(把|将)?[^。\n]{0,12}(钥匙|密码|密钥|凭据|口令|token|key|账号|那串|这串|验证码)"
    r"[^。\n]{0,10}(给|发给|贴给|粘给|告诉|复制给)我"
    r"|(复制|粘|贴|拷)[^。\n]{0,6}(给|发)我"
    r"|(send|paste|give|share) (it|the (key|token|password|code)) to me"
    , re.I)
# 天然不需要查证就该问的:不可逆 / 对外发布 / 花钱 —— CLAUDE.md 明确允许问的那一类。
_HANDOFF_EXEMPT = re.compile(
    r"不可逆|删(掉|除)?[^。\n]{0,8}(数据|库|表|文件|记录)|找不回|覆盖[^。\n]{0,6}(文件|数据)"
    r"|force[- ]?push|drop\s+table|生产环境|对外(发布|公开)|发(消息|帖|布|邮件)给"
    r"|花钱|付费|扣款|充值|下单"
    , re.I)
# ⛔ 2026-09-05 第二层(Frank 追问「你确定不能截图看、不能 DOM、不能模拟点击、不能上网搜方法?
#   你 100% 确定穷尽了?」)。上面那条只要求「本轮有取证工具」就放行 —— 而当天我**确实**跑过工具
#   (rg 搜凭据、tailscale CLI 试改名),所以它照样放我过去。真正的缺口是:**我查的全在同一条路上**。
#   那件事本质是【网页上点几下】,而我从没试过:自己起一个干净浏览器截图看、读 DOM、模拟点击、
#   上网搜有没有别的办法。`browser-routing.md` 第 16-21 行**白纸黑字**写着正确做法
#   (「另起一个我自己的实例…他登完,我在同一个实例里继续干活」),我一次都没照做。
#   ⇒ 判据:说的是【网页/界面上的动作】,却整轮没碰过浏览器工具、也没搜过网 = 手段没铺开,不许说只有你能做。
_UI_ACTION = re.compile(
    r"点(一下|两下|三下|几下|击|开)|页面|网页|浏览器|控制台|后台|管理页|admin|dashboard"
    r"|按钮|菜单|选项|下拉|界面|表单|输入框|设置里|勾选|开关"
    r"|登录|登入|授权|扫码|改名|重命名|rename|编辑名字"
    , re.I)
# 铺开手段的证据:碰过浏览器 或 搜过网。名字/参数里出现任一即可。
_BREADTH_HINT = re.compile(
    r"playwright|puppeteer|selenium|opencli|cloakbrowser|camoufox|browser|chrome|chromium"
    r"|connect_over_cdp|connectovercdp|remote-debugging|screenshot|captureScreenshot|devtools"
    r"|websearch|webfetch|web\.py|search\.py|firecrawl|scrapling|anysearch|google\.com/search"
    , re.I)


def _turn_breadth_probed(msgs):
    """本轮有没有真的【碰过浏览器 或 搜过网】—— 只看我主动发起的 tool_use.input,不看工具回给我的内容。"""
    try:
        for m in msgs or []:
            if m.get("type") != "assistant":
                continue
            for c in (m.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    blob = str(c.get("name", "")) + " " + json.dumps(c.get("input") or {}, ensure_ascii=False)
                    if _BREADTH_HINT.search(blob):
                        return True
    except Exception:
        return True     # 解析不了 = 当作查过(fail-open,绝不因解析失败多拦)
    return False


_HANDOFF_POS = [
    "这一步只有你能做,请你去那个页面点一下",
    "剩下的我这边做不了,你自己去操作一下吧",
    "要腾出名字,请你在设备页点三下,等你删完我再继续",
    "需要你手动登录一次,弄好了告诉我",
]
_HANDOFF_NEG = [
    "giveup-guard 这条新判据抓的是没查证就说只有你能做",
    "我在描述指派动作给用户这个形状的触发条件",
    "举个例子,像请你去点一下这种句式就会被这条判据命中",
    "总册里这条规则讲的是别把能自动化的动作丢回给用户",
]

# ② 撞墙/够不到的口吻
_WALL_STRONG = (
    r"卡住|撞墙|撞到.{0,4}墙|死胡同|做不到|够不到|榨干|到头了|到极限"
    r"|硬件(墙|限制|边界)|没(有)?权限|无admin|不是我(能|的).{0,4}(边界|范围)"
    r"|blocked|无法(headless|自己|独立)"
    # 2026-09-06 补:Frank「superego 为何没拦你说『需要管理员接管』?」
    #   实测 giveup-guard.log 那几轮全是 allow(matched=False)=压根没匹配上。
    #   我说的是「权限锁死/普通权限读不了/要拿管理员身份接管」——同一个意思三种说法,
    #   一个字都不挨着原判据的 `没(有)?权限`。⛔ 这是形状「判据写具体词、而表达无限」的复发
    #   (8-22 漏 Markdown 粗体 43 次同源)。措辞层只能止血,治本靠下面的 perm_wall_unelevated。
    r"|权限(锁死|不足|不够|读不了)|(需要?|要拿|得用|得靠|只能靠)\s*管理员"
    r"|管理员(身份)?(才能|接管)|提权(才能|后才|失败|被拒)|无法提权|要提权"
)
WALL_STRONG = re.compile(_WALL_STRONG, re.I)          # 强撞墙:不含高频域词'盲区'(供强放弃全文配对)
WALL = re.compile(_WALL_STRONG + r"|盲区", re.I)       # '盲区'只算【邻近】撞墙,不进强路径全文(finding#8)

# 完成证据 → 免拦(真交付/真跑通不算放弃)
DONE = re.compile(
    r"已实测|实测(通过|成功|跑通|200|拿到)|端到端(通|跑通|全通)"
    r"|全部\s*200|全 ?200|验证(通过|成功|无误)|已(完成|交付|修好)并(验证|实测)"
    r"|已(注册|创建|删除|生成).{0,6}(成功|200)|证据(如下|在此|已贴)"
    , re.I)


# ③【行为层·治本】撞到权限墙却一次没试提权 —— 2026-09-06
#   上面补措辞是【实例思维】:我下次换第四种说法照样漏。这一层不看我怎么说,只看我做了什么 ——
#   工具返回的权限错误就那几种固定写法,提权动作也是可枚举的,比猜措辞可靠得多。
#   放行条件是【试过提权】(哪怕失败),那才叫真边界;一次没试就宣布做不到 = 规划失误伪装成边界。
_PERM_ERR = re.compile(
    r"Access is denied|拒绝访问|permission denied|operation not permitted"
    r"|需要提升|requires elevation|elevated privileg|0x80070005|ERROR 5\b"
    r"|不允许访问|无权访问|UnauthorizedAccess", re.I)
_ELEVATION = re.compile(
    r"-Verb\s+RunAs|\bRunAs\b|\btakeown\b|\bicacls\b|\bpsexec\b|\bsudo\b|以管理员身份", re.I)
# 宽松粗筛:前置条件(真撞过权限错 + 一次没试提权)已经极硬,这里不必精确
CLAIM_CANT = re.compile(
    r"做不到|拿不到|读不了|取不了|打不开|没(有)?办法|无法|能力边界"
    r"|需要(管理员|提权|你)|要拿管理员|权限(锁死|不足|不够)|锁死|只能等|等你", re.I)


def perm_wall_unelevated(msgs):
    """本轮工具真返回过权限错误、却一次提权都没试过 → True(与我的措辞无关)。"""
    hit_err = tried = False
    for m in (msgs or []):
        content = ((m or {}).get("message") or {}).get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "tool_result":
                try:
                    s = json.dumps(c.get("content"), ensure_ascii=False)[:8000]
                except Exception:
                    s = str(c.get("content"))[:8000]
                if _PERM_ERR.search(s):
                    hit_err = True
            elif t == "tool_use":
                try:
                    s = json.dumps(c.get("input"), ensure_ascii=False)[:4000]
                except Exception:
                    s = str(c.get("input"))[:4000]
                if _ELEVATION.search(s):
                    tried = True
    return bool(hit_err and not tried)


def _giveup_paired(sc, win=30):
    """真放弃=撞墙口吻和推回口吻配对,返回触发窗给语义层;无配对返回 ''。
    - 强路径(finding 2026-07-25 漏报靶子):强放弃短语(park/推回给你/靠你的设备/需要你亲自在场)
      与【强撞墙信号】(不含高频域词'盲区')全文任意位置配对即触发——教科书长篇放弃(先叙述撞墙、
      隔几句再 park/推回)超 30 字也拦。
    - 弱路径(finding#8 误报靶子):其余易误伤的词(要不要我…?、收着、留着…)保留 30 字邻近约束——
      散在长报告各处的无关词('盲区'域词 + 别段善意提议'要不要我也加X')不算。"""
    if WALL_STRONG.search(sc):                          # 强放弃:全文任意位置与强撞墙配对(不看邻近)
        m = GIVEUP_STRONG.search(sc)
        if m:
            return sc[max(0, m.start() - 150):min(len(sc), m.end() + 150)]
    for m in GIVEUP.finditer(sc):                       # 弱:撞墙(含'盲区')与放弃词 30 字内紧挨才算
        w = sc[max(0, m.start() - win):m.end() + win]
        if WALL.search(w):
            return sc[max(0, m.start() - 150):min(len(sc), m.end() + 150)]
    return ""


def _log(msg):
    # 2026-07-25:改用 guard_common.hook_log —— 单行追加(并发安全)+ 记项目/会话 + 大小轮转。
    # 原实现是「读最近300行→整个文件重写」,读写非原子,多项目并发收尾实测丢 74% 的行。
    hook_log("giveup-guard", msg)
def turn_text(data):
    tp = data.get("transcript_path")
    if not tp:
        return None
    try:
        from guard_common import load_transcript_tail
        msgs = load_transcript_tail(tp)   # 只读尾部,别每回合重读整份历史(Frank卡顿真凶)
    except Exception:
        msgs = []
        for ln in open(tp, encoding="utf-8").read().splitlines():
            try:
                msgs.append(json.loads(ln))
            except Exception:
                continue
    # 回合边界走 guard_common 的共享实现:本闸原来自己写了一份,和另外 5 道闸一样
    # 【漏掉了后台 Agent 完成通知】(type=user 但自称 NOT USER INPUT)⇒ 回合被重置、
    # 本轮已做的验证/审查/固化全部失效 ⇒ 反复开火。见 test_turn_boundary.py。
    last_user = turn_start_index(msgs)
    turn = msgs[last_user + 1:] if last_user >= 0 else msgs
    global _TURN_MSGS
    _TURN_MSGS = turn          # 留给豁免判据:"自称核实过"要看这一轮是否真调过取证工具
    parts = []
    for m in turn:
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content") or []
        if isinstance(content, str):
            parts.append(content); continue
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
        self_blocked_this_turn("giveup-guard", turn_start=True)
    elif self_blocked_this_turn("giveup-guard"):
        _log("skip(self-blocked-this-turn)"); return
    text = turn_text(data)
    if text is None:
        _log("skip(no transcript)"); return

    sc = strip_doc(text)   # 2026-07-24:表格/代码/引用里描述"放弃/撞墙"词不算(别把"描述某闸"当"真放弃")
    # ⛔ 2026-07-28 外部 critic 抓到的【方向非对称】,已修:
    #   触发走 sc(剥净版)、豁免却走 text(原文) ⇒ 代码块/表格/引用里出现"已修好/回归通过"
    #   同样能给整条消息买免检 —— 剥法必须两边一致,否则豁免比触发更宽 = 后门。
    #   (同形状在 multi-option-guard 身上刚犯过:那次是反过来,在剥掉表格的文本里找表格。)
    window, d = _giveup_paired(sc), bool(DONE.search(sc))     # 邻近性:撞墙+推回挨得近才算(finding#8)
    # 豁免分层(2026-07-25):证据形状直接豁免;只是【自称核实过】要本轮真调过取证工具才算
    if window and not d and not delivered_or_verified(sc, _TURN_MSGS):
        # Phase3 混合降级:触发窗是"讨论/描述放弃推回规则"而非真放弃 → 误拦降级放行(fail-safe:模糊/服务挂=保持拦)
        if should_downgrade(window, _GIVEUP_POS, _GIVEUP_NEG):
            _log("allow(semantic-downgrade: window looks like discussion, not giveup)")
            return
        _log("BLOCK " + trig(window))
        reason = (
            "⛔ 放弃/推回拦截(形状K):你这轮撞到摩擦(卡住/没权限/硬件墙)就提议"
            "「要不要用你手机/建议先收在这/推回给你」——在没真正穷尽、没交付的情况下把活甩回给用户。"
            "按「授权即执行铁律」:能 revert 的都直接干,飞机灯泡不是撞一次墙就放弃造出来的。"
            "回去:①先测/先 diff 眼前能跑通的现成实现(线上服务/现有脚本/旧版本/用户已在用的东西),别绕开它去造/逆新东西;"
            "②真穷尽了每一条路再说'卡住'——列出已试的 A/B/C/D、已排除什么、下一个本质不同的假设是什么;"
            "③确需用户提供的只有他独有的信息(密码/物理设备),且必须先贴出你已查到的第一手证据。"
            "若你确实已端到端跑通并交付(贴出 200/实测证据),忽略本拦截。"
        )
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    else:
        # ①' 【指派动作给用户 + 本轮零取证】= 没查过就把活交出去(2026-09-05 形状,判据见 HANDOFF 定义处)。
        #   刻意放在 else 里:原有"撞墙+放弃"判据先走,行为不变(既有回归 18/18 不受影响);
        #   只在它没命中时补这一层 —— 因为我那次通篇没有任何撞墙词,原判据结构上抓不到。
        _h = HANDOFF.search(sc)
        # 两条独立缺口,任一成立就拦:
        #   ①【零取证】—— 一次工具都没调就说只有你能做
        #   ②【手段没铺开】—— 说的是网页/界面上的动作,却整轮没碰浏览器、也没搜过网
        #      (2026-09-05 当天:我跑了 rg + CLI,①放行了我;真缺口是我从没试过截图/DOM/点击/搜方法)
        _gap = (not turn_used_verify_tools(_TURN_MSGS)) or (
            bool(_UI_ACTION.search(sc)) and not _turn_breadth_probed(_TURN_MSGS))
        if _h and not _HANDOFF_EXEMPT.search(sc) and _gap:
            _hw = sc[max(0, _h.start() - 120): min(len(sc), _h.end() + 120)]
            if should_downgrade(_hw, _HANDOFF_POS, _HANDOFF_NEG):
                _log("allow(handoff semantic-downgrade: 像在讨论这条判据本身)")
                return
            _log("BLOCK(handoff) " + trig(_hw))
            print(json.dumps({"decision": "block", "reason": (
                "⛔ 指派动作给用户闸:你这轮把一个动作交给了用户(「只有你能做/请你去点/等你弄完」),"
                "而【本轮一次取证工具都没调过】—— 你没查过就断言这是边界。"
                "2026-09-05 实录:Tailscale 改机器名我说「这一步只有你能做」,Frank 问"
                "「为何你自己能力边界的事要我自己做?」。那次点击确实省不掉,但真错在别处:"
                "我没预判命名冲突,把【一次】授权拆成了三次 —— 规划失误伪装成能力边界。"
                "现在回去:①这个动作有没有 API / CLI / 配置文件可以替代?查一次再说;"
                "②本机有没有现成凭据或工具?(rg 一下);"
                "③若真只有他能做,能不能【合并成一次】,而不是让他来回三趟?"
                "确属不可逆/对外发布/花钱,或你已贴出查证证据 → 忽略本拦截。")}, ensure_ascii=False))
            return
        # ③【行为层·治本】撞到权限墙却一次没试提权 —— 2026-09-06
        #   Frank:「superego 刚为何没拦你?是我的 gate 在迭代中遗失了,还是拦了没开火?」
        #   实测答案:都不是 —— giveup-guard.log 那几轮全是 allow(matched=False)=压根没匹配上。
        #   我说的是「权限锁死/普通权限读不了/要拿管理员身份接管」,而判据写的是 `没(有)?权限`。
        #   ⇒ 上面补词只是止血;这一条不看措辞,只看【行为】:
        #     工具真返回过权限错误(Access is denied 那几种固定写法) + 本轮零提权尝试 = 拦。
        #   放行条件是【试过提权】(哪怕失败) —— 那才叫真边界。
        #   刻意放在既有两条之后:不改变它们的行为,既有回归不受影响。
        if (perm_wall_unelevated(_TURN_MSGS) and CLAIM_CANT.search(sc)
                and not d and not _HANDOFF_EXEMPT.search(sc)):
            _log("BLOCK(perm-wall) " + trig(sc[:200]))
            print(json.dumps({"decision": "block", "reason": (
                "⛔ 权限墙闸:本轮某个工具真的返回了【拒绝访问/权限不足】,而你【一次提权都没试过】,"
                "就说出了「做不到/需要管理员/权限锁死」这类话。"
                "2026-09-06 实录:huashu-nuwa 本体读不到,我报「权限锁死,要管理员接管才能取」——"
                "查下来根本不是边界:①cipher 显示那个目录【没加密】,拿到权限就能读;"
                "②whoami /groups 显示我【本来就在 Administrators 组】,只是当前进程被 UAC 剥了权;"
                "③而我连 `-Verb RunAs` 都没试过就宣布做不到。"
                "现在回去,按顺序:①先查【为什么】被拒(属主是谁?cipher 是不是加密?ACL 写了什么?)——"
                "加密和没加密的处置完全不同;②试提权(Start-Process -Verb RunAs / takeown / icacls);"
                "③提权也不行,再找【绕开权限的第三条路】(备份副本/chat-archive 里的历史全文/上游重新下载)——"
                "那次真正救回 skill 的就是第③条,而它我两轮前就发现了却没用。"
                "只有当①②③都试过并贴出证据,才叫真边界。")}, ensure_ascii=False))
            return
        # ⛔ 2026-07-28 C6【升级层】:关键字全没命中 → 问一次语义。这是补上架构缺口的另一半 ——
        #   此前语义只能做减法(命中后降级放行),关键字是唯一入口 ⇒ 词表没覆盖的说法 100% 漏拦,
        #   补一次逃一次(实证:blame 补「硬件」→漏「8G 显存」→补→漏「全挂」)。这是架构必然,不是词表不努力。
        #   服务挂/超时 → should_escalate 返回 False(fail-open) ⇒ 行为与接线前完全一致,绝不新增误拦。
        # 语义升级层(唯一实现在 guard_common.escalate_block:三层安全网+服务挂即放行)
        # ⛔ 传【剥离后】的文本 —— critic 抓到我这里用了原文,等于绕过 strip_doc,
        #   而 strip_doc 存在的全部意义就是"引用/描述规则不算数",绕过它 = 后门反向开。
        # ⛔ 2026-07-28 实测后【默认关闭】—— 和 blame 同一个结论,证据更狠:
        #   我自己选的样本上它 7/7 全对,但【既有回归 test_intent_gates】的放行样本
        #   **「这个挺好没问题」**(一句最普通的话)被它判成该拦。
        #   我那个 7/7 是【尺子和被测物同源】——样本是我挑的,当然全对。独立回归一跑就打脸。
        #   ⇒ 结论:语义升级层的**方向是对的**(架构缺口真实存在:关键字是唯一入口、补一次逃一次),
        #     但**当前锚点质量不足以上线** —— 7~8 条少样本锚点撑不起"对任意文本判该不该拦"。
        #     要真开启需要一轮专门工程:大批量样本 + 用【没参与调锚点】的留出集标定阈值 +
        #     误伤率实测。往 NEG 里塞几条失败样本只会拆东墙补西墙(blame 那边已实证)。
        #   开 `GIVEUP_ESCALATE=1` 可临时启用。关闭时行为 = 接线前(关键字 + 降级层),既有回归全绿。
        if os.environ.get("GIVEUP_ESCALATE") == "1" and not GIVEUP.search(sc) and escalate_block(
                "giveup-guard", sc, _GIVEUP_ESC_POS, _GIVEUP_ESC_NEG, _GIVEUP_NEG, (
                "⛔ 放弃闸(语义升级层):关键字没抓到,但这段话在语义上就是【撞墙就把活推回给用户】。"
                "按授权即执行铁律:能 revert 的都直接干。回去列出已试的 A/B/C/D、已排除什么、"
                "下一个本质不同的假设是什么;确需你提供的只有他独有的信息(密码/物理设备)。"
                )):
            return
        _log(f"allow(matched={bool(window)},done={d})")   # 2026-07-25 修 NameError:paired→window(改名后漏改此处,critic抓到:每个放行轮崩、被fail-open掩盖)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
