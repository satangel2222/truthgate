"""独立看图（visual-truth-gate，2026-10-03）。REQUIREMENTS 第 3、11 条：交付之前自己先验；只凭事实拦。

病历：AG 会话 cb9b2465 最后一次交付，流程全做了（跑浏览器、听控制台、截图、view_file 看图），
回复写「人物全身道袍与长剑完整无瑕疵」，而那张图里人物下半身被横切、血条被标题栏盖住。
流程类的闸（anti-toy-test / visual-proof）全过 —— 它们查「看没看图」，不查「图里是什么」。

做法：本轮改了网页、改完之后看过截图 ⇒ 把【最后看的那张图】交给另一个模型盲看，只让它列显示缺陷。
  · 还没结论 ⇒ 后台起一次看图，本次收尾先拦，让它跑 `py vision_proof.py <图>` 等结论；
  · 有缺陷 ⇒ 回复里要逐条原样写出这些缺陷（Frank 看得到），或者修好重新截图；否则拦；
  · 没缺陷 / 看图服务出错 ⇒ 放（出错会记在结论文件里，10 分钟后重试）。
结论按图片内容的 md5 存在 ~/.truthgate/ledger/vision/，同一张图只看一次。

用法：py vision_proof.py <图>      看图并打印结论（已有结论直接打印）
      py vision_proof.py --selftest
"""
import base64, hashlib, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

CACHE = Path.home() / ".truthgate" / "ledger" / "vision"
GATE = "visual-truth-gate"
MODELS = ("agnes-2.5-flash", "agnes-3.0-flash")
PROMPT = ("这是一个软件界面 / 网页 / 游戏画面的截图。请只列出你在画面上看到的显示缺陷："
          "界面元素互相遮挡、人物或物体被切断、比例明显异常、背景接缝或错位、大片空白、破图、文字重叠或溢出。"
          "每条一行，写明在画面的哪个位置。没有缺陷就只写「无」。不要夸奖，不要猜测意图。")
IMG_RE = re.compile(r'"([^"]+?\.(?:png|jpe?g|webp))\\?"', re.I)
CLEAN = {"无", "没有", "没有缺陷", "无缺陷", "无明显缺陷", "none"}
RETRY_ERR, PENDING_TTL = 600, 150


