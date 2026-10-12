#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""orphan-asset-gate — 拦【生成了资产，却没有任何代码在消费它】。

⛔ 来历（2026-08-18，Frank：「为何 shot3, shot4 人脸变了，你方向到底对不对」）：
   他早就明确要求「要能参考 9 张 maximum 图片」。我据此做了
   **5 个人物 × 3 个角度 = 15 张定妆图**，存进 `assets/character-sheets/`，
   然后开始出片，跑了三条 15 秒成片、约 780 币。人脸每条都不一样。
   查真实结构才发现：
     逐镜出片工作流可传图的槽位 = **1 个**；我脚本实际传的 = **1 张**（该镜首帧图）。
   **那 15 张定妆图从做完到现在一次都没被消费过。**
   我逐步验证了每一步【产出】什么（定妆图✅ 关键帧✅ 成片✅），
   **从没验证过每一步【吃进去】什么** —— 中间断了一环，两头看起来都正常。
   完整形状见 lessons.md「形状 2026-08-18-M」。

⛔ 这个病为什么内省抓不住：产出物确实存在、目录确实有文件、脚本确实跑通了。
   所有我习惯检查的信号全是绿的。唯一的红灯是「谁读它」——而那是个我从不问的问题。

⛔ 先查现成（2026-08-18 WebSearch「detect unused generated assets orphan files
   never referenced in code linter tool」）→ 判定 **只能自建，但判据照抄业界**：
   · 现成件：Knip(knip.dev, JS/TS, 150+插件)、unimported、DCM(Flutter
     `dcm check-unused-code`)、Android Lint「Unused Resources」、Unity 的
     Unused Assets Detector —— 全是**扫全项目找死代码**的静态分析器，
     面向代码的 import/export 图，跑一次几秒到几分钟。
   · 我要的是**收尾瞬间**判断「我这轮刚生成的这几个文件有没有人读」：
     增量（只看本轮产出）、毫秒级（挂 Stop hook）、不需要构建依赖图。
   · **判据直接照抄 Knip 对 orphan 的定义**：
     「orphan files: files present in the repository but **not imported by any
      other file**」—— 我只把范围从"全仓库"缩到"本轮产出"。

判据（客观、不需要理解语义；全部成立才拦）：
  ① 本轮**新生成**了资产文件（图片/音频/模型/数据）
  ② 本轮说了**正面推进类**的话（做好了/生成了/已就绪/可以用了…）
  ③ 该资产的**文件名或其所在目录名**，在项目代码里 **grep 引用数为 0**

⛔ 宁漏勿误杀 —— 以下一律放行：
   · 资产落在 scratchpad/tmp 里（中间产物）
   · grep 跑不动（测不出就不猜）
   · 本轮同时就在消费它（哪怕代码是刚写的）

自检：`python orphan-asset-gate.py --self-test`（用 2026-08-18 这次的真实数据打靶）
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ASSET_EXT = re.compile(
    r"(?:[A-Za-z]:)?[^\"',;:\[\]<>|*?][^\"',;:\[\]<>|*?]*\.(?:png|jpe?g|webp|gif|bmp|tiff?"
    r"|wav|mp3|flac|m4a|ogg|safetensors|ckpt|gguf|npy|npz)", re.I)

CLAIM = re.compile(
    # 强信号（带"已/了/完/可以/能"等时态/语气助词的单字或短语）
    r"(做好了|生成好了|已生成|已就绪|准备好了|可以用了|全部产出"
    r"|搞定了|完成了|弄好了|做完了|全部做好|全部完成|出好了|出片完成|出图完成"
    r"|OK了|可以了|能用了|可用了|上线了|交付了|交付完成|收工了|收尾了|收完了"
    r"|都(做好|做完|搞定|完成|就绪|上线|交付|出好)"
    r"|I (am|'m) done|it's done|done\.|finished\.|all done|all set"
    r"|资产.{0,6}(齐|完成|好了)"
    r"|定妆图.{0,6}(好了|完成|齐)"
    r"|素材.{0,6}(齐|好了)"
    r"|assets? (are )?ready)", re.I)

