"""Mô hình chuẩn, khai phá quy trình và kiểm định tuân thủ (B1, B5), cùng bảng Work System.

- **Mô hình chuẩn** là giả định của tác giả (Quyết định 4): danh sách cung được phép giữa các trạng
  thái, dựng thành Petri net "mỗi activity một transition, mỗi cung một transition ẩn" để nhãn không
  trùng và token replay của pm4py chạy đúng (Ruling 71).
- **Khai phá** Alpha / Heuristics / Inductive trên status log (activity = CREATE + tên trạng thái).
- **Cờ quy tắc** chỉ đếm, không kết luận lỗi; quy tắc 0 vi phạm vẫn được báo.
pm4py chỉ được import trong các hàm cần nó (extra `process`).
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd

from jira_ad.process_config import FlagRule  # noqa: F401 - tái xuất cho người gọi
from jira_ad.process_metrics import is_human
from jira_ad.status_log import CREATED, CohortData

DAY = 86_400.0
CASE, ACT, TIME = "case:concept:name", "concept:name", "time:timestamp"
WORK_SYSTEM_COMPONENTS = ("Khách hàng", "Sản phẩm/dịch vụ", "Quy trình và hoạt động", "Người tham gia",
                          "Thông tin", "Công nghệ", "Môi trường", "Hạ tầng")
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DD_NS = "http://www.omg.org/spec/DD/20100524/DI"


def _pm4py():
    os.environ.setdefault("PM4PY_SHOW_PROGRESS_BAR", "False")
    import pm4py
    from pm4py.util import constants

    constants.SHOW_PROGRESS_BAR = False
    return pm4py


# ------------------------------------------------------------------------------- mô hình chuẩn


@dataclass(frozen=True)
class ReferenceModel:
    arcs: tuple[tuple[str, str], ...]
    start: str
    ends: tuple[str, ...]

    @staticmethod
    def parse_arcs(arcs) -> tuple[tuple[str, str], ...]:
        parsed = []
        for text in arcs:
            if "->" not in text:
                raise ValueError(f"Cung {text!r} phải có dạng 'A -> B'")
            a, b = (part.strip() for part in text.split("->", 1))
            parsed.append((a, b))
        return tuple(parsed)

    @classmethod
    def from_strings(cls, arcs, *, start: str, ends) -> ReferenceModel:
        model = cls(cls.parse_arcs(arcs), start, tuple(ends))
        model.validate()
        return model

    def with_extra_arcs(self, arcs) -> ReferenceModel:
        """Mô hình mới = mô hình này + các cung thêm (vd ứng viên TO-BE); mô hình gốc không đổi."""
        extra = self.parse_arcs(arcs)
        dup = sorted(f"{a} -> {b}" for a, b in extra if (a, b) in self.arcs)
        if dup:
            raise ValueError(f"Cung đã có trong mô hình: {dup}")
        model = ReferenceModel(self.arcs + extra, self.start, self.ends)
        model.validate()
        return model

    @property
    def activities(self) -> set[str]:
        return {a for arc in self.arcs for a in arc}

    def validate(self) -> None:
        targets = {b for _, b in self.arcs}
        sources = {a for a, _ in self.arcs}
        orphans = sorted(self.activities - targets - {self.start})
        if orphans:
            raise ValueError(f"Mô hình chuẩn: {orphans} không có cung vào")
        dead = sorted(self.activities - sources - set(self.ends))
        if dead:
            raise ValueError(f"Mô hình chuẩn: {dead} không có cung ra và không phải trạng thái kết thúc")
        if self.start not in sources:
            raise ValueError(f"Mô hình chuẩn: điểm bắt đầu {self.start!r} không có cung ra")


def reference_net(model: ReferenceModel):
    """Workflow net: place vào/ra mỗi activity, transition ẩn mỗi cung, sink sau trạng thái kết thúc."""
    _pm4py()
    from pm4py.objects.petri_net.obj import Marking, PetriNet
    from pm4py.objects.petri_net.utils import petri_utils as pu

    net = PetriNet("mo_hinh_chuan")
    place: dict[str, Any] = {}

    def p(name: str):
        if name not in place:
            place[name] = PetriNet.Place(name)
            net.places.add(place[name])
        return place[name]

    def t(name: str, label: str | None):
        tr = PetriNet.Transition(name, label)
        net.transitions.add(tr)
        return tr

    for act in sorted(model.activities):
        tr = t(f"t_{act}", act)
        pu.add_arc_from_to(p(f"in_{act}"), tr, net)
        pu.add_arc_from_to(tr, p(f"out_{act}"), net)
    for a, b in model.arcs:
        tau = t(f"tau_{a}->{b}", None)
        pu.add_arc_from_to(p(f"out_{a}"), tau, net)
        pu.add_arc_from_to(tau, p(f"in_{b}"), net)
    sink = p("sink")
    for end in model.ends:
        tau = t(f"tau_{end}->end", None)
        pu.add_arc_from_to(p(f"out_{end}"), tau, net)
        pu.add_arc_from_to(tau, sink, net)
    return net, Marking({p(f"in_{model.start}"): 1}), Marking({sink: 1})


# --------------------------------------------------------------------------------- event log


def status_event_log(status_log: pd.DataFrame) -> pd.DataFrame:
    """Log mức trạng thái cho pm4py; thời điểm cộng `visit_index` micro giây để giữ thứ tự khi trùng giờ."""
    if status_log.empty:
        return pd.DataFrame({CASE: pd.Series(dtype=str), ACT: pd.Series(dtype=str),
                             TIME: pd.Series(dtype="datetime64[ns, UTC]")})
    ordered = status_log.sort_values(["case_id", "visit_index"], kind="stable")
    out = pd.DataFrame({
        CASE: ordered["case_id"].astype(str),
        ACT: ordered["state"].replace({CREATED: "CREATE"}).astype(str),
        TIME: pd.to_datetime(ordered["t_enter"], utc=True)
        + pd.to_timedelta(ordered["visit_index"], unit="us"),
    })
    return out.reset_index(drop=True)


def _event_log(log: pd.DataFrame):
    if log.empty:
        raise ValueError("Log rỗng: không có ca nào để replay/khai phá")
    pm4py = _pm4py()
    return pm4py.convert_to_event_log(
        pm4py.format_dataframe(log.copy(), case_id=CASE, activity_key=ACT, timestamp_key=TIME))


def discover(log: pd.DataFrame, miner: str, params: dict[str, float]):
    pm4py = _pm4py()
    elog = _event_log(log)
    if miner == "alpha":
        return pm4py.discover_petri_net_alpha(elog)
    if miner == "heuristics":
        return pm4py.discover_petri_net_heuristics(elog, **params)
    if miner == "inductive":
        return pm4py.discover_petri_net_inductive(elog, **params)
    raise ValueError(f"miner không hỗ trợ: {miner!r}")


def quality(log: pd.DataFrame, net, im, fm) -> dict[str, float]:
    """Bốn chiều chất lượng: fitness và precision (token replay), generalization, simplicity."""
    pm4py = _pm4py()
    from pm4py.algo.evaluation.generalization import algorithm as generalization
    from pm4py.algo.evaluation.simplicity import algorithm as simplicity

    elog = _event_log(log)
    fit = pm4py.fitness_token_based_replay(elog, net, im, fm)
    return {
        "fitness": float(fit["log_fitness"]),
        "perc_fit_traces": float(fit["percentage_of_fitting_traces"]),
        "precision": float(pm4py.precision_token_based_replay(elog, net, im, fm)),
        "generalization": float(generalization.apply(elog, net, im, fm)),
        "simplicity": float(simplicity.apply(net)),
        "n_places": len(net.places), "n_transitions": len(net.transitions),
        "n_invisible": sum(t.label is None for t in net.transitions),
    }


def replay_cases(log: pd.DataFrame, net, im, fm) -> pd.DataFrame:
    """Token replay từng ca; activity không có trong mô hình làm ca không khớp (ghi tên activity)."""
    pm4py = _pm4py()
    elog = _event_log(log)
    labels = {t.label for t in net.transitions if t.label is not None}
    diag = pm4py.conformance_diagnostics_token_based_replay(elog, net, im, fm)
    rows = []
    for trace, d in zip(elog, diag, strict=True):
        unknown = sorted({e[ACT] for e in trace} - labels)
        rows.append({
            "case_id": trace.attributes[ACT], "trace_fitness": float(d["trace_fitness"]),
            "is_fit": bool(d["trace_is_fit"]) and not unknown,
            "missing": int(d["missing_tokens"]), "remaining": int(d["remaining_tokens"]),
            "consumed": int(d["consumed_tokens"]), "produced": int(d["produced_tokens"]),
            "unknown_activities": ", ".join(unknown), "variant": " > ".join(e[ACT] for e in trace),
        })
    return pd.DataFrame(rows)


def compare_replays(replays: dict[str, pd.DataFrame], *, reference: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kết quả replay của nhiều mô hình cạnh nhau; ca khớp thêm so với mô hình tham chiếu."""
    base_fit = set(replays[reference].loc[replays[reference]["is_fit"], "case_id"])
    rows, gained = [], []
    for name, r in replays.items():
        fit = set(r.loc[r["is_fit"], "case_id"])
        rows.append({"model": name, "n_cases": len(r), "mean_fitness": float(r["trace_fitness"].mean()),
                     "n_fit": len(fit), "share_fit": len(fit) / len(r),
                     "n_newly_fit_vs_reference": len(fit - base_fit)})
        gained += [{"model": name, "case_id": c} for c in sorted(fit - base_fit)]
    return pd.DataFrame(rows), pd.DataFrame(gained, columns=["model", "case_id"])


