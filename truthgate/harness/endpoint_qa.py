# -*- coding: utf-8 -*-
"""endpoint_qa.py —— 通用后端接口与服务探针脚手架 (Frozen External Harness)

核心功能:
  1. 真实发起 HTTP/HTTPS 请求，检验目标服务的物理网络可用性；
  2. 验证 HTTP 状态码与响应时间 (SLA 契约)；
  3. 可选对 JSON 响应内容或包含关键字进行物理断言；
  4. 产出结构化验证日志与标准 Exit Code。
"""
import sys
import time
import json
import argparse
import urllib.request
import urllib.error


def run_endpoint_qa(url: str, expected_status: int = 200, method: str = "GET", payload: str = None, keyword: str = None, timeout_s: float = 5.0, max_latency_ms: float = None) -> dict:
    result = {
        "url": url,
        "method": method,
        "expected_status": expected_status,
        "actual_status": None,
        "duration_ms": 0,
        "success": False,
        "body_preview": "",
        "error": None
    }

    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "TruthGate-Harness/2.0")
    if payload:
        req.add_header("Content-Type", "application/json")
        req.data = payload.encode("utf-8")

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            result["actual_status"] = resp.status
            result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            raw = resp.read()
            body_text = raw.decode("utf-8", errors="replace")
            result["body_preview"] = body_text[:500]

            if resp.status == expected_status:
                if max_latency_ms is not None and result["duration_ms"] > max_latency_ms:
                    result["success"] = False
                    result["error"] = f"响应耗时超标: 实际 {result['duration_ms']}ms > 预期上限 {max_latency_ms}ms"
                elif keyword:
                    if keyword in body_text:
                        result["success"] = True
                    else:
                        result["success"] = False
                        result["error"] = f"响应体中未找到预期关键字: '{keyword}'"
                else:
                    result["success"] = True
            else:
                result["success"] = False
                result["error"] = f"状态码不匹配: 期望 {expected_status}, 实际得到 {resp.status}"

    except urllib.error.HTTPError as e:
        result["actual_status"] = e.code
        result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["success"] = (e.code == expected_status)
        result["error"] = f"HTTP 错误 {e.code}: {e.reason}"
    except Exception as e:
        result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        result["success"] = False
        result["error"] = f"网络连接异常: {e}"

    return result


def main():
    parser = argparse.ArgumentParser(description="TruthGate 通用接口与网络探针脚手架")
    parser.add_argument("--url", required=True, help="待探测的目标 URL")
    parser.add_argument("--expected-status", type=int, default=200, help="期望的 HTTP 状态码 (默认 200)")
    parser.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "DELETE"], help="HTTP 方法")
    parser.add_argument("--payload", default=None, help="可选: 请求体 JSON 字符串")
    parser.add_argument("--keyword", default=None, help="可选: 响应体中必须包含的关键字")
    parser.add_argument("--timeout", type=float, default=5.0, help="网络请求超时 (秒)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")

    args = parser.parse_args()
    res = run_endpoint_qa(
        url=args.url,
        expected_status=args.expected_status,
        method=args.method,
        payload=args.payload,
        keyword=args.keyword,
        timeout_s=args.timeout
    )

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        status_tag = "[PASS]" if res["success"] else "[FAIL]"
        print(f"{status_tag} Endpoint QA: {args.method} {args.url} (状态码: {res['actual_status']}, 耗时: {res['duration_ms']}ms)")
        if not res["success"] and res["error"]:
            print(f"  ! 错误原因: {res['error']}")
        if res["body_preview"]:
            print(f"  + 响应预览: {res['body_preview'][:120]}...")

    sys.exit(0 if res["success"] else 1)


if __name__ == "__main__":
    main()
