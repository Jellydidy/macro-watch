"""采集公共层:HTTP 重试、原子写、CSV 读写、行数护栏、状态记录。

可靠性约定:
- 纯标准库实现(urllib),零第三方依赖 —— 实测某些网络环境会选择性阻断
  requests/urllib3 的 TLS 指纹而放行 urllib,且少一个依赖多十年可维护性;
- 单源失败绝不影响其他源(run_all 逐源 try/except);
- 全量覆盖类数据在写盘前做行数护栏,响应异常时保留旧文件;
- status.json 中失败源保留历史 last_success,只更新 last_attempt/error。
"""
import concurrent.futures
import csv
import gzip
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CONFIG = os.path.join(ROOT, "config", "thresholds.json")

# 诚实 UA:实测 FRED(Akamai)对"假浏览器指纹"(curl/urllib 报 Chrome UA)直接掐流,
# 对诚实的工具 UA 反而放行。伪装是负收益,别改回浏览器 UA。
UA = "macro-watch/1.0 (+https://github.com/Jellydidy/macro-watch)"

# 行数护栏:新数据行数低于旧数据的该比例视为响应异常,拒绝覆盖
GUARD_RATIO = 0.95


class GuardError(Exception):
    """新数据行数异常收缩,拒绝覆盖旧文件。"""


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_thresholds():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


class Response:
    """轻量响应对象,接口对齐 requests 的常用子集。"""

    def __init__(self, status_code, headers, content):
        self.status_code = status_code
        self.headers = dict(headers)
        self.content = content

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


def _get_once(url, headers, timeout, deadline):
    """urllib 单次请求。分块读 + 总时限死线:防"滴流"型网络干扰
    (中间设备每隔数秒送一点数据,socket 超时永不触发,读挂死)。"""
    req = urllib.request.Request(url, headers=headers)
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        chunks = []
        while True:
            if time.monotonic() - start > deadline:
                raise TimeoutError(f"total deadline {deadline}s exceeded (drip-feed?)")
            chunk = r.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        if r.headers.get("Content-Encoding", "") == "gzip":
            content = gzip.decompress(content)
        return Response(r.status, r.headers.items(), content)


def _get_curl(url, headers, deadline):
    """curl 子进程兜底:HTTP/2 + 不同 TLS 栈,实测在 urllib 被干扰的网络下仍稳定。"""
    cmd = ["curl", "-sS", "--fail", "--compressed",
           "--retry", "3", "--retry-delay", "2", "--retry-all-errors",
           "--max-time", str(deadline),
           "-w", "\\n%{http_code}\\n%{content_type}", "--output", "-"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, timeout=deadline + 10, check=True)
    body, code, ctype = p.stdout.rsplit(b"\n", 2)
    status = int(code)
    if status >= 400:
        raise urllib.error.HTTPError(url, status, "curl fallback got error status",
                                     None, None)
    return Response(status, [("Content-Type", ctype.decode("ascii", "replace"))], body)


_prefer_curl = False  # 本进程内出现过滴流超时后置 True:后续请求 curl 优先


def fetch(url, headers=None, params=None, timeout=30, retries=3, deadline=None):
    global _prefer_curl
    if deadline is None:
        deadline = int(os.environ.get("MW_DEADLINE", "90"))  # 本地坏网络可调小快速探测
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(params)
    if _prefer_curl and shutil.which("curl"):
        try:
            return _get_curl(url, h, deadline)
        except Exception:  # noqa: BLE001 - curl 失败则回落到 urllib 正常流程
            pass
    delays = [2, 5, 10]
    last_err = None
    for i in range(retries):
        # 线程级硬超时:滴流发生在响应头阶段时,urlopen 内部 readline 也会挂死,
        # socket 超时被不断重置,只有外部硬超时能兜住。
        # 注意不能用 with(shutdown 会 join 挂死的线程),必须 wait=False。
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(_get_once, url, h, timeout, deadline)
            return fut.result(timeout=deadline + 15)
        except Exception as e:  # noqa: BLE001 - 重试/兜底后由调用方统一记录
            last_err = e
            if isinstance(e, TimeoutError):
                _prefer_curl = True
                break  # 滴流/超时型干扰重试无意义,直接走 curl 兜底
            if i < retries - 1:
                time.sleep(delays[min(i, len(delays) - 1)])
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    if shutil.which("curl"):
        try:
            return _get_curl(url, h, deadline)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise last_err


def atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def read_csv_dicts(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def count_data_rows(path):
    rows = read_csv_dicts(path)
    return len(rows)


def write_csv_guarded(path, header, rows):
    """全量覆盖写 CSV,带行数护栏。rows 为 list[list]。"""
    if os.path.exists(path):
        old_n = count_data_rows(path)
        if old_n > 0 and len(rows) < old_n * GUARD_RATIO:
            raise GuardError(
                f"row guard: new={len(rows)} < old={old_n} * {GUARD_RATIO}, refuse to overwrite")
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(str(x) for x in r))
    atomic_write(path, "\n".join(lines) + "\n")


def fmt_num(v):
    """浮点落盘格式:去掉无意义尾零,最多 4 位小数。"""
    if v is None:
        return ""
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"
    return str(v)


class Status:
    """data/status.json 的读改写。失败时保留 last_success,只更新 last_attempt。"""

    PATH = os.path.join(DATA, "status.json")

    def __init__(self):
        self.doc = {"generated_at": None, "sources": {}, "extra": {}}
        if os.path.exists(self.PATH):
            try:
                with open(self.PATH, encoding="utf-8") as f:
                    old = json.load(f)
                if isinstance(old.get("sources"), dict):
                    self.doc["sources"] = old["sources"]
                if isinstance(old.get("extra"), dict):
                    self.doc["extra"] = old["extra"]
            except (json.JSONDecodeError, OSError):
                pass  # 状态文件损坏时从零开始,不阻塞采集

    def record(self, source_id, ok, rows=0, latest_date=None, error=None, freq=None):
        prev = self.doc["sources"].get(source_id, {})
        now = now_utc()
        entry = {
            "ok": bool(ok),
            "last_attempt": now,
            "last_success": now if ok else prev.get("last_success"),
            "error": None if ok else str(error)[:500],
            "rows": rows if ok else prev.get("rows", 0),
            "latest_date": latest_date if ok else prev.get("latest_date"),
            "freq": freq or prev.get("freq"),
        }
        self.doc["sources"][source_id] = entry
        flag = "OK " if ok else "FAIL"
        print(f"[{flag}] {source_id}: rows={entry['rows']} latest={entry['latest_date']}"
              + ("" if ok else f" error={entry['error']}"))

    def set_extra(self, key, value):
        self.doc["extra"][key] = value

    def save(self):
        self.doc["generated_at"] = now_utc()
        atomic_write(self.PATH, json.dumps(self.doc, ensure_ascii=False, indent=1))