def unobserved_arc_precision(status_log: pd.DataFrame, model: ReferenceModel) -> pd.DataFrame:
    """Với mỗi cung của mô hình chưa từng xảy ra: precision/fitness khi giữ và khi bỏ cung đó."""
    arcs = arc_table(status_log, model)
    unseen = arcs[arcs["in_model"] & (arcs["count"] == 0)]
    events = status_event_log(status_log)
    with_q = quality(events, *reference_net(model))
    rows = []
    for a, b in zip(unseen["source"], unseen["target"], strict=True):
        reduced = ReferenceModel(tuple(x for x in model.arcs if x != (a, b)), model.start, model.ends)
        row = {"source": a, "target": b, "count": 0, "precision_with": with_q["precision"],
               "fitness_with": with_q["fitness"], "precision_without": float("nan"),
               "fitness_without": float("nan"), "note": ""}
        try:
            reduced.validate()
        except ValueError as exc:
            row["note"] = f"bỏ cung làm mô hình không hợp lệ: {exc}"
        else:
            without_q = quality(events, *reference_net(reduced))
            row.update(precision_without=without_q["precision"], fitness_without=without_q["fitness"])
        rows.append(row)
    return pd.DataFrame(rows, columns=["source", "target", "count", "precision_with", "precision_without",
                                       "fitness_with", "fitness_without", "note"])


