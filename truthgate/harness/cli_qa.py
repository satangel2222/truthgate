# -*- coding: utf-8 -*-
"""cli_qa.py —— 通用命令行与子进程真实执行质检脚手架 (Frozen External Harness)

核心功能:
  1. 真实运行指定命令（非 Mock），捕获实际退出码、stdout 与 stderr；
  2. 验证命令执行时延与预期退出码；
  3. 可选验证产物文件是否真实落盘且非空；
  4. 产出结构化日志与标准 Exit Code。
"""
import os
import sys
import time
import json
import argparse
import subprocess
from pathlib import Path


def run_cli_qa(cmd: str, expected_code: int = 0, cwd: str = None, check_file: str = None, timeout_s: float = 30.0, require_artifacts: list = None) -> dict:
    result = {
        "command": cmd,
        "expected_code": expected_code,
        "actual_code": None,
        "duration_ms": 0,
        "success": False,
        "stdout": "",
        "stderr": "",
        "file_verified": None,
        "error": None
    }

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s
        )
        result["actual_code"] = proc.returncode
        result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["stdout"] = proc.stdout[:2000]
        result["stderr"] = proc.stderr[:2000]

        if proc.returncode == expected_code:
            files_to_check = []
            if check_file:
                files_to_check.append(check_file)
            if require_artifacts:
                files_to_check.extend(require_artifacts)

            if files_to_check:
                missing = []
                verified = []
                for cf in files_to_check:
                    fp = Path(cwd or os.getcwd()) / cf if not Path(cf).is_absolute() else Path(cf)
                    if fp.exists() and fp.stat().st_size > 0:
                        verified.append(f"{fp.name} ({fp.stat().st_size} bytes)")
                    else:
                        missing.append(cf)
                if missing:
                    result["success"] = False
                    result["error"] = f"期望产物文件不存在或为空: {', '.join(missing)}"
                else:
                    result["file_verified"] = f"产物落盘验证通过: {', '.join(verified)}"
                    result["success"] = True
            else:
                result["success"] = True
        else:
            result["success"] = False
            result["error"] = f"命令退出码不匹配: 期望 {expected_code}, 实际为 {proc.returncode}"

    except subprocess.TimeoutExpired:
        result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["success"] = False
        result["error"] = f"命令执行超时 ({timeout_s}s)"
    except Exception as e:
        result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["success"] = False
        result["error"] = f"执行异常: {e}"

    return result


def main():
    parser = argparse.ArgumentParser(description="TruthGate 通用 CLI 进程质检脚手架")
    parser.add_argument("--cmd", required=True, help="待执行并验证的命令字符串")
    parser.add_argument("--expected-code", type=int, default=0, help="期望的退出码 (默认 0)")
    parser.add_argument("--cwd", default=None, help="工作目录 (默认为当前目录)")
    parser.add_argument("--check-file", default=None, help="可选: 命令执行后必须落盘的文件路径")
    parser.add_argument("--timeout", type=float, default=30.0, help="超时时间 (秒)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()
    res = run_cli_qa(
        cmd=args.cmd,
        expected_code=args.expected_code,
        cwd=args.cwd,
        check_file=args.check_file,
        timeout_s=args.timeout
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        status_tag = "[PASS]" if res["success"] else "[FAIL]"
        print(f"{status_tag} CLI QA: `{args.cmd}` (退出码: {res['actual_code']}, 耗时: {res['duration_ms']}ms)")
        if res["file_verified"]:
            print(f"  + {res['file_verified']}")
        if not res["success"] and res["error"]:
            print(f"  ! 错误详情: {res['error']}")
        if res["stderr"]:
            print(f"  - stderr: {res['stderr'].strip()[:200]}")

    sys.exit(0 if res["success"] else 1)


if __name__ == "__main__":
    main()
