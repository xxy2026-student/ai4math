"""SymPy 符号验证模板：以线性需求 Stackelberg 双寡头为例。

演示两类机械验证（新问题照此模式写自己的符号验证器）：
1. 闭式解验算：候选解代回最优性条件 / 与独立求解结果比对，simplify 后须恒等于 0；
2. comparative statics：对参数求导，在假设域（positive=True 等）上判号。

用法:
    python verifiers/symbolic/stackelberg_demo.py
"""
import os
import sys

import sympy as sp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import verdict

# 模型：P = a - q1 - q2，成本 c1, c2；leader 先动。假设：内点解，参数为正。
a, c1, c2, q1 = sp.symbols("a c1 c2 q1", positive=True)

# follower 最优反应（由其 FOC 解出）
q2_br = (a - c2 - q1) / 2

# leader 利润与最优产量
leader_profit = (a - q1 - q2_br - c1) * q1
q1_star = sp.solve(sp.diff(leader_profit, q1), q1)[0]

checks = {}
# 检验 1：闭式解 q1* = (a - 2 c1 + c2) / 2
checks["closed_form_q1"] = sp.simplify(q1_star - (a - 2 * c1 + c2) / 2) == 0
# 检验 2：dq1*/dc2 = 1/2 > 0（对手成本上升，leader 增产）
checks["dq1_dc2_is_half"] = sp.simplify(sp.diff(q1_star, c2) - sp.Rational(1, 2)) == 0
# 检验 3：二阶条件（利润严格凹）
checks["soc_concave"] = sp.simplify(sp.diff(leader_profit, q1, 2)) == -1

for name, ok in checks.items():
    print(f"{name}: {'OK' if ok else 'FAILED'}")

if all(checks.values()):
    verdict("PASS", checks=len(checks))
else:
    verdict("REFUTED", failed=[k for k, v in checks.items() if not v])
