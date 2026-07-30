"""CFTC COT 采集(Socrata legacy futures-only 数据集,周频)。

黄金 088691 / COMEX 铜 085692。增量追加:只拉本地最新日期之后的数据。
口径说明:legacy 报告的 noncommercial 净多头作为"管理基金净多头"的代理
(与 disaggregated 的 managed money 高度同向,README 方法论有说明)。
自愈:删除对应 CSV,下次运行自动全量重拉。
"""
import os
import time

from . import common

URL = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
MARKETS = [
    ("gold", "088691", "gold_legacy.csv"),
    ("copper", "085692", "copper_legacy.csv"),
]
PAGE = 1000


def collect(status):
    for name, code, filename in MARKETS:
        sid = f"cot:{name}"
        path = os.path.join(common.DATA, "cot", filename)
        try:
            existing = {r["report_date"]: r for r in common.read_csv_dicts(path)}
            since = max(existing) if existing else None
            fetched = _fetch_all(code, since)
            for rec in fetched:
                existing[rec["report_date"]] = rec  # 同日重复取后到的
            if not existing:
                raise ValueError("no COT data at all")
            rows = [[r["report_date"], r["noncomm_long"], r["noncomm_short"],
                     r["net_long"], r["open_interest"]]
                    for r in (existing[d] for d in sorted(existing))]
            common.write_csv_guarded(
                path, ["report_date", "noncomm_long", "noncomm_short",
                       "net_long", "open_interest"], rows)
            status.record(sid, True, rows=len(rows), latest_date=rows[-1][0],
                          freq="weekly")
        except Exception as e:  # noqa: BLE001
            status.record(sid, False, error=e, freq="weekly")
        time.sleep(1)


def _fetch_all(code, since):
    out = []
    offset = 0
    while True:
        where = f"cftc_contract_market_code='{code}'"
        if since:
            where += f" AND report_date_as_yyyy_mm_dd > '{since}'"
        r = common.fetch(URL, params={
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd",
            "$limit": PAGE,
            "$offset": offset,
        })
        batch = r.json()
        if not isinstance(batch, list):
            raise ValueError(f"unexpected response: {str(batch)[:120]}")
        for item in batch:
            long_ = int(float(item["noncomm_positions_long_all"]))
            short = int(float(item["noncomm_positions_short_all"]))
            out.append({
                "report_date": item["report_date_as_yyyy_mm_dd"][:10],
                "noncomm_long": long_,
                "noncomm_short": short,
                "net_long": long_ - short,
                "open_interest": int(float(item["open_interest_all"])),
            })
        if len(batch) < PAGE:
            break
        offset += PAGE
        time.sleep(1)
    return out
