"""信号计算层:把文章框架编码为 data/signals.json。

约定:
- 灯色 green / yellow / red / neutral / gray;
  gray 专指"输入数据缺失或过期,信号不可信"(宁灰勿错),neutral 指"条件未触发,无方向"。
- 每个信号带 as_of(所用最新数据日期)、stale、inputs、detail,全部可人工核查。
- 所有"日"均指交易日行数;阈值一律读 config/thresholds.json。
- 纯标准库实现(EMA/分位数/滚动极值),不依赖 pandas。
"""
import datetime as dt
import json
import os

from . import common
from .check_status import age_days

STALE_RED = None  # 运行时由 thresholds 填充


# ---------- 数据加载 ----------

def _load_fred(series_id):
    path = os.path.join(common.DATA, "fred", f"{series_id}.csv")
    return [(r["date"], float(r["value"])) for r in common.read_csv_dicts(path)]


def _load_market(filename):
    path = os.path.join(common.DATA, "market", filename)
    return [{"date": r["date"], "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])}
            for r in common.read_csv_dicts(path)]


def _load_cot(filename):
    path = os.path.join(common.DATA, "cot", filename)
    return [{"date": r["report_date"], "net_long": int(r["net_long"]),
             "oi": int(r["open_interest"])} for r in common.read_csv_dicts(path)]


def _load_manual(filename):
    path = os.path.join(common.DATA, "manual", filename)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("series") or []
    except (OSError, json.JSONDecodeError):
        return []


# ---------- 数值工具 ----------

def ema(values, n):
    """EMA,前 n 个值的 SMA 作种子(标准算法,可人工复算)。"""
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out  # 与 values[n-1:] 对齐


def delta(values, w):
    """最新值相对 w 个交易行之前的变化;数据不足返回 None。"""
    if len(values) <= w:
        return None
    return values[-1] - values[-1 - w]


def pctile_rank(window, x):
    """x 在 window 中的百分位(0-100,<=x 的占比)。"""
    if not window:
        return None
    return 100.0 * sum(1 for v in window if v <= x) / len(window)


def _is_stale(latest_date, freq, thresholds, today):
    red = thresholds["freshness_days"].get(freq, thresholds["freshness_days"]["daily"])["red"]
    return age_days(latest_date, today) > red


def _sig(id_, group, name, light, value, detail, inputs, as_of, stale):
    if stale:
        light = "gray"
        detail = f"[数据过期,信号不可信] {detail}"
    return {"id": id_, "group": group, "name": name, "light": light, "value": value,
            "detail": detail, "inputs": inputs, "as_of": as_of, "stale": stale}


def _gray(id_, group, name, reason):
    return {"id": id_, "group": group, "name": name, "light": "gray",
            "value": "数据缺失", "detail": reason, "inputs": {}, "as_of": None,
            "stale": True}


# ---------- 主入口 ----------

def compute(status):
    th = common.load_thresholds()
    today = dt.date.today()
    signals = []

    t10yie = _load_fred("T10YIE")
    dfii10 = _load_fred("DFII10")
    pce = _load_fred("PCETRIM12M159SFRBDAL")
    unrate = _load_fred("UNRATE")
    t10y2y = _load_fred("T10Y2Y")
    dgs30 = _load_fred("DGS30")
    dgs10 = _load_fred("DGS10")
    hy = _load_fred("BAMLH0A0HYM2")
    wti = _load_fred("DCOILWTICO")
    gc = _load_market("gc_daily.csv")
    copx = _load_market("copx_daily.csv")
    ixic = _load_market("ixic_daily.csv")
    cu = _load_market("cu0_daily.csv")
    cot_gold = _load_cot("gold_legacy.csv")
    etf_flows = _load_manual("gold_etf_flows.json")
    cb_gold = _load_manual("central_bank_gold.json")
    capex = _load_manual("ai_capex.json")

    # ===== 联储区 =====
    sahm_gap, sahm_asof = _sahm(unrate)
    signals.append(_fed_zone(th, today, t10yie, pce, sahm_gap, sahm_asof))
    signals.append(_sahm_signal(th, today, sahm_gap, sahm_asof, unrate))
    dk = _double_kill(th, today, t10yie, dfii10)
    signals.append(dk)
    signals.append(_curve(th, today, t10y2y, dgs30))

    # ===== AI 区 =====
    nas = _nasdaq_high(th, today, ixic)
    signals.append(nas)
    capex_sig = _ai_capex(th, today, capex)
    signals.append(capex_sig)
    scenario = _scenario(th, today, wti, dgs10, nas, capex_sig)

    # ===== 黄金区 =====
    g_ema = _gold_ema(th, today, gc)
    g_net = _gold_net_long(th, today, cot_gold)
    g_oi = _gold_oi(th, today, cot_gold)
    g_etf = _gold_etf(th, today, etf_flows)
    g_cb = _cb_gold(th, today, cb_gold)
    signals += [g_ema, g_net, g_oi, g_etf, g_cb]
    signals.append(_gold_composite([g_ema, g_net, g_oi, g_etf, g_cb], dk))

    # ===== 沪铜区 =====
    signals.append(_cu_range(th, today, cu))
    signals.append(_cu_dip(th, today, cu, hy, wti))
    signals.append(_copx_trend(th, today, copx, cu))

    doc = {"generated_at": common.now_utc(), "scenario": scenario, "signals": signals}
    common.atomic_write(os.path.join(common.DATA, "signals.json"),
                        json.dumps(doc, ensure_ascii=False, indent=1))
    status.record("signals", True, rows=len(signals),
                  latest_date=today.isoformat(), freq="daily")


# ---------- 联储区 ----------

def _sahm(unrate):
    """Sahm gap = UNRATE 近3月均值 − 过去12个月内3月均值最小值。"""
    vals = [v for _, v in unrate]
    if len(vals) < 15:
        return None, None
    m3 = [sum(vals[i - 2:i + 1]) / 3 for i in range(2, len(vals))]
    gap = m3[-1] - min(m3[-12:])
    return round(gap, 3), unrate[-1][0]


def _fed_zone(th, today, t10yie, pce, sahm_gap, sahm_asof):
    f = th["fed"]
    if not t10yie or not pce or sahm_gap is None:
        return _gray("fed_zone", "fed", "联储反应区间", "缺少 T10YIE / TrimmedPCE / UNRATE")
    e, e_date = t10yie[-1][1], t10yie[-1][0]
    p, p_date = pce[-1][1], pce[-1][0]
    stale = (_is_stale(e_date, "daily", th, today)
             or _is_stale(p_date, "monthly_fred", th, today))
    notes = []
    if e >= f["t10yie_hawk"]:
        light, value = "red", "鹰派警戒"
        notes.append(f"通胀预期 {e:.2f} ≥ {f['t10yie_hawk']}(联储容忍线)")
    elif p <= f["pce_dove"] or sahm_gap >= f["sahm_trigger"]:
        light, value = "green", "降息条件成立"
        if p <= f["pce_dove"]:
            notes.append(f"TrimmedPCE {p:.2f} ≤ {f['pce_dove']}")
        if sahm_gap >= f["sahm_trigger"]:
            notes.append(f"Sahm gap {sahm_gap:.2f} ≥ {f['sahm_trigger']}(失业率明显走高)")
    else:
        light, value = "yellow", "按兵不动区"
        if e >= f["t10yie_warn"]:
            notes.append(f"通胀预期 {e:.2f} 接近警戒位 {f['t10yie_hawk']}")
        if p <= f["pce_near"]:
            notes.append(f"TrimmedPCE {p:.2f} 接近降息条件 {f['pce_dove']}")
        if sahm_gap >= f["sahm_near"]:
            notes.append(f"Sahm gap {sahm_gap:.2f} 接近触发 {f['sahm_trigger']}")
        if not notes:
            notes.append("距离鹰派警戒与降息条件均有距离")
    detail = (f"T10YIE={e:.2f}({e_date}),TrimmedPCE={p:.2f}({p_date}),"
              f"Sahm gap={sahm_gap:.2f}({sahm_asof})。" + ";".join(notes))
    return _sig("fed_zone", "fed", "联储反应区间", light, value, detail,
                {"t10yie": e, "trimmed_pce": p, "sahm_gap": sahm_gap},
                max(e_date, p_date), stale)


def _sahm_signal(th, today, sahm_gap, sahm_asof, unrate):
    f = th["fed"]
    if sahm_gap is None:
        return _gray("sahm_gap", "fed", "Sahm 规则(失业率)", "UNRATE 数据不足")
    stale = _is_stale(sahm_asof, "monthly_fred", th, today)
    u = unrate[-1][1]
    if sahm_gap >= f["sahm_trigger"]:
        light, value = "red", "衰退信号触发"
    elif sahm_gap >= f["sahm_near"]:
        light, value = "yellow", "接近触发"
    else:
        light, value = "green", "就业稳定"
    detail = (f"失业率 {u:.1f}%({sahm_asof}),Sahm gap={sahm_gap:.2f}"
              f"(3月均值−12个月内最低3月均值;≥{f['sahm_trigger']} 即文章所说'失业率明显走高')")
    return _sig("sahm_gap", "fed", "Sahm 规则(失业率)", light, value, detail,
                {"unrate": u, "sahm_gap": sahm_gap}, sahm_asof, stale)


def _double_kill(th, today, t10yie, dfii10):
    d = th["double_kill"]
    w = d["window_days"]
    ev, rv = [v for _, v in t10yie], [v for _, v in dfii10]
    de, dr = delta(ev, w), delta(rv, w)
    if de is None or dr is None:
        return _gray("gold_double_kill", "fed", "黄金双杀组合", "T10YIE/DFII10 数据不足")
    stale = (_is_stale(t10yie[-1][0], "daily", th, today)
             or _is_stale(dfii10[-1][0], "daily", th, today))
    cond_e = de <= d["t10yie_drop_pp"]
    cond_r = dr >= d["dfii10_rise_pp"]
    if cond_e and cond_r:
        light, value = "red", "双杀触发"
    elif cond_e or cond_r:
        light, value = "yellow", "半条件"
    else:
        light, value = "green", "未触发"
    detail = (f"近{w}交易日:通胀预期 {de:+.2f}pp(触发≤{d['t10yie_drop_pp']}),"
              f"实际利率 {dr:+.2f}pp(触发≥+{d['dfii10_rise_pp']})。"
              "文章:'通胀预期回落+实际利率走高'是黄金最不利组合,一票否决")
    return _sig("gold_double_kill", "fed", "黄金双杀组合", light, value, detail,
                {"t10yie_d20": round(de, 3), "dfii10_d20": round(dr, 3)},
                max(t10yie[-1][0], dfii10[-1][0]), stale)


def _curve(th, today, t10y2y, dgs30):
    c = th["curve"]
    sv = [v for _, v in t10y2y]
    lv = [v for _, v in dgs30]
    ds = delta(sv, c["window_days"])
    if ds is None or len(lv) < c["high_lookback_days"] + 1:
        return _gray("curve_steepening", "fed", "曲线陡峭化", "T10Y2Y/DGS30 数据不足")
    stale = (_is_stale(t10y2y[-1][0], "daily", th, today)
             or _is_stale(dgs30[-1][0], "daily", th, today))
    prior_high = max(lv[-(c["high_lookback_days"] + 1):-1])
    broke = lv[-1] >= prior_high
    steep = ds >= c["steepen_pp"]
    if steep or broke:
        light, value = "red", "市场在自行收紧"
    else:
        light, value = "green", "曲线平稳"
    detail = (f"10Y-2Y 近{c['window_days']}日 {ds:+.2f}pp(触发≥+{c['steepen_pp']});"
              f"30Y={lv[-1]:.2f} vs 前{c['high_lookback_days']}日高点 {prior_high:.2f}"
              f"({'已破前高' if broke else '未破'})")
    return _sig("curve_steepening", "fed", "曲线陡峭化(市场自行收紧)", light, value,
                detail, {"t10y2y_d20": round(ds, 3), "dgs30": lv[-1],
                         "dgs30_prior_high": round(prior_high, 2), "dgs30_broke": broke},
                max(t10y2y[-1][0], dgs30[-1][0]), stale)


# ---------- AI 区 ----------

def _nasdaq_high(th, today, ixic):
    n = th["nasdaq"]
    lb, recent = n["high_lookback_days"], n["recent_days"]
    closes = [r["close"] for r in ixic]
    if len(closes) < lb + recent:
        return _gray("nasdaq_high", "ai", "纳指 vs 前高(追铜信号)", "^IXIC 数据不足")
    stale = _is_stale(ixic[-1]["date"], "daily", th, today)
    prior_high = max(closes[-(lb + 1):-1])
    gap_pct = (closes[-1] / prior_high - 1) * 100
    breaks = [i for i in range(len(closes) - recent, len(closes))
              if closes[i] >= max(closes[i - lb:i])]
    if breaks:
        light, value = "green", "追铜信号有效"
        last_break = ixic[breaks[-1]]["date"]
        extra = f"近{recent}日内破位日:{last_break}"
    elif gap_pct >= -n["near_pct"]:
        light, value = "yellow", "逼近前高"
        extra = ""
    else:
        light, value = "neutral", "未破前高"
        extra = ""
    detail = (f"纳指 {closes[-1]:,.0f},距前{lb}日高点 {prior_high:,.0f} 为 {gap_pct:+.1f}%。"
              f"文章:纳指破前高=追铜信号。{extra}")
    return _sig("nasdaq_high", "ai", "纳指 vs 前高(追铜信号)", light, value, detail,
                {"close": closes[-1], "prior_high": prior_high,
                 "gap_pct": round(gap_pct, 2), "broke_recent": bool(breaks)},
                ixic[-1]["date"], stale)


def _ai_capex(th, today, capex):
    if not capex:
        return _gray("ai_capex", "ai", "AI Capex 增速", "manual/ai_capex.json 无数据")
    rows = sorted(capex, key=lambda x: x["quarter"])
    latest_q = rows[-1]["quarter"]
    stale = age_days(latest_q, today) > th["freshness_days"]["quarterly"]["red"]
    totals = {}
    for r in rows:
        vals = [r.get(k) for k in ("MSFT", "GOOG", "META", "AMZN")]
        if all(isinstance(v, (int, float)) for v in vals):
            totals[r["quarter"]] = sum(vals)
    yoy = {}
    for q, total in totals.items():
        prev_q = f"{int(q[:4]) - 1}{q[4:]}"
        if prev_q in totals:
            yoy[q] = (total / totals[prev_q] - 1) * 100
    if len(yoy) < 2:
        return _sig("ai_capex", "ai", "AI Capex 增速", "gray",
                    "样本不足", f"可计算 YoY 的季度只有 {len(yoy)} 个(需四家数据齐的季度,"
                    f"且上年同季也齐)。最新数据 {latest_q}", {"yoy": yoy}, latest_q, stale)
    qs = sorted(yoy)
    cur, prev = yoy[qs[-1]], yoy[qs[-2]]
    slowdown_confirmed = False
    if len(qs) >= 3:
        slowdown_confirmed = cur < prev < yoy[qs[-3]]
    if slowdown_confirmed:
        light, value = "red", "放缓确认(连续2季回落)"
    elif cur < prev:
        light, value = "yellow", "增速回落(1季)"
    else:
        light, value = "green", "主线延续"
    detail = (f"四家(MSFT/GOOG/META/AMZN)Capex 合计 YoY:{qs[-1]}={cur:+.0f}%,"
              f"{qs[-2]}={prev:+.0f}%。放缓确认→情景②权重上升;主线延续→情景①")
    return _sig("ai_capex", "ai", "AI Capex 增速", light, value, detail,
                {"yoy": {q: round(v, 1) for q, v in yoy.items()},
                 "slowdown_confirmed": slowdown_confirmed}, latest_q, stale)


def _scenario(th, today, wti, dgs10, nas, capex_sig):
    s = th["scenario"]
    conds = []
    wv = [v for _, v in wti]
    dw = delta(wv, s["wti_window_days"])
    wti_surge = None
    if dw is not None and len(wv) > s["wti_window_days"]:
        base = wv[-1 - s["wti_window_days"]]
        surge_pct = (wv[-1] / base - 1) * 100 if base else 0
        window = wv[-(252 * s["wti_pctile_years"]):]
        pr = pctile_rank(window, wv[-1])
        wti_surge = surge_pct >= s["wti_surge_pct"] or pr >= s["wti_pctile"]
        conds.append(f"WTI {s['wti_window_days']}日 {surge_pct:+.0f}%"
                     f"(触发≥+{s['wti_surge_pct']}%),3年分位 {pr:.0f}"
                     f"(触发≥{s['wti_pctile']})")
    rv = [v for _, v in dgs10]
    d10 = delta(rv, s["rate_window_days"])
    if d10 is not None:
        conds.append(f"10Y 利率 {s['rate_window_days']}日 {d10:+.2f}pp")
    nas_broke = nas.get("inputs", {}).get("broke_recent", False)
    capex_slow = capex_sig.get("inputs", {}).get("slowdown_confirmed", False)
    conds.append(f"纳指近期破前高={'是' if nas_broke else '否'};"
                 f"Capex放缓确认={'是' if capex_slow else '否'}")

    if wti_surge is None or d10 is None:
        lean, label = 0, "数据不足"
    elif wti_surge:
        lean, label = 3, "倾向情景③:地缘不稳/滞胀(一票优先)"
    elif nas_broke and d10 >= 0:
        lean, label = 1, "倾向情景①:AI 新叙事、利率高位(金不利、铜可追)"
    elif capex_slow and d10 < 0:
        lean, label = 2, "倾向情景②:Capex 放缓、利率回落(金铜双受益)"
    else:
        lean, label = 0, "情景不明朗"
    return {"lean": lean, "label": label, "conditions": conds,
            "as_of": today.isoformat()}


# ---------- 黄金区 ----------

def _gold_ema(th, today, gc):
    n = th["gold"]["ema_period"]
    closes = [r["close"] for r in gc]
    if len(closes) < n + 1:
        return _gray("gold_ema", "gold", "金价 vs EMA200", "GC=F 数据不足")
    stale = _is_stale(gc[-1]["date"], "daily", th, today)
    e = ema(closes, n)[-1]
    dev = (closes[-1] / e - 1) * 100
    above = closes[-1] > e
    light = "green" if above else "red"
    value = "站上长期趋势线" if above else "趋势线下方"
    detail = (f"GC=F 收盘 {closes[-1]:,.1f} vs EMA{n} {e:,.1f},偏离 {dev:+.1f}%。"
              "文章:黄金趋势性极强,均线上下区别巨大")
    return _sig("gold_ema", "gold", f"金价 vs EMA{n}", light, value, detail,
                {"close": closes[-1], "ema": round(e, 1), "dev_pct": round(dev, 2)},
                gc[-1]["date"], stale)


def _gold_net_long(th, today, cot_gold):
    g = th["gold"]
    if len(cot_gold) < 30:
        return _gray("gold_net_long", "gold", "CFTC 净多头分位", "COT 数据不足")
    stale = _is_stale(cot_gold[-1]["date"], "weekly", th, today)
    nl = [r["net_long"] for r in cot_gold]
    window = nl[-g["netlong_window_weeks"]:]
    q = pctile_rank(window, nl[-1])
    d4 = delta(nl, g["netlong_delta_weeks"])
    warming = d4 is not None and d4 > 0
    if g["netlong_mid_lo"] <= q <= g["netlong_mid_hi"] and warming:
        light, value = "green", "中位回暖(文章看多条件)"
    elif q > g["netlong_crowded"]:
        light, value = "yellow", "持仓拥挤"
    elif q < g["netlong_washed"]:
        light, value = "yellow", "极度悲观(反转观察)"
    else:
        light, value = "neutral", "中性"
    detail = (f"非商业净多头 {nl[-1]:,}(口径:legacy noncommercial,作管理基金代理),"
              f"5年分位 {q:.0f}%,近{g['netlong_delta_weeks']}周 {d4:+,d}" if d4 is not None
              else f"非商业净多头 {nl[-1]:,},5年分位 {q:.0f}%")
    return _sig("gold_net_long", "gold", "CFTC 净多头分位", light, value, detail,
                {"net_long": nl[-1], "pctile_5y": round(q, 1),
                 "delta_4w": d4}, cot_gold[-1]["date"], stale)


def _gold_oi(th, today, cot_gold):
    g = th["gold"]
    if len(cot_gold) < g["oi_low_weeks"] + 1:
        return _gray("gold_oi", "gold", "COMEX 持仓量(OI)", "COT 数据不足")
    stale = _is_stale(cot_gold[-1]["date"], "weekly", th, today)
    oi = [r["oi"] for r in cot_gold]
    low52 = min(oi[-g["oi_low_weeks"]:])
    rebound_pct = (oi[-1] / low52 - 1) * 100
    d4 = delta(oi, g["oi_delta_weeks"])
    if oi[-1] <= low52:
        light, value = "red", "创52周新低(持续离场)"
    elif rebound_pct >= g["oi_rebound_pct"] and d4 is not None and d4 > 0:
        light, value = "green", "见底反弹"
    else:
        light, value = "neutral", "中性"
    detail = (f"OI={oi[-1]:,},52周低点 {low52:,},反弹 {rebound_pct:+.1f}%"
              f"(触发≥+{g['oi_rebound_pct']}% 且近4周走高)")
    return _sig("gold_oi", "gold", "COMEX 持仓量(OI)", light, value, detail,
                {"oi": oi[-1], "low_52w": low52, "rebound_pct": round(rebound_pct, 1),
                 "delta_4w": d4}, cot_gold[-1]["date"], stale)


def _gold_etf(th, today, etf_flows):
    """优先 auto/gld_holdings.csv(端点恢复时),否则人工月度流量。"""
    g = th["gold"]
    auto_path = os.path.join(common.DATA, "auto", "gld_holdings.csv")
    auto = common.read_csv_dicts(auto_path)
    if auto:
        last = auto[-1]
        if age_days(last["date"], today) <= g["etf_auto_max_age_days"]:
            tonnes = [float(r["tonnes"]) for r in auto]
            d21 = delta(tonnes, 21)  # 约一个月
            if d21 is not None:
                light = "green" if d21 >= 0 else "red"
                value = "持仓回升/持稳" if d21 >= 0 else "持仓流出"
                detail = f"GLD 官方吨位 {tonnes[-1]:,.1f}t,近21交易日 {d21:+,.1f}t(自动源)"
                return _sig("gold_etf", "gold", "黄金 ETF 流向", light, value, detail,
                            {"tonnes": tonnes[-1], "delta_21d": round(d21, 1),
                             "source": "auto"}, last["date"], False)
    if not etf_flows:
        return _gray("gold_etf", "gold", "黄金 ETF 流向",
                     "自动源失效且 manual/gold_etf_flows.json 无数据")
    rows = sorted(etf_flows, key=lambda x: x["month"])
    latest = rows[-1]
    stale = age_days(latest["month"], today) > th["freshness_days"]["monthly_manual"]["red"]
    flow = latest["monthly_flow_t"]
    flows2 = [r["monthly_flow_t"] for r in rows[-2:]]
    if flow >= 0:
        light, value = "green", "止跌/流入"
    elif len(flows2) == 2 and all(f < 0 for f in flows2):
        light, value = "red", "连续流出"
    else:
        light, value = "yellow", "单月流出"
    detail = (f"全球黄金 ETF {latest['month']} 净流量 {flow:+,.1f}t"
              f"(人工月度录入,来源 WGC goldhub)")
    return _sig("gold_etf", "gold", "黄金 ETF 流向", light, value, detail,
                {"monthly_flow_t": flow, "month": latest["month"], "source": "manual"},
                latest["month"], stale)


def _cb_gold(th, today, cb):
    if not cb:
        return _gray("cb_gold", "gold", "央行购金", "manual/central_bank_gold.json 无数据")
    rows = sorted(cb, key=lambda x: x["quarter"])
    stale = age_days(rows[-1]["quarter"], today) > th["freshness_days"]["quarterly"]["red"]
    latest = rows[-1]["net_purchases_t"]
    prev4 = [r["net_purchases_t"] for r in rows[-5:-1]]
    if len(prev4) < 2:
        light, value, cmp_txt = "neutral", "样本不足", "历史季度不足,无法比较"
    else:
        avg = sum(prev4) / len(prev4)
        if latest >= avg:
            light, value = "green", "购金力度维持"
        elif latest < avg * 0.5:
            light, value = "yellow", "边际明显减弱"
        else:
            light, value = "neutral", "略低于均值"
        cmp_txt = f"vs 前{len(prev4)}季均值 {avg:,.0f}t"
    detail = f"{rows[-1]['quarter']} 央行净购金 {latest:,.0f}t,{cmp_txt}(人工季度录入,来源 WGC)"
    return _sig("cb_gold", "gold", "央行购金", light, value, detail,
                {"quarter": rows[-1]["quarter"], "net_purchases_t": latest},
                rows[-1]["quarter"], stale)


def _gold_composite(parts, double_kill):
    bullish = sum(1 for p in parts if p["light"] == "green")
    usable = sum(1 for p in parts if p["light"] != "gray")
    names = {p["id"]: p["light"] for p in parts}
    forced_red = double_kill["light"] == "red" and not double_kill["stale"]
    if forced_red:
        light, value = "red", f"双杀触发(一票否决)| 看多条件 {bullish}/{usable}"
    elif usable == 0:
        light, value = "gray", "全部子信号数据缺失"
    elif bullish >= 4:
        light, value = "green", f"看多条件 {bullish}/{usable}"
    elif bullish >= 2:
        light, value = "yellow", f"看多条件 {bullish}/{usable}"
    else:
        light, value = "red", f"看多条件 {bullish}/{usable}"
    detail = ("计数展示(非黑箱打分):EMA/净多头/OI/ETF/央行购金 五项中绿灯数;"
              f"双杀组合触发时强制红灯。子信号状态:{names}")
    return {"id": "gold_composite", "group": "gold", "name": "黄金总灯",
            "light": light, "value": value, "detail": detail,
            "inputs": {"bullish": bullish, "usable": usable, "forced_red": forced_red},
            "as_of": max((p["as_of"] or "") for p in parts) or None,
            "stale": all(p["stale"] for p in parts)}


# ---------- 沪铜区 ----------

def _cu_range(th, today, cu):
    c = th["copper"]
    if not cu:
        return _gray("cu_range", "copper", "沪铜区间位置", "CU0 数据不足")
    stale = _is_stale(cu[-1]["date"], "daily", th, today)
    closes = [r["close"] for r in cu]
    p = closes[-1]
    span = c["range_top"] - c["support"]
    pos_pct = (p - c["support"]) / span * 100

    def _consec(cond):
        n = 0
        for v in reversed(closes):
            if cond(v):
                n += 1
            else:
                break
        return n

    below = _consec(lambda v: v < c["support"])
    above = _consec(lambda v: v > c["range_top"])
    if below >= c["breakdown_closes"]:
        light, value = "red", f"支撑失守(连续{below}收盘<{c['support']:,})"
    elif above >= c["breakout_closes"]:
        light, value = "green", f"向上突破(连续{above}收盘>{c['range_top']:,})"
    elif above > 0:
        light, value = "yellow", f"疑似突破(连续{above}收盘,需{c['breakout_closes']}日确认)"
    elif p <= c["support_buffer"]:
        light, value = "green", "点价支撑区(买点观察)"
    elif p < c["pressure"]:
        light, value = "yellow", "区间中部"
    else:
        light, value = "yellow", "压力带"
    detail = (f"CU0 收盘 {p:,.0f},区间 {c['support']:,}–{c['range_top']:,} 内位置 "
              f"{pos_pct:.0f}%。文章:{c['support']:,} 下游愿意点价=支撑,"
              f"{c['pressure']:,}–{c['range_top']:,} 有压力")
    return _sig("cu_range", "copper", "沪铜区间位置", light, value, detail,
                {"close": p, "range_pos_pct": round(pos_pct, 1),
                 "consec_below_support": below, "consec_above_top": above},
                cu[-1]["date"], stale)


def _cu_dip(th, today, cu, hy, wti):
    c = th["copper"]
    closes = [r["close"] for r in cu]
    w = c["dip_window_days"]
    if len(closes) <= w:
        return _gray("cu_dip_type", "copper", "回调性质判定", "CU0 数据不足")
    stale = _is_stale(cu[-1]["date"], "daily", th, today)
    chg_pct = (closes[-1] / closes[-1 - w] - 1) * 100
    if chg_pct > c["dip_pct"]:
        return _sig("cu_dip_type", "copper", "回调性质判定", "neutral",
                    "未触发", f"近{w}日 {chg_pct:+.1f}%,无≥{-c['dip_pct']}% 级别回调,"
                    "判定不激活(仅在显著回调时区分'宏观风险'与'非宏观扰动')",
                    {"chg_20d_pct": round(chg_pct, 1)}, cu[-1]["date"], stale)
    hv, wv = [v for _, v in hy], [v for _, v in wti]
    dhy, dwti_pct = delta(hv, w), None
    if len(wv) > w and wv[-1 - w]:
        dwti_pct = (wv[-1] / wv[-1 - w] - 1) * 100
    if dhy is None or dwti_pct is None:
        return _gray("cu_dip_type", "copper", "回调性质判定", "HY利差/WTI 数据不足")
    if dhy >= c["hy_widen_pp"]:
        light, value = "red", "宏观风险驱动,勿接"
    elif abs(dwti_pct) < c["wti_move_pct"] and dhy < c["hy_widen_pp"]:
        light, value = "green", "非宏观扰动回调(文章定义的买点)"
    else:
        light, value = "yellow", "地缘扰动型,谨慎"
    detail = (f"CU0 近{w}日 {chg_pct:+.1f}%(激活判定);同期 HY 利差 {dhy:+.2f}pp"
              f"(宏观风险线 +{c['hy_widen_pp']}),WTI {dwti_pct:+.1f}%"
              f"(地缘线 ±{c['wti_move_pct']}%)")
    return _sig("cu_dip_type", "copper", "回调性质判定", light, value, detail,
                {"chg_20d_pct": round(chg_pct, 1), "hy_d20_pp": round(dhy, 2),
                 "wti_d20_pct": round(dwti_pct, 1)}, cu[-1]["date"], stale)


def _copx_trend(th, today, copx, cu):
    c = th["copper"]
    n = c["copx_ema"]
    closes = [r["close"] for r in copx]
    if len(closes) < n + c["copx_slope_days"] + 1:
        return _gray("copx_trend", "copper", "COPX 领先趋势", "COPX 数据不足")
    stale = _is_stale(copx[-1]["date"], "daily", th, today)
    e = ema(closes, n)
    above = closes[-1] > e[-1]
    slope_up = e[-1] > e[-1 - c["copx_slope_days"]]
    if above and slope_up:
        light, value = "green", "铜矿股领先转强"
    elif above:
        light, value = "yellow", "站上均线但斜率未转正"
    else:
        light, value = "red", "趋势线下方"
    note = ""
    cu_closes = [r["close"] for r in cu]
    w = c["copx_slope_days"]
    if len(closes) > w and len(cu_closes) > w:
        div = ((closes[-1] / closes[-1 - w] - 1) - (cu_closes[-1] / cu_closes[-1 - w] - 1)) * 100
        if div > c["divergence_pp"]:
            note = f";COPX 近{w}日跑赢沪铜 {div:+.1f}pp,关注铜补涨(文章:COPX 领先铜价)"
        elif div < -c["divergence_pp"]:
            note = f";COPX 近{w}日落后沪铜 {div:+.1f}pp,警惕铜价趋势转弱"
    detail = (f"COPX {closes[-1]:.2f} vs EMA{n} {e[-1]:.2f}"
              f"({'上' if above else '下'}方),EMA 斜率{'向上' if slope_up else '向下'}{note}")
    return _sig("copx_trend", "copper", "COPX 领先趋势", light, value, detail,
                {"close": closes[-1], "ema": round(e[-1], 2), "above": above,
                 "slope_up": slope_up}, copx[-1]["date"], stale)