def _key():
    v = os.environ.get("AGNES_API_KEY")
    if v:
        return v
    for ln in open(os.path.expanduser("~/.claude/.env"), encoding="utf-8-sig", errors="ignore"):
        if ln.strip().startswith("AGNES_API_KEY="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("AGNES_API_KEY 在环境变量和 ~/.claude/.env 里都没找到")


def _cache_file(img):
    return CACHE / (hashlib.md5(Path(img).read_bytes()).hexdigest() + ".json")


def cached(img):
    try:
        c = json.loads(_cache_file(img).read_text(encoding="utf-8"))
    except Exception:
        return None
    if "error" in c and time.time() - c.get("ts", 0) > RETRY_ERR:
        return None
    if "looks" not in c:   # 旧版（只看一次就定论）留下的结论不认，重看
        return None
    return c


def parse(out):
    """模型回的文字 → 缺陷列表（没有缺陷 ⇒ 空列表）。"""
    lines = [re.sub(r"^[\s\-\*·•\d\.、）)]+", "", l).strip() for l in (out or "").splitlines()]
    lines = [l for l in lines if l]
    if not lines or all(l.rstrip("。.！!").lower() in CLEAN for l in lines):
        return []
    return [l for l in lines if l.rstrip("。.！!").lower() not in CLEAN][:8]


def judge(img):
    """看图。有结论直接返回；没有就调模型（20~90 秒），结论落盘。"""
    c = cached(img)
    if c:
        return c
    CACHE.mkdir(parents=True, exist_ok=True)
    f = _cache_file(img)
    pend = f.with_suffix(".pending")
    pend.write_text(str(time.time()), encoding="utf-8")
    b64 = base64.b64encode(Path(img).read_bytes()).decode()
    # 它先出思考再出答案：上限给小了，答案会被截在半句（实测 900 时只回了半行）
    body = {"max_tokens": 3000, "messages": [{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    t = time.time()

    def look():
        """看一次 → (模型回的文字, None) 或 (None, 出错原因)。空白 ≠ 没缺陷：当成没看成，换下一次。"""
        err = "没试"
        for model in MODELS + MODELS[:1]:
            try:
                req = urllib.request.Request("https://apihub.agnes-ai.com/v1/chat/completions",
                                             json.dumps(dict(body, model=model)).encode(),
                                             {"Content-Type": "application/json", "Authorization": "Bearer " + _key()})
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = (json.load(r)["choices"][0]["message"]["content"] or "").strip()
                if raw:
                    return raw, None
                err = "看图模型回了空白"
            except Exception as e:
                err = repr(e)[:300]
        return None, err

    # 实测（2026-10-03，同一张坏图）：16 次里 7 次回空白；认真回答的 7 次里 1 次说「无」。
    # ⇒ 任何一次看到缺陷就算有；说「没缺陷」要连续两次独立看都没有才算（看走眼约 1/7 → 约 1/50）。
    raws = []
    res = {"img": str(img)}
    for _ in range(2):
        raw, err = look()
        if raw is None:
            res["error"] = err
            break
        raws.append(raw)
        if parse(raw):
            break
    if "error" not in res:
        res["defects"] = parse(raws[-1])
    res.update(raw=raws, looks=len(raws), sec=round(time.time() - t, 1), ts=time.time())
    f.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        pend.unlink()
    except OSError:
        pass
    return res


def _img_path(a):
    for src in (a.get("path", ""), a.get("text", "")):
        for m in IMG_RE.finditer('"' + src + '"' if src and '"' not in src else src):
            p = m.group(1).replace("\\\\", "\\").strip('\\"')
            if os.path.isfile(p):
                return p
    return None


def delivery_image(actions):
    """本轮最后一次改网页之后、最后看的那张图；没改网页或改完没看图 ⇒ None（那种情况归 visual-proof-gate 管）。"""
    from delivery_check import FRONT, NOT_SHIPPED, GEN_WEB
    acts = [dict(a, kind="write", path=m.group(1)) if (m := GEN_WEB.search(a.get("text", ""))) else a for a in actions]
    wi = max((i for i, a in enumerate(acts) if a["kind"] == "write" and FRONT.search(a.get("path", "").strip('"'))
              and not NOT_SHIPPED.search(a["path"])), default=-1)
    if wi < 0:
        return None
    imgs = [p for a in acts[wi + 1:] if a["kind"] == "image" for p in [_img_path(a)] if p]
    return imgs[-1] if imgs else None


def _norm(s):
    return re.sub(r"[\s\W_]+", "", s or "")


def unquoted(defects, text):
    """回复里没有原样写出来的缺陷（按去掉标点空白后的前 12 个字比）。"""
    t = _norm(text)
    return [d for d in defects if _norm(d)[:12] not in t]


def check(text, actions, spawn=True):
    """→ None（放）或拦截文案。spawn=False（考卷 / 回放）时没有结论就放，不起后台看图。"""
    img = delivery_image(actions)
    if not img:
        return None
    c = cached(img)
    me = os.path.abspath(__file__)
    if c is None:
        if not spawn:
            return None
        pend = _cache_file(img).with_suffix(".pending")
        fresh = pend.exists() and time.time() - pend.stat().st_mtime < PENDING_TTL
        if not fresh:   # AG 一次收尾调桥接 3 次：只起一个看图进程
            CACHE.mkdir(parents=True, exist_ok=True)
            pend.write_text(str(time.time()), encoding="utf-8")
            flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0
            subprocess.Popen([sys.executable, me, img], creationflags=flags, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return (f"[TruthGate 拦截 - {GATE}] 你这轮改了网页并拿截图当证据。这张图正在由另一个模型独立看（20~90 秒）：\n  {img}\n"
                f"现在运行：py -3 \"{me}\" \"{img}\"\n它会等到结论并打印缺陷清单。有缺陷就修好重新截图，或在回复里逐条原样写给 Frank；之后再收尾。")
    if "error" in c:
        return None
    miss = unquoted(c.get("defects") or [], text)
    if not miss:
        return None
    return (f"[TruthGate 拦截 - {GATE}] 另一个模型独立看了你当作证据的截图，看到这些显示缺陷，而你的回复里没有写：\n"
            + "\n".join("  · " + d for d in miss)
            + f"\n图：{img}\n二选一：① 修好，重新截图并看图（新图会重新判）；② 在给 Frank 的回复里把上面每一条原样写出来，并说明为什么保留。\n"
              "不许把这张图描述成没有问题。")


def selftest():
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    assert parse("无") == [] and parse("- 无。") == [] and parse("") == []
    assert parse("- 右下角人物腿部被裁切\n2. 顶部标题栏遮住血条") == ["右下角人物腿部被裁切", "顶部标题栏遮住血条"]
    d = ["右下角蓝色人物角色的身体下部被画面底边裁切，缺少腿部"]
    assert unquoted(d, "人物全身道袍与长剑完整无瑕疵") == d
    assert unquoted(d, "独立看图发现：右下角蓝色人物角色的身体下部被画面底边裁切，缺少腿部。这是原版构图。") == []
    td = tempfile.mkdtemp()
    png = os.path.join(td, "shot.png")
    open(png, "wb").write(b"\x89PNG fake " + os.urandom(8))
    W = lambda p: {"kind": "write", "text": "edit " + p, "path": p}
    I = lambda p: {"kind": "image", "text": 'view_file "' + p.replace("\\", "\\\\") + '" "看图"', "path": ""}
    assert delivery_image([I(png)]) is None, "没改网页 ⇒ 不管"
    assert delivery_image([I(png), W("D:/p/index.html")]) is None, "改完没看图 ⇒ 不归这道管"
    assert delivery_image([W('"D:/p/index.html"'), I(png)]) == png, "AG 的路径带引号和双反斜杠也要认得"
    acts = [W("D:/p/index.html"), I(png)]
    assert check("做好了", acts, spawn=False) is None, "考卷模式没有结论 ⇒ 放"
    global CACHE
    old, CACHE = CACHE, Path(td) / "vision"
    try:
        CACHE.mkdir()
        _cache_file(png).write_text(json.dumps({"defects": [], "ts": time.time()}), encoding="utf-8")
        assert cached(png) is None, "旧版只看一次的结论（没有 looks）⇒ 不认"
        _cache_file(png).write_text(json.dumps({"defects": d, "looks": 1, "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
        r = check("人物完整无瑕疵", acts, spawn=False)
        assert r and GATE in r and "被画面底边裁切" in r, "有缺陷、回复没写 ⇒ 拦"
        assert check("另一个模型看到：" + d[0], acts, spawn=False) is None, "逐条原样写出 ⇒ 放"
        _cache_file(png).write_text(json.dumps({"defects": [], "looks": 2, "ts": time.time()}), encoding="utf-8")
        assert check("完整无瑕疵", acts, spawn=False) is None, "两次看图都没缺陷 ⇒ 放"
        _cache_file(png).write_text(json.dumps({"error": "x", "looks": 0, "ts": time.time()}), encoding="utf-8")
        assert check("完整无瑕疵", acts, spawn=False) is None, "看图服务出错 ⇒ 放"
    finally:
        CACHE = old
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif len(sys.argv) > 1:
        r = judge(sys.argv[1])
        if "error" in r:
            print("看图服务出错：", r["error"])
        elif r["defects"]:
            print(f"另一个模型看到 {len(r['defects'])} 处显示缺陷：")
            for x in r["defects"]:
                print("  ·", x)
        else:
            print("另一个模型没看到显示缺陷。")
    else:
        print(__doc__)
