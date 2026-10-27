"""Đối chiếu tự động mọi con số trong báo cáo giai đoạn 2 với artifact của một run `outputs/process/`.

Một số trong báo cáo (định dạng Việt Nam: `1.928,6`, `16,7%`) được coi là khớp khi có ít nhất một giá trị
trong artifact (ô số của CSV, số trong chuỗi bằng chứng, JSON, cấu hình trong manifest) cho đúng chuỗi đó
khi làm tròn tới cùng số chữ số thập phân (phần trăm: giá trị × 100). Bỏ qua số trong code span, ngày tháng
và số hiệu tham chiếu (Ruling, Task, Quyết định, Chương, Buổi, notebook, B1–B6, Ch1–Ch6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

MAX_DECIMALS = 4
_CODE = re.compile(r"`[^`]*`")
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?(?:T\d{6}Z)?\b|\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{1,2}/10\b")
_LABEL = re.compile(r"(?:Ruling|Rulings|Task|Quyết định|Chương|Buổi|notebook|Bước|Phụ lục|bước)"
                    r"\s+\d+(?:[–-]\d+)?"
                    r"|\b(?:B|Ch|R)\d+(?:[–-](?:B|Ch)?\d+)?\b|\b\d{2}_\w+")
_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?(%)?(?![\w])")
_PLAIN = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class ReportNumber:
    token: str
    value: float
    decimals: int
    percent: bool
    context: str


def _scrub(text: str) -> str:
    for pattern in (_CODE, _LINK_TARGET, _DATE, _LABEL):
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def extract_numbers(text: str) -> list[ReportNumber]:
    clean = _scrub(text)
    found = []
    for m in _NUMBER.finditer(clean):
        whole, frac, pct = m.group(1), m.group(2), m.group(3)
        value = float(whole.replace(".", "") + ("." + frac if frac else ""))
        start = max(0, m.start() - 50)
        found.append(ReportNumber(m.group(0), value, len(frac or ""), bool(pct),
                                  text[start:m.end() + 30].replace("\n", " ")))
    return found


class ArtifactValues:
    """Tập giá trị số của một run, đã định dạng sẵn theo số chữ số thập phân để so khớp nhanh."""

    def __init__(self, values: list[float]) -> None:
        self.values = values
        self._plain = {d: {f"{abs(v):.{d}f}" for v in values} for d in range(MAX_DECIMALS + 1)}
        self._pct = {d: {f"{abs(v) * 100:.{d}f}" for v in values} for d in range(MAX_DECIMALS + 1)}

    def matches(self, number: ReportNumber) -> bool:
        d = min(number.decimals, MAX_DECIMALS)
        key = f"{number.value:.{d}f}"
        return key in self._plain[d] or (number.percent and key in self._pct[d])


def _walk(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(float(x.replace(",", ".")) for x in _PLAIN.findall(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def artifact_values(run_dir: Path) -> ArtifactValues:
    run_dir = Path(run_dir)
    values: list[float] = []
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    _walk(manifest.get("config", {}), values)
    for path in sorted(run_dir.rglob("*")):
        if "notebooks_executed" in path.parts or path.name == "manifest.json" or not path.is_file():
            continue
        if path.suffix == ".csv":
            frame = pd.read_csv(path)
            values.extend(frame.select_dtypes("number").to_numpy(dtype=float).ravel().tolist())
            for column in frame.select_dtypes(exclude="number").columns:
                for cell in frame[column].dropna().astype(str):
                    _walk(cell, values)
        elif path.suffix == ".json":
            _walk(json.loads(path.read_text(encoding="utf-8")), values)
    return ArtifactValues([v for v in values if v == v])


def check_report(text: str, values: ArtifactValues) -> list[ReportNumber]:
    """Các số trong báo cáo không tìm thấy trong artifact (cần sửa hoặc giải thích)."""
    return [n for n in extract_numbers(text) if not values.matches(n)]