def deviation_breakdown(status_log: pd.DataFrame, *, arcs, example_cases: int = 5) -> pd.DataFrame:
    """Sai lệch chọn lọc (cung cho trước, lùi trạng thái, mở lại) theo nhánh; tách lần sai lệch THUỘC một đợt
    cập nhật bù (lần đổi đó nằm trong chuỗi đổi trạng thái < ngưỡng, kể cả lần mở đầu chuỗi) — cùng định nghĩa
    với FPY adjusted (rà soát độc lập I1)."""
    ordered = status_log.sort_values(["case_id", "visit_index"]).copy()
    ordered["prev"] = ordered.groupby("case_id")["state"].shift().replace({CREATED: "CREATE"})
    ordered["in_burst"] = ordered["burst_id"] != -1
    categories = {f"{a} → {b}": (ordered["prev"] == a) & (ordered["state"] == b) for a, b in arcs}
    categories["Lùi trạng thái"] = ordered["is_back"].astype(bool)
    categories["Mở lại"] = ordered["is_reopen"].astype(bool)
    rows = []
    for name, mask in categories.items():
        for branch in ("all", "DONE", "Rejected"):
            hit = ordered[mask & ((ordered["terminal_status"] == branch) | (branch == "all"))]
            per_case = hit.groupby("case_id")["in_burst"].all()
            only = sorted(per_case[per_case].index)
            outside = sorted(per_case[~per_case].index)
            rows.append({"category": name, "branch": branch, "n_cases": len(per_case),
                         "n_occurrences": len(hit), "n_occ_in_burst": int(hit["in_burst"].sum()),
                         "n_cases_only_in_burst": len(only), "n_cases_outside_burst": len(outside),
                         "examples_only_in_burst": ", ".join(only[:example_cases]),
                         "examples_outside_burst": ", ".join(outside[:example_cases])})
    return pd.DataFrame(rows)


