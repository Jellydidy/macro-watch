"""编排入口:采集全部数据源 → 校验人工数据 → 计算信号 → 落盘 status。

- 逐源 try/except 在各模块内部完成,这里再包一层保证模块级 bug 也不互相拖累;
- 进程退出码恒为 0:失败通过 status.json 表达,CI 红绿由 check_status 决定;
- 环境变量 SKIP_SOURCES=fred,yahoo 可跳过慢源(本地调前端用)。
"""
import os
import sys
import traceback

from . import common, cot, fred, gld_holdings, manual_check, markets, signals, sina

MODULES = [
    ("fred", fred),
    ("sina", sina),
    ("markets", markets),
    ("cot", cot),
    ("gld_holdings", gld_holdings),
    ("manual", manual_check),
]


def main():
    skip = {s.strip() for s in os.environ.get("SKIP_SOURCES", "").split(",") if s.strip()}
    status = common.Status()
    for name, module in MODULES:
        if name in skip:
            print(f"[SKIP] {name}")
            continue
        try:
            module.collect(status)
        except Exception:  # noqa: BLE001 - 模块级兜底,单模块崩溃不拖累其他
            traceback.print_exc()
            status.record(f"module:{name}", False, error="module-level crash, see log")
    try:
        signals.compute(status)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        status.record("signals", False, error="signal computation crashed, see log")
    status.save()
    print("status.json written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
