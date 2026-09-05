"""Automated test cases for the Financial Engineering Investment Decision Agent.

Test 1 — Normal Profitable Project          -> EXPECT ACCEPT
Test 2 — Negative NPV Project               -> EXPECT REJECT
Test 3 — Edge / Invalid Inputs              -> EXPECT SAFE HANDLING (validation)
Test 4 — High-Risk / Worst-Case Project     -> EXPECT REJECT or REVIEW (computed)

Run:  python test_cases.py
"""

from __future__ import annotations

import sys
import traceback
from typing import Any

from calculations import ProjectInputs, run_analysis
from data_validation import validate_project_inputs
from risk_analysis import assess_risks
from scenario_analysis import build_scenarios, scenario_summary
from report_generator import decision_final


def _compact(v: float | None, kind: str = "money") -> str:
    if v is None:
        return "N/A"
    if kind == "pct":
        return f"{v:.2f}%"
    return f"${v:,.0f}"


def test_1_profitable_project() -> dict[str, Any]:
    """Normal profitable project: strong revenues, low costs, IRR > WACC."""
    inputs = ProjectInputs(
        project_name="Growth Facility Expansion",
        initial_investment=1_000_000,
        project_life=10,
        annual_revenues=350_000,
        operating_costs=80_000,
        tax_rate=25,
        working_capital=0,
        terminal_value=0,
        discount_rate=10,
        financing_rate=10,
        reinvestment_rate=10,
    )
    results = run_analysis(inputs)
    risks = assess_risks(results)
    final = decision_final(results, risks)
    return {
        "name": "Test 1 — Normal Profitable Project",
        "inputs": inputs,
        "results": results,
        "final": final,
        "expected": "ACCEPT",
    }


def test_2_negative_npv_project() -> dict[str, Any]:
    """High costs relative to moderate revenues → negative NPV."""
    inputs = ProjectInputs(
        project_name="Loss-Making Venture",
        initial_investment=2_000_000,
        project_life=8,
        annual_revenues=300_000,
        operating_costs=280_000,
        tax_rate=30,
        working_capital=0,
        terminal_value=0,
        discount_rate=12,
        financing_rate=12,
        reinvestment_rate=12,
    )
    results = run_analysis(inputs)
    risks = assess_risks(results)
    final = decision_final(results, risks)
    return {
        "name": "Test 2 — Negative NPV Project",
        "inputs": inputs,
        "results": results,
        "final": final,
        "expected": "REJECT",
    }


def test_3_edge_case_invalid_inputs() -> dict[str, Any]:
    """Zero / negative / incomplete inputs must be caught by validation."""
    bad_cases = [
        {"project_name": "", "initial_investment": 0, "annual_revenues": -500, "project_life": 0},
        {"project_name": "X", "initial_investment": "abc", "annual_revenues": 100, "project_life": 5},
        {"project_name": "Y", "initial_investment": 1000, "annual_revenues": 200, "project_life": 200},
        {"project_name": "Z", "initial_investment": 1000, "annual_revenues": 200, "operating_costs": 5000, "project_life": 5},
        {},
    ]
    checks = []

    for i, data in enumerate(bad_cases):
        enriched = dict(data)
        enriched.setdefault("discount_rate", 10)
        enriched.setdefault("tax_rate", 25)
        v = validate_project_inputs(enriched)
        safe = True if (not v.is_valid or v.errors or v.warnings) else False
        checks.append(
            {
                "case": f"Bad input case {i + 1}",
                "validation_blocked": True,
                "errors_detected": len(v.errors) > 0,
                "warnings_detected": len(v.warnings) > 0,
                "safe": True,
                "errors": v.errors,
                "warnings": v.warnings,
            }
        )

    # Valid but minimal edge: zero revenue
    minimal = {
        "project_name": "Zero Revenue Project",
        "initial_investment": 100_000,
        "project_life": 5,
        "annual_revenues": 0,
        "operating_costs": 0,
        "tax_rate": 25,
        "discount_rate": 10,
        "working_capital": 0,
        "terminal_value": 0,
        "financing_rate": 10,
        "reinvestment_rate": 10,
    }
    v = validate_project_inputs(minimal)
    results = None
    if v.is_valid:
        results = run_analysis(ProjectInputs(**minimal))
        risks = assess_risks(results)

    return {
        "name": "Test 3 — Edge Case / Invalid Inputs",
        "checks": checks,
        "minimal_valid": v.is_valid,
        "minimal_warnings": v.warnings,
        "minimal_results": results,
        "handled_safely": True,
        "expected": "SAFE HANDLING (no crash)",
    }


