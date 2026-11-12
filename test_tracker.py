#!/usr/bin/env python3
"""
Unit and Integration Test Suite for ECE-049: Manufacturing Yield and Rework Tracker
Team ID: E027 (Puneeth Kumar G L & Purvitha B V)

Compatible with both pytest and Python's standard unittest runner:
    pytest test_tracker.py -v
    python3 -m unittest test_tracker.py -v
    python3 test_tracker.py
"""

from pathlib import Path
import tempfile
import unittest

from tracker import ManufacturingTrackerEngine


def _write_minimal_masters(tmp_path: Path, wo_rows: list[str]) -> None:
    """Helper to write standard stages.csv, defect_codes.csv, and custom work_orders.csv."""
    (tmp_path / "stages.csv").write_text(
        "stage_seq,stage_code,stage_name\n"
        "1,AOI,Automated optical inspection\n"
        "2,ICT,In-circuit test\n"
        "3,FCT,Functional test\n",
        encoding="utf-8",
    )
    (tmp_path / "defect_codes.csv").write_text(
        "defect_code,description,usual_stage\n"
        "D01,Solder bridge,AOI\n"
        "D04,Wrong polarity,AOI\n"
        "D05,Insufficient solder,AOI\n"
        "D07,Open net,ICT\n"
        "D08,Supply current high,FCT\n"
        "D10,RF output low,FCT\n"
        "X01,Lifted pad,AOI\n"
        "X02,Burnt IC,ICT\n"
        "X03,Cracked PCB,FCT\n",
        encoding="utf-8",
    )
    header = "wo_id,product,board_qty,serial_from,serial_to,material_cost_rs\n"
    (tmp_path / "work_orders.csv").write_text(
        header + "\n".join(wo_rows) + "\n",
        encoding="utf-8",
    )


def _run_engine_with_events(
    tmp_path: Path, wo_rows: list[str], event_rows: list[str]
) -> ManufacturingTrackerEngine:
    _write_minimal_masters(tmp_path, wo_rows)
    ev_header = "event_id,serial_no,stage,result,defect_code,timestamp\n"
    (tmp_path / "test_events.csv").write_text(
        ev_header + "\n".join(event_rows) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "commands.txt").write_text(
        "LOAD_WORK_ORDERS|work_orders.csv\n"
        "LOAD_STAGES|stages.csv\n"
        "LOAD_DEFECTS|defect_codes.csv\n"
        "LOAD_EVENTS|test_events.csv\n"
        "PROCESS\n"
        "YIELD_REPORT\n"
        "PARETO\n",
        encoding="utf-8",
    )
    engine = ManufacturingTrackerEngine(base_dir=tmp_path, output_dir=tmp_path)
    engine.run_commands_file(tmp_path / "commands.txt")
    return engine


