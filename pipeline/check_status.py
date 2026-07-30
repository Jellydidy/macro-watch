"""CI 末步:检查 status.json,数据源失败或超龄则 exit 1(让 workflow 变红)。

刻意放在数据 commit 之后运行:成功的源照常上线,失败只体现为红标+页面红灯。
GitHub 会对连续失败的 scheduled workflow 发邮件,补足"出事能知道"。
"""
import datetime as dt
import json
import os
import sys

from . import common


def age_days(date_str, today):
    """支持 YYYY-MM-DD / YYYY-MM / YYYYQn 三种周期格式,统一按周期末算龄。"""
    if not date_str:
        return 9999
    try:
        if "Q" in date_str:
            year, q = int(date_str[:4]), int(date_str[-1])
            end = dt.date(year + (1 if q == 4 else 0), (q % 4) * 3 + 1, 1)
            return (today - (end - dt.timedelta(days=1))).days
        if len(date_str) == 7:  # YYYY-MM,按月末
            year, month = int(date_str[:4]), int(date_str[5:7])
            nxt = dt.date(year + (1 if month == 12 else 0), month % 12 + 1, 1)
            return (today - (nxt - dt.timedelta(days=1))).days
        return (today - dt.date.fromisoformat(date_str[:10])).days
    except ValueError:
        return 9999


def main():
    with open(common.Status.PATH, encoding="utf-8") as f:
        doc = json.load(f)
    thresholds = common.load_thresholds()["freshness_days"]
    today = dt.date.today()
    problems = []
    for sid, s in sorted(doc["sources"].items()):
        if sid == "auto:gld_holdings" and not s["ok"]:
            continue  # 已知失效端点,常态失败不红标(信号层已降级到人工数据)
        if not s["ok"]:
            problems.append(f"{sid}: FAIL ({s['error']})")
            continue
        freq = s.get("freq") or "daily"
        red = thresholds.get(freq, thresholds["daily"])["red"]
        age = age_days(s.get("latest_date"), today)
        if age > red:
            problems.append(f"{sid}: stale, latest={s['latest_date']} age={age}d > {red}d")
    if problems:
        print("=== check_status: PROBLEMS ===")
        for p in problems:
            print(" -", p)
        return 1
    print(f"check_status: all {len(doc['sources'])} sources healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