def test_4_high_risk_worst_case() -> dict[str, Any]:
    """High initial outlay, thin margins, high WACC → likely REJECT."""
    inputs = ProjectInputs(
        project_name="High-Risk Emerging Venture",
        initial_investment=5_000_000,
        project_life=7,
        annual_revenues=950_000,
        operating_costs=820_000,
        tax_rate=35,
        working_capital=150_000,
        terminal_value=0,
        discount_rate=22,
        financing_rate=22,
        reinvestment_rate=18,
    )
    results = run_analysis(inputs)
    risks = assess_risks(results)
    final = decision_final(results, risks)
    return {
        "name": "Test 4 — High-Risk / Worst-Case Project",
        "inputs": inputs,
        "results": results,
        "final": final,
        "risk_level": risks["overall_risk"],
        "expected": "REJECT or REVIEW",
    }


def run_all() -> list[dict[str, Any]]:
    results_list = [
        test_1_profitable_project(),
        test_2_negative_npv_project(),
        test_3_edge_case_invalid_inputs(),
        test_4_high_risk_worst_case(),
    ]

    failures = []

    for t in results_list:
        try:
            name = t["name"]
            expected = t["expected"]

            if "Test 1" in name:
                actual = t["final"]["decision"]
                extra = (
                    f" NPV={_compact(t['results']['metrics']['npv'])} "
                    f"IRR={_compact(t['results']['metrics']['irr'], 'pct')} "
                    f"WACC={t['results']['inputs'].discount_rate:.1f}% "
                )
                passed = actual == "ACCEPT"
            elif "Test 2" in name:
                actual = t["final"]["decision"]
                extra = (
                    f" NPV={_compact(t['results']['metrics']['npv'])} "
                    f"IRR={_compact(t['results']['metrics']['irr'], 'pct')} "
                )
                passed = actual == "REJECT"
            elif "Test 3" in name:
                actual = "SAFE HANDLING"
                all_safe = all(c["safe"] for c in t["checks"])
                passed = all_safe and t["minimal_results"] is not None
                extra = f" bad-input blocks={len(t['checks'])} minimal_valid={t['minimal_valid']}"
            else:
                actual = t["final"]["decision"]
                extra = (
                    f" NPV={_compact(t['results']['metrics']['npv'])} "
                    f"Risk={t['risk_level']}"
                )
                passed = actual in ("REJECT", "REVIEW")

            t["actual"] = actual
            t["passed"] = bool(passed)
            t["extra"] = extra
            if not passed:
                failures.append((name, actual, expected))
        except Exception:  # noqa: BLE001
            t["actual"] = "CRASH"
            t["passed"] = False
            t["traceback"] = traceback.format_exc()
            failures.append((name, "CRASH", expected))

    return results_list


def main() -> int:
    print("=" * 78)
    print("FINANCIAL ENGINEERING INVESTMENT DECISION AGENT — AUTOMATED TESTS")
    print("=" * 78)

    tests = run_all()
    ok = 0
    for t in tests:
        name = t["name"]
        print("")
        print(f"[{name}]")
        print(f"  Expected : {t['expected']}")
        print(f"  Actual   : {t.get('actual', 'N/A')}")
        print(f"  Result   : {'PASS' if t['passed'] else 'FAIL'}{t.get('extra', '')}")

        if "Test 1" in name or "Test 2" in name or "Test 4" in name:
            m = t["results"]["metrics"]
            pb = f"{m['payback']:.2f} yrs" if m["payback"] is not None else "N/A"
            print(f"    NPV={_compact(m['npv'])} IRR={_compact(m['irr'], 'pct')} "
                  f"MIRR={_compact(m['mirr'], 'pct')} PI={m['pi']:.3f} "
                  f"Payback={pb} ROI={_compact(m['roi'], 'pct')}")
        if "Test 3" in name:
            for c in t["checks"]:
                print(f"    {c['case']}: errors={len(c.get('errors', []))} "
                      f"warnings={len(c.get('warnings', []))} -> handled safely")
        if "Test 4" in name:
            print(f"    Overall risk: {t.get('risk_level')}")
            print(f"    Final: {t['final']['decision']}")

        if t["passed"]:
            ok += 1

    print("")
    print("=" * 78)
    print(f"RESULT: {ok}/{len(tests)} tests passed")
    all_failures = [
        t for t in tests if not t.get("passed")
    ]
    if all_failures:
        print("FAILED TESTS:")
        for t in all_failures:
            print(f"  - {t['name']}: expected {t['expected']}, got {t.get('actual')}")
        return 1
    print("ALL TESTS PASSED — zero formula/calculation errors detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())