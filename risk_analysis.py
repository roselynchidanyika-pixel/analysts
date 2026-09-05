"""Risk analysis engine for the Financial Engineering Investment Decision Agent.

Every risk assessment derives entirely from user-provided inputs and calculated
financial indicators. No external market or entity data is fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskAssessment:
    risk: str
    severity: str
    impact: str
    explanation: str
    mitigation: str
    score: float
    driver: str


SEVERITY_LEVELS = {
    "LOW": 1,
    "MODERATE": 2,
    "HIGH": 3,
    "VERY HIGH": 4,
}


def assess_risks(results: dict[str, Any]) -> dict[str, Any]:
    """Analyse financial risks based purely on model results and inputs."""
    metrics = results["metrics"]
    inputs = results["inputs"]
    table = results["cash_flow_table"]

    risks: list[RiskAssessment] = []
    warnings = []
    total_score = 0.0
    max_score = 0.0

    npv = metrics["npv"]
    irr = metrics["irr"]
    discount = inputs.discount_rate
    revenues = inputs.annual_revenues
    costs = inputs.operating_costs
    life = metrics["project_life"]
    payback = metrics["payback"]
    pi = metrics["pi"]
    roi = metrics["roi"]

    # 1. Revenue risk
    if revenues <= 0:
        severity, impact = "VERY HIGH", "Extreme"
        explanation = (
            "Annual revenues are zero or negative. The project has no identified income stream, "
            "so all expected value depends entirely on unmodelled upside, making the investment "
            "fundamentally unsupported."
        )
        mitigation = "Identify and quantify a realistic revenue base before committing capital."
    elif revenues > 0 and costs / revenues >= 0.9:
        severity, impact = "HIGH", "Significant"
        explanation = (
            f"Operating costs consume {costs/revenues*100:.0f}% of revenues, leaving a very thin "
            "margin. Small downward moves in revenue or upward moves in costs could erase the "
            "project's profitability."
        )
        mitigation = "Negotiate cost structures, add price escalation clauses, and stress-test margins."
    elif revenues > 0 and costs / revenues >= 0.7:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"Operating costs consume roughly {costs/revenues*100:.0f}% of revenues. The project "
            "retains a workable margin but is sensitive to revenue slippage."
        )
        mitigation = "Diversify revenue sources and build margin buffers into budgets."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            f"Operating costs consume {costs/revenues*100:.0f}% of revenues. Healthy gross margins "
            "provide a buffer against moderate revenue deviations."
        )
        mitigation = "Maintain routine market monitoring to sustain the favourable margin position."

    risks.append(
        RiskAssessment(
            risk="Revenue Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="User-provided revenue and cost inputs",
        )
    )

    # 2. Operating-cost risk
    if costs <= 0:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            "Operating costs are zero or not provided, which understates the cost burden and risks "
            "over-stating project returns."
        )
        mitigation = "Provide complete, audited operating cost estimates."
    elif costs / revenues >= 0.9 and revenues > 0:
        severity, impact = "HIGH", "Significant"
        explanation = (
            "Costs are near or above revenue. Any cost inflation above assumptions directly "
            "threatens cash-flow generation."
        )
        mitigation = "Secure fixed-price supply contracts and implement cost-containment controls."
    else:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            "Operating costs are significant relative to project scale. Cost escalation beyond the "
            "growth assumptions will compress margins and reduce cash flows."
        )
        mitigation = "Benchmark cost assumptions, hedge input-price exposure where possible."

    risks.append(
        RiskAssessment(
            risk="Operating-Cost Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="User-provided operating cost inputs",
        )
    )

    # 3. WACC / interest-rate risk
    if irr is not None and discount > 0:
        spread = irr - discount
        if spread < 0:
            severity, impact = "HIGH", "Significant"
            explanation = (
                f"The project IRR ({irr:.2f}%) is below the discount rate ({discount:.2f}%). "
                "The project already fails to earn its cost of capital, and any rise in "
                "interest rates or required return worsens value destruction."
            )
            mitigation = "Reconsider the financing structure or demand a lower hurdle rate; refinance debt."
        elif spread < 2:
            severity, impact = "MODERATE", "Moderate"
            explanation = (
                f"The project IRR ({irr:.2f}%) barely exceeds the discount rate ({discount:.2f}%). "
                "The margin over the cost of capital is thin, leaving limited protection against "
                "rising interest rates."
            )
            mitigation = "Lock in fixed-rate financing and re-test the decision under higher WACC."
        else:
            severity, impact = "LOW", "Limited"
            explanation = (
                f"The project IRR ({irr:.2f}%) provides a cushion of {spread:.2f} percentage points "
                "over the discount rate ({discount:.2f}%). The project can absorb meaningful rises "
                "in the cost of capital."
            )
            mitigation = "Continue to monitor the rate environment but risk is contained."

    risks.append(
        RiskAssessment(
            risk="WACC / Interest-Rate Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Calculated IRR vs user-specified discount rate",
        )
    )

    # 4. NPV breakeven / value-creation risk
    if npv < 0:
        severity, impact = "VERY HIGH", "Extreme"
        explanation = (
            f"NPV of ${npv:,.0f} is negative. The project is expected to destroy value and every "
            "additional percentage point of uncertainty compounds the expected loss."
        )
        mitigation = "Do not proceed unless structure, costs or revenues change materially."
    elif npv > 0 and npv / max(inputs.initial_investment, 1) < 0.10:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"NPV of ${npv:,.0f} is only {npv/max(inputs.initial_investment, 1)*100:.1f}% of the "
            "initial investment. Value creation is marginal and could be erased by small "
            "assumption shifts."
        )
        mitigation = "Search for upside catalysts or cost savings to widen the value margin."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            f"NPV of ${npv:,.0f} exceeds 10% of the initial investment, providing a robust buffer "
            "against reasonably foreseeable deviations from the base case."
        )
        mitigation = "Standard monitoring and variance reporting."

    risks.append(
        RiskAssessment(
            risk="Value-Creation (Breakeven) Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Calculated NPV relative to initial investment",
        )
    )

    # 5. Investment recovery / payback risk
    if payback is None or payback > life:
        severity, impact = "HIGH", "Significant"
        explanation = (
            f"Payback ({payback if payback else 'N/A'}) exceeds the project life of {life} years. "
            "Capital is tied up for the project's entire operating window without full recovery, "
            "heightening liquidity and opportunity-cost exposure."
        )
        mitigation = "Shorten the recovery profile with earlier cash inflows or exit clauses."
    elif payback > life * 0.75:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"Payback of {payback:.1f} years consumes over 75% of the {life}-year project life, "
            "meaning most of the value is earned late and is more exposed to forecast error."
        )
        mitigation = "Consider accelerating cash collection or staging investment tranches."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            f"Payback of {payback:.1f} years is well within the {life}-year project life, "
            "providing early capital recovery and reducing liquidity exposure."
        )
        mitigation = "Maintain current cash-collection discipline."

    risks.append(
        RiskAssessment(
            risk="Investment-Recovery (Payback) Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Calculated payback vs project life",
        )
    )

    # 6. Cash-flow timing risk
    first_year = table.iloc[0]["Net Cash Flow"] if len(table) > 0 else 0
    if len(table) > 0 and first_year <= 0:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            "The project generates little or no cash flow in the first year. Early-year reliance "
            "on the base case means small timing slippages delay recovery and reduce NPV."
        )
        mitigation = "Stage the project, phase capital outlays, and negotiate flexible vendor terms."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            "The project begins generating net cash flow immediately, reducing cash-flow timing "
            "risk relative to the base case."
        )
        mitigation = "Sustain early-phase execution discipline."

    risks.append(
        RiskAssessment(
            risk="Cash-Flow Timing Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Shape of the calculated net cash-flow stream",
        )
    )

    # 7. Inflation risk
    if inputs.revenue_growth_rate > 0 or inputs.cost_growth_rate > 0:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"The model applies growth rates to revenue ({inputs.revenue_growth_rate:.1f}%/yr) and "
            f"costs ({inputs.cost_growth_rate:.1f}%/yr). The real (inflation-adjusted) cash-flow "
            "outcome depends on whether prices and costs move as assumed; divergences directly "
            "shift NPV."
        )
        mitigation = "Build inflation-indexed contracts and re-run the model under inflation-adjusted scenarios."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            "No explicit growth assumptions were entered. Cash flows are modelled in nominal "
            "terms with no inflation adjustment, so inflation risk is largely unmeasured and "
            "potentially understated."
        )
        mitigation = "Add explicit revenue and cost growth assumptions to model inflation explicitly."

    risks.append(
        RiskAssessment(
            risk="Inflation Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="User-specified growth assumptions and currency assumptions",
        )
    )

    # 8. Liquidity risk
    if pi is not None and pi < 1:
        severity, impact = "HIGH", "Significant"
        explanation = (
            f"Profitability index of {pi:.3f} is below 1.0. The present value of inflows does not "
            "cover the outlay, meaning capital committed is not expected to be fully returned in "
            "present-value terms, restricting liquidity recovery."
        )
        mitigation = "Require higher return thresholds or shorter exposure horizons."
    elif payback is not None:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"Capital is recovered over {payback:.1f} years based on the payback profile, tying up "
            "liquidity until recovery completes. Liquidity stays restricted during this window."
        )
        mitigation = "Monitor debt-covenant headroom and maintain contingency credit lines."
    else:
        severity, impact = "MODERATE", "Moderate"
        explanation = "Capital recovery is indeterminate; liquidity is treated as continuously at risk."
        mitigation = "Set explicit recovery milestones before commitment."

    risks.append(
        RiskAssessment(
            risk="Liquidity Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Calculated PI and payback profile",
        )
    )

    # 9. Profitability-sustainability risk
    if roi is not None and roi < 0:
        severity, impact = "HIGH", "Significant"
        explanation = (
            f"ROI of {roi:.1f}% is negative: total returns never exceed the committed capital over "
            f"the {life}-year horizon, so the project structurally loses money."
        )
        mitigation = "Re-scope or abandon the project; adjust pricing, volumes or costs materially."
    elif roi is not None and roi < 20:
        severity, impact = "MODERATE", "Moderate"
        explanation = (
            f"ROI of {roi:.1f}% is modest. The project creates some total return but limited "
            "headroom against downside deviations."
        )
        mitigation = "Pursue efficiency gains and revenue synergies to lift returns."
    else:
        severity, impact = "LOW", "Limited"
        explanation = (
            f"ROI of {roi:.1f}% provides a strong total return relative to the initial investment."
        )
        mitigation = "Retain the current approach while tracking actual vs budgeted performance."

    risks.append(
        RiskAssessment(
            risk="Profitability-Sustainability Risk",
            severity=severity,
            impact=impact,
            explanation=explanation,
            mitigation=mitigation,
            score=SEVERITY_LEVELS[severity],
            driver="Calculated ROI",
        )
    )

    # Composite risk levels per supplied inputs
    total_score = sum(r.score for r in risks)
    max_score = sum(max(SEVERITY_LEVELS.values()) for _ in risks)

    weighted = total_score / (max_score or 1)
    if weighted >= 0.75:
        overall = "VERY HIGH"
    elif weighted >= 0.55:
        overall = "HIGH"
    elif weighted >= 0.35:
        overall = "MODERATE"
    else:
        overall = "LOW"

    if weighted >= 0.75:
        overall_explanation = (
            "The composite risk assessment is very high. Multiple indicators point to expected "
            "value destruction or fragile returns; the project should not proceed without "
            "fundamental restructuring of assumptions."
        )
    elif weighted >= 0.55:
        overall_explanation = (
            "The composite risk assessment is high. Several metrics operate near unfavourable "
            "thresholds and the project is vulnerable to realistic assumption changes. "
            "Obtain additional assurance before approving capital."
        )
    elif weighted >= 0.35:
        overall_explanation = (
            "The composite risk assessment is moderate. The project shows acceptable but not "
            "overwhelming financial merit, with standard operational risks best managed through "
            "monitoring and contingency planning."
        )
    else:
        overall_explanation = (
            "The composite risk assessment is low. Most indicators sit comfortably in favourable "
            "territory and the project can absorb a reasonable level of deviation from the "
            "base case."
        )

    return {
        "risks": risks,
        "overall_risk": overall,
        "overall_risk_level": SEVERITY_LEVELS[overall],
        "overall_score": weighted,
        "overall_explanation": overall_explanation,
        "warnings": warnings,
    }