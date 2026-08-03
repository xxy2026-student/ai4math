"""计算双矩阵博弈的全部 Nash 均衡（support enumeration，nashpy）。

用法:
    python verifiers/numeric/nash_check.py --spec <spec.json>

spec.json:
{
  "A": [[3, 0], [0, 2]],        # 玩家1支付矩阵
  "B": [[3, 0], [0, 2]],        # 玩家2支付矩阵；零和博弈可省略（默认 -A）
  "evidence": "problems/<p>/results/xxx_equilibria.json"
}

输出全部均衡到 stdout 与 evidence；VERDICT: PASS n_equilibria=k。
主要供 /explore 快速验算小型博弈，或被谓词脚本 import 复用。
"""
import argparse
import json
import os
import sys

import numpy as np
import nashpy as nash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import write_evidence, verdict


def equilibria(A, B=None):
    A = np.asarray(A, dtype=float)
    B = -A if B is None else np.asarray(B, dtype=float)
    game = nash.Game(A, B)
    return [(p1.tolist(), p2.tolist()) for p1, p2 in game.support_enumeration()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)

    eqs = equilibria(spec["A"], spec.get("B"))
    for i, (p1, p2) in enumerate(eqs):
        print(f"eq{i}: p1={np.round(p1, 6).tolist()} p2={np.round(p2, 6).tolist()}")
    if spec.get("evidence"):
        write_evidence(spec["evidence"], {"spec": args.spec.replace("\\", "/"),
                                          "equilibria": eqs})
    verdict("PASS", n_equilibria=len(eqs))


if __name__ == "__main__":
    main()
