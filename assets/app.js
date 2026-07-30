/* macro-watch 前端:fetch data/ 下的 CSV/JSON → 信号灯 + ECharts 图表。
 * 零构建、零外部依赖(echarts 已 vendor)。所有动态文本用 textContent 插入。 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var charts = [];   // {el, build} 主题切换时重建

  // ---------- 小工具 ----------
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function fetchText(url) {
    return fetch(url + (url.indexOf("?") < 0 ? "?_=" : "&_=") + Date.now())
      .then(function (r) { if (!r.ok) throw new Error(url + " -> " + r.status); return r.text(); });
  }
  function fetchJSON(url) { return fetchText(url).then(JSON.parse); }
  function parseCSV(text) {
    var lines = text.trim().split(/\r?\n/);
    var header = lines[0].split(",");
    var rows = [];
    for (var i = 1; i < lines.length; i++) {
      var parts = lines[i].split(",");
      if (parts.length !== header.length) continue;
      var row = {};
      for (var j = 0; j < header.length; j++) row[header[j]] = parts[j];
      rows.push(row);
    }
    return rows;
  }
  function lastN(arr, n) { return arr.length > n ? arr.slice(arr.length - n) : arr; }
  function ema(values, n) {
    if (values.length < n) return [];
    var k = 2 / (n + 1), sum = 0, i;
    for (i = 0; i < n; i++) sum += values[i];
    var out = [sum / n];
    for (i = n; i < values.length; i++) out.push(values[i] * k + out[out.length - 1] * (1 - k));
    return out; // 与 values[n-1:] 对齐
  }
  // 周期末龄期(天):YYYY-MM-DD / YYYY-MM / YYYYQn
  function ageDays(s) {
    if (!s) return 9999;
    var end;
    if (s.indexOf("Q") > 0) {
      var y = +s.slice(0, 4), q = +s.slice(5);
      end = new Date(Date.UTC(q === 4 ? y + 1 : y, (q % 4) * 3, 1) - 86400000);
    } else if (s.length === 7) {
      var y2 = +s.slice(0, 4), m = +s.slice(5, 7);
      end = new Date(Date.UTC(m === 12 ? y2 + 1 : y2, m % 12, 1) - 86400000);
    } else {
      end = new Date(s.slice(0, 10) + "T00:00:00Z");
    }
    return Math.floor((Date.now() - end.getTime()) / 86400000);
  }

  var LIGHT_META = {
    green:   { icon: "🟢", cls: "green" },
    yellow:  { icon: "🟡", cls: "yellow" },
    red:     { icon: "🔴", cls: "red" },
    neutral: { icon: "⚪", cls: "neutral" },
    gray:    { icon: "◌",  cls: "gray" }
  };
  var GROUP_ANCHOR = { fed: "sec-fed", ai: "sec-ai", gold: "sec-gold", copper: "sec-copper" };

  // ---------- ECharts 公共 ----------
  function baseOpt() {
    return {
      animation: false,
      grid: { left: 56, right: 18, top: 30, bottom: 28, containLabel: false },
      textStyle: { color: cssVar("--muted"), fontSize: 11.5 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross", label: { backgroundColor: cssVar("--baseline") } },
        backgroundColor: cssVar("--surface"),
        borderColor: cssVar("--border"),
        textStyle: { color: cssVar("--ink"), fontSize: 12.5 },
        valueFormatter: function (v) {
          return (v === null || v === undefined) ? "-" : (+v).toLocaleString("en-US", { maximumFractionDigits: 2 });
        }
      },
      legend: { top: 0, right: 0, textStyle: { color: cssVar("--ink-2"), fontSize: 12 }, itemWidth: 14, itemHeight: 9 }
    };
  }
  function axes(dates, yFmt) {
    return {
      xAxis: {
        type: "category", data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: cssVar("--baseline") } },
        axisTick: { show: false },
        axisLabel: { color: cssVar("--muted"), hideOverlap: true }
      },
      yAxis: {
        type: "value", scale: true,
        axisLabel: { color: cssVar("--muted"), formatter: yFmt },
        splitLine: { lineStyle: { color: cssVar("--grid"), width: 1 } }
      }
    };
  }
  function lineSeries(name, data, color, extra) {
    var s = {
      name: name, type: "line", data: data, symbol: "none",
      lineStyle: { width: 2, color: color }, itemStyle: { color: color },
      emphasis: { disabled: true }
    };
    if (extra) Object.keys(extra).forEach(function (k) { s[k] = extra[k]; });
    return s;
  }
  function markLines(items) {
    return {
      silent: true, symbol: "none",
      label: { position: "insideEndTop", color: cssVar("--ink-2"), fontSize: 11 },
      data: items.map(function (it) {
        return { yAxis: it.y, name: it.label,
          label: { formatter: it.label },
          lineStyle: { color: it.color, type: "dashed", width: 1 } };
      })
    };
  }
  function registerChart(id, build) {
    var dom = $(id);
    if (!dom) return;
    var entry = { dom: dom, build: build, inst: null };
    charts.push(entry);
    renderChart(entry);
  }
  function renderChart(entry) {
    try {
      if (entry.inst) { entry.inst.dispose(); }
      entry.inst = echarts.init(entry.dom);
      var opt = entry.build();
      if (!opt) { chartEmpty(entry); return; }
      entry.inst.setOption(opt);
    } catch (e) {
      chartEmpty(entry);
      if (window.console) console.error("chart failed:", entry.dom.id, e);
    }
  }
  function chartEmpty(entry) {
    if (entry.inst) entry.inst.dispose();
    entry.inst = null;
    entry.dom.textContent = "数据缺失或采集失败,详见数据新鲜度表";
    entry.dom.classList.add("err");
  }
  function rebuildAll() { charts.forEach(renderChart); }
  window.addEventListener("resize", function () {
    charts.forEach(function (c) { if (c.inst) c.inst.resize(); });
  });

  // ---------- 主题切换 ----------
  $("themeToggle").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = root.dataset.theme === "dark" ||
      (root.dataset.theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.dataset.theme = dark ? "light" : "dark";
    localStorage.setItem("mw-theme", root.dataset.theme);
    rebuildAll();
  });

  // ---------- 数据加载 ----------
  var D = {};  // 所有数据集
  function loadCSV(key, path, mapper) {
    return fetchText(path).then(function (t) { D[key] = parseCSV(t).map(mapper); })
      .catch(function () { D[key] = null; });
  }
  var numRow = function (fields) {
    return function (r) {
      var o = { date: r.date || r.report_date || r.month || r.quarter };
      fields.forEach(function (f) { o[f] = r[f] === "" || r[f] === undefined ? null : +r[f]; });
      return o;
    };
  };

  var FRED = ["T10YIE", "DFII10", "PCETRIM12M159SFRBDAL", "DGS30", "T10Y2Y", "UNRATE",
              "BAMLH0A0HYM2", "DCOILWTICO", "NASDAQCOM"];
  var loads = FRED.map(function (s) { return loadCSV("fred_" + s, "data/fred/" + s + ".csv", numRow(["value"])); });
  loads.push(loadCSV("gold", "data/market/gold_usd_daily.csv", numRow(["close"])));
  loads.push(loadCSV("copx", "data/market/copx_daily.csv", numRow(["close"])));
  loads.push(loadCSV("cu", "data/market/cu0_daily.csv", numRow(["open", "high", "low", "close", "volume", "oi"])));
  loads.push(loadCSV("cot_gold", "data/cot/gold_legacy.csv", numRow(["net_long", "open_interest"])));
  loads.push(fetchJSON("data/signals.json").then(function (j) { D.signals = j; }).catch(function () { D.signals = null; }));
  loads.push(fetchJSON("data/status.json").then(function (j) { D.status = j; }).catch(function () { D.status = null; }));
  loads.push(fetchJSON("config/thresholds.json").then(function (j) { D.th = j; }).catch(function () { D.th = null; }));
  loads.push(fetchJSON("data/manual/gold_etf_flows.json").then(function (j) { D.etf = j; }).catch(function () { D.etf = null; }));
  loads.push(fetchJSON("data/manual/central_bank_gold.json").then(function (j) { D.cb = j; }).catch(function () { D.cb = null; }));
  loads.push(fetchJSON("data/manual/ai_capex.json").then(function (j) { D.capex = j; }).catch(function () { D.capex = null; }));

  Promise.all(loads).then(render);

  // ---------- 渲染 ----------
  function render() {
    renderSignals();
    renderCharts();
    renderStatus();
    renderMethodology();
    renderFooter();
  }

  function sigById(id) {
    if (!D.signals) return null;
    for (var i = 0; i < D.signals.signals.length; i++)
      if (D.signals.signals[i].id === id) return D.signals.signals[i];
    return null;
  }

  function signalCard(sig) {
    var meta = LIGHT_META[sig.light] || LIGHT_META.gray;
    var card = el("div", "signal");
    var head = el("div", "head");
    head.appendChild(el("span", "dot " + meta.cls));
    head.appendChild(el("span", "name", sig.name));
    head.appendChild(el("span", "light-icon", meta.icon));
    card.appendChild(head);
    card.appendChild(el("div", "val", sig.value));
    if (sig.as_of) card.appendChild(el("div", "asof", "数据至 " + sig.as_of));
    card.title = sig.detail || "";
    card.addEventListener("click", function () {
      var anchor = GROUP_ANCHOR[sig.group];
      if (anchor) $(anchor).scrollIntoView();
    });
    return card;
  }

  function headlineTile(label, sig, extraText) {
    var t = el("div", "tile");
    t.appendChild(el("div", "label", label));
    var v = el("div", "value");
    if (sig) {
      var meta = LIGHT_META[sig.light] || LIGHT_META.gray;
      v.appendChild(el("span", "dot " + meta.cls));
      v.appendChild(el("span", null, sig.value));
    } else {
      v.appendChild(el("span", null, extraText || "数据缺失"));
    }
    t.appendChild(v);
    if (sig && extraText) t.appendChild(el("div", "label", extraText));
    return t;
  }

  function renderSignals() {
    var grid = $("signalGrid"), head = $("headline");
    if (!D.signals) {
      head.appendChild(el("div", "tile err", "signals.json 加载失败——请先运行 pipeline 采集"));
      return;
    }
    // 顶部三横条
    var scen = D.signals.scenario || {};
    var scenTile = el("div", "tile");
    scenTile.appendChild(el("div", "label", "三情景倾向(判定依据见 AI 区)"));
    scenTile.appendChild(el("div", "value", scen.label || "未知"));
    if (scen.conditions) scenTile.title = scen.conditions.join("\n");
    head.appendChild(scenTile);

    var rt = D.status && D.status.extra && D.status.extra.cu0_realtime;
    head.appendChild(headlineTile("黄金总灯", sigById("gold_composite")));
    head.appendChild(headlineTile("沪铜区间", sigById("cu_range"),
      rt ? "盘中快照 " + rt.price.toLocaleString("en-US") + "(" + rt.date + " " + rt.time + ")" : null));

    // 信号矩阵 + 各区详情块
    var groupBox = { fed: $("fedDetails"), ai: $("aiDetails"), gold: $("goldDetails"), copper: $("copperDetails") };
    D.signals.signals.forEach(function (sig) {
      grid.appendChild(signalCard(sig));
      var box = groupBox[sig.group];
      if (box) {
        var meta = LIGHT_META[sig.light] || LIGHT_META.gray;
        var d = el("div", "sig-detail");
        var b = el("b", null, meta.icon + " " + sig.name + ":" + sig.value);
        d.appendChild(b);
        d.appendChild(document.createTextNode(" — " + (sig.detail || "")));
        box.appendChild(d);
      }
    });
  }

  // ---------- 图表 ----------
  function seriesOf(key) { return D[key] ? D[key].filter(function (r) { return r.value !== null; }) : null; }

  function simpleLine(id, key, opts) {
    registerChart(id, function () {
      var rows = seriesOf(key);
      if (!rows || !rows.length) return null;
      rows = lastN(rows, opts.n || 756);
      var o = baseOpt();
      var ax = axes(rows.map(function (r) { return r.date; }), opts.yFmt);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      var s = lineSeries(opts.name, rows.map(function (r) { return r.value; }), cssVar("--s1"));
      if (opts.area) s.areaStyle = { color: cssVar("--s1"), opacity: 0.1 };
      if (opts.marks) s.markLine = markLines(opts.marks());
      o.series = [s];
      return o;
    });
  }

  function renderCharts() {
    var th = D.th || {};
    var fed = th.fed || {}, copper = th.copper || {};

    simpleLine("ch-t10yie", "fred_T10YIE", {
      name: "T10YIE", n: 756, area: true,
      marks: function () {
        return [
          { y: fed.t10yie_hawk || 2.5, label: "警戒 " + (fed.t10yie_hawk || 2.5), color: cssVar("--critical") },
          { y: fed.t10yie_warn || 2.4, label: "接近 " + (fed.t10yie_warn || 2.4), color: cssVar("--warning") }
        ];
      }
    });

    registerChart("ch-doublekill", function () {
      var a = seriesOf("fred_T10YIE"), b = seriesOf("fred_DFII10");
      if (!a || !b) return null;
      a = lastN(a, 504); b = lastN(b, 504);
      var dates = a.map(function (r) { return r.date; });
      var bMap = {};
      b.forEach(function (r) { bMap[r.date] = r.value; });
      var o = baseOpt();
      var ax = axes(dates, null);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.series = [
        lineSeries("通胀预期 T10YIE", a.map(function (r) { return r.value; }), cssVar("--s1")),
        lineSeries("实际利率 DFII10", dates.map(function (d) { return bMap[d] !== undefined ? bMap[d] : null; }), cssVar("--s2"), { connectNulls: true })
      ];
      return o;
    });

    simpleLine("ch-pce", "fred_PCETRIM12M159SFRBDAL", {
      name: "Trimmed PCE", n: 120,
      marks: function () {
        return [{ y: fed.pce_dove || 2.0, label: "降息条件 " + (fed.pce_dove || 2.0), color: cssVar("--good") }];
      }
    });
    simpleLine("ch-unrate", "fred_UNRATE", { name: "UNRATE", n: 120 });
    simpleLine("ch-t10y2y", "fred_T10Y2Y", {
      name: "10Y-2Y", n: 756, area: true,
      marks: function () { return [{ y: 0, label: "0", color: cssVar("--baseline") }]; }
    });

    registerChart("ch-dgs30", function () {
      var rows = seriesOf("fred_DGS30");
      if (!rows || !rows.length) return null;
      rows = lastN(rows, 756);
      var sig = sigById("curve_steepening");
      var o = baseOpt();
      var ax = axes(rows.map(function (r) { return r.date; }), null);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      var s = lineSeries("DGS30", rows.map(function (r) { return r.value; }), cssVar("--s1"));
      if (sig && sig.inputs && sig.inputs.dgs30_prior_high) {
        s.markLine = markLines([{ y: sig.inputs.dgs30_prior_high, label: "一年前高 " + sig.inputs.dgs30_prior_high, color: cssVar("--warning") }]);
      }
      o.series = [s];
      return o;
    });

    registerChart("ch-ixic", function () {
      var rows = seriesOf("fred_NASDAQCOM");
      if (!rows || !rows.length) return null;
      rows = lastN(rows, 504);
      var sig = sigById("nasdaq_high");
      var o = baseOpt();
      var ax = axes(rows.map(function (r) { return r.date; }), function (v) { return (v / 1000) + "k"; });
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      var s = lineSeries("纳指", rows.map(function (r) { return r.value; }), cssVar("--s1"));
      if (sig && sig.inputs && sig.inputs.prior_high) {
        s.markLine = markLines([{ y: sig.inputs.prior_high, label: "一年前高", color: cssVar("--warning") }]);
      }
      o.series = [s];
      return o;
    });

    simpleLine("ch-hy", "fred_BAMLH0A0HYM2", { name: "HY OAS", n: 756, area: true });
    simpleLine("ch-wti", "fred_DCOILWTICO", { name: "WTI", n: 756 });

    registerChart("ch-capex", function () {
      if (!D.capex || !D.capex.series || !D.capex.series.length) return null;
      var rows = D.capex.series.slice().sort(function (x, y) { return x.quarter < y.quarter ? -1 : 1; });
      var quarters = rows.map(function (r) { return r.quarter; });
      var o = baseOpt();
      o.tooltip.axisPointer.type = "shadow";
      var ax = axes(quarters, null);
      ax.xAxis.boundaryGap = true;
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      var colors = [cssVar("--s1"), cssVar("--s2"), cssVar("--s3"), cssVar("--muted")];
      o.series = ["MSFT", "GOOG", "META", "AMZN"].map(function (k, i) {
        return {
          name: k, type: "bar", barMaxWidth: 24,
          itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] },
          data: rows.map(function (r) { return r[k]; })
        };
      });
      return o;
    });

    registerChart("ch-gold", function () {
      var rows = D.gold;
      if (!rows || rows.length < 210) return null;
      var closes = rows.map(function (r) { return r.close; });
      var period = (th.gold && th.gold.ema_period) || 200;
      var e = ema(closes, period);              // 对齐 closes[period-1:]
      var view = 756;
      var vRows = lastN(rows, view);
      var emaByIdx = {};
      for (var i = 0; i < e.length; i++) emaByIdx[period - 1 + i] = e[i];
      var start = rows.length - vRows.length;
      var o = baseOpt();
      var ax = axes(vRows.map(function (r) { return r.date; }), null);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.series = [
        lineSeries("LBMA PM", vRows.map(function (r) { return r.close; }), cssVar("--s1")),
        lineSeries("EMA" + period, vRows.map(function (r, idx) {
          var v = emaByIdx[start + idx];
          return v === undefined ? null : +v.toFixed(1);
        }), cssVar("--s2"), { connectNulls: true })
      ];
      return o;
    });

    registerChart("ch-netlong", function () {
      var rows = D.cot_gold;
      if (!rows || !rows.length) return null;
      rows = lastN(rows, 260);
      var o = baseOpt();
      var ax = axes(rows.map(function (r) { return r.date; }), function (v) { return (v / 1000) + "k"; });
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      var s = lineSeries("净多头", rows.map(function (r) { return r.net_long; }), cssVar("--s1"));
      s.areaStyle = { color: cssVar("--s1"), opacity: 0.1 };
      o.series = [s];
      return o;
    });

    registerChart("ch-goldoi", function () {
      var rows = D.cot_gold;
      if (!rows || !rows.length) return null;
      rows = lastN(rows, 260);
      var o = baseOpt();
      var ax = axes(rows.map(function (r) { return r.date; }), function (v) { return (v / 1000) + "k"; });
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      o.series = [lineSeries("OI", rows.map(function (r) { return r.open_interest; }), cssVar("--s1"))];
      return o;
    });

    registerChart("ch-etf", function () {
      if (!D.etf || !D.etf.series || !D.etf.series.length) return null;
      var rows = D.etf.series.slice().sort(function (x, y) { return x.month < y.month ? -1 : 1; });
      var o = baseOpt();
      o.tooltip.axisPointer.type = "shadow";
      var ax = axes(rows.map(function (r) { return r.month; }), null);
      ax.xAxis.boundaryGap = true;
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      o.series = [{
        name: "月度净流量(吨)", type: "bar", barMaxWidth: 24,
        itemStyle: { color: cssVar("--s1"), borderRadius: [4, 4, 0, 0] },
        data: rows.map(function (r) { return r.monthly_flow_t; })
      }];
      return o;
    });

    registerChart("ch-cb", function () {
      if (!D.cb || !D.cb.series || !D.cb.series.length) return null;
      var rows = D.cb.series.slice().sort(function (x, y) { return x.quarter < y.quarter ? -1 : 1; });
      var o = baseOpt();
      o.tooltip.axisPointer.type = "shadow";
      var ax = axes(rows.map(function (r) { return r.quarter; }), null);
      ax.xAxis.boundaryGap = true;
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.legend.show = false;
      o.series = [{
        name: "央行净购金(吨)", type: "bar", barMaxWidth: 24,
        itemStyle: { color: cssVar("--s1"), borderRadius: [4, 4, 0, 0] },
        data: rows.map(function (r) { return r.net_purchases_t; })
      }];
      return o;
    });

    registerChart("ch-cu", function () {
      var rows = D.cu;
      if (!rows || !rows.length) return null;
      rows = lastN(rows, 300);
      var dates = rows.map(function (r) { return r.date; });
      var o = baseOpt();
      o.grid = [
        { left: 64, right: 18, top: 26, height: "58%" },
        { left: 64, right: 18, top: "76%", height: "16%" }
      ];
      o.legend.show = false;
      o.tooltip.axisPointer.type = "cross";
      o.xAxis = [
        { type: "category", data: dates, boundaryGap: true, gridIndex: 0,
          axisLine: { lineStyle: { color: cssVar("--baseline") } }, axisTick: { show: false },
          axisLabel: { show: false } },
        { type: "category", data: dates, boundaryGap: true, gridIndex: 1,
          axisLine: { lineStyle: { color: cssVar("--baseline") } }, axisTick: { show: false },
          axisLabel: { color: cssVar("--muted"), hideOverlap: true } }
      ];
      o.yAxis = [
        { type: "value", scale: true, gridIndex: 0,
          axisLabel: { color: cssVar("--muted"), formatter: function (v) { return (v / 1000) + "k"; } },
          splitLine: { lineStyle: { color: cssVar("--grid"), width: 1 } } },
        { type: "value", scale: true, gridIndex: 1, axisLabel: { show: false },
          splitLine: { show: false } }
      ];
      // 沪市习惯:红涨绿跌
      var up = cssVar("--critical"), down = cssVar("--good");
      o.series = [
        {
          name: "CU0", type: "candlestick", xAxisIndex: 0, yAxisIndex: 0,
          data: rows.map(function (r) { return [r.open, r.close, r.low, r.high]; }),
          itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down },
          markLine: markLines([
            { y: copper.support || 95000, label: "支撑 " + ((copper.support || 95000) / 1000) + "k", color: cssVar("--good") },
            { y: copper.pressure || 105000, label: "压力 " + ((copper.pressure || 105000) / 1000) + "k", color: cssVar("--warning") },
            { y: copper.range_top || 110000, label: "区间顶 " + ((copper.range_top || 110000) / 1000) + "k", color: cssVar("--critical") }
          ])
        },
        {
          name: "持仓量", type: "line", xAxisIndex: 1, yAxisIndex: 1, symbol: "none",
          lineStyle: { width: 1.5, color: cssVar("--s3") },
          data: rows.map(function (r) { return r.oi; })
        }
      ];
      return o;
    });

    registerChart("ch-copx", function () {
      var rows = D.copx;
      if (!rows || rows.length < 80) return null;
      var closes = rows.map(function (r) { return r.close; });
      var n = copper.copx_ema || 50;
      var e = ema(closes, n);
      var view = lastN(rows, 504);
      var start = rows.length - view.length;
      var emaByIdx = {};
      for (var i = 0; i < e.length; i++) emaByIdx[n - 1 + i] = e[i];
      var o = baseOpt();
      var ax = axes(view.map(function (r) { return r.date; }), null);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.series = [
        lineSeries("COPX", view.map(function (r) { return r.close; }), cssVar("--s1")),
        lineSeries("EMA" + n, view.map(function (r, idx) {
          var v = emaByIdx[start + idx];
          return v === undefined ? null : +v.toFixed(2);
        }), cssVar("--s2"), { connectNulls: true })
      ];
      return o;
    });

    registerChart("ch-copxcu", function () {
      if (!D.copx || !D.cu) return null;
      var cu = lastN(D.cu, 252);
      if (cu.length < 30) return null;
      var copxMap = {};
      D.copx.forEach(function (r) { copxMap[r.date] = r.close; });
      var lastCopx = null, base_cu = cu[0].close, base_copx = null;
      var dates = [], cuIdx = [], copxIdx = [];
      cu.forEach(function (r) {
        if (copxMap[r.date] !== undefined) lastCopx = copxMap[r.date];  // 前向填充(交易日历不同)
        if (lastCopx === null) return;
        if (base_copx === null) { base_copx = lastCopx; base_cu = r.close; }
        dates.push(r.date);
        cuIdx.push(+(r.close / base_cu * 100).toFixed(2));
        copxIdx.push(+(lastCopx / base_copx * 100).toFixed(2));
      });
      var o = baseOpt();
      var ax = axes(dates, null);
      o.xAxis = ax.xAxis; o.yAxis = ax.yAxis;
      o.series = [
        lineSeries("沪铜(=100)", cuIdx, cssVar("--s1")),
        lineSeries("COPX(=100)", copxIdx, cssVar("--s2"))
      ];
      return o;
    });
  }

  // ---------- 数据新鲜度表 ----------
  function freshnessLight(src) {
    if (!src.ok && !src.last_success) return { icon: "🔴", txt: "从未成功" };
    var fd = (D.th && D.th.freshness_days) || {};
    var band = fd[src.freq] || fd.daily || { yellow: 4, red: 7 };
    var age = ageDays(src.latest_date);
    if (!src.ok) return { icon: "🔴", txt: "本次失败" };
    if (age > band.red) return { icon: "🔴", txt: age + " 天未更新" };
    if (age > band.yellow) return { icon: "🟡", txt: age + " 天前" };
    return { icon: "🟢", txt: age <= 0 ? "最新" : age + " 天前" };
  }

  function renderStatus() {
    var table = $("statusTable");
    if (!D.status) {
      table.appendChild(el("caption", "err", "status.json 加载失败"));
      return;
    }
    var thead = el("tr");
    ["状态", "数据源", "频率", "最新数据日", "最后成功采集(UTC)", "行数", "错误"].forEach(function (h) {
      thead.appendChild(el("th", null, h));
    });
    table.appendChild(thead);
    Object.keys(D.status.sources).sort().forEach(function (sid) {
      var s = D.status.sources[sid];
      var f = freshnessLight(s);
      var tr = el("tr");
      tr.appendChild(el("td", null, f.icon + " " + f.txt));
      tr.appendChild(el("td", null, sid));
      tr.appendChild(el("td", null, s.freq || "-"));
      tr.appendChild(el("td", "num", s.latest_date || "-"));
      tr.appendChild(el("td", "num", s.last_success ? s.last_success.replace("T", " ").replace("Z", "") : "-"));
      tr.appendChild(el("td", "num", String(s.rows || 0)));
      tr.appendChild(el("td", "err", s.error || ""));
      table.appendChild(tr);
    });
  }

  // ---------- 方法论 ----------
  function renderMethodology() {
    var box = $("methodology");
    var th = D.th || {};
    var f = th.fed || {}, dk = th.double_kill || {}, g = th.gold || {}, c = th.copper || {},
        nq = th.nasdaq || {}, sc = th.scenario || {};
    var items = [
      ["联储反应区间", "T10YIE ≥ " + f.t10yie_hawk + " → 鹰派警戒;Trimmed PCE ≤ " + f.pce_dove +
        " 或 Sahm gap ≥ " + f.sahm_trigger + "(失业率3月均值−12个月内最低3月均值,即'失业率明显走高'的量化)→ 降息条件成立;其余为按兵不动区。"],
      ["黄金双杀组合", "近 " + dk.window_days + " 交易日内,通胀预期变化 ≤ " + dk.t10yie_drop_pp +
        "pp 且实际利率变化 ≥ +" + dk.dfii10_rise_pp + "pp 同时成立 → 触发(红)。文章语义:黄金最不利组合,一票否决黄金总灯。"],
      ["曲线陡峭化", "10Y−2Y 近 " + (th.curve || {}).window_days + " 日走扩 ≥ +" + (th.curve || {}).steepen_pp +
        "pp,或 30Y ≥ 前 " + (th.curve || {}).high_lookback_days + " 交易日高点 → 市场在自行收紧。"],
      ["纳指 vs 前高(追铜)", "收盘 ≥ 前 " + nq.high_lookback_days + " 交易日最高收盘,且发生在近 " + nq.recent_days +
        " 日内 → 追铜信号有效;距前高 " + nq.near_pct + "% 以内 → 逼近。"],
      ["AI Capex 增速", "四家(MSFT/GOOG/META/AMZN)季度 Capex 合计的 YoY;连续两季回落 → 放缓确认(情景②权重上升)。仅在本季与上年同季四家数据都齐时计算。"],
      ["三情景倾向", "WTI " + sc.wti_window_days + " 日 ≥ +" + sc.wti_surge_pct + "% 或处 " + sc.wti_pctile_years +
        " 年 " + sc.wti_pctile + " 分位 → 情景③(一票优先);纳指破前高且 10Y 利率 " + sc.rate_window_days +
        " 日未回落 → 情景①;Capex 放缓确认且 10Y 回落 → 情景②。"],
      ["金价 vs EMA" + g.ema_period, "GC=F 收盘与 EMA" + g.ema_period + "(SMA 种子标准算法)。站上=绿,站下=红。"],
      ["CFTC 净多头分位", "legacy 报告非商业净多头(作管理基金代理,与 disaggregated 的 managed money 高度同向)在 " +
        g.netlong_window_weeks + " 周窗口的分位:" + g.netlong_mid_lo + "–" + g.netlong_mid_hi + "% 且近 " +
        g.netlong_delta_weeks + " 周回升 → 中位回暖(文章看多条件);>" + g.netlong_crowded + "% 拥挤;<" + g.netlong_washed + "% 极度悲观。"],
      ["COMEX OI", "较 " + g.oi_low_weeks + " 周低点反弹 ≥ " + g.oi_rebound_pct + "% 且近 " + g.oi_delta_weeks +
        " 周走高 → 见底反弹;创 " + g.oi_low_weeks + " 周新低 → 持续离场。"],
      ["黄金 ETF 流向", "优先 SPDR 官方吨位自动源(" + g.etf_auto_max_age_days + " 天内有效);失效时用 WGC 人工月度净流量:最新月 ≥0 → 止跌;连续两月为负 → 连续流出。"],
      ["央行购金", "最新季度 vs 前四季均值:≥ 均值 → 力度维持;< 均值一半 → 明显减弱。"],
      ["黄金总灯", "五项看多条件计数(非黑箱打分),双杀触发时强制红。"],
      ["沪铜区间位置", "支撑 " + c.support + "(缓冲至 " + c.support_buffer + ")/ 压力 " + c.pressure + " / 区间顶 " + c.range_top +
        ";向上突破需连续 " + c.breakout_closes + " 个收盘确认,支撑失守需连续 " + c.breakdown_closes + " 个收盘。"],
      ["回调性质判定", "仅当沪铜近 " + c.dip_window_days + " 日 ≤ " + c.dip_pct + "% 时激活:HY 利差同期走扩 < +" + c.hy_widen_pp +
        "pp 且 WTI 变动 < ±" + c.wti_move_pct + "% → 非宏观扰动回调(文章买点);HY 利差走扩 ≥ +" + c.hy_widen_pp + "pp → 宏观风险,勿接。"],
      ["COPX 领先趋势", "COPX vs EMA" + c.copx_ema + ":站上且斜率(" + c.copx_slope_days + " 日)向上 → 转强;近 " +
        c.copx_slope_days + " 日相对沪铜收益差 > ±" + c.divergence_pp + "pp 时提示领先/背离。"],
      ["数据口径与降级", "国际金价=LBMA PM 定盘价(USD);纳指=FRED NASDAQCOM(综合指数);沪铜=新浪主力连续 CU0;" +
        "COPX=新浪美股日K;COT=CFTC legacy futures-only(Yahoo 对数据中心 IP 拦截,已弃用)。" +
        "SPDR GLD 官方持仓端点当前失效(返回 PDF),采集器保留探测,恢复即自动接管;失效期间 ETF 信号用 WGC 人工月度数据。" +
        "任何数据源过期(阈值见 config)对应信号强制转灰——宁灰勿错。"]
    ];
    items.forEach(function (it) {
      var d = el("details", "method");
      d.appendChild(el("summary", null, it[0]));
      d.appendChild(el("p", null, it[1]));
      box.appendChild(d);
    });
  }

  function renderFooter() {
    var f = $("footer");
    var gen = D.signals ? D.signals.generated_at : null;
    f.textContent = "macro-watch · 信号生成于 " + (gen || "未知") +
      "(UTC)· 数据仅供个人研究参考,不构成投资建议 · 框架出处:公众号「市场评论和展望」";
  }
})();
