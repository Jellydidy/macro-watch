"""校验三个人工维护 JSON 的 schema 与新鲜度。

格式坏了只报 status 错误 + 对应信号变灰,绝不炸掉流水线。
"""
import json
import os
import re

from . import common

FILES = [
    # (文件名, series 每项必须字段: {字段: 允许null}, 周期字段, 周期格式, 频率)
    ("gold_etf_flows.json",
     {"month": False, "global_holdings_t": True, "monthly_flow_t": False},
     "month", r"^\d{4}-\d{2}$", "monthly_manual"),
    ("central_bank_gold.json",
     {"quarter": False, "net_purchases_t": False},
     "quarter", r"^\d{4}Q[1-4]$", "quarterly"),
    ("ai_capex.json",
     {"quarter": False, "MSFT": True, "GOOG": True, "META": True, "AMZN": True},
     "quarter", r"^\d{4}Q[1-4]$", "quarterly"),
]


def collect(status):
    for filename, fields, period_key, period_re, freq in FILES:
        sid = f"manual:{filename.removesuffix('.json')}"
        path = os.path.join(common.DATA, "manual", filename)
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            series = doc.get("series")
            if not isinstance(series, list) or not series:
                raise ValueError("'series' missing or empty")
            for i, item in enumerate(series):
                for field, nullable in fields.items():
                    if field not in item:
                        raise ValueError(f"series[{i}] missing field {field!r}")
                    v = item[field]
                    if v is None:
                        if not nullable:
                            raise ValueError(f"series[{i}].{field} must not be null")
                    elif field == period_key:
                        if not re.match(period_re, str(v)):
                            raise ValueError(f"series[{i}].{field}={v!r} bad format")
                    elif not isinstance(v, (int, float)):
                        raise ValueError(f"series[{i}].{field}={v!r} not a number")
            latest = max(str(item[period_key]) for item in series)
            status.record(sid, True, rows=len(series), latest_date=latest, freq=freq)
        except Exception as e:  # noqa: BLE001
            status.record(sid, False, error=e, freq=freq)
