# Astra 78c0e4aa768511e888c392aa27de357b02aaf0f4; AGPL-3.0, see LICENSE.
def safe_float(val, default: float = 0.0) -> float:
    """把 `val` 转成有限浮点；**转不出有限值就返回 `default`**（数值强转的单一事实源）。

    第一百五十刀：本语义在仓内有**三份**逐条等价的实现
    （`scripts/factor_library.py`、`scripts/ai_brain_trader.py` 的公开同名函数，以及
    `scripts/calculus/regime.py` 的私有 `_safe_float`）。它们恰好一致（我按 14 组输入做过
    行为对拍：`nan`/`±inf`/`'nan'`/`'inf'`/`None`/`''`/`[1]`/`' 2 '`/`True` …全部同判），
    但**逐字重复三次**意味着：任何一次"顺手优化"都会让因子与风控算出的数**静默不同**
    —— 比读取失败更隐蔽，因为不报错、没日志、结果看起来还很合理。

    语义（**逐条钉住，勿"顺手"改**）：

    - `nan` / `inf` / `-inf`（含字符串形式）⇒ `default`；
    - `None` / `''` / 不可转类型（list 等）⇒ `default`；
    - 可转的字符串（含前后空格）⇒ 其数值；
    - `bool` 走 `float()` ⇒ `True→1.0` / `False→0.0`（这是既有怪癖，**不是**要改成 `default`）。
    """
    if val is None:
        return default
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default
