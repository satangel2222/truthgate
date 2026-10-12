#!/usr/bin/env python3
"""Stop hook: 拦截「产物生成了、我自己看了,却没送到 Frank 眼前」(形状 C 新变种)。

2026-07-29 manju 实录:装完 zy-cinematic-realism 后跑 A/B 出图验证,两张图我自己 Read 过、
看得很仔细,回复里写「图在 zy-cinematic-test/：A-skill.png、B-naive.png」就收尾了。
Frank:「**给我打开啊,不然我怎么看?噶你妈的**」

病根不是忘,是**规则字面没覆盖到**:CLAUDE.md 第105行红线只写了
「交付的 localhost/超链接一律 Start-Process(贴链接=没交付)」——
我生成的是本地 png/html **文件路径**,字面上既不是 localhost 也不是超链接,
于是我的大脑合法放行了。⇒ 光加一条警告没用,得让"只贴路径"这条路在结构上走不通。

查过现成(2026-07-29,别重复查):WebSearch 两轮(force open generated file deliver artifact /
agent hook show output file auto open viewer)→ 只找到 anthropics/claude-code#35893,
那是【尚未实现的 feature request】(提议 Claude 想给你看图时自动 open/xdg-open);
`gh search repos` 四轮零命中,阳性对照通过(同命令搜 "claude code hooks" 返回 3875★/3855★,
确认不是搜索坏了)⇒ 只能自建,复用本机 guard_common 骨架。

与既有闸的分工(查过,不重复造):
  · unread-evidence-guard  = 存了证据【我自己】没读(形状W)  ← 这次我读了
  · dropped-output-guard   = 我主观决定丢掉用户成果(形状V)  ← 这次我没丢
  · ui-edit-guard          = UI 文件被改要过设计规矩        ← 管长相,不管送达
  本闸 = 【我看到了,但他没看到】,交付停在我自己的眼睛里。

触发条件(两条同时成立):
  ① 本轮回复正文里,把一个用户可见产物当交付物报出来(png/jpg/gif/webp/svg/pdf/mp4/html
     + 路径形态:带 / 或 \\ 或 markdown 链接或行内码)
  ② 本轮工具调用里没有任何"打开"动作(Start-Process/Invoke-Item/ii/explorer/open/xdg-open)
豁免:用户本轮说了别开/只要路径;我在引述本闸。

安全设计(照 dropped-output-guard):fail-open、只拦自己一次、只读 transcript。
回归:test_show_open_guard.py,正例用【这次真实的原话】。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from guard_common import hook_log, load_transcript_tail, self_blocked_this_turn, trig, is_real_user_msg
except Exception:                                    # guard_common 坏了也不许拦每一轮
    def is_real_user_msg(m):        # guard_common 挂了时的保守桩:只排 tool_result
        c = (m.get('message') or {}).get('content')
        return m.get('type') == 'user' and not (isinstance(c, list) and any(
            isinstance(x, dict) and x.get('type') == 'tool_result' for x in c))
    def hook_log(*a, **k):
        pass

    def load_transcript_tail(*a, **k):
        return []

    def self_blocked_this_turn(*a, **k):
        return True

    def trig(x, n=120):
        return "trig=?"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_EXT = r"(?:png|jpe?g|gif|webp|svg|pdf|mp4|mov|html?)"
# 交付形态:markdown 链接、带分隔符的路径、或行内码包着的文件名
DELIVERED = re.compile(
    r"\[[^\]]*\]\([^)]*\.{e}[^)]*\)"
    r"|[\w一-鿿.\-]*[\\/][\w一-鿿.\- \\/]*\.{e}"
    r"|`[^`]*\.{e}`".format(e=_EXT),
    re.I)
# 打开【动作】(本轮工具调用里出现)—— ⛔ 注意:这只证明我【发出了】打开命令,不证明他【看到了】
# ⛔⛔ 2026-09-12:我第一轮用 Bash `Start-Process` 直接开，绕过 show.py → 它只记录了一次，但实际开了两个窗口。
#   根因：hook 只认 `Start-Process` 字面，没覆盖 PowerShell 的 `Start-Process`，Bash 更是直接裸开。
#   ⇒ 三种开口方式全要认:
OPENED = re.compile(
    r"Start-Process|Invoke-Item|\bii\s|\bexplorer\b|xdg-open"
    r"|\bopen\s+[-\w./\\\"']"
    r"|powershell.*Start-Process"          # PowerShell 的 Start-Process
    r"|powershell.*start\b"                # PowerShell start 命令
    r"|cmd.*start\b.*html"                 # cmd /c start *.html
    r"|start\s+\"\""                       # start "" 直接开
    r"|show(?:_on_desktop)?\.py",          # ⛔ 补: 支持 show.py 与 show_on_desktop.py 统一送达
    re.I | re.M)
# ⛔ 2026-08-17 补(第 9 次发作,前 8 次在 lessons.md):送达【证据】——
#    实录:我 Start-Process 打开 `data/付房东审核-2026-08.html`,命令返回成功,我就宣称「报告页在你屏幕上」。
#    Frank:「干你妈的为何我找不到有,你有打开给我看?」实测现场:**没有任何窗口标题含该报告**,
#    他屏幕上只有一个 `chrome about:blank` —— 路径含【中文+空格】,Chrome 拿到后解析失败开成空白页。
#    ⇒ 本闸原判据「工具入参里出现 Start-Process 字样」= 只看动作发出、不看结果成立,
#      和同日我在业务代码里修掉的那个 bug 是同一个形状(只读 missed 不读 ok)。
#    ⇒ 放行现在要求两样都有:打开动作 + 至少一次【看见它真的在】的验证。
VERIFIED = re.compile(
    r"MainWindowTitle"                       # 查窗口标题(最省:一条 Get-Process 就够)
    r"|GetForegroundWindow"
    r"|shot-window\.ps1|desktop-window-shot"  # 桌面窗口截图 skill
    r"|captureScreenshot|\.screenshot\("      # CDP / playwright 截图
    r"|webapp-testing",
    re.I)
USER_OPTOUT = re.compile(r"别开|不用开|不要打开|只(?:要|给)路径|别弹|不用弹", re.I)

# ⛔⛔ 2026-09-18 第四档:【一批没有扩展名的网页链接】——上面 DELIVERED 只认文件后缀,
#   而我那轮交付的是 20 条 `https://…/stay/<token>`(页面路由,**没有 .html**)⇒ 正则一条都不匹配
#   ⇒ 闸静默放行,我贴完 20 条就收尾。Frank 只能拿他熟悉的【旧入口】去验,看到的当然"什么都没变",
#   于是问「你到底改了什么?还是 mock 而已」。**这和 2026-07-29 那次是同一个病**:
#   规则字面没覆盖到我这次的载体形态(那次是本地文件路径,这次是无后缀 URL)。
#   判据收窄到"成批交付"才开火,避免误伤正常引用:
#     · 同一个域名在正文里出现 ≥3 条不同链接(参考资料极少这样)
#     · 且不是文档/代码站(github/docs/stackoverflow… 白名单)
URL_RE = re.compile(r"https?://([\w.\-]+)(/[^\s)\]\"'<>，。、]*)?", re.I)
URL_REF_HOSTS = re.compile(
    r"(?:^|\.)(?:github\.com|githubusercontent\.com|docs?\..+|stackoverflow\.com|wikipedia\.org"
    r"|npmjs\.com|pypi\.org|developer\..+|help\..+|support\..+|anthropic\.com|claude\.ai"
    r"|google\.com|youtube\.com|airbnb\.com|booking\.com|agoda\.com)$", re.I)
URL_BATCH_MIN = 3


def _url_batch(said):
    """正文里【成批给他、要他自己去点】的页面链接 ⇒ 返回 (域名, 条数);没有就 None。"""
    by_host = {}
    for m in URL_RE.finditer(said):
        host, path = m.group(1).lower(), (m.group(2) or "")
        if URL_REF_HOSTS.search(host) or host in ("localhost", "127.0.0.1"):
            continue
        if not path.strip("/"):                       # 光秃秃的首页,不算逐条交付物
            continue
        by_host.setdefault(host, set()).add(m.group(0))
    for host, links in by_host.items():
        if len(links) >= URL_BATCH_MIN:
            return host, len(links)
    return None

# ⛔⛔ 2026-09-08 Frank 原话:「每次都给我电脑里乱开一大堆 html,而不是复用,每次都要我去读了关闭…
#    只是少改几个 statement 有给我开一个新的 html,我觉得**这个 html 应该去掉,只是看这里就好了**」
#    ⇒ **这道闸自己在制造那个问题**:它只判"有没有打开",不判"这东西值不值得开一个窗口"。
#    形状 2026-08-18-D(每次开新窗口、从不复用)在 lessons 里已记 3 次,而闸一直在往反方向推我。
# ⇒ 分两类,别一刀切:
#    · **画面类**(png/jpg/gif/webp/svg/mp4/mov):文字替代不了 ⇒ 仍必须真打开。
#    · **文档类**(html/pdf):若我**已经在回复里把内容给出来了**(表格/清单/一串带单位的数字),
#      那就是他说的"看这里就好了" ⇒ 放行,别再开一个他还要去关的窗口。
PICTURE_EXT = re.compile(r"\.(png|jpe?g|gif|webp|svg|mp4|mov)\b", re.I)
CONTENT_IN_CHAT = re.compile(
    r"\|[^\n]*\|[^\n]*\n\s*\|?\s*[-: |]{5,}"                            # markdown 表格
    r"|(?:^|\n)\s*[-*•]\s+\S[\s\S]{0,400}?(?:\n\s*[-*•]\s+\S){2,}"      # ≥3 条清单
    r"|(?:\d[\d,.]*\s*(?:次|秒|条|个|%|道|分)[\s\S]{0,200}?){3,}",        # ≥3 处带单位的数字
    re.M)

REASON = (
    "⛔ 送达闸:你这轮产出了【Frank 能看的东西】(图片/网页/PDF/视频),"
    "却只在回复里贴了路径/文件名,没有真的打开给他看。\n"
    "他 2026-07-29 原话:「给我打开啊,不然我怎么看?」——**贴路径 = 没交付**,"
    "和 CLAUDE.md 第105行那条 localhost 红线是同一条,只是这次载体是本地文件。\n"
    "现在补上再收尾:\n"
    "  · 图片/PDF/视频 → `Start-Process \"<绝对路径>\"`(多张就拼一个并排 html 一次开)\n"
    "  · 网页/报告 → `Start-Process \"<html 绝对路径>\"` 开真实浏览器\n"
    "⛔ 别靠改措辞躲闸(把路径从正文删掉就放行)——那是把东西藏起来,不是送到他眼前。\n"
    "豁免:他本轮说过别开、或那只是中间产物(那就别在正文里当交付物报)。"
)

REASON_URL = (
    "⛔ 送达闸(第四档·成批链接):你这轮把一批【网页链接】当交付物给他了,"
    "却一条都没打开给他看。\n"
    "2026-09-18 实录(本档就是这次补的):我把 20 条客人专属入住链接列在回复里就收尾。"
    "他手上只有【旧入口】那个网址,于是他点了旧的、看到什么都没变,"
    "问「你到底改了什么?还是 mock 而已」——**新东西上线了,他却一眼都没看见**。\n"
    "⛔ 这和 2026-07-29「给我打开啊」是同一条红线,只是载体换成了没有 .html 后缀的页面路由,"
    "所以上面那几档的正则一条都没匹配上。\n"
    "现在补上再收尾:\n"
    "  · `py -3.12 ~/.claude/bin/show.py <其中一条代表性链接>`(复用同一个窗口,别开一堆)\n"
    "  · 同时在回复里说清【新入口 vs 他手上那个旧入口】的区别,否则他只会去点他熟悉的那个。\n"
    "豁免:他本轮说过别开;或这些链接只是引用资料、不是这轮的交付物。"
)

REASON_UNVERIFIED = (
    "⛔ 送达闸(第二级):你这轮【发出了打开命令】,但没有任何一次验证他真的看得到 ——\n"
    "**命令返回成功 ≠ 窗口出现了 ≠ 页面渲染出来了。**\n"
    "2026-08-17 实录(本闸就是这次补的):我 Start-Process 打开一个报告 html、命令返回成功,\n"
    "就宣称「报告页在你屏幕上」。Frank:「干你妈的为何我找不到有,你有打开给我看?」\n"
    "现场一查:**没有任何窗口标题含那个报告**,他屏幕上只有一个 `chrome about:blank` ——\n"
    "路径含【中文 + 空格】,Chrome 拿到后解析失败开成了空白页。\n"
    "这和「接口 200 就说服务健康」是同一个病:**只看了动作发出,没看结果成立**。\n"
    "现在补一条(任选其一,最省的是第一条)再收尾:\n"
    "  · 查窗口真的在:`Get-Process | Where-Object { $_.MainWindowTitle -like '*<标题关键词>*' }`\n"
    "  · 桌面窗口截图:`~/.claude/skills/desktop-window-shot/shot-window.ps1 -Match <标题> -Out x.png`,再 Read 那张图\n"
    "  · 网页/localhost:playwright/CDP 截图后 Read\n"
    "⛔ 顺带记死:**给他看的文件别用中文名/别放含空格的路径**,ASCII 文件名 + `file:///` URL 最稳。"
)


def _log(msg):
    hook_log("show-open-guard", msg)


def _turn(msgs):
    """切出本轮:最后一个真实 user(非 tool_result)之后的所有消息。"""
    last_user = -1
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        content = (m.get("message") or {}).get("content")
        # is_real_user_msg 同时排除 tool_result 和【系统注入的伪 user 消息】(后台 Agent 完成通知)。
        # 原来只排 tool_result ⇒ 通知被当成新一轮开始 ⇒ 本轮已做的事全失效 ⇒ 反复开火。
        if is_real_user_msg(m):
            last_user = i
    return msgs[last_user + 1:], (msgs[last_user] if last_user >= 0 else None)


def _text_of(m):
    content = (m.get("message") or {}).get("content") or []
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text")


def _tool_blob(turn_msgs):
    """本轮所有工具调用的入参拼成一坨,用来找打开动作。"""
    out = []
    for m in turn_msgs:
        content = (m.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                out.append(json.dumps(c.get("input") or {}, ensure_ascii=False))
    return "\n".join(out)



# ⛔ 2026-08-19 补的第三档:我打开给他的那份,可能是【已经过期的副本】。
#   实录:我把页面复制到 scratchpad 再打开(怕原路径带空格开不了 —— 这个顾虑当场实测是假的),
#   之后所有修改都落在原件上,副本再没同步。他看到的是 14:27 的旧版、5 处自造词;
#   我验收时截的是原件、0 处 ⇒ **我怎么验都对,他怎么看都是旧的**。
#   ⇒ 判据:本轮打开的文件,如果在别处存在【同名但更新】的文件 ⇒ 我多半开错了那一份。
STALE_SKEW = 5          # 秒:同一次复制产生的两份允许这点误差
SCAN_DIRS_MAX = 400     # 扫描上界,别把收尾拖慢


def _opened_paths(blob):
    """从本轮工具入参里把被打开的绝对路径抠出来。"""
    out = []
    for m in re.finditer(r'[A-Za-z]:[\\/][^"\'<>|*?\n]+?\.(?:html?|png|jpe?g|gif|webp|pdf|mp4)', blob):
        q = m.group(0).replace('\\\\', '\\')
        if os.path.exists(q):
            out.append(os.path.abspath(q))
    return list(dict.fromkeys(out))


_WALK_CACHE = {}
_SKIP_DIRS = ("node_modules", ".git", "__pycache__", ".venv", "venv", "tasks")


def _walk_names(root, budget):
    """root 下(最多 budget 个目录,顺序同 os.walk 自顶向下)每个文件名 -> 所在目录列表;同一个根只扫一次。
    2026-10-03 提速:原来每个被打开的文件都对同样的根 os.walk 一遍,os.walk 每个子目录还要 islink 一次
    (Windows 上一次系统调用)⇒ 一轮开 10 个文件 = 11.6 万次 islink、10.9 秒,远超 AG 收尾 4.5 秒时限,
    这道闸在 AG 端从来没跑完过。改用 scandir(是不是目录随目录项带回)+ 按根缓存,扫的范围和顺序不变。"""
    key = (os.path.normcase(os.path.abspath(root)), budget)
    if key in _WALK_CACHE:
        return _WALK_CACHE[key]
    idx, stack = {}, [root]
    while stack:
        d = stack.pop()
        budget -= 1
        if budget <= 0:
            break                                     # 这个根扫不完就换下一个,别整个放弃
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        subs = []
        for e in entries:
            try:
                if e.is_dir():                        # 同 os.walk:指向目录的链接算目录,但不往里走
                    if e.name not in _SKIP_DIRS and not e.is_symlink():
                        subs.append(e.path)
                else:
                    idx.setdefault(e.name, []).append(d)
            except OSError:
                continue
        stack.extend(reversed(subs))
    _WALK_CACHE[key] = idx
    return idx


def _newer_twin(path):
    """在常见的兄弟目录里找【同名但更新】的那一份;找到就说明我开的是过期副本。"""
    base = os.path.basename(path)
    try:
        mine = os.path.getmtime(path)
    except OSError:
        return None
    # ⛔ 2026-08-19 当场修的 bug:第一版用 `set` 装要扫的根目录 —— **集合遍历顺序是随机的**,
    #   如果先扫到项目大目录、把全局预算烧光,就 `return None` **静默不报**。
    #   表现:同一份代码同一个测试,一会儿 6/6 一会儿红 2 条。**这正是"闸静默失效"那一族** ——
    #   闸不报不代表没事,可能只是它没扫到。⇒ 改成:①有序列表(不是集合)②预算按【每个根】算,
    #   一个大目录烧不掉别人的份 ③先扫离被打开文件最近的地方。
    d = os.path.dirname(path)
    roots = [d, os.path.dirname(d)]
    for extra in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if extra and os.path.isdir(extra):
            roots += [os.path.join(extra, "data"), extra]
    ordered, seen_root = [], set()
    for r in roots:                                   # 去重但保持顺序
        rn = os.path.normcase(os.path.abspath(r))
        if rn not in seen_root and os.path.isdir(r):
            seen_root.add(rn)
            ordered.append(r)
    for r in ordered:
        budget = SCAN_DIRS_MAX                        # 每个根独立预算,互不挤占
        for dirpath in _walk_names(r, budget).get(base, []):
            cand = os.path.join(dirpath, base)
            if os.path.normcase(os.path.abspath(cand)) == os.path.normcase(path):
                continue
            try:
                if os.path.getmtime(cand) - mine > STALE_SKEW:
                    return cand
            except OSError:
                continue
    return None


def verdict(msgs):
    turn, user_msg = _turn(msgs)
    if not turn:
        return None
    if user_msg and USER_OPTOUT.search(_text_of(user_msg)):
        return None
    said = "\n".join(_text_of(m) for m in turn if m.get("type") == "assistant")
    if "show-open-guard" in said:                     # 我在引述本闸
        return None
    hit = DELIVERED.search(said)
    batch = None if hit else _url_batch(said)         # 第四档:成批无后缀页面链接(2026-09-18)
    if batch:
        blob_u = _tool_blob(turn)
        if not OPENED.search(blob_u):
            return ("not-shown-url", "%s 共 %d 条链接,一条都没打开给他看" % batch)
        return None                                   # 开过就算送达;URL 的窗口标题不好核,不上第二级
    _semhit = ""
    if not hit and not _semhit:
        try:
            from guard_common import claim_kinds as _ck
            if "done" in _ck(said[-1500:], kinds=("done",)):
                _semhit = "语义判定:词表没命中,但这话语义上就是该类断言"
        except Exception:
            pass
    if not hit:
        return None
    # ⛔ 2026-09-08 Frank:「乱开一大堆 html…这个 html 应该去掉,只是看这里就好了」
    #   命中的是【文档类】(html/pdf,不是图片/视频)、而我**已经把内容写在回复里**了
    #   ⇒ 那就是"看这里就好了",别再逼我开一个他还要去关的窗口。
    #   ⛔ 画面类(png/mp4…)不适用:文字替代不了画面,那种仍必须真打开。
    _m = hit.group(0) if hit else ""
    if not PICTURE_EXT.search(_m) and CONTENT_IN_CHAT.search(said):
        return None
    blob = _tool_blob(turn)
    if not OPENED.search(blob):                       # 连打开动作都没有
        return ("not-shown", (hit.group(0) if hit else _semhit))
    if not VERIFIED.search(blob):                     # 开了,但没验证他真的看得到(2026-08-17 的坑)
        return ("not-verified", (hit.group(0) if hit else _semhit))
    for opened in _opened_paths(blob):                # 开了、也验证了,但开的是【过期副本】(2026-08-19 的坑)
        twin = _newer_twin(opened)
        if twin:
            return ("stale-copy", "%s ← 更新的那份在 %s" % (opened, twin))
    return None


def main():
    data = json.loads(sys.stdin.read())
    if not data.get("stop_hook_active"):
        self_blocked_this_turn("show-open-guard", turn_start=True)
    elif self_blocked_this_turn("show-open-guard"):
        _log("skip(self-blocked-this-turn)")
        return
    tp = data.get("transcript_path")
    if not tp:
        _log("skip(no tp)")
        return
    res = verdict(load_transcript_tail(tp))
    if not res:
        _log("allow")
        return
    kind, hit = res
    _log(f"BLOCK({kind}) " + trig(hit))
    reason = {"not-shown": REASON, "not-shown-url": REASON_URL}.get(kind, REASON_UNVERIFIED)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"error(fail-open): {e}")