def arc_table(status_log: pd.DataFrame, model: ReferenceModel, example_cases: int = 3) -> pd.DataFrame:
    """Cung quan sát được (và cung của mô hình chưa từng thấy), có nằm trong mô hình chuẩn không."""
    rows = []
    for case_id, v in status_log.sort_values(["case_id", "visit_index"]).groupby("case_id", sort=True):
        states = [("CREATE" if s == CREATED else s) for s in v["state"]]
        waits = list(v["dwell_work_s"] / DAY)
        rows += [(a, b, w, case_id) for a, b, w in zip(states, states[1:], waits, strict=False)]
    obs = pd.DataFrame(rows, columns=["source", "target", "wait", "case_id"])
    allowed = set(model.arcs)
    out = []
    for (a, b), e in obs.groupby(["source", "target"], sort=True):
        out.append({"source": a, "target": b, "in_model": (a, b) in allowed, "count": len(e),
                    "n_cases": e["case_id"].nunique(), "median_wait_days": float(e["wait"].median()),
                    "example_cases": ", ".join(sorted(e["case_id"].unique())[:example_cases])})
    seen = {(r["source"], r["target"]) for r in out}
    out += [{"source": a, "target": b, "in_model": True, "count": 0, "n_cases": 0,
             "median_wait_days": float("nan"), "example_cases": ""} for a, b in model.arcs
            if (a, b) not in seen]
    table = pd.DataFrame(out)
    return table.sort_values(["in_model", "count", "source", "target"],
                             ascending=[True, False, True, True]).reset_index(drop=True)


# ----------------------------------------------------------------------------------- cờ quy tắc


def _count(rule: FlagRule, seq: list[str], backfill: int) -> int:
    prev = [CREATED, *seq[:-1]]
    if rule.kind == "missing_before":
        first = next((i for i, s in enumerate(seq) if s in rule.states), None)
        return int(first is not None and not any(s in rule.other_states for s in seq[:first]))
    if rule.kind == "first_status_is":
        return int(bool(seq) and seq[0] in rule.states)
    if rule.kind == "after":
        return sum(1 for i, s in enumerate(seq) if s in rule.states
                   and any(x in rule.other_states for x in seq[:i]))
    if rule.kind == "leaves":
        return sum(1 for s in seq[:-1] if s in rule.states)
    if rule.kind == "enters_from_status":
        return sum(1 for s, p in zip(seq, prev, strict=True) if s in rule.states and p != CREATED)
    if rule.kind == "enters_not_from":
        return sum(1 for s, p in zip(seq, prev, strict=True)
                   if s in rule.states and p not in rule.other_states)
    return backfill  # "backfill"


