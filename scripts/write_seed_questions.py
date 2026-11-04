"""Seed eval set for the Phase-2 chunking/embedding comparison.
Phase 3 expands this to 40+ questions and moves it to evals/questions.jsonl.
page=None + section != null -> Markdown section ground truth; refuse=true -> unanswerable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUESTIONS = [
    # --- easy (single doc) ---
    {
        "id": "S01",
        "question": "What is the maximum allowable working pressure of the VES-9 vessel at 40 degC?",
        "expected": [{"source": "VES-9_Pressure_Vessel_Manual.pdf", "page": 1}],
    },
    {
        "id": "S02",
        "question": "What torque must M8 fasteners on the PB-220 pump be installed with?",
        "expected": [{"source": "PB-220_Pump_Installation_Guide.pdf", "page": 2}],
    },
    {
        "id": "S03",
        "question": "What supply voltage does the TSX-400 controller require?",
        "expected": [
            {
                "source": "TSX-400_Temperature_Controller_Datasheet.md",
                "page": None,
                "section": "2 Electrical specifications",
            }
        ],
    },
    {
        "id": "S04",
        "question": "What is the EN7000 motor rated power and speed?",
        "expected": [{"source": "EN7000_Motor_Datasheet.pdf", "page": 1}],
    },
    {
        "id": "S05",
        "question": "What is the ampacity of a 10 mm2 copper single core cable in free air?",
        "expected": [
            {"source": "CableCatalog_Ampacity.md", "page": None, "section": "C1 Copper single core"}
        ],
    },
    {
        "id": "S06",
        "question": "Which PB-220 serial numbers are affected by the 2026-02 impeller bulletin?",
        "expected": [
            {
                "source": "PumpSafetyBulletin_2026-02.md",
                "page": None,
                "section": "S1 Affected units",
            }
        ],
    },
    # --- numeric ---
    {
        "id": "S07",
        "question": "What is the voltage drop per ampere per metre for 10 mm2 copper cable?",
        "expected": [
            {"source": "CableCatalog_Ampacity.md", "page": None, "section": "C3 Voltage drop"}
        ],
    },
    {
        "id": "S08",
        "question": "How often must the VES-9 safety valve set pressure be checked?",
        "expected": [{"source": "VES-9_Pressure_Vessel_Manual.pdf", "page": 2}],
    },
    {
        "id": "S09",
        "question": "What accuracy does the TSX-400 achieve after calibration?",
        "expected": [
            {
                "source": "TSX-400_Temperature_Controller_Datasheet.md",
                "page": None,
                "section": "4 Calibration",
            }
        ],
    },
    # --- multi-hop ---
    {
        "id": "S10",
        "question": "The VES-9 operates at 150 degC. What is its derated maximum allowable working pressure?",
        "expected": [{"source": "VES-9_Pressure_Vessel_Manual.pdf", "page": 1}],
    },
    {
        "id": "S11",
        "question": "A PB-220 pump runs fluid at 70 degC. Which vibration alarm limit applies and why?",
        "expected": [
            {"source": "PB-220_Pump_Installation_Guide.pdf", "page": 3},
            {
                "source": "PumpSafetyBulletin_2026-02.md",
                "page": None,
                "section": "S3 Interim operation",
            },
        ],
    },
    {
        "id": "S12",
        "question": "Which EN7000 bearing has the longer relubrication interval, DE or NDE?",
        "expected": [{"source": "EN7000_Motor_Datasheet.pdf", "page": 3}],
    },
    {
        "id": "S13",
        "question": "What torque values does the site commissioning checklist use for M8 and M10 fasteners?",
        "expected": [{"source": "CommissioningChecklist.md", "page": None, "section": "K2 Day 2"}],
    },
    {
        "id": "S14",
        "question": "Which pump vibration limits are reported as dangerous at fluid temperatures above 60 degC according to the vendor quality addendum?",
        "expected": [{"source": "QA-VX-7_Vendor_Addendum.pdf", "page": 2}],
    },
    # --- unanswerable (refuse: not in the documents) ---
    {
        "id": "S15",
        "question": "What is the melting point of the internal rubber gasket of the VES-9 vessel?",
        "refuse": True,
        "expected": [],
    },
    {
        "id": "S16",
        "question": "How much does the EN7000 motor cost in EUR?",
        "refuse": True,
        "expected": [],
    },
    {
        "id": "S17",
        "question": "What is the warranty period of the TSX-400 controller?",
        "refuse": True,
        "expected": [],
    },
]


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "evals" / "seed_questions.jsonl"
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for q in QUESTIONS:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"wrote {len(QUESTIONS)} seed questions -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