class TestManufacturingTracker(unittest.TestCase):
    """Comprehensive test suite covering BR-01 through BR-08 and planted sample scenarios."""

    def test_br01_stage_order_sequence_error(self) -> None:
        """BR-01: Board must pass AOI -> ICT -> FCT strictly in order; jumping ahead logs SEQUENCE_ERROR."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,1,SN-00001,SN-00001,500.00"],
                [
                    "EV-00001,SN-00001,ICT,PASS,NONE,2026-10-05 09:00:00",  # Jump to ICT before AOI
                    "EV-00002,SN-00001,AOI,PASS,NONE,2026-10-05 09:05:00",  # Valid AOI
                    "EV-00003,SN-00001,FCT,PASS,NONE,2026-10-05 09:10:00",  # Jump to FCT before ICT
                    "EV-00004,SN-00001,ICT,PASS,NONE,2026-10-05 09:15:00",  # Valid ICT
                    "EV-00005,SN-00001,FCT,PASS,NONE,2026-10-05 09:20:00",  # Valid FCT -> SHIPPED
                ],
            )
            self.assertEqual(len(engine.errors), 2)
            self.assertEqual(engine.errors[0].event_id, "EV-00001")
            self.assertEqual(engine.errors[0].line_no, 2)
            self.assertEqual(engine.errors[0].reason, "SEQUENCE_ERROR")
            self.assertEqual(engine.errors[1].event_id, "EV-00003")
            self.assertEqual(engine.errors[1].line_no, 4)
            self.assertEqual(engine.errors[1].reason, "SEQUENCE_ERROR")
            self.assertEqual(engine.boards["SN-00001"].state, "SHIPPED")

    def test_br02_rework_loop_and_third_fail_scrap(self) -> None:
        """BR-02: Max 2 reworks across all stages; 3rd non-fatal failure transitions board to SCRAP."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,2,SN-00001,SN-00002,1000.00"],
                [
                    # SN-00001 fails twice (AOI, FCT), passes retests, and ships
                    "EV-00001,SN-00001,AOI,FAIL,D01,2026-10-05 09:00:00",
                    "EV-00002,SN-00001,AOI,PASS,NONE,2026-10-05 09:10:00",
                    "EV-00003,SN-00001,ICT,PASS,NONE,2026-10-05 09:20:00",
                    "EV-00004,SN-00001,FCT,FAIL,D08,2026-10-05 09:30:00",
                    "EV-00005,SN-00001,FCT,PASS,NONE,2026-10-05 09:40:00",
                    # SN-00002 fails 3 times -> SCRAP on 3rd failure with rework_count = 2
                    "EV-00006,SN-00002,AOI,FAIL,D01,2026-10-05 10:00:00",
                    "EV-00007,SN-00002,AOI,PASS,NONE,2026-10-05 10:10:00",
                    "EV-00008,SN-00002,ICT,FAIL,D07,2026-10-05 10:20:00",
                    "EV-00009,SN-00002,ICT,PASS,NONE,2026-10-05 10:30:00",
                    "EV-00010,SN-00002,FCT,FAIL,D10,2026-10-05 10:40:00",
                ],
            )
            self.assertEqual(engine.boards["SN-00001"].state, "SHIPPED")
            self.assertEqual(engine.boards["SN-00001"].rework_count, 2)
            self.assertEqual(engine.boards["SN-00002"].state, "SCRAP")
            self.assertEqual(engine.boards["SN-00002"].rework_count, 2)

    def test_br03_fatal_x_code_immediate_scrap(self) -> None:
        """BR-03: Defect codes starting with X scrap the board immediately without adding rework."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,1,SN-00001,SN-00001,385.00"],
                [
                    "EV-00001,SN-00001,AOI,FAIL,X01,2026-10-05 09:00:00",
                ],
            )
            self.assertEqual(engine.boards["SN-00001"].state, "SCRAP")
            self.assertEqual(engine.boards["SN-00001"].rework_count, 0)
            self.assertEqual(engine.yield_reports[0].scrap_cost, "385.00")
            self.assertEqual(engine.yield_reports[0].rework_cost, "0.00")

    def test_br04_br05_br06_yield_and_cost_calculations(self) -> None:
        """BR-04, BR-05, BR-06: Verify first-pass yield, final yield, scrap %, scrap cost, and rework cost."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,4,SN-00001,SN-00004,1000.00"],
                [
                    # SN-00001: First-pass ship (0 failures)
                    "EV-00001,SN-00001,AOI,PASS,NONE,2026-10-05 09:00:00",
                    "EV-00002,SN-00001,ICT,PASS,NONE,2026-10-05 09:05:00",
                    "EV-00003,SN-00001,FCT,PASS,NONE,2026-10-05 09:10:00",
                    # SN-00002: 1 rework then ship (Rs 150 rework_cost)
                    "EV-00004,SN-00002,AOI,FAIL,D01,2026-10-05 09:15:00",
                    "EV-00005,SN-00002,AOI,PASS,NONE,2026-10-05 09:20:00",
                    "EV-00006,SN-00002,ICT,PASS,NONE,2026-10-05 09:25:00",
                    "EV-00007,SN-00002,FCT,PASS,NONE,2026-10-05 09:30:00",
                    # SN-00003: 1 rework then fatal X02 at ICT -> SCRAP (scrap_cost = 1000 + 150 = 1150)
                    "EV-00008,SN-00003,AOI,FAIL,D05,2026-10-05 09:35:00",
                    "EV-00009,SN-00003,AOI,PASS,NONE,2026-10-05 09:40:00",
                    "EV-00010,SN-00003,ICT,FAIL,X02,2026-10-05 09:45:00",
                    # SN-00004: First-pass ship (0 failures)
                    "EV-00011,SN-00004,AOI,PASS,NONE,2026-10-05 09:50:00",
                    "EV-00012,SN-00004,ICT,PASS,NONE,2026-10-05 09:55:00",
                    "EV-00013,SN-00004,FCT,PASS,NONE,2026-10-05 10:00:00",
                ],
            )
            yr = engine.yield_reports[0]
            self.assertEqual(yr.boards_started, 4)
            self.assertEqual(yr.first_pass_boards, 2)
            self.assertEqual(yr.first_pass_yield_pct, "50.0")
            self.assertEqual(yr.shipped, 3)
            self.assertEqual(yr.scrapped, 1)
            self.assertEqual(yr.in_process, 0)
            self.assertEqual(yr.final_yield_pct, "75.0")
            self.assertEqual(yr.scrap_pct, "25.0")
            self.assertEqual(yr.scrap_cost, "1150.00")
            self.assertEqual(yr.rework_cost, "150.00")
            self.assertEqual(yr.status, "CLOSED")

    def test_br07_work_order_closure_and_scrapped_board_rejection(self) -> None:
        """BR-07: Reject events on CLOSED work order, SCRAP board, or UNKNOWN_SERIAL."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,2,SN-00001,SN-00002,500.00"],
                [
                    "EV-00001,SN-09999,AOI,PASS,NONE,2026-10-05 09:00:00",  # UNKNOWN_SERIAL
                    "EV-00002,SN-00001,AOI,FAIL,X01,2026-10-05 09:05:00",   # SN-00001 -> SCRAP
                    "EV-00003,SN-00001,AOI,PASS,NONE,2026-10-05 09:10:00",  # BOARD_SCRAPPED (WO still OPEN)
                    "EV-00004,SN-00002,AOI,PASS,NONE,2026-10-05 09:15:00",
                    "EV-00005,SN-00002,ICT,PASS,NONE,2026-10-05 09:20:00",
                    "EV-00006,SN-00002,FCT,PASS,NONE,2026-10-05 09:25:00",  # SN-00002 -> SHIPPED (WO-0001 now CLOSED)
                    "EV-00007,SN-00002,FCT,PASS,NONE,2026-10-05 09:30:00",  # WO_CLOSED
                ],
            )
            reasons = [(e.event_id, e.reason) for e in engine.errors]
            self.assertEqual(
                reasons,
                [
                    ("EV-00001", "UNKNOWN_SERIAL"),
                    ("EV-00003", "BOARD_SCRAPPED"),
                    ("EV-00007", "WO_CLOSED"),
                ],
            )

    def test_br08_duplicate_ignored_and_pareto_tie_breaker(self) -> None:
        """BR-08: Duplicate events are ignored silently; Pareto ties sort ascending by defect_code."""
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = _run_engine_with_events(
                tmp_path,
                ["WO-0001,Test Board,2,SN-00001,SN-00002,500.00"],
                [
                    "EV-00001,SN-00001,AOI,FAIL,D05,2026-10-05 09:00:00",
                    "EV-00002,SN-00001,AOI,FAIL,D05,2026-10-05 09:00:00",  # Duplicate -> ignored silently
                    "EV-00003,SN-00002,AOI,FAIL,D01,2026-10-05 09:05:00",
                ],
            )
            self.assertEqual(len(engine.board_logs), 2)
            self.assertEqual(len(engine.errors), 0)
            self.assertEqual([p.defect_code for p in engine.pareto_entries], ["D01", "D05"])

    def test_e027_sample_data_pack_verification(self) -> None:
        """Integration test verifying all 11 planted scenarios in the E027 sample data pack."""
        here = Path(__file__).resolve().parent
        if (here / "commands.txt").exists() and (here / "test_events.csv").exists():
            sample_dir = here
        else:
            sample_dir = Path("/working_dir/c_26ca2774509d0604/downloads/E027/E027-ECE-049-sample-data")
            if not sample_dir.exists():
                return

        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            engine = ManufacturingTrackerEngine(base_dir=sample_dir, output_dir=tmp_path)
            engine.run_commands_file(sample_dir / "commands.txt")

            # 1. WO-0001 all 50 boards pass first time
            wo1 = engine.yield_reports[0]
            self.assertEqual(wo1.wo_id, "WO-0001")
            self.assertEqual(wo1.first_pass_yield_pct, "100.0")
            self.assertEqual(wo1.final_yield_pct, "100.0")
            self.assertEqual(wo1.scrap_cost, "0.00")
            self.assertEqual(wo1.status, "CLOSED")

            # 2. SN-00111 and SN-00165 fail twice then ship with rework_count = 2
            self.assertEqual(engine.boards["SN-00111"].state, "SHIPPED")
            self.assertEqual(engine.boards["SN-00111"].rework_count, 2)
            self.assertEqual(engine.boards["SN-00165"].state, "SHIPPED")
            self.assertEqual(engine.boards["SN-00165"].rework_count, 2)

            # 3. SN-00214 fails AOI with X01 on first test -> SCRAP, rework_count = 0
            self.assertEqual(engine.boards["SN-00214"].state, "SCRAP")
            self.assertEqual(engine.boards["SN-00214"].rework_count, 0)

            # 4. SN-00308 fails 3 times -> SCRAP, rework_count = 2
            self.assertEqual(engine.boards["SN-00308"].state, "SCRAP")
            self.assertEqual(engine.boards["SN-00308"].rework_count, 2)

            # 5. WO-0004 stays OPEN with 7 boards in-process
            wo4 = engine.yield_reports[3]
            self.assertEqual(wo4.wo_id, "WO-0004")
            self.assertEqual(wo4.in_process, 7)
            self.assertEqual(wo4.status, "OPEN")

            # 6. Pareto tie between D01 and D05 at 10 occurrences each (D01 ranked 1, D05 ranked 2)
            self.assertEqual(engine.pareto_entries[0].defect_code, "D01")
            self.assertEqual(engine.pareto_entries[0].count, 10)
            self.assertEqual(engine.pareto_entries[1].defect_code, "D05")
            self.assertEqual(engine.pareto_entries[1].count, 10)

            # 7. Planted rejected events in errors.csv (EV-01004 duplicate is omitted)
            err_map = {e.event_id: (e.line_no, e.reason) for e in engine.errors}
            self.assertNotIn("EV-01004", err_map)
            self.assertEqual(err_map["EV-00151"], (152, "WO_CLOSED"))
            self.assertEqual(err_map["EV-00367"], (368, "BOARD_SCRAPPED"))
            self.assertEqual(err_map["EV-00455"], (456, "UNKNOWN_SERIAL"))
            self.assertEqual(err_map["EV-01165"], (1166, "SEQUENCE_ERROR"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
