#!/usr/bin/env python3
"""
ECE-049: Manufacturing Yield and Rework Tracker
Team ID: E027 (Puneeth Kumar G L & Purvitha B V)
Language: Python 3.10+

Command-file-driven PCBA factory test & rework tracking engine implementing
Business Rules BR-01 through BR-08.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


REWORK_LABOR_COST = Decimal("150.00")
MAX_REWORK_LIMIT = 2


@dataclass
class WorkOrder:
    """Represents a manufacturing work order (batch of PCBA boards)."""
    wo_id: str
    product: str
    board_qty: int
    serial_from: str
    serial_to: str
    material_cost_rs: Decimal
    serials: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        prefix, start_str = self.serial_from.split("-")
        _, end_str = self.serial_to.split("-")
        width = len(start_str)
        start_num = int(start_str)
        end_num = int(end_str)
        self.serials = {
            f"{prefix}-{i:0{width}d}" for i in range(start_num, end_num + 1)
        }


@dataclass
class StageInfo:
    """Represents a test stage in sequential order (1: AOI, 2: ICT, 3: FCT)."""
    stage_seq: int
    stage_code: str
    stage_name: str


@dataclass
class DefectInfo:
    """Represents a registered defect code (Dnn = non-fatal, Xnn = fatal)."""
    defect_code: str
    description: str
    usual_stage: str

    @property
    def is_fatal(self) -> bool:
        return self.defect_code.upper().startswith("X")


@dataclass
class TestEvent:
    """Represents a raw test event row from test_events.csv."""
    event_id: str
    serial_no: str
    stage: str
    result: str
    defect_code: str
    timestamp: str
    line_no: int


@dataclass
class BoardState:
    """Tracks the lifecycle state and rework history of a single board serial."""
    serial_no: str
    wo_id: str
    state: str = "IN_PROCESS"  # Initial before first test; logs IN_TEST, REWORK, SCRAP, SHIPPED
    expected_stage_idx: int = 0  # Index into ordered stages [AOI, ICT, FCT]
    rework_count: int = 0
    had_any_failure: bool = False


@dataclass
class BoardLogEntry:
    """One accepted event row in board_log.csv."""
    event_id: str
    serial_no: str
    wo_id: str
    stage: str
    result: str
    defect_code: str
    new_state: str
    rework_count: int


@dataclass
class ErrorEntry:
    """One rejected event row in errors.csv."""
    event_id: str
    line_no: int
    reason: str


@dataclass
class YieldReportEntry:
    """One work-order summary row in yield_report.csv."""
    wo_id: str
    boards_started: int
    first_pass_boards: int
    first_pass_yield_pct: str
    shipped: int
    scrapped: int
    in_process: int
    final_yield_pct: str
    scrap_pct: str
    scrap_cost: str
    rework_cost: str
    status: str


@dataclass
class ParetoEntry:
    """One defect frequency row in defect_pareto.csv."""
    rank: int
    defect_code: str
    count: int
    pct_of_failures: str
    cumulative_pct: str


def fmt_pct(num: Decimal) -> str:
    """Format percentage to 1 decimal place using standard half-up rounding."""
    return str(num.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fmt_money(amount: Decimal) -> str:
    """Format currency in Rs to 2 decimal places using standard half-up rounding."""
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class ManufacturingTrackerEngine:
    """Core rules engine for ECE-049 Manufacturing Yield and Rework Tracker."""

    def __init__(self, base_dir: Path, output_dir: Optional[Path] = None) -> None:
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir) if output_dir else self.base_dir

        self.work_orders: Dict[str, WorkOrder] = {}
        self.work_order_list: List[WorkOrder] = []
        self.serial_to_wo: Dict[str, str] = {}

        self.stages: List[StageInfo] = []
        self.stage_order: List[str] = []

        self.defects: Dict[str, DefectInfo] = {}
        self.events: List[TestEvent] = []

        self.boards: Dict[str, BoardState] = {}
        self.wo_closed: Dict[str, bool] = {}
        self.seen_events: Set[Tuple[str, str, str]] = set()

        self.board_logs: List[BoardLogEntry] = []
        self.errors: List[ErrorEntry] = []
        self.failure_counts: Dict[str, int] = {}

        self.yield_reports: List[YieldReportEntry] = []
        self.pareto_entries: List[ParetoEntry] = []

    # ------------------------------------------------------------------
    # CSV Loaders
    # ------------------------------------------------------------------

    def load_work_orders(self, filename: str) -> None:
        path = self.base_dir / filename
        with path.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                wo = WorkOrder(
                    wo_id=row["wo_id"].strip(),
                    product=row["product"].strip(),
                    board_qty=int(row["board_qty"].strip()),
                    serial_from=row["serial_from"].strip(),
                    serial_to=row["serial_to"].strip(),
                    material_cost_rs=Decimal(row["material_cost_rs"].strip()),
                )
                self.work_orders[wo.wo_id] = wo
                self.work_order_list.append(wo)
                self.wo_closed[wo.wo_id] = False
                for sn in wo.serials:
                    self.serial_to_wo[sn] = wo.wo_id
                    self.boards[sn] = BoardState(serial_no=sn, wo_id=wo.wo_id)

    def load_stages(self, filename: str) -> None:
        path = self.base_dir / filename
        loaded: List[StageInfo] = []
        with path.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                loaded.append(
                    StageInfo(
                        stage_seq=int(row["stage_seq"].strip()),
                        stage_code=row["stage_code"].strip(),
                        stage_name=row["stage_name"].strip(),
                    )
                )
        loaded.sort(key=lambda s: s.stage_seq)
        self.stages = loaded
        self.stage_order = [s.stage_code for s in loaded]

    def load_defects(self, filename: str) -> None:
        path = self.base_dir / filename
        with path.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = DefectInfo(
                    defect_code=row["defect_code"].strip(),
                    description=row["description"].strip(),
                    usual_stage=row["usual_stage"].strip(),
                )
                self.defects[d.defect_code] = d

    def load_events(self, filename: str) -> None:
        path = self.base_dir / filename
        with path.open(mode="r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Header row is line 1; first data row is line 2
            for idx, row in enumerate(reader, start=2):
                self.events.append(
                    TestEvent(
                        event_id=row["event_id"].strip(),
                        serial_no=row["serial_no"].strip(),
                        stage=row["stage"].strip(),
                        result=row["result"].strip(),
                        defect_code=row["defect_code"].strip(),
                        timestamp=row["timestamp"].strip(),
                        line_no=idx,
                    )
                )

    # ------------------------------------------------------------------
    # Event Processing (BR-01, BR-02, BR-03, BR-07, BR-08)
    # ------------------------------------------------------------------

    def process_events(self) -> None:
        """Route every board event-by-event in file order and write board_log.csv and errors.csv."""
        for ev in self.events:
            # BR-08: Duplicate events (same serial, stage, timestamp) are ignored silently
            dup_key = (ev.serial_no, ev.stage, ev.timestamp)
            if dup_key in self.seen_events:
                continue
            self.seen_events.add(dup_key)

            # Check if serial belongs to any registered work order
            wo_id = self.serial_to_wo.get(ev.serial_no)
            if wo_id is None:
                self.errors.append(
                    ErrorEntry(event_id=ev.event_id, line_no=ev.line_no, reason="UNKNOWN_SERIAL")
                )
                continue

            # BR-07: Check if work order is already CLOSED
            if self.wo_closed.get(wo_id, False):
                self.errors.append(
                    ErrorEntry(event_id=ev.event_id, line_no=ev.line_no, reason="WO_CLOSED")
                )
                continue

            board = self.boards[ev.serial_no]

            # BR-07 / Pack convention: A SCRAP board accepts no more events
            if board.state == "SCRAP":
                self.errors.append(
                    ErrorEntry(event_id=ev.event_id, line_no=ev.line_no, reason="BOARD_SCRAPPED")
                )
                continue

            # BR-01: Stage order validation (AOI -> ICT -> FCT)
            # Also rejects if a board already SHIPPED (whilst WO is still OPEN) or wrong stage
            if (
                board.state == "SHIPPED"
                or board.expected_stage_idx >= len(self.stage_order)
                or ev.stage != self.stage_order[board.expected_stage_idx]
            ):
                self.errors.append(
                    ErrorEntry(event_id=ev.event_id, line_no=ev.line_no, reason="SEQUENCE_ERROR")
                )
                continue

            # Validated & accepted event
            if ev.result == "PASS":
                if board.expected_stage_idx == len(self.stage_order) - 1:
                    # Passed final stage (FCT) -> SHIPPED
                    board.state = "SHIPPED"
                    board.expected_stage_idx += 1
                else:
                    # Passed AOI or ICT -> advances to next stage, state is IN_TEST
                    board.state = "IN_TEST"
                    board.expected_stage_idx += 1
            elif ev.result == "FAIL":
                board.had_any_failure = True
                # Count accepted FAIL event for Defect Pareto (BR-08)
                self.failure_counts[ev.defect_code] = (
                    self.failure_counts.get(ev.defect_code, 0) + 1
                )

                is_fatal = ev.defect_code.upper().startswith("X")
                if is_fatal:
                    # BR-03: Fatal defects (X-code) scrap the board immediately regardless of rework count
                    board.state = "SCRAP"
                else:
                    # BR-02: Rework loop (max 2 times in total across all stages; 3rd failure -> SCRAP)
                    if board.rework_count >= MAX_REWORK_LIMIT:
                        board.state = "SCRAP"
                    else:
                        board.rework_count += 1
                        board.state = "REWORK"
                        # Remains at the same expected_stage_idx for retest

            # Record accepted event in board_log
            self.board_logs.append(
                BoardLogEntry(
                    event_id=ev.event_id,
                    serial_no=ev.serial_no,
                    wo_id=wo_id,
                    stage=ev.stage,
                    result=ev.result,
                    defect_code=ev.defect_code,
                    new_state=board.state,
                    rework_count=board.rework_count,
                )
            )

            # BR-07: Check if work order is now CLOSED (every serial is SHIPPED or SCRAP)
            if board.state in ("SHIPPED", "SCRAP"):
                wo = self.work_orders[wo_id]
                if all(self.boards[s].state in ("SHIPPED", "SCRAP") for s in wo.serials):
                    self.wo_closed[wo_id] = True

        self._write_board_log()
        self._write_errors()

    # ------------------------------------------------------------------
    # Reports (BR-04, BR-05, BR-06, BR-07, BR-08)
    # ------------------------------------------------------------------

    def generate_yield_report(self) -> List[YieldReportEntry]:
        """Compute per-work-order yield and cost metrics and write yield_report.csv."""
        self.yield_reports.clear()
        for wo in self.work_order_list:
            boards_started = wo.board_qty
            first_pass_boards = 0
            shipped = 0
            scrapped = 0
            in_process = 0
            scrap_cost = Decimal("0.00")
            rework_cost = Decimal("0.00")

            for sn in sorted(wo.serials):
                b = self.boards[sn]
                if b.state == "SHIPPED":
                    shipped += 1
                    if not b.had_any_failure and b.rework_count == 0:
                        first_pass_boards += 1
                    rework_cost += REWORK_LABOR_COST * b.rework_count
                elif b.state == "SCRAP":
                    scrapped += 1
                    scrap_cost += wo.material_cost_rs + (REWORK_LABOR_COST * b.rework_count)
                else:
                    in_process += 1
                    rework_cost += REWORK_LABOR_COST * b.rework_count

            # BR-04: First-pass yield
            fpy = (Decimal(first_pass_boards) * Decimal("100")) / Decimal(boards_started)
            # BR-05: Final yield and scrap percentage
            final_yield = (Decimal(shipped) * Decimal("100")) / Decimal(boards_started)
            scrap_pct = Decimal("100.0") - Decimal(fmt_pct(final_yield))

            status = "CLOSED" if self.wo_closed.get(wo.wo_id, False) else "OPEN"

            self.yield_reports.append(
                YieldReportEntry(
                    wo_id=wo.wo_id,
                    boards_started=boards_started,
                    first_pass_boards=first_pass_boards,
                    first_pass_yield_pct=fmt_pct(fpy),
                    shipped=shipped,
                    scrapped=scrapped,
                    in_process=in_process,
                    final_yield_pct=fmt_pct(final_yield),
                    scrap_pct=fmt_pct(scrap_pct),
                    scrap_cost=fmt_money(scrap_cost),
                    rework_cost=fmt_money(rework_cost),
                    status=status,
                )
            )

        self._write_yield_report()
        return self.yield_reports

    def generate_pareto(self) -> List[ParetoEntry]:
        """Compute defect Pareto sorted by count desc, defect_code asc and write defect_pareto.csv."""
        self.pareto_entries.clear()
        total_failures = sum(self.failure_counts.values())

        # Sort by count descending, then defect_code ascending (pack tie-breaker rule)
        sorted_defects = sorted(
            self.failure_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )

        cumulative_count = 0
        for rank, (defect_code, count) in enumerate(sorted_defects, start=1):
            cumulative_count += count
            if total_failures > 0:
                pct = (Decimal(count) * Decimal("100")) / Decimal(total_failures)
                cum_pct = (Decimal(cumulative_count) * Decimal("100")) / Decimal(total_failures)
            else:
                pct = Decimal("0.0")
                cum_pct = Decimal("0.0")

            self.pareto_entries.append(
                ParetoEntry(
                    rank=rank,
                    defect_code=defect_code,
                    count=count,
                    pct_of_failures=fmt_pct(pct),
                    cumulative_pct=fmt_pct(cum_pct),
                )
            )

        self._write_pareto()
        return self.pareto_entries

    # ------------------------------------------------------------------
    # Command File Runner
    # ------------------------------------------------------------------

    def run_commands_file(self, commands_file: Path) -> None:
        """Execute commands from commands.txt in top-to-bottom order."""
        with Path(commands_file).open(mode="r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                cmd = parts[0].upper()

                if cmd == "LOAD_WORK_ORDERS":
                    self.load_work_orders(parts[1])
                elif cmd == "LOAD_STAGES":
                    self.load_stages(parts[1])
                elif cmd == "LOAD_DEFECTS":
                    self.load_defects(parts[1])
                elif cmd == "LOAD_EVENTS":
                    self.load_events(parts[1])
                elif cmd == "PROCESS":
                    self.process_events()
                elif cmd == "YIELD_REPORT":
                    self.generate_yield_report()
                elif cmd == "PARETO":
                    self.generate_pareto()
                else:
                    raise ValueError(f"Unknown command: {cmd}")

    # ------------------------------------------------------------------
    # CSV Writers
    # ------------------------------------------------------------------

    def _write_board_log(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "board_log.csv"
        with out_path.open(mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "event_id",
                "serial_no",
                "wo_id",
                "stage",
                "result",
                "defect_code",
                "new_state",
                "rework_count",
            ])
            for entry in self.board_logs:
                writer.writerow([
                    entry.event_id,
                    entry.serial_no,
                    entry.wo_id,
                    entry.stage,
                    entry.result,
                    entry.defect_code,
                    entry.new_state,
                    entry.rework_count,
                ])

    def _write_errors(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "errors.csv"
        with out_path.open(mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["event_id", "line_no", "reason"])
            for err in self.errors:
                writer.writerow([err.event_id, err.line_no, err.reason])

    def _write_yield_report(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "yield_report.csv"
        with out_path.open(mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "wo_id",
                "boards_started",
                "first_pass_boards",
                "first_pass_yield_pct",
                "shipped",
                "scrapped",
                "in_process",
                "final_yield_pct",
                "scrap_pct",
                "scrap_cost",
                "rework_cost",
                "status",
            ])
            for r in self.yield_reports:
                writer.writerow([
                    r.wo_id,
                    r.boards_started,
                    r.first_pass_boards,
                    r.first_pass_yield_pct,
                    r.shipped,
                    r.scrapped,
                    r.in_process,
                    r.final_yield_pct,
                    r.scrap_pct,
                    r.scrap_cost,
                    r.rework_cost,
                    r.status,
                ])

    def _write_pareto(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "defect_pareto.csv"
        with out_path.open(mode="w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank",
                "defect_code",
                "count",
                "pct_of_failures",
                "cumulative_pct",
            ])
            for p in self.pareto_entries:
                writer.writerow([
                    p.rank,
                    p.defect_code,
                    p.count,
                    p.pct_of_failures,
                    p.cumulative_pct,
                ])


def main() -> None:
    cmd_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("commands.txt")
    base_dir = cmd_path.parent
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else base_dir
    engine = ManufacturingTrackerEngine(base_dir=base_dir, output_dir=out_dir)
    engine.run_commands_file(cmd_path)


if __name__ == "__main__":
    main()
