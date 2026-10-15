#!/usr/bin/env python3
"""study-tips-kb 数据完整性校验（多科目通用）。

用法: python3 tools/validate.py
退出码: 0 = 全部通过, 1 = 存在错误
"""
import json
import re
import sys
from pathlib import Path

KB_ROOT = Path(__file__).resolve().parent.parent
VALID_SLOTS = {"morning", "evening", "any"}
VALID_TAGS = {"词汇", "语法", "句型", "易错", "自测", "写作", "口语", "方法", "口诀",
              "公式", "定律", "定理", "题型", "实验", "概念", "单位"}
REQUIRED_TIP_FIELDS = ["id", "slot", "tag", "text"]
ID_RE = re.compile(r"^[a-z0-9]+-u\d{1,2}-\d{2}$")

errors: list[str] = []
all_tip_ids: list[str] = []


def err(file: Path, msg: str) -> None:
    errors.append(f"[{file.relative_to(KB_ROOT)}] {msg}")


def validate_book_file(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(path, f"JSON 解析失败: {e}")
        return

    book = data.get("book", {})
    for field in ["subject", "publisher", "grade", "term_code"]:
        if field not in book:
            err(path, f"book 缺少字段: {field}")

    units = data.get("units", [])
    if not 4 <= len(units) <= 8:
        err(path, f"单元数应在 4~8 之间，实际 {len(units)}")

    seen_units = set()
    for unit in units:
        label = f"Unit/章 {unit.get('unit', '?')}"
        u_no = unit.get("unit")
        if u_no in seen_units:
            err(path, f"单元序号重复: {u_no}")
        seen_units.add(u_no)
        for field in ["unit", "title", "topic_cn", "tips"]:
            if field not in unit:
                err(path, f"{label} 缺少字段: {field}")
        if "key_points" not in unit and "grammar" not in unit:
            err(path, f"{label} 缺少核心内容（key_points 或 grammar）")

        # 英语科目附加结构
        grammar = unit.get("grammar")
        if grammar is not None:
            for field in ["name", "key_points", "examples"]:
                if field not in grammar:
                    err(path, f"{label} grammar 缺少字段: {field}")

        for item in unit.get("core_vocab", []):
            if "en" not in item or "cn" not in item:
                err(path, f"{label} core_vocab 项缺少 en/cn: {item}")
        for item in unit.get("key_phrases", []):
            if "en" not in item or "cn" not in item:
                err(path, f"{label} key_phrases 项缺少 en/cn: {item}")

        tips = unit.get("tips", [])
        if len(tips) < 8:
            err(path, f"{label} tips 数量少于 8（当前 {len(tips)}），轮换池偏小")
        for tip in tips:
            for field in REQUIRED_TIP_FIELDS:
                if field not in tip:
                    err(path, f"{label} tip 缺少字段 {field}: {tip}")
            all_tip_ids.append(tip.get("id", ""))
            if tip.get("slot") not in VALID_SLOTS:
                err(path, f"{label} tip slot 非法: {tip.get('slot')!r}")
            if tip.get("tag") not in VALID_TAGS:
                err(path, f"{label} tip tag 非法: {tip.get('tag')!r}")
            text = tip.get("text", "")
            if not text or len(text) > 140:
                err(path, f"{label} tip text 过长或为空（{len(text)} 字符）: {text[:30]}...")
            if not ID_RE.fullmatch(tip.get("id", "")):
                err(path, f"{label} tip id 格式非法（应如 phy-u3-01 / 8a-u3-01）: {tip.get('id')!r}")


def main() -> int:
    files = sorted(KB_ROOT.glob("*/*/*/8[ab].json"))
    if not files:
        print("未找到任何 8a/8b.json，请检查目录结构（科目/版本/年级/8a.json）")
        return 1
    for f in files:
        validate_book_file(f)

    dup = {tid for tid in all_tip_ids if all_tip_ids.count(tid) > 1}
    if dup:
        errors.append(f"全局 tip id 重复: {sorted(dup)}")

    total_units = 0
    total_tips = 0
    print("资料库清单:")
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        book = data.get("book", {})
        n_units = len(data.get("units", []))
        n_tips = sum(len(u.get("tips", [])) for u in data.get("units", []))
        total_units += n_units
        total_tips += n_tips
        print(f"  {book.get('subject', '?'):8s} {book.get('publisher', ''):6s} "
              f"{book.get('term_code', '?')}  单元×{n_units}  tips×{n_tips}")

    print(f"合计: 单元 {total_units} | tips {total_tips}")
    if errors:
        print(f"\n发现 {len(errors)} 个问题:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
