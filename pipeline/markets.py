"""国际市场行情采集(替代 Yahoo:Yahoo 对数据中心 IP 一律 429,不可用于 Actions)。

- 国际金价:LBMA 官方 gold_pm.json(1968 至今,USD PM 定盘价),口径为 LBMA PM fix,
  与 COMEX/现货同趋势,权威且无风控。
- COPX:新浪美股日K(2010 至今),中国 CDN,本地与云端都稳定。
- 纳指由 fred.py 的 NASDAQCOM 覆盖,不在本模块。
全量覆盖策略(两端点都返回全历史,自愈)。
"""
import json
import os

from . import common

LBMA_URL = "https://prices.lbma.org.uk/json/gold_pm.json"
SINA_US_KLINE = ("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
                 "var%20_=/US_MinKService.getDailyK?symbol={}&___qn=3")
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

US_SYMBOLS = [("copx", "copx_daily.csv")]


def collect(status):
    _collect_lbma(status)
    for symbol, filename in US_SYMBOLS:
        _collect_sina_us(status, symbol, filename)


def _collect_lbma(status):
    sid = "lbma:gold_pm"
    try:
        r = common.fetch(LBMA_URL)
        data = r.json()
        rows = []
        for item in data:
            usd = (item.get("v") or [None])[0]
            d = item.get("d")
            if usd and d and usd > 0:
                rows.append([d, common.fmt_num(float(usd))])
        rows.sort(key=lambda x: x[0])
        if len(rows) < 1000:
            raise ValueError(f"only {len(rows)} rows, response suspicious")
        path = os.path.join(common.DATA, "market", "gold_usd_daily.csv")
        common.write_csv_guarded(path, ["date", "close"], rows)
        status.record(sid, True, rows=len(rows), latest_date=rows[-1][0], freq="daily")
    except Exception as e:  # noqa: BLE001
        status.record(sid, False, error=e, freq="daily")


def _collect_sina_us(status, symbol, filename):
    sid = f"sina_us:{symbol}"
    try:
        r = common.fetch(SINA_US_KLINE.format(symbol), headers=SINA_HEADERS)
        text = r.text
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            raise ValueError(f"no JSON array in response: {text[:80]!r}")
        data = json.loads(text[start:end + 1])
        rows = []
        for item in data:
            rows.append([
                item["d"],
                common.fmt_num(float(item["o"])),
                common.fmt_num(float(item["h"])),
                common.fmt_num(float(item["l"])),
                common.fmt_num(float(item["c"])),
                common.fmt_num(float(item.get("v", 0) or 0)),
            ])
        rows.sort(key=lambda x: x[0])
        if len(rows) < 100:
            raise ValueError(f"only {len(rows)} rows, response suspicious")
        path = os.path.join(common.DATA, "market", filename)
        common.write_csv_guarded(
            path, ["date", "open", "high", "low", "close", "volume"], rows)
        status.record(sid, True, rows=len(rows), latest_date=rows[-1][0], freq="daily")
    except Exception as e:  # noqa: BLE001
        status.record(sid, False, error=e, freq="daily")
