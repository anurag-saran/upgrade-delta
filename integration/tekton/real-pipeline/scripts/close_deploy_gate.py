#!/usr/bin/env python3
"""Close (or fail) downstream obligations in deploy-gate.json after CD steps.

Usage:
  close_deploy_gate.py --status CLOSED|FAILED --obligation-id canary [--note TEXT]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gate", type=Path, default=Path("out/routing-out/deploy-gate.json"))
    p.add_argument("--status", choices=("CLOSED", "FAILED", "OPEN"), required=True)
    p.add_argument("--obligation-id", default="canary")
    p.add_argument("--note", default="")
    p.add_argument(
        "--signoff",
        type=Path,
        default=Path("out/cab-signoff.json"),
        help="Optional CAB signoff to attach",
    )
    args = p.parse_args()

    if args.gate.is_file():
        gate = json.loads(args.gate.read_text(encoding="utf-8"))
    else:
        gate = {
            "schema": "upgrade-delta/deploy-gate/v1",
            "app": "",
            "date": str(date.today()),
            "project_grade": None,
            "obligations_downstream": [],
            "note": "Gate file created by close_deploy_gate.py (was missing).",
        }

    found = False
    for ob in gate.setdefault("obligations_downstream", []):
        if ob.get("id") == args.obligation_id:
            ob["status"] = args.status
            if args.note:
                ob["note"] = args.note
            found = True
            break
    if not found:
        gate["obligations_downstream"].append(
            {
                "id": args.obligation_id,
                "status": args.status,
                "note": args.note or f"Marked {args.status} by CD stage",
            }
        )

    if args.signoff.is_file():
        gate["cab_signoff"] = json.loads(args.signoff.read_text(encoding="utf-8"))

    args.gate.parent.mkdir(parents=True, exist_ok=True)
    args.gate.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    print(f"updated {args.gate}: {args.obligation_id} → {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
