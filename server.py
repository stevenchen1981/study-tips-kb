#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""study-tips-kb 看板服务（Kindle 友好，多科目）。

Kindle 固定访问: http://192.168.31.109:8001/study
- 扫描资料库下所有科目（english/yilin2024、physics/suke …）
- progress.json: subjects 为各科目独立进度（override_unit 优先，否则按
  term_start + weeks_per_unit 自动推算当前单元）
- 每 REFRESH_SECONDS 换一条：随机种子 = 时间桶（2分钟一个），科目与 tip 均纯随机，
  同一桶内内容稳定、跨桶自动换新；科目范围仅限 progress.json 中配置的科目
- 页面 2 分钟 meta refresh，Kindle 停留在该页即可
"""
import html
import json
import random
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8001
REFRESH_SECONDS = 120

SUBJECT_CN = {"english": "英语", "physics": "物理", "math": "数学"}
DEFAULT_PROGRESS = {
    "subjects": {
        "english": {"term": "8A", "term_start": "2026-09-01", "weeks_per_unit": 2.5, "override_unit": None},
        "physics": {"term": "8A", "term_start": "2026-09-01", "weeks_per_unit": 4, "override_unit": None},
        "math": {"term": "8A", "term_start": "2026-09-01", "weeks_per_unit": 5, "override_unit": None},
    },
}


def load_books() -> dict:
    """返回 {subject: {term_code: {"units": [...], "publisher": str}}}。

    8a/8b.json 为按学期进度的教材册；exam.json（如有）为技能专栏，
    展示时以一定概率插入，不受学期进度控制。
    """
    books: dict = {}
    paths = sorted(ROOT.glob("*/*/*/8[ab].json")) + sorted(ROOT.glob("*/*/*/exam.json"))
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"跳过无法解析的资料文件 {path}: {e}", flush=True)
            continue
        book = data.get("book", {})
        subject = book.get("subject", path.parts[-4])
        term = book.get("term_code", path.stem.upper())
        books.setdefault(subject, {})[term] = {
            "units": data.get("units", []),
            "publisher": book.get("publisher", ""),
        }
    return books


BOOKS = load_books()


def load_progress() -> dict:
    try:
        return json.loads((ROOT / "progress.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return json.loads(json.dumps(DEFAULT_PROGRESS))


def learned_index(subject: str, conf: dict, units: list) -> int:
    """按 term_start + weeks_per_unit 推算"已学到第几个单元"（累计、单调递增）。

    override_unit 非空时直接当作进度（锁定学到的单元数）。
    """
    override = conf.get("override_unit")
    if override:
        return max(1, min(len(units), int(override)))
    start = date.fromisoformat(conf.get("term_start", "2026-09-01"))
    weeks = float(conf.get("weeks_per_unit", 2.5))
    elapsed = (date.today() - start).days
    idx = 1 if elapsed < 0 else int(elapsed // (weeks * 7)) + 1
    return max(1, min(len(units), idx))


def pick_tip(bucket: int | None = None) -> dict:
    """滚动复习模式：总体按学期进度走，但随机范围 = 已学过的全部单元。

    bucket 不传则取当前 2 分钟时间桶。科目随机 → 随机单元限定在
    units[:进度]，即随学习推进池子越来越大，期末自然变成全量随机。
    单元若带 pages 字段（多页内容），命中时按顺序翻页（内存轮换指针）。
    """
    if bucket is None:
        bucket = int(time.time() // REFRESH_SECONDS)
    progress = load_progress()
    subject_confs = {
        s: conf for s, conf in progress.get("subjects", {}).items() if s in BOOKS
    }
    if not subject_confs:
        subject_confs = {s: {} for s in BOOKS}
    subject = random.Random(f"{bucket}|subject").choice(list(subject_confs))
    conf = subject_confs[subject]
    terms = BOOKS[subject]
    term = conf.get("term") or next(iter(terms))
    if term not in terms:
        term = next(iter(terms))
    # 技能专栏（EXAM）以 25% 概率插入
    if "EXAM" in terms and term != "EXAM":
        term = random.Random(f"{bucket}|term").choice([term, term, term, "EXAM"])
    entry = terms[term]
    units = entry["units"]
    learned = len(units)
    if term == "EXAM":
        unit = random.Random(f"{bucket}|exam-unit").choice(units)
        learned_label = "技能专栏"
    else:
        idx = learned_index(subject, conf, units)
        unit = random.Random(f"{bucket}|unit|{subject}|{term}").choice(units[:idx])
        learned_label = f"已学 {idx}/{len(units)}"
    if unit.get("pages"):
        key = f"{subject}|{term}-u{unit['unit']}"
        page_no = _next_page(key, len(unit["pages"]))
        return {"subject": subject, "term": term, "publisher": entry["publisher"],
                "unit": unit, "page_no": page_no, "bucket": bucket,
                "learned_label": learned_label}
    pool = unit["tips"] or [t for u in units[:learned] for t in u["tips"]]
    seed = f"{bucket}|{subject}|{term}-u{unit['unit']}"
    tip = random.Random(seed).choice(pool)
    return {"subject": subject, "term": term, "publisher": entry["publisher"],
            "unit": unit, "tip": tip, "bucket": bucket, "learned_label": learned_label}


# 多页内容的翻页指针（内存态，重启后从第1页重新开始）
_PAGE_STATE: dict = {}


def _next_page(key: str, total: int) -> int:
    i = _PAGE_STATE.get(key, -1) + 1
    _PAGE_STATE[key] = i % total
    return i % total


PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>今日学习 tips</title>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #ffffff; color: #111111; }}
  body {{ font-family: sans-serif; }}
  .wrap {{ display: flex; flex-direction: column; min-height: 100vh; box-sizing: border-box; padding: 36px 42px; }}
  .head {{ font-size: 26px; color: #333333; }}
  .head b {{ color: #000000; }}
  .tag {{ display: inline-block; border: 2px solid #111; border-radius: 8px; padding: 2px 14px; font-size: 24px; margin-left: 10px; }}
  .tip {{ flex: 1; display: flex; align-items: center; }}
  .tip p {{ font-size: 52px; line-height: 1.65; font-weight: bold; margin: 0; word-wrap: break-word; }}
  .foot {{ border-top: 2px solid #cccccc; padding-top: 14px; font-size: 22px; color: #555555; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head"><b>{subject_cn} {term} · {unit_label}</b> <span class="tag">{tag}</span></div>
  <div class="tip"><p>{text}</p></div>
  <div class="foot">{date_cn} · {learned_label} · 滚动复习，每2分钟随机换新</div>
</div>
</body>
</html>"""


