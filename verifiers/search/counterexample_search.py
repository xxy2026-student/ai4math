"""随机参数搜索：在参数域上检验猜想谓词，寻找反例。

用法:
    python verifiers/search/counterexample_search.py --spec <spec.json>

spec.json 格式:
{
  "conjecture": "C-000",
  "predicate": "problems/<p>/predicates/c000_pred.py",
  "params": {"a": [0.1, 5.0], "b": [0.1, 5.0]},
  "n_samples": 1000,
  "seed": 0,
  "evidence": "problems/<p>/results/c000_evidence.json"
}

- predicate 文件必须定义 check(params: dict) -> bool，True 表示猜想在该参数点成立。
- params 每项为 [下界, 上界]，均匀采样。
- 输出：VERDICT: PASS checked=N，或 VERDICT: REFUTED checked=i + 反例参数。
"""
import argparse
import importlib.util
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import write_evidence, verdict


def load_predicate(path):
    spec = importlib.util.spec_from_file_location("predicate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    args = ap.parse_args()
    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)

    check = load_predicate(spec["predicate"])
    rng = np.random.default_rng(spec.get("seed", 0))
    names = list(spec["params"])
    n = int(spec.get("n_samples", 1000))
    base = {
        "conjecture": spec.get("conjecture"),
        "spec": args.spec.replace("\\", "/"),
        "seed": spec.get("seed", 0),
    }

    for i in range(n):
        params = {k: float(rng.uniform(*spec["params"][k])) for k in names}
        try:
            ok = bool(check(params))
        except Exception as e:
            write_evidence(spec["evidence"], {**base, "result": "ERROR",
                                              "at_sample": i, "params": params,
                                              "error": repr(e)})
            verdict("ERROR", at=i, error=type(e).__name__)
            sys.exit(1)
        if not ok:
            write_evidence(spec["evidence"], {**base, "result": "REFUTED",
                                              "checked": i + 1,
                                              "counterexample": params})
            print("counterexample:", json.dumps(params))
            verdict("REFUTED", checked=i + 1)
            return

    write_evidence(spec["evidence"], {**base, "result": "PASS", "checked": n})
    verdict("PASS", checked=n)


if __name__ == "__main__":
    main()
