# ECE-049: Manufacturing Yield and Rework Tracker

**10 SECONDS Placement Training (V Semester) — Mandatory Capstone Project**

* **Team ID:** `E027`
* **Problem Statement:** `ECE-049 · Manufacturing Yield and Rework Tracker`
* **Domain:** Electronics Manufacturing — Quality
* **Section:** ECM B, Atria Institute of Technology, Bengaluru
* **Team Members:**
  * **Member 1:** Puneeth Kumar G L (`1AT24UE053` · `puneethdesires@gmail.com`)
  * **Member 2:** Purvitha B V (`1AT24UE054` · `battipurvitha31@gmail.com`)
* **Language & Runtime:** Python 3.10+ (Standard Library + `unittest` / `pytest`)
* **Repository:** [https://github.com/puneethgl2006-dev/E027-ECE-049](https://github.com/puneethgl2006-dev/E027-ECE-049)

* **5-Minute Demo Video:** https://drive.google.com/file/d/1SksVPOPLp7Cl73rKvCenHBiz0SdvXhLe/view?usp=sharing

## 1. Project Overview

`tracker.py` is a deterministic, command-file-driven back-end rules engine for a Printed Circuit Board Assembly (PCBA) factory. It tracks every registered circuit board serial through three sequential inspection stages—**AOI** (Automated Optical Inspection), **ICT** (In-Circuit Test), and **FCT** (Functional Test)—routes non-fatal defects (`D01`–`D10`) to rework with a strict 2-retry limit across all stages, immediately scraps boards encountering fatal `X`-code defects (`X01`–`X03`) or a 3rd non-fatal failure, and generates exact field-for-field CSV reports for board state transitions, per-work-order yield and scrap/rework costs, defect Pareto rankings, and rejected events.

## 2. Repository Structure

| File | Description |
| :--- | :--- |
| `tracker.py` | Main CLI rules engine implementing Business Rules `BR-01` through `BR-08` |
| `test_tracker.py` | Automated unit and integration test suite covering every `BR-ID` and all 11 planted scenarios |
| `design_document.pdf` | Formal Design Document containing Glossary, Class Diagram, State Machine Diagram, and `BR-01`–`BR-08` Register |
| `decision_log.md` | 15 one-line architectural and rule-interpretation decisions (`DL-01` to `DL-15`) |
| `commands.txt` | Pipe-delimited (`\|`) command script controlling master loading, event processing, and report generation |
| `work_orders.csv` | Input work order master (`WO-0001` to `WO-0004`, 450 total boards `SN-00001`–`SN-00450`) |
| `stages.csv` | Input test stage sequence master (`1: AOI`, `2: ICT`, `3: FCT`) |
| `defect_codes.csv` | Input defect master (`D01`–`D10` non-fatal defects, `X01`–`X03` fatal defects) |
| `test_events.csv` | Input chronological test event stream (1,386 events) |
| `board_log.csv` | Generated output log of all 1,381 accepted events in processing order |
| `yield_report.csv` | Generated per-work-order yield, status, scrap cost, and rework cost summary |
| `defect_pareto.csv` | Generated defect frequency Pareto table sorted by count descending, then defect code ascending |
| `errors.csv` | Generated log of rejected events (`WO_CLOSED`, `BOARD_SCRAPPED`, `UNKNOWN_SERIAL`, `SEQUENCE_ERROR`) |

## 3. How to Run the Engine

Requires **Python 3.10+** with zero external runtime dependencies.

Run the engine against `commands.txt` in the current directory:

```bash
python tracker.py commands.txt
```

Or specify an explicit command file path and custom output directory:

```bash
python tracker.py path/to/commands.txt path/to/output_dir
```

Upon execution, the engine reads `commands.txt` top-to-bottom and writes four CSV files (`board_log.csv`, `yield_report.csv`, `defect_pareto.csv`, and `errors.csv`) into the target directory.

## 4. How to Run the Test Suite (Single Command)

The test suite (`test_tracker.py`) is compatible with both **`pytest`** and Python's built-in **`unittest`** runner so it executes with a single command in any environment:

```bash
pytest test_tracker.py -v
```

Or using standard library `unittest` (no third-party packages required):

```bash
python -m unittest test_tracker.py -v
```

## 5. Business Rules Implemented (`BR-01` to `BR-08`)

| Rule ID | Rule Name | Implementation Summary |
| :--- | :--- | :--- |
| `BR-01` | Strict Stage Order | Enforces progression `AOI -> ICT -> FCT`; rejects stage-jumping or wrong retest stages with `SEQUENCE_ERROR`. |
| `BR-02` | Rework Loop & Retry Cap | Routes non-fatal `FAIL` to `REWORK` (`rework_count += 1`, re-entering the same stage); scraps board on the 3rd non-fatal failure (`rework_count` capped at 2). |
| `BR-03` | Fatal `X`-Code Defects | Immediately transitions board to `SCRAP` on any `X`-prefixed defect (`X01`, `X02`, `X03`) without incrementing `rework_count`. |
| `BR-04` | First-Pass Yield (FPY) | Computes `first_pass_yield_pct = (first_pass_boards / boards_started) * 100` to 1 decimal place (`ROUND_HALF_UP`). |
| `BR-05` | Final Yield & Scrap % | Computes `final_yield_pct = (shipped / boards_started) * 100` to 1 decimal place and `scrap_pct = 100.0 - final_yield_pct`. |
| `BR-06` | Scrap & Rework Costing | Computes `scrap_cost = material_cost_rs + (150.00 * rework_count)` for scrapped boards and `rework_cost = 150.00 * rework_count` for non-scrapped boards. |
| `BR-07` | Work-Order Closure & Guards | Marks work order `CLOSED` when all serials reach `SHIPPED` or `SCRAP`; rejects events with `WO_CLOSED`, `BOARD_SCRAPPED`, or `UNKNOWN_SERIAL`. |
| `BR-08` | Duplicate Filter & Pareto | Silently ignores duplicate `(serial_no, stage, timestamp)` events; orders Pareto ties by `defect_code` ascending (`D01` before `D05`). |

## 6. Verified Sample Data Output Summary (`yield_report.csv`)

| `wo_id` | `boards_started` | `first_pass_boards` | `first_pass_yield_pct` | `shipped` | `scrapped` | `in_process` | `final_yield_pct` | `scrap_pct` | `scrap_cost` | `rework_cost` | `status` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `WO-0001` | 50 | 50 | `100.0` | 50 | 0 | 0 | `100.0` | `0.0` | `0.00` | `0.00` | `CLOSED` |
| `WO-0002` | 80 | 68 | `85.0` | 76 | 4 | 0 | `95.0` | `5.0` | `5920.00` | `1500.00` | `CLOSED` |
| `WO-0003` | 120 | 105 | `87.5` | 117 | 3 | 0 | `97.5` | `2.5` | `1305.00` | `2250.00` | `CLOSED` |
| `WO-0004` | 200 | 167 | `83.5` | 185 | 8 | 7 | `92.5` | `7.5` | `14860.00` | `3150.00` | `OPEN` |
