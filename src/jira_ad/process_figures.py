"""Hình quy trình bằng Graphviz (`dot`): nguồn DOT tất định, render PNG + SVG cạnh file `.dot`."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import networkx as nx


def _num(x: float, digits: int = 1) -> str:
    """Số kiểu Việt Nam (dấu phẩy thập phân) cho nhãn hình."""
    return f"{x:.{digits}f}".replace(".", ",")


def status_dfg_dot(g: nx.DiGraph, *, title: str) -> str:
    """DFG trạng thái: nhãn cạnh = số lần + trung vị thời gian nằm ở trạng thái nguồn (ngày làm việc)."""
    lines = ["digraph G {", "  rankdir=LR;", f'  label="{title}"; labelloc=t; fontname="Helvetica";',
             '  node [shape=box, style="rounded", fontname="Helvetica"];',
             '  edge [fontname="Helvetica", fontsize=10];']
    lines += [f'  "{n}";' for n in sorted(g.nodes)]
    width_max = max((d["count"] for *_, d in g.edges(data=True)), default=1)
    for a, b, d in sorted(g.edges(data=True)):
        pen = 0.6 + 4.0 * d["count"] / width_max
        label = f'{d["count"]} lần\\n{_num(d["median_wait_days"])} ngày'
        lines.append(f'  "{a}" -> "{b}" [label="{label}", penwidth={pen:.2f}];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_dot(source: str, stem: Path) -> list[Path]:
    """Ghi `<stem>.dot` và (nếu có `dot`) `<stem>.png`, `<stem>.svg`."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    dot_path = stem.with_suffix(".dot")
    dot_path.write_text(source, encoding="utf-8")
    written = [dot_path]
    exe = shutil.which("dot")
    if exe is None:
        return written
    for fmt in ("png", "svg"):
        target = stem.with_suffix(f".{fmt}")
        subprocess.run([exe, f"-T{fmt}", str(dot_path), "-o", str(target)], check=True)
        written.append(target)
    return written


def _structural_colors(net, im, fm) -> dict:
    """Khóa sắp xếp thuần cấu trúc (tinh chỉnh màu kiểu Weisfeiler–Lehman, băm SHA-256).

    Không dùng tên place/transition ẩn: pm4py đặt các tên đó theo thứ tự duyệt set, đổi theo PYTHONHASHSEED.
    """
    nodes = list(net.places) + list(net.transitions)
    color = {p: f"P|{p in im}|{p in fm}" for p in net.places}
    color.update({t: f"T|{t.label}" if t.label is not None else "T|τ" for t in net.transitions})
    for _ in range(len(nodes)):
        new = {n: hashlib.sha256("|".join([
            color[n], ",".join(sorted(color[a.source] for a in n.in_arcs)),
            ",".join(sorted(color[a.target] for a in n.out_arcs))]).encode()).hexdigest() for n in nodes}
        if len(set(new.values())) == len(set(color.values())):
            break
        color = new
    return color


def petri_dot(net, im, fm, *, title: str) -> str:
    """Petri net tất định: place tròn (● = đánh dấu đầu, vòng kép = đích), transition ẩn là thanh đen."""
    color = _structural_colors(net, im, fm)
    places = sorted(net.places, key=lambda p: color[p])
    transitions = sorted(net.transitions, key=lambda t: color[t])
    pid = {p: f"p{i}" for i, p in enumerate(places)}
    tid = {t: f"t{i}" for i, t in enumerate(transitions)}
    lines = ["digraph P {", "  rankdir=LR;", f'  label="{title}"; labelloc=t; fontname="Helvetica";',
             '  node [fontname="Helvetica"];']
    for p in places:
        mark = "●" if p in im else ""
        shape = "doublecircle" if p in fm else "circle"
        lines.append(f'  {pid[p]} [shape={shape}, label="{mark}", width=0.3, fixedsize=true];')
    for t in transitions:
        if t.label is None:
            bar = 'shape=box, style=filled, fillcolor=black, label="", width=0.12, height=0.4'
            lines.append(f"  {tid[t]} [{bar}];")
        else:
            lines.append(f'  {tid[t]} [shape=box, label="{t.label}"];')
    arcs = sorted((pid.get(a.source) or tid[a.source], pid.get(a.target) or tid[a.target]) for a in net.arcs)
    lines += [f"  {s} -> {d};" for s, d in arcs]
    lines.append("}")
    return "\n".join(lines) + "\n"


def bpmn_dot(model, lanes: dict[str, str], *, title: str, automated=frozenset()) -> str:
    """Sơ đồ kiểu BPMN: lane theo vai trò (cluster), task bo góc, XOR (◇ ×) khi có > 1 cung ra."""
    tasks = sorted(model.activities - {model.start} - set(model.ends))
    out_deg = {a: sum(1 for x, _ in model.arcs if x == a) for a in model.activities}
    lines = ["digraph B {", "  rankdir=LR;", f'  label="{title}"; labelloc=t; fontname="Helvetica";',
             '  node [fontname="Helvetica"]; edge [fontname="Helvetica"];',
             f'  "{model.start}" [shape=circle, label="{model.start}", width=0.8];']
    lines += [f'  "{e}" [shape=doublecircle, label="{e}", width=0.8];' for e in sorted(model.ends)]
    for k, lane in enumerate(sorted(set(lanes.get(t, "Không xác định") for t in tasks))):
        lines += [f"  subgraph cluster_{k} {{", f'    label="{lane}"; style=rounded; color=gray;']
        members = [t for t in tasks if lanes.get(t, "Không xác định") == lane]
        lines += [f'    "{t}" [shape=box, style=rounded];' for t in members]
        lines.append("  }")
    for a in sorted(model.activities):
        targets = sorted(b for x, b in model.arcs if x == a)
        def style(b: str, a: str = a) -> str:
            return ' [style=dashed, label="tự động"]' if (a, b) in automated else ""

        if out_deg[a] > 1:
            lines.append(f'  "xor_{a}" [shape=diamond, label="×", width=0.4, height=0.4];')
            lines.append(f'  "{a}" -> "xor_{a}";')
            lines += [f'  "xor_{a}" -> "{b}"{style(b)};' for b in targets]
        else:
            lines += [f'  "{a}" -> "{b}"{style(b)};' for b in targets]
    lines.append("}")
    return "\n".join(lines) + "\n"