CONSUMED_HINT = re.compile(
    r"(upload_file|--file\s|\brefs?\s*[=:]|reference_image|ref_image|LoadImage"
    r"|character-sheets|sheet_of|global_refs)", re.I)

SKIP_DIR = re.compile(r"(scratchpad|node_modules|\.git[/\\])", re.I)


def _is_scratch(path, root=None):
    """临时产物判定 —— 临时目录用【真实路径】比对，不用正则猜。

    ⛔ 2026-08-18 打靶抓到：原本正则写 `[/\\]temp[/\\]`，
       Windows 的 `C:\\Users\\...\\AppData\\Local\\Temp\\` 命中它 ⇒
       **任何路径中段含 Temp 的项目，这道闸永远不开火**。自检夹具就栽在这：
       用 tempfile.mkdtemp() 建夹具 ⇒ 每条用例都被跳过 ⇒ 假绿。

    ⛔ 2026-08-30 回归测试踩中：测试用 mkdtemp() 造项目根（也落系统 temp），
       collect() 看到文件路径在 temp 下直接跳过 ⇒ assets=[] ⇒ 闸假绿。
       修法：传 root 时，若该路径在 root 内部、root 不在系统 temp 下，
       就不算 scratch（用户/测试在项目内造的任何东西都该被闸看到）。
    """
    if SKIP_DIR.search(path):
        return True
    if root is not None:
        try:
            rp = os.path.normcase(os.path.abspath(root))
            pp = os.path.normcase(os.path.abspath(path))
            # 路径在 root 内部 → 是用户/测试在项目里造的东西，不该被当 scratch。
            # root 是否在系统 temp 不论（test_unique_subdir_is_orphan 就在 temp 里造项目根）。
            if pp.startswith(rp):
                return False
        except Exception:
            pass
    try:
        import tempfile
        t = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        return os.path.normcase(os.path.abspath(path)).startswith(t)
    except Exception:
        return False


def collect(turn, root=None):
    said, assets, consumed = [], [], False
    for m in turn:
        if m.get("type") != "assistant":
            continue
        for c in ((m.get("message") or {}).get("content") or []):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text":
                said.append(c.get("text") or "")
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                blob = json.dumps(inp, ensure_ascii=False)
                if CONSUMED_HINT.search(blob):
                    consumed = True
                # ⛔ 第二轮外部审查抓到的洞：之前用 `json.dumps(input)` 全量
                # 抓所有 path-like 串，会把 content 字段、注释示例里的 `.png`
                # 误判为本轮产出。修法：只从明确是文件路径的字段收
                # （Write/Edit 的 file_path、NotebookEdit 的 notebook_path 等），
                # 其它字段的 `.png` 字符串一律不要。
                path_fields = []
                for k, v in inp.items():
                    if not isinstance(v, str):
                        continue
                    kl = k.lower()
                    if kl in ("file_path", "filepath", "notebook_path", "source_path",
                              "destination_path", "target_path", "output_path"):
                        path_fields.append(v)
                    elif kl == "content" and ASSET_EXT.search(v):
                        # Write/Edit 的 content 字段：只有当整段内容看起来就是
                        # 文件路径时（短、含 .png/.jpg 等），才视为"写一个图片文件"
                        v_strip = v.strip()
                        if len(v_strip) < 260 and ASSET_EXT.fullmatch(v_strip):
                            path_fields.append(v_strip)
                for v in path_fields:
                    if _is_scratch(v, root=root):
                        continue
                    if v not in assets:
                        assets.append(v)
    return "\n".join(said), assets, consumed


