# -*- coding: utf-8 -*-
"""把一条 shell/PowerShell 命令拆成【一次次真实调用】,供各安全闸判据使用。

⛔ 为什么建它(2026-09-07,查外部现成实现时暴露出来的洞):
   `kenryu42/cc-safety-net`(★1.5k)的卖点是「**它解析这条命令在干什么**;换个包装、
   调下参数顺序藏不住」。而本仓库的安全闸全是**在整条命令字符串上做正则**,有三类真实缺陷:

     ① **开关不分家**:`data-overwrite-guard` 用 `_has("-force")` 在【整条命令】里找开关,
        不管它属于哪个命令 ⇒ `Copy-Item a b; Remove-Item c -Force` 被算成
        「Copy-Item 强制覆盖」= 误伤,而真正危险的那条反而没按自己的判据判。
     ② **引号里的字当成命令**:`git commit -m "copy-item -force"` 会命中。
     ③ **动词互相包含**:`remove-item` 字面上含 `move-item`、`uninstall` 含 `install`。
        今天已经踩到第三次,每次都靠事后补 `\\b` ——**那是打补丁,不是解析**。

   本模块只做一件事:**把命令切成一段段真实调用,每段带自己的动词和自己的参数**。
   ③ 由「动词是整个 token 相等」天然解决,不再依赖词边界正则。

⛔ 边界(老实登记,别当没有):这是【结构解析】不是完整 shell 语法分析。
   变量间接(`C=Copy-Item; $C -Force`)、`$IFS` 拼接、base64 解码后执行 —— 都识别不了。
   目标是把最常见的三类缺陷消掉,不是做成沙箱。要更强得上真 parser(bashlex/PSParser)。
"""
import re

# 只是"前缀"、真正的命令在后面
_PREFIX = {"sudo", "nohup", "env", "command", "exec", "stdbuf", "nice", "ionice",
           "time", "xargs", "builtin", "doas"}
# 这些把【后面那串引号里的东西】当代码执行 ⇒ 要钻进去看
_EXEC_WRAP = {"bash", "sh", "zsh", "dash", "ash", "ksh", "eval", "ssh",
              "pwsh", "powershell", "powershell.exe", "pwsh.exe", "cmd", "cmd.exe"}


def _tokenize(seg):
    """按【引号外的空白】切词。返回 [(文本, 是否整体被引号包住)]。

    ⛔ 不用 shlex:posix 模式会吃掉 Windows 路径里的反斜杠(`C:\\Users` → `C:Users`),
       非 posix 模式又把引号留在 token 里。这里自己走一遍,反斜杠原样保留。
    """
    out, buf, quoted, q = [], [], False, None
    for ch in seg:
        if q:
            if ch == q:
                q = None
            else:
                buf.append(ch)
        elif ch in ("'", '"'):
            q, quoted = ch, True
        elif ch.isspace():
            if buf or quoted:
                out.append(("".join(buf), quoted and len(out) >= 0))
            buf, quoted = [], False
        else:
            buf.append(ch)
    if buf or quoted:
        out.append(("".join(buf), quoted))
    return out


def _split_segments(cmd):
    """按引号外的分隔符把命令切成段。`$(...)` / 反引号里的内容也单独成段(它会被执行)。"""
    segs, buf, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            i += 1
            continue
        if ch in ("'", '"'):
            q = ch
            buf.append(ch)
            i += 1
            continue
        two = cmd[i:i + 2]
        if two in ("&&", "||"):
            segs.append("".join(buf)); buf = []; i += 2; continue
        if two == "$(":
            segs.append("".join(buf)); buf = []; i += 2; continue
        if ch in (";", "|", "&", "\n", "`", "(", ")", "{", "}"):
            segs.append("".join(buf)); buf = []; i += 1; continue
        buf.append(ch)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


def _verb_of(tok):
    """把 `C:/x/y/pm2.cmd` 这种取成 `pm2`;PowerShell 动词保持原样(含连字符)。"""
    t = re.split(r"[/\\]", tok)[-1].lower()
    return re.sub(r"\.(exe|cmd|bat|ps1|sh)$", "", t)


def invocations(cmd, _depth=0):
    """返回 [(动词, [该次调用自己的参数...])]。

    引号里的内容【不】当命令看 —— 除非它是 `bash -c "..."` 这类执行包装的载荷。
    """
    if not cmd or _depth > 3:
        return []
    out = []
    for seg in _split_segments(str(cmd)):
        toks = _tokenize(seg)
        # 剥前缀(sudo / env VAR=V / timeout 600 / nohup ...)
        idx = 0
        while idx < len(toks):
            t, was_q = toks[idx]
            v = _verb_of(t)
            if v in _PREFIX or re.match(r"^[A-Za-z_][\w]*=", t):
                idx += 1
                continue
            if v == "timeout" and idx + 1 < len(toks):
                idx += 2 if re.match(r"^/?t?\d+$", toks[idx + 1][0]) else 1
                continue
            break
        if idx >= len(toks):
            continue
        head, head_quoted = toks[idx]
        if head_quoted:
            continue                      # 整个命令名都在引号里 = 当数据,不当命令
        verb = _verb_of(head)
        args = [t for t, _ in toks[idx + 1:]]
        out.append((verb, args))
        # 执行包装:钻进载荷再解析一层(`bash -c "pm2 save"` / `powershell -Command "..."`)
        if verb in _EXEC_WRAP:
            for j in range(idx + 1, len(toks)):
                t, was_q = toks[j]
                if was_q:
                    out.extend(invocations(t, _depth + 1))
                    break
    return out


def _flag_hit(args, flag):
    """参数里有没有这个开关。支持 `-rf` 这种把多个短开关挤在一起的写法。"""
    f = flag.lower().lstrip("-/")
    for a in args:
        al = a.lower()
        if al.lstrip("-/") == f:
            return True
        if al.startswith("-") and not al.startswith("--") and len(f) == 1 and f in al[1:]:
            return True                   # `-rf` 里含 r / f
        if al.startswith("--") and al[2:].split("=")[0] == f:
            return True
        if al.startswith("/") and al[1:].lower() == f:
            return True                   # robocopy 的 /MIR
    return False


def has_invocation(cmd, verb, *flags):
    """这条命令里,有没有【一次 `verb` 调用】而且【那一次自己】带齐了这些开关。

    ⇒ 这就是替掉「整条命令里找 -force」的那个函数:开关必须属于同一次调用。
    """
    v = verb.lower()
    for got, args in invocations(cmd):
        if got == v and all(_flag_hit(args, f) for f in flags):
            return True
    return False
