# -*- coding: utf-8 -*-
# PostToolUse(Edit|Write)守卫:改 UI 文件的那一刻注入设计纪律提醒(回合开头的注入会被读飘,point-of-action 才贴脸)
# 2026-07-18 Frank:「之前写的 ui/ux Hook 根本没有自动触发你用 taste skill」+「密密麻麻像写小说」后钉死
# 2026-07-25 收窄触发面(audit 确认 over-fire):非设计型/生成物 HTML/CSS/JS 不再开火(coverage/dist/build/
#   hyperframes 视频合成帧/node_modules/markitdown 产物/.min. 压缩件等),真·手写设计文件照旧贴脸。
import sys, json, re, os      # os:收尾兜底要落日志(2026-07-29 补,别再静默死掉)

# ⛔ 2026-09-10 接进账本(Frank:「为何 superego 没拦你还是没开火?」):
#   本闸当天响了 8 次、我 8 次没理、直到 Stop 硬闸才补 —— 而 hook-stats.jsonl 里【0 条】。
#   因为它从没 import guard_common ⇒ nudge-escalation-gate 数不到它 ⇒ 永远不会升级成硬拦。
#   对照同日 lesson-anchor-gate 311 条,差别就是下面这一行。
#   guard_common 一 import 就自动观测 stdout + 退出时按内容判 nudge/block/allow,本闸逻辑一字不改。
#   ⇒ 这正是「纸老虎 = 跑了、我可以无视、而且没人数」的第三条:接上账本,第二次就会被升级。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import guard_common  # noqa: F401  接线即记账;失败不影响本闸(fail-open)
except Exception:
    pass

# 生成物/非设计目录:路径里任一【目录段】命中即视为非设计,不注入。
# ⛔按目录段精确匹配(不做子串),避免误伤 my-dashboard / report-page 这类正常设计文件名。
_SKIP_DIRS = {
    "coverage", "dist", "build", "out", "output", "node_modules",
    "hyperframes", "artifacts", "target",
    ".next", ".nuxt", ".output", ".svelte-kit", ".cache", "__pycache__",
}
# 非设计型文件名形态:视频合成帧 frame-001.html、压缩产物 *.min.css/js/html
_SKIP_NAME = re.compile(r"\.min\.(css|html?|js|jsx|tsx|vue)$|^frame[-_.]?\d+\.(html?|css|js)$", re.I)

try:
    d = json.load(sys.stdin)
    fp = str(((d.get("tool_input") or {}).get("file_path")) or "")
    segs = [s for s in re.split(r"[\\/]", fp) if s]
    name = segs[-1] if segs else ""
    is_ui = re.search(r"\.(css|html|jsx|tsx|vue)$|app\.js$", fp, re.I)
    # 目录段命中生成物集,或文件名是帧/压缩产物 → 判为非设计,不开火
    is_noise = any(s.lower() in _SKIP_DIRS for s in segs[:-1]) or _SKIP_NAME.search(name)
    if is_ui and not is_noise:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
            "⛔UI文件刚被改(" + name + "):①设计skill分层栈 invoke 了吗?没有→现在补:【底座·永远】design-taste-frontend 的反slop硬规则(字体/颜色/间距/对比度纪律——Frank裁决:dashboard也用,只是不套它的landing结构);【叠加·内部工具时】ui-ux-pro-max 的UX细则;【素材·新建页面/成套/大改版时】先翻 open-design 47套模板选底子,别从零硬编。②收尾必须:真浏览器截图→陌生人眼睛过五问+扫读性(小说墙/无层次/焦点不突出=违规)→迭代到完美,不许让用户先看到。代码改成功≠渲染合格。"}}, ensure_ascii=True))  # ⛔ensure_ascii=True:Windows cp1252 终端打中文会炸并被except吞成静默假失败(2026-07-18实测)
except Exception as _e:
    # ⛔ fail-open 保留,但**绝不静默**(2026-07-29 纸老虎普查 D 类):
    #    这道闸的注释里自己就写着"Windows cp1252 终端打中文会炸并被 except 吞成静默假失败"——
    #    也就是说它**已经因为这个静默兜底翻过一次车**,却仍然没留痕。今晚 ruff 抓到 6 次 `F821`,
    #    每一个都会被这种 `except: pass` 吞掉 ⇒ 闸哑了也没人知道。
    try:
        import datetime
        _d = os.environ.get("SUPEREGO_LOG_DIR") or os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(_d, "ui-edit-guard.log"), "a", encoding="utf-8") as _f:
            _f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
                     f"error(fail-open): {type(_e).__name__}: {str(_e)[:160]}\n")
    except Exception:
        pass
