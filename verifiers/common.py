"""验证器公共工具：evidence 写入与 VERDICT 协议。

协议：每个验证器结束前必须调用 verdict() 打印一行
    VERDICT: PASS ...  /  VERDICT: REFUTED ...  /  VERDICT: ERROR ...
hook_gate.py 依据这一行核验猜想文件的 status 是否与验证结果一致。
"""
import json
import os
import time


def write_evidence(path, payload):
    """把验证细节写入 evidence JSON（自动补时间戳、建目录）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = dict(payload)
    payload.setdefault("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def verdict(kind, **kv):
    """打印 VERDICT 行。kind: PASS | REFUTED | ERROR"""
    extra = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"VERDICT: {kind} {extra}".rstrip(), flush=True)