def flag_cases(status_log: pd.DataFrame, rules) -> pd.DataFrame:
    """Một dòng mỗi (ca, cờ): số lần cờ xảy ra (0 nếu không)."""
    rows = []
    for case_id, v in status_log.sort_values(["case_id", "visit_index"]).groupby("case_id", sort=True):
        seq = list(v["state"].iloc[1:])
        backfill = int(v["is_backfill_entry"].sum())
        for rule in rules:
            rows.append({"case_id": case_id, "terminal_status": v["terminal_status"].iloc[0],
                         "flag": rule.id, "label": rule.label, "n": _count(rule, seq, backfill)})
    return pd.DataFrame(rows, columns=["case_id", "terminal_status", "flag", "label", "n"])


def flag_summary(flags: pd.DataFrame, n_cases: int, example_cases: int = 5) -> pd.DataFrame:
    rows = []
    for (flag, label), g in flags.groupby(["flag", "label"], sort=False):
        hit = g[g["n"] > 0]
        rows.append({"flag": flag, "label": label, "n_cases": len(hit), "share_cases": len(hit) / n_cases,
                     "n_occurrences": int(g["n"].sum()),
                     "n_done": int((hit["terminal_status"] == "DONE").sum()),
                     "n_rejected": int((hit["terminal_status"] == "Rejected").sum()),
                     "example_cases": ", ".join(sorted(hit["case_id"])[:example_cases])})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------- BPMN + lane


def state_lanes(status_log: pd.DataFrame, model: ReferenceModel) -> dict[str, str]:
    """Lane của mỗi task = vai trò người hay chuyển ca RA khỏi trạng thái đó nhất (người hoàn tất bước)."""
    tasks = sorted(model.activities - {model.start} - set(model.ends))
    lanes = {}
    for state in tasks:
        roles = [r for r in status_log.loc[status_log["state"] == state, "exit_role"] if is_human(r)]
        counts = Counter(roles)
        lanes[state] = (sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                        if counts else "Không xác định")
    return lanes


def _ranks(model: ReferenceModel) -> dict[str, int]:
    """Cột bố cục = khoảng cách ngắn nhất từ điểm bắt đầu (vòng lặp không đẩy cột)."""
    rank = {model.start: 0}
    frontier = [model.start]
    while frontier:
        nxt = []
        for a in frontier:
            for x, b in model.arcs:
                if x == a and b not in rank:
                    rank[b] = rank[a] + 1
                    nxt.append(b)
        frontier = nxt
    return rank