def unit_label(term: str, subject: str, unit: dict) -> str:
    if term == "EXAM":
        return unit["title"]
    if subject == "english":
        return f"Unit {unit['unit']} {unit['title']}"
    return unit["title"]  # 苏科版章节名本身是中文，如「声现象」「压强与浮力」


PAGE_MULTI = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>学习 tips · 多页</title>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #ffffff; color: #111111; }}
  body {{ font-family: sans-serif; }}
  .wrap {{ display: flex; flex-direction: column; min-height: 100vh; box-sizing: border-box; padding: 32px 42px; }}
  .head {{ font-size: 26px; color: #333333; }}
  .head b {{ color: #000000; }}
  .tag {{ display: inline-block; border: 2px solid #111; border-radius: 8px; padding: 2px 14px; font-size: 24px; margin-left: 10px; }}
  .list {{ flex: 1; display: flex; align-items: center; }}
  ul {{ margin: 0; padding-left: 40px; }}
  li {{ font-size: 34px; line-height: 1.55; margin-bottom: 26px; word-wrap: break-word; }}
  .en {{ font-size: 30px; color: #222222; display: block; margin-top: 6px; }}
  .foot {{ border-top: 2px solid #cccccc; padding-top: 14px; font-size: 22px; color: #555555; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head"><b>{subject_cn} {term} · {unit_label}</b> <span class="tag">第{page_no}/{page_total}页 · {page_title}</span></div>
  <div class="list"><ul>{items}</ul></div>
  <div class="foot">{date_cn} · {learned_label} · 滚动复习，每2分钟随机换新</div>
</div>
</body>
</html>"""


def term_label(term: str, publisher: str) -> str:
    if term == "EXAM":
        return "技能专栏"
    return f"{term}（{publisher}）" if publisher and term not in ("8A", "8B") else term


PAGE_IMAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>学习 tips · 图片页</title>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; background: #ffffff; color: #111111; }}
  body {{ font-family: sans-serif; }}
  .wrap {{ display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; padding: 24px 30px; }}
  .head {{ font-size: 26px; color: #333333; }}
  .head b {{ color: #000000; }}
  .tag {{ display: inline-block; border: 2px solid #111; border-radius: 8px; padding: 2px 14px; font-size: 24px; margin-left: 10px; }}
  .imgwrap {{ flex: 1; display: flex; align-items: center; justify-content: center; overflow: hidden; min-height: 0; }}
  .imgwrap img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
  .foot {{ border-top: 2px solid #cccccc; padding-top: 12px; font-size: 22px; color: #555555; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head"><b>{subject_cn} {term} · {unit_label}</b> <span class="tag">第{page_no}/{page_total}页 · {page_title}</span></div>
  <div class="imgwrap"><img src="/media/{image}" alt="{page_title}"></div>
  <div class="foot">{date_cn} · {learned_label} · 滚动复习，每2分钟随机换新</div>
</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith("/media/"):
            name = Path(path[len("/media/"):]).name  # 防目录穿越
            f = ROOT / "media" / name
            if f.exists() and f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                ctype = "image/png" if f.suffix.lower() == ".png" else "image/jpeg"
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send(404, "not found", "text/plain; charset=utf-8")
            return
        if path in ("/study", "/"):
            item = pick_tip()
            if "page_no" in item:
                unit = item["unit"]
                pg = unit["pages"][item["page_no"]]
                if pg.get("image"):
                    page = PAGE_IMAGE.format(
                        refresh=REFRESH_SECONDS,
                        subject_cn=SUBJECT_CN.get(item["subject"], item["subject"]),
                        term=term_label(item["term"], item["publisher"]),
                        unit_label=unit_label(item["term"], item["subject"], unit),
                        page_no=item["page_no"] + 1,
                        page_total=len(unit["pages"]),
                        page_title=pg.get("title", ""),
                        image=pg["image"],
                        date_cn=date.today().strftime("%Y年%m月%d日"),
                        learned_label=item["learned_label"],
                    )
                    self._send(200, page)
                    return
                lis = []
                for it in pg["items"]:
                    li = html.escape(it["cn"])
                    if it.get("en"):
                        li += f'<span class="en">{html.escape(it["en"])}</span>'
                    lis.append(f"<li>{li}</li>")
                page = PAGE_MULTI.format(
                    refresh=REFRESH_SECONDS,
                    subject_cn=SUBJECT_CN.get(item["subject"], item["subject"]),
                    term=term_label(item["term"], item["publisher"]),
                    unit_label=unit_label(item["term"], item["subject"], unit),
                    page_no=item["page_no"] + 1,
                    page_total=len(unit["pages"]),
                    page_title=pg.get("title", ""),
                    items="".join(lis),
                    date_cn=date.today().strftime("%Y年%m月%d日"),
                    learned_label=item["learned_label"],
                )
            else:
                page = PAGE.format(
                    refresh=REFRESH_SECONDS,
                    subject_cn=SUBJECT_CN.get(item["subject"], item["subject"]),
                    term=term_label(item["term"], item["publisher"]),
                    unit_label=unit_label(item["term"], item["subject"], item["unit"]),
                    tag=item["tip"]["tag"],
                    text=item["tip"]["text"],
                    date_cn=date.today().strftime("%Y年%m月%d日"),
                    learned_label=item["learned_label"],
                )
            self._send(200, page)
        elif path == "/study.json":
            item = pick_tip()
            payload = {
                "subject": item["subject"],
                "term": item["term"],
                "unit": item["unit"]["unit"],
                "unit_title": item["unit"]["title"],
                "topic_cn": item["unit"].get("topic_cn", ""),
                "bucket": item["bucket"],
                "date": date.today().isoformat(),
            }
            if "page_no" in item:
                pg = item["unit"]["pages"][item["page_no"]]
                payload.update({"type": "pages", "page_no": item["page_no"] + 1,
                                "page_total": len(item["unit"]["pages"]),
                                "page_title": pg.get("title", ""),
                                "items": pg.get("items", [])})
                if pg.get("image"):
                    payload["image"] = pg["image"]
            else:
                payload["tip"] = item["tip"]
            self._send(200, json.dumps(payload, ensure_ascii=False, indent=2), "application/json; charset=utf-8")
        elif path == "/health":
            self._send(200, "ok", "text/plain; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain; charset=utf-8")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"study-tips server listening on 0.0.0.0:{PORT}", flush=True)
    subjects = {s: list(t) for s, t in BOOKS.items()}
    print(f"loaded subjects: {subjects}", flush=True)
    server.serve_forever()