def _py_refcount(root, name, _exts=(".py", ".js", ".ts", ".sh", ".ps1", ".json", ".md")):
    """rg 不可用时的回退: 纯 Python 数「name 出现在多少个代码文件里」。
    只有连目录都走不动才返 None(那才叫"测不出")。"""
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    hits = 0
    try:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in skip]
            for fn in fns:
                if not fn.lower().endswith(_exts):
                    continue
                fp = os.path.join(dp, fn)
                try:
                    if os.path.getsize(fp) > 2_000_000:
                        continue
                    if name in open(fp, encoding="utf-8", errors="ignore").read():
                        hits += 1
                except Exception:
                    continue
        return hits
    except Exception:
        return None


def refcount(root, name, _rg=[None]):
    """这个名字在项目代码里被引用几次。工具跑不动返回 None（测不出不猜）。"""
    if _rg[0] is None:
        import shutil
        _rg[0] = shutil.which("rg") or ""
    if not _rg[0]:
        # ⛔ 2026-09-05: 本机 rg 是 Claude Code 注入 bash 的 shell 函数、不是 PATH 上的 exe,
        #   subprocess 永远调不到 => 原来直接返 None => judge 全放行 => 这道闸真实运行时是死的。
        #   回退纯 Python 扫(只扫代码类扩展名, 跳过重目录), 慢一点但闸真的活着。
        return _py_refcount(root, name)
    try:
        r = subprocess.run(
            [_rg[0], "-l", "--fixed-strings", name, "-g", "*.py", "-g", "*.js",
             "-g", "*.ts", "-g", "*.sh", "-g", "*.ps1", "-g", "*.json",
             "-g", "*.md", str(root)],
            capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if r.returncode not in (0, 1):
        return None
    return len([x for x in (r.stdout or "").split("\n") if x.strip()])


def _relative(root, a):
    """返回 a 相对 root 的路径（用 OS 原生分隔符），形如 assets\\char\\foo.png 或 assets/char/foo.png。"""
    try:
        return Path(a).resolve().relative_to(Path(root).resolve())
    except Exception:
        return Path()


def judge(said, assets, consumed, root):
    """返回 (要不要拦, 孤儿清单)。判据：资产文件的完整相对路径在项目里零引用。"""
    # ⛔ 2026-08-18 打靶抓到的自身 bug：旧版只检查「文件名 + 父目录名」，
    #    常见目录名（tools/、docs/、assets/）在项目里到处被引用，refcount 永远 > 0，
    #    导致真项目里的孤儿资产全部漏拦。修复：改用完整相对路径（形如 assets/char/foo.png）。
    assets = [a for a in (assets or []) if not _is_scratch(a, root=root)]
    if consumed or not assets or not CLAIM.search(said):
        return False, []
    orphans = []
    for a in assets:
        p = Path(a)
        rel = _relative(root, a)
        if not rel:
            # _relative 算不出完整路径时，用文件名兜底 refcount，
            # 防止 Windows 路径含特殊字符或仅传文件名的场景漏拦真孤儿。
            name_count = refcount(root, p.name)
            if name_count and name_count > 0:
                continue
            # ⛔ 2026-09-05 修静默漏拦:原来这里无条件 continue —— 只要 _relative 算不出
            #   (资产落在项目外、临时目录、路径含特殊字符),就永远判不出孤儿,闸静默失效。
            #   而 name_count 已经算过了:文件名在整个项目里【零引用】= 没有任何代码消费它 = 真孤儿。
            #   name_count is None(工具跑不动)才放行,那才是"无法确认"。
            if name_count == 0:
                orphans.append(a)
            continue
        count = refcount(root, rel)
        if count is None:
            # 工具跑不动这个资产 → 宁漏这一个，别让整个闸被卡住
            continue
        if count == 0:
            # 完整路径零引用 → 再用文件名兜底，防止动态 import 漏拦
            name_count = refcount(root, p.name)
            if name_count and name_count > 0:
                continue          # 文件名在代码里有引用（动态 import 等），不算孤儿
            orphans.append(a)
    return bool(orphans), orphans


def main():
    if "--self-test" in sys.argv:
        return self_test()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tp = data.get("transcript_path")
    if not tp:
        return 0
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from guard_common import load_transcript_tail, turn_start_index
        msgs = load_transcript_tail(tp)
        turn = msgs[turn_start_index(msgs):]
    except Exception:
        return 0
    root = Path(data.get("cwd") or os.getcwd())
    said, assets, consumed = collect(turn, root=str(root))
    hit, orphans = judge(said, assets, consumed, root)
    if not hit:
        return 0
    sys.stderr.write(
        "⛔ 孤儿资产闸：你这轮生成了资产并说它「好了」，但**项目里没有任何代码在读它**。\n"
        "   零引用的资产：\n"
        + "".join("     · %s\n" % o for o in orphans[:6]) +
        "⛔ 实录 2026-08-18：我做了 5人×3角度=15 张定妆图，然后出片跑了三条、约780币，\n"
        "   人脸每条都不一样。查了才知道那条出片链路**只有 1 个图槽位**，\n"
        "   15 张定妆图一次都没被消费过。我逐步验了每步【产出】什么，\n"
        "   **从没验过每步【吃进去】什么** —— 两头都绿，中间断了。（lessons 形状 2026-08-18-M）\n"
        "⇒ 现在回答一句：**谁在消费它？把那行代码/那个参数指出来。**\n"
        "   指不出来 = 这些资产是孤儿，等于没做，别说「好了」。\n"
        "   若确实是中间产物/只给人看、不进代码，说明一句即可放行。\n")
    return 2


# --------------------------- 真实靶打靶 ---------------------------
def self_test():
    """⛔ 用 2026-08-18 这次的**真实错误数据**打靶，不是测组件。"""
    import shutil
    if not shutil.which("rg"):
        print("⛔ 没有 rg，本闸判据跑不动（会一律放行）。装 ripgrep 再自检。")
        return 1
    ok = True
    # 夹具**不能**放系统 temp —— 那会被 _is_scratch 正确地跳过，
    # 于是每条用例都放行、自检假绿（2026-08-18 打靶实录）。
    tmp = Path(__file__).parent / ".selftest_orphan"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "art").mkdir(parents=True, exist_ok=True)
    (tmp / "gen.py").write_text(
        "NODE_IMAGE='38'\ncmd=['--file','38:image='+img]\nUSED='hero_front.png'\n",
        encoding="utf-8")

    def case(name, said, assets, consumed, want):
        nonlocal ok
        hit, _ = judge(said, assets, consumed, tmp)
        good = (hit == want)
        ok = ok and good
        print("%s %-46s 拦=%-5s 期望=%s" % ("✅" if good else "⛔", name, hit, want))

    case("真实靶:定妆图零引用+说「做好了」", "5 个人物的定妆图全部生成好了，可以进下一步",
         [str(tmp / "assets" / "suxu_front.png")], False, True)
    case("同一资产,本轮已 upload_file 传入", "定妆图做好了",
         [str(tmp / "assets" / "suxu_front.png")], True, False)
    case("纯诊断,没说「好了」", "抽了三帧看接缝，SH02 尾部漂到了包厢",
         [str(tmp / "seam" / "SH01_tail.png")], False, False)
    case("产物在 scratchpad(中间产物)", "对比图做好了",
         ["D:/Temp/claude/x/scratchpad/seam_compare.png"], False, False)
    case("资产名在代码里出现(被消费)", "图做好了",
         [str(tmp / "art" / "hero_front.png")], False, False)
    case("本轮没产出资产", "全部做好了", [], False, False)
    case("多个资产,只要有一个被引用之外的孤儿就拦", "素材齐了",
         [str(tmp / "art" / "hero_front.png"), str(tmp / "art2" / "ghost.png")], False, True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("✅ 7/7 通过" if ok else "⛔ 有用例没过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
