#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英语 tips 采集流水线（部署于 Ubuntu 109，仿 xuge_pipeline）

流程: 抖音指定英语博主最新视频 → faster-whisper 转写 → Ollama qwen 归纳 tips
      → 追加到 tools/en_tips_queue.json 供人工审核，审核通过后并入资料库 JSON

用法:
    ~/venvs/dy/bin/python en_tips_pipeline.py --sec <博主sec_uid>            # 处理最新3条
    ~/venvs/dy/bin/python en_tips_pipeline.py --sec <sec_uid> --count 6     # 多取几条
    ~/venvs/dy/bin/python en_tips_pipeline.py --sec <sec_uid> --force       # 忽略已处理记录重跑
依赖: 复用 ~/kindle-gold-panel 的 douyin_collect.py(含 sign/ 与 cookie.txt) 与 ~/venvs/dy
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

KB = Path(__file__).resolve().parent.parent          # ~/study-tips-kb
PANEL = Path.home() / "kindle-gold-panel"            # 复用采集层与 cookie
sys.path.insert(0, str(PANEL))

MEDIA_DIR = KB / "tools" / "en_media"
QUEUE_FILE = KB / "tools" / "en_tips_queue.json"
STATE_FILE = KB / "tools" / "en_tips_state.json"
MAX_VIDEOS = 3
OLLAMA_MODEL = "qwen3:8b"

PROMPT = """你是一名初中英语老师。下面是一条英语教学短视频的语音转写文字（可能混有英文和错别字）。
请从中提炼学生值得看的学习 tips，严格输出 JSON 数组（不要输出其他文字）：
[
  {"tag": "标签", "text": "tip内容"}
]
要求：
1. tag 只能是：词汇、语法、句型、易错、口语、方法 之一；
2. 每条 text 不超过 60 字，一句话讲清一个点，可含简单例句；
3. 只提炼视频里讲到的内容，不自己编造；最多 5 条；
4. 若视频内容与英语学习无关，输出 []。
转写内容：
"""


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_videos(sec: str, count: int):
    """拉指定博主作品列表并下载未处理过的视频。"""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    import douyin_collect as dc
    dc.SEC = sec  # monkey-patch 目标博主
    data = dc.fetch_awemes(count=count)
    items = [a for a in (data.get("aweme_list") or []) if a.get("aweme_id")]
    items.sort(key=lambda a: a.get("create_time") or 0, reverse=True)
    return items


def download(item) -> Path | None:
    aweme_id = item["aweme_id"]
    ts = item.get("create_time") or 0
    out = MEDIA_DIR / f"{ts}_{aweme_id}.mp4"
    if out.exists() and out.stat().st_size > 100_000:
        return out
    urls = ((item.get("video") or {}).get("play_addr") or {}).get("url_list") or []
    if not urls:
        return None
    u = urls[0].replace("playwm", "play")
    sh(f'curl -sL --max-time 300 -A "Mozilla/5.0" '
       f'-H "Referer: https://www.douyin.com/" "{u}" -o {out}', timeout=330)
    if out.exists() and out.stat().st_size > 100_000:
        return out
    print(f"下载失败: {aweme_id}")
    return None


def transcribe(video: Path) -> str:
    wav = video.with_suffix(".wav")
    sh(f"ffmpeg -y -i {video} -ac 1 -ar 16000 -vn {wav}", timeout=300)
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), vad_filter=True)  # 不限定语言，中英混合
    return "".join(s.text for s in segments)


def extract_tips(text: str) -> list:
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps({"model": OLLAMA_MODEL, "prompt": PROMPT + text,
                         "stream": False, "options": {"temperature": 0.2}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())["response"].strip()
    m = re.search(r"\[.*\]", raw, re.S)  # 容错：从回复中抠出 JSON 数组
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    valid_tags = {"词汇", "语法", "句型", "易错", "口语", "方法"}
    out = []
    for t in arr:
        if isinstance(t, dict) and t.get("text"):
            tag = t.get("tag", "方法")
            out.append({"tag": tag if tag in valid_tags else "方法",
                        "text": str(t["text"]).strip()[:80]})
    return out[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", required=True, help="抖音博主 sec_uid（主页 URL 中 sec_user_id= 后那串）")
    ap.add_argument("--count", type=int, default=MAX_VIDEOS)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    state = load_json(STATE_FILE, {"processed": []})
    queue = load_json(QUEUE_FILE, [])

    print(f"拉取博主作品列表（最新 {args.count} 条）…")
    items = fetch_videos(args.sec, args.count)
    if not items:
        print("未获取到作品（多半是 cookie 失效），退出")
        sys.exit(1)

    for item in items:
        aweme_id = item["aweme_id"]
        if aweme_id in state["processed"] and not args.force:
            print(f"跳过已处理: {aweme_id}")
            continue
        desc = (item.get("desc") or "").strip()[:60]
        print(f"处理: {aweme_id} | {desc}")
        video = download(item)
        if not video:
            continue
        print("转写中…")
        text = transcribe(video)
        if len(text.strip()) < 100:
            # 转写太短说明视频是宣传/展示类，没有实质教学内容，qwen 只会瞎编
            print(f"  → 转写仅 {len(text.strip())} 字，内容太少，跳过归纳")
            state["processed"].append(aweme_id)
            save_json(STATE_FILE, state)
            continue
        print(f"转写 {len(text)} 字，qwen 归纳中…")
        tips = extract_tips(text)
        if tips:
            queue.append({
                "source": {"aweme_id": aweme_id, "desc": desc,
                           "sec_uid": args.sec, "author": "douyin"},
                "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
                "tips": tips,
            })
            save_json(QUEUE_FILE, queue)
            print(f"  → 提炼出 {len(tips)} 条 tips，已入审核队列")
        else:
            print("  → 未提炼出有效 tips（可能内容无关或解析失败）")
        state["processed"].append(aweme_id)
        save_json(STATE_FILE, state)

    print(f"\n完成。审核队列: {QUEUE_FILE}")
    print("人工筛选后告诉我，把选中的 tips 并入 english/yilin2024/grade8/*.json 的对应单元。")


if __name__ == "__main__":
    main()
