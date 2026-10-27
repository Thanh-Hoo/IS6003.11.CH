"""CLI `jira-ad`: `audit`, `prepare`, `run`, `compare`, `score` (và `notebooks` ở bước notebook)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jira_ad.analysis import NotebookInputError
from jira_ad.config import ConfigError, RunConfig, load_config, resolve_project_root
from jira_ad.data import DataError, build_audit_report
from jira_ad.detector import load_bundle
from jira_ad.experiments import load_plan, run_plan
from jira_ad.improvement import run_improvement
from jira_ad.notebook_runner import (
    NotebookExecutionError,
    execute_notebooks,
    execute_process_notebooks,
    is_process_run,
)
from jira_ad.pipeline import (
    PrepareError,
    PrepareResult,
    RunError,
    compare_runs,
    comparison_frame,
    prepare,
    run_experiment,
    score_raw_csv,
    write_json_atomic,
)
from jira_ad.preprocess import ActionRulesError
from jira_ad.process_run import FrozenInputChanged, RunExistsError, run_process
from jira_ad.splits import SplitError


def _print_audit_summary(report: dict, out_path: Path, cfg: RunConfig) -> None:
    for item in report["inputs"]:
        print(f"[{item['cohort']}] {item['relative_path']}  sha256={item['sha256'][:16]}…  "
              f"{item['n_rows']} dòng, {item['size_bytes']} byte")
    differences = []
    for cohort, stats in report["cohorts"].items():
        epc = stats["events_per_case"]
        spread = "n/a" if epc is None else f"{epc['min']}-{epc['median']}-{epc['max']}"
        print(
            f"[{cohort}] {stats['n_events']} event, {stats['n_cases']} issue; "
            f"role trống={stats['n_blank_role']}, bot={stats['n_role_bot']}; "
            f"issue cần sắp lại={stats['n_cases_needing_reorder']}; "
            f"nhóm trùng thời điểm={stats['n_tie_groups']}; event/issue min-median-max={spread}"
        )
        for key, diff in (stats["reference_diff"] or {}).items():
            if diff["delta"] != 0:
                differences.append(
                    f"[{cohort}] {key}: tài liệu {diff['expected']}, thực tế {diff['actual']}"
                )
    if differences:
        print("Có sai khác so với số liệu tham chiếu trong tài liệu (dùng số thực tế):")
        for line in differences:
            print("  " + line)
    elif any(s["reference_diff"] for s in report["cohorts"].values()):
        print("Số event/issue khớp số liệu tham chiếu trong tài liệu.")
    print(f"Báo cáo: {out_path.relative_to(cfg.project_root)}")


def _cmd_audit(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    report = build_audit_report(cfg)
    out_path = cfg.output_dir / "analysis" / "audit_raw.json"
    write_json_atomic(out_path, report)
    _print_audit_summary(report, out_path, cfg)
    return 0


def _print_prepare_summary(result: PrepareResult, cfg: RunConfig) -> None:
    a = result.audit
    full, core, funnel = a["full_view"], a["core_view"], a["funnel"]
    print(f"[{a['cohort']}] full view: {full['n_events']} event, {full['n_cases']} issue")
    print(f"[{a['cohort']}] core view ({a['noise_policy']}): "
          f"{core['n_events']} event, {core['n_cases']} issue")
    reasons = ", ".join(f"{k}={v}" for k, v in a["case_exclusions"].items()) or "không có"
    print(f"Issue bị loại: {reasons}")
    print(f"Event bị loại: case bị loại={funnel['n_events_in_excluded_cases']}, "
          f"sau terminal={funnel['n_events_post_terminal']}, "
          f"nhiễu theo policy={funnel['n_events_dropped_noise']}")
    print(f"Issue có reopen trước mốc cuối: {a['reopen']['n_cases_with_reopen']}; "
          f"terminal: {core['terminal_status_counts']}")
    sizes = a["split"]["sizes"]
    print(f"Split (seed {a['settings']['split']['seed']}, "
          f"stratify {a['settings']['split']['stratify']}): train={sizes['train']}, "
          f"validation={sizes['validation']}, test={sizes['test']}; "
          f"split_hash={a['split']['split_hash'][:16]}…")
    note = "đã có và khớp bản tính lại (không ghi đè)" if result.reused else "mới"
    print(f"Prepared ({note}): {result.directory.relative_to(cfg.project_root)}")


def _cmd_prepare(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    result = prepare(cfg)
    _print_prepare_summary(result, cfg)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = run_experiment(cfg)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    print(f"Run dir: {run_dir.relative_to(cfg.project_root).as_posix()}")
    elapsed = sum(manifest["stage_timings"].values())
    print(f"Trạng thái: {manifest['status']}; thời gian: {elapsed:.1f}s; "
          f"split_hash={manifest['split_hash'][:16]}…")
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    test = metrics["splits"]["test"]
    print("Test (holdout; mutant bán tổng hợp, tỷ lệ thiết kế 0,5) — macro theo loại:")
    for method, macro in test["macro_by_method"].items():
        print(f"  {method:12s} AUROC={macro['macro_auroc']:.3f}  "
              f"AP={macro['macro_average_precision']:.3f}  "
              f"paired_win={macro['macro_paired_win_rate']:.3f}")
    print("Đây là đánh giá bán tổng hợp, không phải độ chính xác phát hiện lỗi thực tế.")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    result = compare_runs(args.runs_dir, split=args.split)
    frame = comparison_frame(result)
    out = Path(args.runs_dir) / "comparison.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False, lineterminator="\n")
    for group in result["groups"]:
        print(f"protocol {group['protocol_id']} / model {group['model_config_id']}: "
              f"{len(group['runs'])} run — {', '.join(group['runs'])}")
    for item in result["skipped"]:
        print(f"bỏ qua {item['run_id']}: {item['reason']}")
    print(f"{len(result['groups'])} nhóm (không trộn protocol khác nhau); bảng: {out}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    bundle = load_bundle(args.bundle)
    frame = score_raw_csv(bundle, args.input_csv, args.output)
    print(f"Đã chấm {int(frame['scored'].sum())}/{len(frame)} ca bằng {bundle.method} "
          f"(không fit lại); ca không chấm kèm lý do: {args.output}")
    return 0


def _cmd_notebooks(args: argparse.Namespace) -> int:
    runner = execute_process_notebooks if is_process_run(args.run_dir) else execute_notebooks
    results = runner(args.run_dir, args.notebooks_dir, args.timeout, args.only)
    for item in results:
        print(f"{item['name']}: {item['status']} ({item['seconds']:.1f}s)")
    print(f"Đã lưu bản thực thi vào {Path(args.run_dir) / 'notebooks_executed'} (kernel: {sys.executable})")
    return 0


def _cmd_experiments(args: argparse.Namespace) -> int:
    if args.dry_run:
        plan = load_plan(args.config)
        for experiment in plan.experiments:
            if args.only and experiment.name not in args.only:
                continue
            changes = ", ".join(f"{k}={v}" for k, v in experiment.changes.items()) or "(baseline)"
            print(f"{experiment.name}: {changes}; model seeds {list(experiment.seeds)}"
                  + (f" — {experiment.note}" if experiment.note else ""))
        print("Dry-run: chưa chạy gì.")
        return 0
    results = run_plan(args.config, only=args.only)
    root = resolve_project_root(args.config)
    for item in results:
        print(f"{item.experiment} (seed {item.seed}) → Run dir: "
              f"{item.run_dir.relative_to(root).as_posix()}")
    print(f"Đã chạy {len(results)} run; so sánh: uv run jira-ad compare --runs-dir outputs/runs")
    return 0


def _cmd_improve(args: argparse.Namespace) -> int:
    import pandas as pd

    out = run_improvement(args.plan)
    print(f"Thư mục kết quả: {out}")
    decision = pd.read_csv(out / "decision_validation.csv")
    print("Phán quyết (decision, validation, khóa trước):")
    for row in decision.itertuples():
        print(f"  {row.candidate} − {row.reference}: {row.estimate:+.4f} "
              f"[{row.ci_low:+.4f}, {row.ci_high:+.4f}] ⇒ {row.verdict}")
    print("Mức ứng dụng (cross-validation):")
    for row in pd.read_csv(out / "applicability.csv").itertuples():
        print(f"  {row.method:15s} macro AUROC {row.cv_macro_auroc:.3f} "
              f"[{row.cv_macro_auroc_ci_low:.3f}, {row.cv_macro_auroc_ci_high:.3f}] ⇒ {row.verdict}")
    print("Đây là đánh giá bán tổng hợp, không phải độ chính xác phát hiện lỗi thực tế.")
    return 0


def _cmd_process(args: argparse.Namespace) -> int:
    out = run_process(args.config)
    root = resolve_project_root(args.config)
    print(f"Run dir: {out.relative_to(root).as_posix()}")
    return 0


def _cmd_check_report(args: argparse.Namespace) -> int:
    from jira_ad.process_report import artifact_values, check_report, extract_numbers

    text = Path(args.report).read_text(encoding="utf-8")
    missing = check_report(text, artifact_values(args.run_dir))
    total = len(extract_numbers(text))
    print(f"Đã đối chiếu {total} con số trong {args.report} với {args.run_dir}; chưa khớp: {len(missing)}")
    for item in missing:
        print(f"  {item.token}: …{item.context}…")
    return 1 if missing else 0


def _cmd_blind_review_compare(args: argparse.Namespace) -> int:
    import pandas as pd

    from jira_ad.process_analysis import fmt, open_process_run
    from jira_ad.ranking import compare_blind_review

    run = open_process_run(args.run_dir)  # kiểm fingerprint trước khi mở khóa
    key = run.csv("e_ranking/blind_review_key.csv")
    try:
        out = compare_blind_review(pd.read_csv(args.labels, keep_default_na=False), key)
    except ValueError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2
    for group, name in (("top", "top (nên xem trước)"), ("random", "ngẫu nhiên")):
        g = out[group]
        lo, hi = g["share_ci"]
        print(f"{name}: {g['needs_review']}/{g['n']} needs_review = {fmt(g['share'], 1, percent=True)} "
              f"[Wilson 95%: {fmt(lo, 1, percent=True)}; {fmt(hi, 1, percent=True)}]; "
              f"plausibly_valid {g['plausibly_valid']}, insufficient_evidence {g['insufficient_evidence']}")
    lo, hi = out["difference_ci"]
    print(f"Hiệu tỉ lệ (top − ngẫu nhiên): {fmt(out['difference'], 1, percent=True)} "
          f"[Newcombe 95%: {fmt(lo, 1, percent=True)}; {fmt(hi, 1, percent=True)}]")
    olo, ohi = out["odds_ratio_ci"]
    print(f"Odds ratio {fmt(out['odds_ratio'], 2)} [95%: {fmt(olo, 2)}; {fmt(ohi, 2)}]; "
          f"Fisher exact hai phía p = {out['fisher_p_two_sided']:.4f}".replace(".", ","))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jira-ad", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser(
        "audit", help="Audit dữ liệu thô: fingerprint, số event/issue, chất lượng"
    )
    audit.add_argument("--config", required=True, type=Path)
    audit.set_defaults(handler=_cmd_audit)
    prep = sub.add_parser(
        "prepare", help="Chuẩn hóa, core view và split cố định; ghi artifact trước khi học mô hình"
    )
    prep.add_argument("--config", required=True, type=Path)
    prep.set_defaults(handler=_cmd_prepare)
    run = sub.add_parser("run", help="prepare → fit A–D → mutant → score → evaluate → artifact")
    run.add_argument("--config", required=True, type=Path)
    run.set_defaults(handler=_cmd_run)
    compare = sub.add_parser("compare", help="So sánh các run đã hoàn tất, nhóm theo protocol")
    compare.add_argument("--runs-dir", required=True, type=Path)
    compare.add_argument("--split", default="test", choices=("validation", "test"))
    compare.set_defaults(handler=_cmd_compare)
    score = sub.add_parser("score", help="Chấm điểm CSV thô bằng bundle đã lưu (không fit)")
    score.add_argument("--bundle", required=True, type=Path)
    score.add_argument("--input-csv", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    score.set_defaults(handler=_cmd_score)
    exp = sub.add_parser("experiments", help="Chạy ma trận thực nghiệm thành phần (từng yếu tố một)")
    exp.add_argument("--config", required=True, type=Path)
    exp.add_argument("--only", nargs="*", default=None, help="chỉ chạy các thí nghiệm này")
    exp.add_argument("--dry-run", action="store_true", help="chỉ liệt kê kế hoạch, không chạy")
    exp.set_defaults(handler=_cmd_experiments)
    imp = sub.add_parser("improve", help="Giai đoạn cải tiến: chọn phương án, cross-validation, ứng dụng")
    imp.add_argument("--plan", required=True, type=Path)
    imp.set_defaults(handler=_cmd_improve)
    proc = sub.add_parser("process", help="Giai đoạn 2: phân tích, kiểm định, tái thiết kế quy trình")
    proc.add_argument("--config", required=True, type=Path)
    proc.set_defaults(handler=_cmd_process)
    chk = sub.add_parser("check-report",
                         help="Đối chiếu mọi con số trong báo cáo với artifact của một run process")
    chk.add_argument("--report", required=True, type=Path)
    chk.add_argument("--run-dir", required=True, type=Path)
    chk.set_defaults(handler=_cmd_check_report)
    blind = sub.add_parser("blind-review-compare",
                           help="Mở khóa bảng mù đã gán nhãn, so top với ngẫu nhiên (Fisher, khoảng tin cậy)")
    blind.add_argument("--run-dir", required=True, type=Path)
    blind.add_argument("--labels", required=True, type=Path)
    blind.set_defaults(handler=_cmd_blind_review_compare)
    nbs = sub.add_parser("notebooks", help="Chạy các notebook trên một run bằng nbclient")
    nbs.add_argument("--run-dir", required=True, type=Path)
    nbs.add_argument("--notebooks-dir", type=Path, default=None)
    nbs.add_argument("--timeout", type=int, default=None, help="giây mỗi cell (mặc định: cấu hình)")
    nbs.add_argument("--only", nargs="*", default=None, help="chỉ chạy các notebook này")
    nbs.set_defaults(handler=_cmd_notebooks)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, DataError, ActionRulesError, SplitError, PrepareError, RunError,
            NotebookInputError, NotebookExecutionError, RunExistsError, FrozenInputChanged) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