def reference_bpmn_xml(model: ReferenceModel, lanes: dict[str, str], names: dict[str, str],
                       flow_labels: dict[tuple[str, str], str] | None = None) -> str:
    """BPMN 2.0 (pool + lane theo vai trò, XOR gateway khi có > 1 cung ra) kèm DI để mở bằng bpmn.io."""
    for prefix, uri in (("bpmn", BPMN_NS), ("bpmndi", DI_NS), ("dc", DC_NS), ("di", DD_NS)):
        ET.register_namespace(prefix, uri)
    b = lambda tag: f"{{{BPMN_NS}}}{tag}"  # noqa: E731
    defs = ET.Element(b("definitions"), {"id": "defs", "targetNamespace": "http://jira-ad/process"})
    collab = ET.SubElement(defs, b("collaboration"), {"id": "collab"})
    ET.SubElement(collab, b("participant"), {"id": "pool", "name": "Team xử lý bug", "processRef": "proc"})
    proc = ET.SubElement(defs, b("process"), {"id": "proc", "isExecutable": "false"})
    ids = {}
    nodes = sorted(model.activities, key=lambda a: (_ranks(model).get(a, 99), a))
    for i, act in enumerate(nodes):
        ids[act] = f"n{i}"
    lane_of = dict(lanes)
    out_deg = Counter(a for a, _ in model.arcs)
    first_lane = sorted(set(lanes.values()))[0] if lanes else "Quy trình"
    for act in nodes:
        if act == model.start:
            tag = "startEvent"
            votes = Counter(lanes.get(t, first_lane) for a, t in model.arcs if a == act)
            lane_of[act] = votes.most_common(1)[0][0]
        elif act in model.ends:
            tag = "endEvent"
            preds = sorted(a for a, t in model.arcs if t == act and a in lanes)
            lane_of[act] = lanes[preds[0]] if preds else first_lane
        else:
            tag = "task"
        ET.SubElement(proc, b(tag), {"id": ids[act], "name": names.get(act, act)})
    flows, gateways, labels = [], {}, flow_labels or {}
    for act in nodes:
        targets = [t for a, t in model.arcs if a == act]
        if out_deg[act] > 1:
            gid = f"g_{ids[act]}"
            gateways[gid] = act
            lane_of[gid] = lane_of[act]
            ET.SubElement(proc, b("exclusiveGateway"), {"id": gid, "name": f"Sau {names.get(act, act)}?"})
            flows.append((ids[act], gid, None))
            flows += [(gid, ids[t], labels.get((act, t))) for t in targets]
        else:
            flows += [(ids[act], ids[t], labels.get((act, t))) for t in targets]
    lane_set = ET.SubElement(proc, b("laneSet"), {"id": "lanes"})
    lane_names = sorted(set(lane_of.values()))
    for k, name in enumerate(lane_names):
        lane = ET.SubElement(lane_set, b("lane"), {"id": f"lane{k}", "name": name})
        members = [ids[a] for a in nodes if lane_of[a] == name] + [g for g in gateways if lane_of[g] == name]
        for node_id in members:
            ET.SubElement(lane, b("flowNodeRef")).text = node_id
    for k, (src, tgt, label) in enumerate(flows):
        attrs = {"id": f"f{k}", "sourceRef": src, "targetRef": tgt, **({"name": label} if label else {})}
        ET.SubElement(proc, b("sequenceFlow"), attrs)
    _bpmn_di(defs, model, nodes, ids, gateways, lane_of, lane_names, flows)
    ET.indent(defs)
    return ET.tostring(defs, encoding="unicode", xml_declaration=True)


def _bpmn_di(defs, model, nodes, ids, gateways, lane_of, lane_names, flows) -> None:
    d = lambda tag: f"{{{DI_NS}}}{tag}"  # noqa: E731
    rank = _ranks(model)
    lane_h, col_w, x0 = 150, 170, 80
    diagram = ET.SubElement(defs, d("BPMNDiagram"), {"id": "diagram"})
    plane = ET.SubElement(diagram, d("BPMNPlane"), {"id": "plane", "bpmnElement": "collab"})
    width = x0 + col_w * (max(rank.values()) + 2)
    centers = {}

    def shape(element: str, x: float, y: float, w: float, h: float, extra=None) -> None:
        attrs = {"id": f"{element}_di", "bpmnElement": element, **(extra or {})}
        s = ET.SubElement(plane, d("BPMNShape"), attrs)
        ET.SubElement(s, f"{{{DC_NS}}}Bounds", {"x": str(x), "y": str(y), "width": str(w), "height": str(h)})
        centers[element] = (x + w / 2, y + h / 2)

    shape("pool", 0, 0, width, lane_h * len(lane_names), {"isHorizontal": "true"})
    for k, _ in enumerate(lane_names):
        shape(f"lane{k}", 30, k * lane_h, width - 30, lane_h, {"isHorizontal": "true"})
    for act in nodes:
        y_mid = lane_names.index(lane_of[act]) * lane_h + lane_h / 2
        x = x0 + col_w * rank.get(act, max(rank.values()) + 1)
        w, h = (36, 36) if act == model.start or act in model.ends else (110, 60)
        shape(ids[act], x, y_mid - h / 2, w, h)
    for gid, act in gateways.items():
        cx, cy = centers[ids[act]]
        shape(gid, cx + 60, cy - 25 + 45, 50, 50, {"isMarkerVisible": "true"})
    for k, (src, tgt, _) in enumerate(flows):
        e = ET.SubElement(plane, d("BPMNEdge"), {"id": f"f{k}_di", "bpmnElement": f"f{k}"})
        for x, y in (centers[src], centers[tgt]):
            ET.SubElement(e, f"{{{DD_NS}}}waypoint", {"x": f"{x:.0f}", "y": f"{y:.0f}"})


