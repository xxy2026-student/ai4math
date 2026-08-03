"""C-000 谓词：diag(a,b) 共同利益协调博弈的完全混合均衡概率 = b/(a+b)。"""
import numpy as np
import nashpy as nash


def check(params):
    a, b = params["a"], params["b"]
    A = np.array([[a, 0.0], [0.0, b]])
    game = nash.Game(A, A)
    target = b / (a + b)
    mixed = [(p1, p2) for p1, p2 in game.support_enumeration()
             if np.all(p1 > 1e-9) and np.all(p2 > 1e-9)]
    if len(mixed) != 1:          # 完全混合均衡必须恰好一个
        return False
    return abs(mixed[0][0][0] - target) < 1e-6
