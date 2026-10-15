#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用本地 Ollama 模型逐条审查资料库全部 tips 的正确性。

英语/物理 → qwen3:8b；数学 → qwen2.5-math:7b
每条 tip 单独一次调用（逐单元批量时模型偷懒漏条），断点续跑（已审查的跳过）。
结果追加写入 tools/review_report.json：
  [{file, unit_no, unit_title, id, verdict(correct|wrong|doubtful|error),
    reason, fix}]

用法（109）:
    ~/venvs/dy/bin/python review_tips.py            # 全量审查（断点续跑）
    ~/venvs/dy/bin/python review_tips.py --subject math
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "tools" / "review_report.json"

MODEL_BY_SUBJECT = {
    "english": "qwen3:8b",
    "physics": "qwen3:8b",
    "math": "qwen2.5-math:7b",
}

PROMPT = """你是一名严谨的初中{subject_cn}老师。请审查下面这条展示给初二学生的学习 tip
是否存在知识性错误、表述歧义或例句拼写问题。

科目：{subject_cn}｜单元：{term} {title}（{topic}）
tip：[{tag}] {text}

verdict 取值：correct（完全正确）/ wrong（有知识错误）/ doubtful（存疑或易误导）。
wrong 或 doubtful 时给出 fix（修正后的完整一句话，不超过80字），correct 时 fix 为空。
只输出一个 JSON 对象，不要解释：
{{"id":"{id}","verdict":"...","reason":"...","fix":"..."}}

/no_think
"""


def ollama_json(model: str, prompt: str) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 512},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())["message"]["content"].strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError(f"no JSON in response: {raw[:150]}")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default=None, help="只审查指定科目")
    args = ap.parse_args()

    done_ids: set = set()
    if REPORT.exists():
        for r in json.loads(REPORT.read_text(encoding="utf-8")):
            if r["verdict"] != "error":
                done_ids.add(r["id"])
    report = (json.loads(REPORT.read_text(encoding="utf-8"))
              if REPORT.exists() else [])

    files = sorted(ROOT.glob("*/*/*/8[ab].json")) + sorted(ROOT.glob("*/*/*/exam.json"))
    total = flagged = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        book = data["book"]
        subject = book.get("subject", "")
        if args.subject and subject != args.subject:
            continue
        model = MODEL_BY_SUBJECT.get(subject, "qwen3:8b")
        subject_cn = {"english": "英语", "physics": "物理", "math": "数学"}.get(subject, subject)
        rel = str(f.relative_to(ROOT))
        for unit in data["units"]:
            for tip in unit["tips"]:
                if tip["id"] in done_ids:
                    continue
                total += 1
                prompt = PROMPT.format(
                    subject_cn=subject_cn, term=book["term_code"],
                    title=unit["title"], topic=unit.get("topic_cn", ""),
                    tag=tip["tag"], text=tip["text"], id=tip["id"])
                try:
                    r = ollama_json(model, prompt)
                    entry = {"id": tip["id"],
                             "verdict": r.get("verdict", "doubtful"),
                             "reason": (r.get("reason") or "").strip(),
                             "fix": (r.get("fix") or "").strip()}
                except Exception as e:  # noqa: BLE001
                    entry = {"id": tip["id"], "verdict": "error",
                             "reason": str(e)[:120], "fix": ""}
                report.append({"file": rel, "unit_no": unit["unit"],
                               "unit_title": unit["title"], **entry})
                if entry["verdict"] in ("wrong", "doubtful"):
                    flagged += 1
                    print(f"⚠ {entry['id']} {entry['verdict']}: "
                          f"{entry['reason'][:80]} | fix: {entry['fix'][:60]}", flush=True)
                if total % 20 == 0:
                    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                    print(f"…进度 {total} 条", flush=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(report)
    wrong = sum(1 for r in report if r["verdict"] == "wrong")
    doubtful = sum(1 for r in report if r["verdict"] == "doubtful")
    print(f"\n完成：本次新审 {total} 条，标记 wrong {wrong} / doubtful {doubtful}")
    print(f"报告: {REPORT}")


if __name__ == "__main__":
    main()
