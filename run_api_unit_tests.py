import argparse
import json
import platform
import sys
import time
import traceback
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class ReportingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records: List[Dict[str, Any]] = []
        self._started_at: Dict[unittest.TestCase, float] = {}

    def startTest(self, test):
        self._started_at[test] = time.perf_counter()
        super().startTest(test)

    def _duration(self, test) -> float:
        return round(time.perf_counter() - self._started_at.get(test, time.perf_counter()), 4)

    def _record(self, test, status: str, message: str = "") -> None:
        self.records.append(
            {
                "name": str(test),
                "status": status,
                "duration_seconds": self._duration(test),
                "message": message,
            }
        )

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", "".join(traceback.format_exception(*err)))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", "".join(traceback.format_exception(*err)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)


class ReportingRunner(unittest.TextTestRunner):
    resultclass = ReportingResult


def build_report(result: ReportingResult, elapsed: float) -> Dict[str, Any]:
    counts = {
        "total": result.testsRun,
        "passed": len([record for record in result.records if record["status"] == "passed"]),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "duration_seconds": round(elapsed, 4),
        "status": "passed" if result.wasSuccessful() else "failed",
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "counts": counts,
        "tests": result.records,
    }


def write_json_report(report: Dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(report: Dict[str, Any], path: Path) -> None:
    counts = report["counts"]
    lines = [
        "# API Unit Test Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Duration: `{report['duration_seconds']}s`",
        f"- Python: `{report['python']}`",
        f"- Platform: `{report['platform']}`",
        "",
        "## Summary",
        "",
        "| Total | Passed | Failed | Errors | Skipped |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {counts['total']} | {counts['passed']} | {counts['failed']} | {counts['errors']} | {counts['skipped']} |",
        "",
        "## Cases",
        "",
        "| Status | Duration | Test |",
        "| --- | ---: | --- |",
    ]
    for record in report["tests"]:
        lines.append(f"| `{record['status']}` | {record['duration_seconds']}s | `{record['name']}` |")

    failed_records = [record for record in report["tests"] if record["status"] in {"failed", "error"}]
    if failed_records:
        lines.extend(["", "## Failures"])
        for record in failed_records:
            lines.extend([
                "",
                f"### {record['name']}",
                "",
                "```text",
                record["message"].strip(),
                "```",
            ])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run API gateway unit tests and generate reports.")
    parser.add_argument("--reports-dir", default=str(ROOT / "test_reports"))
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    start = time.perf_counter()
    result = ReportingRunner(verbosity=2).run(suite)
    elapsed = time.perf_counter() - start

    report = build_report(result, elapsed)
    write_json_report(report, reports_dir / "api_unit_report.json")
    write_markdown_report(report, reports_dir / "api_unit_report.md")

    print(f"\nReports written to: {reports_dir}")
    print(f"- {reports_dir / 'api_unit_report.md'}")
    print(f"- {reports_dir / 'api_unit_report.json'}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