# -------------------------------------------------------------------------------- Work System


def _top(counter: Counter, k: int) -> str:
    return "; ".join(f"{name} {n}" for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:k])


def work_system_table(cohort: CohortData, status_log: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    """Tám thành phần Work System; mỗi ô có dẫn chứng từ trường/vai trò thật hoặc ghi rõ là giả định."""
    full, core = cohort.events_full, cohort.events
    creators = Counter(core.loc[core["activity"] == "CREATE", "role"])
    acts = Counter(core["activity"])
    human = Counter(r for r in full["role"] if is_human(r))
    n_bot = int(full["is_bot"].sum())
    statuses = sorted(set(status_log["state"]) - {CREATED})
    skip = ("CREATE", "LINK_COMMIT", "LINK_MERGE_REQUEST")
    info = Counter({a: n for a, n in acts.items() if not a.startswith("STATUS_") and a not in skip})
    terminal = Counter(cases["terminal_status"])
    rows = [
        ("Khách hàng",
         "Người dùng/khách hàng gặp lỗi (giả định đề bài) và các vai trò nội bộ báo lỗi.",
         f"Vai trò tạo issue: {_top(creators, 5)}"),
        ("Sản phẩm/dịch vụ",
         "Lỗi được sửa và đóng (DONE) hoặc quyết định không sửa (Rejected); thay đổi mã liên kết commit/MR.",
         f"DONE {terminal.get('DONE', 0)}; Rejected {terminal.get('Rejected', 0)}; "
         f"LINK_COMMIT {acts.get('LINK_COMMIT', 0)}; "
         f"LINK_MERGE_REQUEST {acts.get('LINK_MERGE_REQUEST', 0)} event"),
        ("Quy trình và hoạt động",
         "Chuỗi trạng thái Jira từ tạo đến đóng, xen các hoạt động sửa trường, gán người, liên kết.",
         f"{len(statuses)} trạng thái ({', '.join(statuses)}); "
         f"{cases['variant'].nunique()} biến thể trạng thái; "
         f"{core['activity'].nunique()} activity"),
        ("Người tham gia",
         "Các vai trò con người trong log (không phân tích cá nhân).",
         f"{_top(human, 8)}; không xác định: unknown {int((full['role'] == 'unknown').sum())}, "
         f"thiếu role {int((full['role'] == '__MISSING_ROLE__').sum())}"),
        ("Thông tin",
         "Mô tả lỗi, phân loại backlog, phiên bản sửa, epic, story point, file đính kèm, liên kết issue.",
         f"Hoạt động trên trường thông tin: {_top(info, 6)}"),
        ("Công nghệ",
         "Jira (theo dõi issue, workflow) tích hợp hệ thống quản lý mã nguồn qua bot.",
         f"bot {n_bot}/{len(full)} event ({n_bot / len(full):.1%}) trong full view"),
        ("Môi trường",
         "Một team trong công ty phần mềm lớn, có áp lực phát hành (giả định đề bài + trường dữ liệu).",
         f"Giai đoạn {full['timestamp_utc'].min():%Y-%m} → {full['timestamp_utc'].max():%Y-%m}; "
         f"UPDATE_BLOCKING_FOR_RELEASE {acts.get('UPDATE_BLOCKING_FOR_RELEASE', 0)} event"),
        ("Hạ tầng",
         "Máy chủ Jira, Git/merge request và tích hợp tự động dùng chung (giả định đề bài; log không mô tả).",
         f"Dấu vết tích hợp: LINK_COMMIT {acts.get('LINK_COMMIT', 0)}, LINK_MERGE_REQUEST "
         f"{acts.get('LINK_MERGE_REQUEST', 0)} event trong core view"),
    ]
    return pd.DataFrame(rows, columns=["component", "content", "evidence"])
