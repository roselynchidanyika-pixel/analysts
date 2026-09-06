"""Management report generation — PDF (reportlab) and Word (python-docx)."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}" if v >= 0 else f"(${abs(v):,.0f})"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2f}%"


def _safe_stat(metrics: dict, key: str, default="N/A") -> str:
    v = metrics.get(key)
    if v is None:
        return default
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


# ---------------------------------------------------------------------------
# Word report
# ---------------------------------------------------------------------------

def build_word_report(results: dict[str, Any], scenarios: dict[str, Any], sensitivity: dict[str, Any], risk_results: dict[str, Any]) -> bytes:
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)

    inputs: Any = results["inputs"]
    metrics = results["metrics"]
    decisions = results["decisions"]
    cash_table = results["cash_flow_table"]

    title = doc.add_heading("Financial Engineering Investment Decision Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Project: {inputs.project_name}")
    doc.add_paragraph(f"Report generated: {datetime.now().strftime('%d %b %Y, %H:%M')}")

    # 1. Executive Summary
    doc.add_heading("1. Executive Summary", level=1)
    final_dec = decision_final(results, risk_results)["decision"]
    p = doc.add_paragraph()
    run = p.add_run(f"FINAL DECISION: {final_dec}")
    run.bold = True
    doc.add_paragraph(
        f"Initial Investment: {_fmt_money(metrics['initial_investment'])} | "
        f"NPV: {_fmt_money(metrics['npv'])} | IRR: {_fmt_pct(metrics['irr'])} | "
        f"MIRR: {_fmt_pct(metrics['mirr'])} | ROI: {_fmt_pct(metrics['roi'])} | "
        f"Payback: {_safe_stat(metrics, 'payback')} years | "
        f"Risk level: {risk_results['overall_risk']}"
    )
    doc.add_paragraph(decision_final(results, risk_results)["reason"])

    # 2. Investment Proposal
    doc.add_heading("2. Investment Proposal", level=1)
    doc.add_paragraph(f"Name: {inputs.project_name}")
    doc.add_paragraph(f"Description: {inputs.project_description or 'Not provided.'}")

    # 3. Input Assumptions
    doc.add_heading("3. Input Assumptions", level=1)
    assumptions_table = doc.add_table(rows=1, cols=2)
    assumptions_table.style = "Table Grid"
    hdr = assumptions_table.rows[0].cells
    hdr[0].text = "Assumption"
    hdr[1].text = "Value"
    for k, v in [
        ("Project life (years)", inputs.project_life),
        ("Initial investment", _fmt_money(inputs.initial_investment)),
        ("Annual revenues", _fmt_money(inputs.annual_revenues)),
        ("Operating costs", _fmt_money(inputs.operating_costs)),
        ("Tax rate", _fmt_pct(inputs.tax_rate)),
        ("WACC / Discount rate", _fmt_pct(inputs.discount_rate)),
        ("Financing rate", _fmt_pct(inputs.financing_rate)),
        ("Reinvestment rate", _fmt_pct(inputs.reinvestment_rate)),
        ("Working capital", _fmt_money(inputs.working_capital)),
        ("Terminal value", _fmt_money(inputs.terminal_value)),
    ]:
        cells = assumptions_table.add_row().cells
        cells[0].text = str(k)
        cells[1].text = str(v)

    # 4. Data Sources
    doc.add_heading("4. Data Sources", level=1)
    doc.add_paragraph("User-provided data: all assumptions listed above.")
    doc.add_paragraph("Uploaded data: if a CSV/Excel file was supplied, its values populate the assumptions.")
    doc.add_paragraph(
        "External data: none imported automatically. Any market rates (WACC, inflation, exchange rates) "
        "are user-specified assumptions and should be validated by the user against external sources."
    )
    doc.add_paragraph(
        "Model assumptions: standard corporate-finance conventions described in the Methodology section."
    )

    # 5. Methodology
    doc.add_heading("5. Methodology", level=1)
    doc.add_paragraph(
        "Cash flows are computed using the operating cash-flow formulation: EBITDA minus tax, plus the "
        "tax shield on depreciation. Net cash flows equal after-tax operating cash flow, less incremental "
        "net working capital, plus terminal value in the final year. All future cash flows are discounted "
        "to present value at the WACC. NPV is the present value of inflows minus the initial investment. "
        "IRR is the discount rate at which NPV equals zero. MIRR reinvests positive cash flows at the "
        "reinvestment rate and discounts outflows at the financing rate. Payback is the time to cumulative "
        "cash-flow breakeven. The profitability index equals PV of inflows divided by the initial investment."
    )

    # 6. Capital Budgeting Analysis
    doc.add_heading("6. Capital Budgeting Analysis", level=1)
    _write_table(doc, results["cash_flow_table"].head(20))
    doc.add_paragraph(
        f"Net present value: {_fmt_money(metrics['npv'])}. "
        f"{decisions['npv']['reason']}"
    )

    # 7. DCF Valuation
    doc.add_heading("7. DCF Valuation", level=1)
    doc.add_paragraph(_write_dcf_table_text(results))
    doc.add_paragraph(
        f"Total project value (present value of operating cash flows): "
        f"{_fmt_money(metrics['total_project_value'])}. "
        f"Present value of terminal value: {_fmt_money(metrics['pv_terminal'])}."
    )

    # 8-13 metric sections
    _write_metric_sections(doc, results)

    # 14. Risk Analysis
    doc.add_heading("14. Risk Analysis", level=1)
    for r in risk_results["risks"]:
        doc.add_paragraph(f"{r.risk}: {r.severity}", style="List Bullet")
        doc.add_paragraph(f"    Impact: {r.impact}. {r.explanation}")
        doc.add_paragraph(f"    Mitigation: {r.mitigation}")
    doc.add_paragraph(f"Overall risk level: {risk_results['overall_risk']}. {risk_results['overall_explanation']}")

    # 15. Scenarios
    doc.add_heading("15. Best / Base / Worst Scenarios", level=1)
    for key in ["best", "base", "worst"]:
        s = scenarios[key]
        sm = s["summary"]
        doc.add_paragraph(
            f"{s['label']}: NPV {_fmt_money(sm['npv'])}, IRR {_fmt_pct(sm['irr'])}, "
            f"MIRR {_fmt_pct(sm['mirr'])}, ROI {_fmt_pct(sm['roi'])}, "
            f"Payback {_safe_stat(sm, 'payback') if sm.get('payback') else 'N/A'} years, "
            f"PI {sm.get('pi', 'N/A')} — {sm['decision']}."
        )
        doc.add_paragraph(sm["explanation"])

    # 16. Sensitivity Analysis
    doc.add_heading("16. Sensitivity Analysis", level=1)
    doc.add_paragraph(
        f"Most sensitive variable: {sensitivity['most_sensitive']}; "
        f"least sensitive variable: {sensitivity['least_sensitive']}."
    )
    st = sensitivity.get("sensitivities", [])
    for item in st:
        doc.add_paragraph(
            f"{item['variable']}: NPV ranges from {_fmt_money(item['npv_low'])} to "
            f"{_fmt_money(item['npv_high'])} around the base {_fmt_money(item['npv_base'])}."
        )
        doc.add_paragraph(f"    {item['explanation']}")

    # 17. Final Investment Decision
    final = decision_final(results, risk_results)
    doc.add_heading("17. Final Investment Decision", level=1)
    p = doc.add_paragraph()
    run = p.add_run(final["decision"])
    run.bold = True
    doc.add_paragraph(final["reason"])

    # 18. Reasons Supporting the Decision
    doc.add_heading("18. Reasons Supporting the Decision", level=1)
    for metric in ["npv", "irr", "mirr", "pi", "roi", "payback"]:
        d = decisions[metric]
        val = _metric_display(metric, metrics)
        doc.add_paragraph(f"{metric.upper()} = {val} — {d['status']}. {d['reason']}", style="List Bullet")

    # 19. Recommendations
    doc.add_heading("19. Recommendations", level=1)
    doc.add_paragraph(final["recommendation"])

    # 20. Limitations
    doc.add_heading("20. Limitations", level=1)
    doc.add_paragraph(
        "This report is a model-based decision aid, not investment advice. Results depend entirely "
        "on the accuracy of the input assumptions. Forecasts are subject to uncertainty in revenues, "
        "costs, discount rates, inflation, and market conditions. No external market or company-specific "
        "data is included beyond user-provided inputs. Terminal value and growth assumptions materially "
        "affect results. Sensitivity and scenario analysis quantify but cannot eliminate this uncertainty."
    )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _write_metric_sections(doc: Document, results: dict[str, Any]):
    metrics = results["metrics"]
    decisions = results["decisions"]
    inputs: Any = results["inputs"]

    doc.add_heading("8. NPV Analysis", level=1)
    doc.add_paragraph(f"NPV = {_fmt_money(metrics['npv'])} — {decisions['npv']['status']}. {decisions['npv']['reason']}")

    doc.add_heading("9. IRR Analysis", level=1)
    doc.add_paragraph(f"IRR = {_fmt_pct(metrics['irr'])} vs WACC = {_fmt_pct(inputs.discount_rate)} — {decisions['irr']['status']}. {decisions['irr']['reason']}")

    doc.add_heading("10. MIRR Analysis", level=1)
    doc.add_paragraph(f"MIRR = {_fmt_pct(metrics['mirr'])} vs required return = {_fmt_pct(inputs.discount_rate)} — {decisions['mirr']['status']}. {decisions['mirr']['reason']}")

    doc.add_heading("11. ROI Analysis", level=1)
    doc.add_paragraph(
        f"ROI = {_fmt_pct(metrics['roi'])}. Holding-period return = {_fmt_pct(metrics['holding_period_return'])}; "
        f"annualized return = {_fmt_pct(metrics['annualized_return'])}. {decisions['roi']['reason']}"
    )

    doc.add_heading("12. Payback Analysis", level=1)
    doc.add_paragraph(
        f"Payback = {_safe_stat(metrics, 'payback')} years vs project life {metrics['project_life']} years — "
        f"{decisions['payback']['status']}. {decisions['payback']['reason']}"
    )

    doc.add_heading("13. Profitability Index", level=1)
    doc.add_paragraph(f"PI = {_safe_stat(metrics, 'pi')} — {decisions['pi']['status']}. {decisions['pi']['reason']}")


def _metric_display(metric: str, metrics: dict) -> str:
    if metric == "npv":
        return _fmt_money(metrics["npv"])
    if metric == "pi":
        return f"{metrics['pi']:.3f}" if metrics.get("pi") is not None else "N/A"
    if metric == "payback":
        return f"{metrics['payback']:.2f} years" if metrics.get("payback") is not None else "N/A"
    return _fmt_pct(metrics[metric])


# ---------------------------------------------------------------------------
# PDF report (landscape tables-friendly)
# ---------------------------------------------------------------------------

def build_pdf_report(results: dict[str, Any], scenarios: dict[str, Any], sensitivity: dict[str, Any], risk_results: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="FTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=16,
            fontName="Helvetica-Bold",
        )
    )
    styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12, spaceAfter=6))
    body = styles["BodyText"]
    body.fontName = "Helvetica"
    body.fontSize = 9

    inputs: Any = results["inputs"]
    metrics = results["metrics"]
    decisions = results["decisions"]

    flow = []
    flow.append(Paragraph("Financial Engineering Investment Decision Report", styles["FTitle"]))
    flow.append(Spacer(1, 8))
    flow.append(Paragraph(f"<b>Project:</b> {inputs.project_name}", body))
    flow.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%d %b %Y, %H:%M')}", body))
    flow.append(Spacer(1, 10))

    # 1 Executive Summary
    final = decision_final(results, risk_results)
    flow.append(Paragraph("1. Executive Summary", styles["H2"]))
    flow.append(Paragraph(f"<b>FINAL DECISION: {final['decision']}</b>", body))
    flow.append(
        Paragraph(
            f"Investment: {_fmt_money(metrics['initial_investment'])} | NPV: {_fmt_money(metrics['npv'])} | "
            f"IRR: {_fmt_pct(metrics['irr'])} | MIRR: {_fmt_pct(metrics['mirr'])} | ROI: {_fmt_pct(metrics['roi'])} | "
            f"Payback: {_safe_stat(metrics, 'payback')} yr | Risk: {risk_results['overall_risk']}",
            body,
        )
    )
    flow.append(Paragraph(final["reason"], body))

    # 2 Investment Proposal
    flow.append(Paragraph("2. Investment Proposal", styles["H2"]))
    flow.append(Paragraph(f"Name: {inputs.project_name}", body))
    flow.append(Paragraph(f"Description: {inputs.project_description or 'Not provided.'}", body))

    # 3 Input Assumptions
    flow.append(Paragraph("3. Input Assumptions", styles["H2"]))
    assumptions = [
        ["Assumption", "Value"],
        ["Project life (years)", str(inputs.project_life)],
        ["Initial investment", _fmt_money(inputs.initial_investment)],
        ["Annual revenues", _fmt_money(inputs.annual_revenues)],
        ["Operating costs", _fmt_money(inputs.operating_costs)],
        ["Tax rate", _fmt_pct(inputs.tax_rate)],
        ["WACC / Discount rate", _fmt_pct(inputs.discount_rate)],
        ["Financing rate", _fmt_pct(inputs.financing_rate)],
        ["Reinvestment rate", _fmt_pct(inputs.reinvestment_rate)],
        ["Working capital", _fmt_money(inputs.working_capital)],
        ["Terminal value", _fmt_money(inputs.terminal_value)],
    ]
    t = Table(assumptions, colWidths=[3 * inch, 3 * inch])
    t.setStyle(_table_style())
    flow.append(t)

    # 4 Data Sources
    flow.append(Paragraph("4. Data Sources", styles["H2"]))
    flow.append(Paragraph("User-provided data: all assumptions above. Uploaded data: from CSV/Excel file when used. External data: none imported; market rates are user assumptions. Model assumptions: corporate-finance conventions below.", body))

    # 5 Methodology
    flow.append(Paragraph("5. Methodology", styles["H2"]))
    flow.append(
        Paragraph(
            "OCF = EBITDA - Tax + Depreciation tax shield. Net cash flow = OCF - ΔNWC (+ terminal value in the final year). "
            "Each cash flow is discounted at the WACC: DF_t = 1/(1+WACC)^t. NPV = Σ PV(inflows) - Initial investment. "
            "IRR solves NPV=0. MIRR reinvests inflows at the reinvestment rate and discounts outflows at the financing rate. "
            "Payback = time to cumulative-total-cash-flow breakeven. PI = PV(inflows) / Investment. ROI = (Total inflows - Investment)/Investment.",
            body,
        )
    )

    # 6 Capital Budgeting
    flow.append(Paragraph("6. Capital Budgeting Analysis", styles["H2"]))
    _pdf_table(flow, results["cash_flow_table"].head(15), body)
    flow.append(Paragraph(f"NPV = {_fmt_money(metrics['npv'])}. {decisions['npv']['reason']}", body))
    flow.append(Paragraph(f"Cumulative cash flow final: {_fmt_money(results['cash_flow_table']['Cumulative Cash Flow'].iloc[-1])}.", body))

    # 7 DCF Valuation
    flow.append(Paragraph("7. DCF Valuation", styles["H2"]))
    flow.append(
        Paragraph(
            f"Total project value (PV of operating cash flows) = {_fmt_money(metrics['total_project_value'])}. "
            f"PV of terminal value = {_fmt_money(metrics['pv_terminal'])}. "
            "Interpretation: this is the estimated present value of the project's future cash flows at the WACC.",
            body,
        )
    )
    _pdf_table(flow, results["dcf_table"], body)

    # 8-13
    flow.append(Paragraph("8. NPV Analysis", styles["H2"]))
    flow.append(Paragraph(f"NPV = {_fmt_money(metrics['npv'])} — {decisions['npv']['status']}. {decisions['npv']['reason']}", body))
    flow.append(Paragraph("9. IRR Analysis", styles["H2"]))
    flow.append(Paragraph(f"IRR = {_fmt_pct(metrics['irr'])} vs WACC = {_fmt_pct(inputs.discount_rate)} — {decisions['irr']['status']}. {decisions['irr']['reason']}", body))
    flow.append(Paragraph("10. MIRR Analysis", styles["H2"]))
    flow.append(Paragraph(f"MIRR = {_fmt_pct(metrics['mirr'])} vs required return {_fmt_pct(inputs.discount_rate)} — {decisions['mirr']['status']}. {decisions['mirr']['reason']}", body))
    flow.append(Paragraph("11. ROI Analysis", styles["H2"]))
    flow.append(Paragraph(f"ROI = {_fmt_pct(metrics['roi'])}; Holding-period return {_fmt_pct(metrics['holding_period_return'])}; Annualized {_fmt_pct(metrics['annualized_return'])}. {decisions['roi']['reason']}", body))
    flow.append(Paragraph("12. Payback Analysis", styles["H2"]))
    flow.append(Paragraph(f"Payback = {_safe_stat(metrics, 'payback')} years vs life {metrics['project_life']} years — {decisions['payback']['status']}. {decisions['payback']['reason']}", body))
    flow.append(Paragraph("13. Profitability Index", styles["H2"]))
    flow.append(Paragraph(f"PI = {_safe_stat(metrics, 'pi')} — {decisions['pi']['status']}. {decisions['pi']['reason']}", body))

    # 14 Risk
    flow.append(Paragraph("14. Risk Analysis", styles["H2"]))
    for r in risk_results["risks"]:
        flow.append(Paragraph(f"<b>{r.risk}: {r.severity}</b> (Impact: {r.impact}) — {r.explanation} Mitigation: {r.mitigation}", body))
    flow.append(Paragraph(f"Overall risk level: <b>{risk_results['overall_risk']}</b>. {risk_results['overall_explanation']}", body))

    # 15 Scenarios
    flow.append(Paragraph("15. Best / Base / Worst Scenarios", styles["H2"]))
    for key in ["best", "base", "worst"]:
        s = scenarios[key]
        sm = s["summary"]
        flow.append(
            Paragraph(
                f"<b>{s['label']}</b> — NPV {_fmt_money(sm['npv'])}, IRR {_fmt_pct(sm['irr'])}, "
                f"MIRR {_fmt_pct(sm['mirr'])}, ROI {_fmt_pct(sm['roi'])}, Payback "
                f"{sm.get('payback', 'N/A')} yr, PI {sm.get('pi', 'N/A')} → <b>{sm['decision']}</b>. "
                f"{sm['explanation']}",
                body,
            )
        )

    # 16 Sensitivity
    flow.append(Paragraph("16. Sensitivity Analysis", styles["H2"]))
    flow.append(Paragraph("Sensitivity (% change in NPV for -30%/+30% shift in each variable):", body))
    sens_rows = [["Variable", "NPV at -30%", "NPV at Base", "NPV at +30%"]]
    for item in sensitivity.get("sensitivities", []):
        sens_rows.append(
            [item["variable"], _fmt_money(item["npv_low"]), _fmt_money(item["npv_base"]), _fmt_money(item["npv_high"])]
        )
    t = Table(sens_rows, colWidths=[2.4 * inch, 2.2 * inch, 2.2 * inch, 2.2 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Paragraph(f"Most sensitive: {sensitivity.get('most_sensitive')}; Least sensitive: {sensitivity.get('least_sensitive')}.", body))
    for item in sensitivity.get("sensitivities", []):
        flow.append(Paragraph(f"{item['variable']}: {item['explanation']}", body))

    # 17-20
    flow.append(Paragraph("17. Final Investment Decision", styles["H2"]))
    flow.append(Paragraph(f"<b>{final['decision']}</b>. {final['reason']}", body))
    flow.append(Paragraph("18. Reasons Supporting the Decision", styles["H2"]))
    for metric in ["npv", "irr", "mirr", "pi", "roi", "payback"]:
        d = decisions[metric]
        flow.append(Paragraph(f"{metric.upper()} = {_metric_display(metric, metrics)} — {d['status']}. {d['reason']}", body))
    flow.append(Paragraph("19. Recommendations", styles["H2"]))
    flow.append(Paragraph(final["recommendation"], body))
    flow.append(Paragraph("20. Limitations", styles["H2"]))
    flow.append(
        Paragraph(
            "Model-based decision aid, not investment advice. Results depend on input accuracy. "
            "Uncertainty in revenues, costs, discount rates, inflation and market conditions is "
            "measured via sensitivity and scenario analysis but cannot be eliminated. Terminal value "
            "and growth assumptions materially affect results. No external or company data is "
            "included beyond user-provided inputs.",
            body,
        )
    )

    doc.build(flow)
    buf.seek(0)
    return buf.getvalue()


def _write_table(doc: Document, df):
    t = doc.add_table(rows=1, cols=len(df.columns))
    t.style = "Table Grid"
    for j, cname in enumerate(df.columns):
        t.rows[0].cells[j].text = str(cname)
    for i, row in df.iterrows():
        cells = t.add_row().cells
        for j, cname in enumerate(df.columns):
            val = row[cname]
            cells[j].text = f"{val:,.2f}" if isinstance(val, float) else str(val)


def _write_dcf_table_text(results: dict[str, Any]) -> str:
    t = results["dcf_table"]
    if len(t) == 0:
        return "No DCF table."
    first_lines = "; ".join(
        f"Year {int(r[1])}: FCF {_fmt_money(r[2])}, DF {r[3]:.4f}, PV {_fmt_money(r[4])}" for r in t.head(6).itertuples()
    )
    return f"Discounting summary: {first_lines}"


def _pdf_table(flow, df, body):
    if df.empty:
        return
    rows = [list(df.columns)]
    for _, row in df.head(12).iterrows():
        rows.append(
            [f"{v:,.2f}" if isinstance(v, float) else str(v) for v in row.tolist()]
        )
    width = 9.0 * inch
    col_w = [width / len(df.columns)] * len(df.columns)
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(_table_style())
    flow.append(t)


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EAF1F8")]),
        ]
    )


# ---------------------------------------------------------------------------
# Final decision engine
# ---------------------------------------------------------------------------

def decision_final(results: dict[str, Any], risk_results: dict[str, Any]) -> dict[str, str]:
    """Combine all metrics into an overall verdict."""
    metrics = results["metrics"]
    decisions = results["decisions"]
    inputs: Any = results["inputs"]

    evidence = []
    statuses = [d["status"] for d in decisions.values()]
    accepts = statuses.count("ACCEPT")
    rejects = statuses.count("REJECT")

    npv = metrics["npv"]
    irr = metrics["irr"]
    mirr = metrics["mirr"]
    pi = metrics["pi"]
    roi = metrics["roi"]
    payback = metrics["payback"]
    lifecycle = metrics["project_life"]

    if npv > 0:
        evidence.append("Positive NPV indicates value creation.")
    else:
        evidence.append("NPV is negative or zero, indicating value destruction or no value creation.")

    if irr is not None:
        if irr > inputs.discount_rate:
            evidence.append(f"IRR ({irr:.2f}%) exceeds the WACC ({inputs.discount_rate:.2f}%).")
        else:
            evidence.append(f"IRR ({irr:.2f}%) is at or below the WACC ({inputs.discount_rate:.2f}%).")

    if mirr is not None:
        if mirr > inputs.discount_rate:
            evidence.append(f"MIRR ({mirr:.2f}%) exceeds the required return.")
        else:
            evidence.append(f"MIRR ({mirr:.2f}%) is at or below the required return.")

    if pi is not None:
        if pi < 1:
            evidence.append("Profitability index is below 1.0, indicating insufficient PV of inflows.")
        else:
            evidence.append(f"Profitability index is {pi:.3f}, at or above 1.0.")

    if roi is not None:
        if roi < 0:
            evidence.append("ROI is negative, indicating total returns below committed capital.")
        else:
            evidence.append(f"ROI is positive ({roi:.1f}%), suggesting total returns above committed capital.")

    if payback is not None:
        if payback > lifecycle:
            evidence.append(f"Payback ({payback:.2f} years) exceeds the project life ({lifecycle:.0f} years).")
        else:
            evidence.append(f"Payback ({payback:.2f} years) is within the project life.")

    risk_level = risk_results["overall_risk"]
    if risk_level in ("HIGH", "VERY HIGH"):
        evidence.append(f"Overall risk is {risk_level}, compounding doubt about base-case outcomes.")
    else:
        evidence.append(f"Overall risk level is {risk_level}.")

    reasons = "\n".join(f"- {e}" for e in evidence)

    if rejects >= accepts and rejects >= 3:
        decision = "REJECT"
        reason = (
            f"Multiple financial indicators fail their required thresholds, the NPV is "
            f"{'negative' if npv < 0 else 'not sufficiently positive'}, and risk exposure remains "
            f"{risk_level}. The weight of evidence indicates the project is unlikely to create value "
            "under the current assumptions. Reasons:\n" + reasons
        )
        recommendation = (
            "Do not proceed under the current assumptions. Management should reconsider project costs, "
            "expected revenues, financing structure, or the required return before reassessment."
        )
    elif accepts >= rejects and accepts >= 4:
        decision = "ACCEPT"
        reason = (
            f"The project clears most financial thresholds: NPV is "
            f"{'positive' if npv > 0 else 'not clearly favourable'}, returns compare favourably with the "
            f"cost of capital, and risk is assessed as {risk_level}. Reasons:\n" + reasons
        )
        recommendation = (
            "Proceed with the investment subject to standard governance, contracting and monitoring "
            "controls, and monitor the sensitivity variables in particular."
        )
    else:
        decision = "REVIEW"
        reason = (
            f"Financial evidence is mixed: some metrics are favourable while others are not, and risk "
            f"is assessed as {risk_level}. A final judgment requires additional qualitative analysis, "
            "re-confirmation of assumptions, or alternative structures. Reasons:\n" + reasons
        )
        recommendation = (
            "Undertake deeper diligence before a final call. Re-validate key assumptions, negotiate "
            "better terms, and re-run the analysis before committing capital."
        )

    return {"decision": decision, "reason": reason, "recommendation": recommendation}


# ---------------------------------------------------------------------------
# Three-Project Multi-Currency comparison report (PDF, landscape)
# ---------------------------------------------------------------------------

def _ccy_money(v, ccy: str) -> str:
    if v is None or v != v:
        return "N/A"
    return f"{ccy}{v:,.0f}"


def _ccy_num(v, digits: int = 2, suffix: str = "") -> str:
    if v is None or v != v:
        return "N/A"
    return f"{v:,.{digits}f}{suffix}"


def _ts_display(ts) -> str:
    if ts is None:
        return "N/A"
    s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
    return s[:19].replace("T", " ")


def build_three_project_pdf_report(result: dict[str, Any]) -> bytes:
    """Render the full comparison -> ranking -> optimization -> recommendation.

    The final report must state, for every project: Rate Used | Source | Timestamp |
    Live or Manual — plus WHAT/WHY/EVIDENCE/RISKS/ACTION for the winner.
    """
    config = result["config"]
    comparison_currency = config.comparison_currency
    ccy = fx_labels().get(comparison_currency, comparison_currency)
    comp_df = result["comparison_df"].sort_values("Project").reset_index(drop=True)
    ranking_df = result["ranking_df"]
    optimisation = result["optimisation"]
    rec = result["recommendation"]
    executed = result["executed"]
    rates_text = result["rates_text"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=0.4 * inch,
        leftMargin=0.4 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="FTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=16,
            fontName="Helvetica-Bold",
        )
    )
    styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=11, spaceAfter=6))
    body = styles["BodyText"]
    body.fontName = "Helvetica"
    body.fontSize = 8.5

    flow = []
    flow.append(Paragraph("Three-Project Multi-Currency Decision Report", styles["FTitle"]))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%d %b %Y, %H:%M')} | <b>Comparison currency:</b> {comparison_currency}", body))
    flow.append(Spacer(1, 8))

    # 1. Projects under review
    flow.append(Paragraph("1. Projects Under Review", styles["H2"]))
    proj_rows = [["Project", "Name", "Source Currency", "Description"]]
    for key in ("A", "B", "C"):
        spec = config.projects[key]
        proj_rows.append(
            [key, spec.name, fx_labels().get(spec.currency, spec.currency),
             (spec.description or "")[:90]]
        )
    t = Table(proj_rows, colWidths=[0.8 * inch, 2.2 * inch, 1.4 * inch, 8.4 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Spacer(1, 8))

    # 2. Exchange rates used (Rate | Source | Timestamp | Live or Manual)
    flow.append(Paragraph("2. Exchange Rates Used", styles["H2"]))
    flow.append(
        Paragraph(
            "Every monetary input was converted from its source currency to the comparison "
            "currency using the rates below. Manual overrides take priority over live rates; "
            "live rates are marked LIVE, manual rates are marked MANUAL, and stored-but-stale "
            "rates are labelled STALE. A rate is never used silently when it is outdated.",
            body,
        )
    )
    rate_rows = [["Pair", "Rate Used", "Source", "Timestamp", "Live or Manual", "Status"]]
    for pair, fr in result["rates"].items():
        rate_rows.append(
            [
                pair,
                _ccy_num(fr.rate, 6),
                fr.source or "stored",
                _ts_display(fr.ts),
                str(fr.status),
                str(fr.status),
            ]
        )
    t = Table(rate_rows, colWidths=[1.2 * inch, 1.2 * inch, 3.2 * inch, 2.2 * inch, 2.0 * inch, 1.8 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Spacer(1, 8))

    # 3. Comparison of results
    flow.append(Paragraph("3. Comparison of Results", styles["H2"]))
    comp_cols = [
        "Project",
        "DCF Value",
        "NPV",
        "IRR",
        "MIRR",
        "ROI",
        "Holding Period Return",
        "Annualized Return",
        "Payback",
        "Profitability Index",
        "WACC",
        "Overall Risk",
        "Best Case NPV",
        "Base Case NPV",
        "Worst Case NPV",
    ]
    cmp_rows = [comp_cols]
    for _, r in comp_df.iterrows():
        cmp_rows.append(
            [
                r["Project"],
                _ccy_money(r["DCF Value"], ccy),
                _ccy_money(r["NPV"], ccy),
                _ccy_num(r["IRR"], 2, "%"),
                _ccy_num(r["MIRR"], 2, "%"),
                _ccy_num(r["ROI"], 2, "%"),
                _ccy_num(r["Holding Period Return"], 2, "%"),
                _ccy_num(r["Annualized Return"], 2, "%"),
                _ccy_num(r["Payback"], 2, " yr"),
                _ccy_num(r["Profitability Index"], 3),
                _ccy_num(r["WACC"], 2, "%"),
                str(r["Risk"]),
                _ccy_money(r["Best Case NPV"], ccy),
                _ccy_money(r["Base Case NPV"], ccy),
                _ccy_money(r["Worst Case NPV"], ccy),
            ]
        )
    t = Table(cmp_rows, colWidths=[0.7 * inch, 1.15 * inch, 1.15 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 1.1 * inch, 1.2 * inch, 0.9 * inch, 0.95 * inch, 0.7 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Spacer(1, 8))

    # 4. Ranking
    flow.append(Paragraph("4. Ranking (1st to 3rd)", styles["H2"]))
    rank_rows = [["Rank", "Project", "Name", "Composite Score", "Risk", "Explanation"]]
    for _, r in ranking_df.iterrows():
        rank_rows.append(
            [
                str(int(r["Rank"])),
                r["Project"],
                r["Name"],
                _ccy_num(r["Composite Score"], 4),
                str(r["Risk"]),
                rec.get(f"explanation_rank{int(r['Rank'])}", ""),
            ]
        )
    t = Table(rank_rows, colWidths=[0.7 * inch, 0.7 * inch, 2.0 * inch, 1.4 * inch, 1.0 * inch, 8.0 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Spacer(1, 8))

    # 5. Optimization
    flow.append(Paragraph("5. Capital Optimisation", styles["H2"]))
    flow.append(Paragraph(
        f"Investment type: <b>{optimisation['type']}</b>. Budget: "
        f"{_ccy_money(getattr(config, 'budget', 0), ccy)}. {optimisation['explanation']}",
        body,
    ))
    if optimisation["type"] == "Divisible":
        alloc = optimisation["allocation_df"]
        alloc_rows = [["Project", "NPV", "Investment", "Allocated", "Portion %", "NPV Contribution"]]
        for _, r in alloc.iterrows():
            alloc_rows.append(
                [
                    r["Project"],
                    _ccy_money(r["NPV"], ccy),
                    _ccy_money(r["Investment"], ccy),
                    _ccy_money(r["Allocated"], ccy),
                    _ccy_num(r["Portion %"], 1, "%"),
                    _ccy_money(r["NPV Contribution"], ccy),
                ]
            )
        t = Table(alloc_rows, colWidths=[0.9 * inch, 1.6 * inch, 1.6 * inch, 1.6 * inch, 1.2 * inch, 1.6 * inch])
    else:
        comb = optimisation["combinations_df"]
        comb_rows = [["Combination", "Investment", "Total NPV", "Within Budget"]]
        for _, r in comb.iterrows():
            comb_rows.append(
                [
                    r["Combination"],
                    _ccy_money(r["Investment"], ccy),
                    _ccy_money(r["Total NPV"], ccy),
                    "Yes" if r["Feasible"] else "No",
                ]
            )
        t = Table(comb_rows, colWidths=[2.4 * inch, 2.4 * inch, 2.4 * inch, 2.4 * inch])
    t.setStyle(_table_style())
    flow.append(t)
    flow.append(Spacer(1, 8))

    # 6. Final Recommendation (WHAT won -> WHY -> EVIDENCE -> RISKS -> WHAT MANAGEMENT SHOULD DO)
    flow.append(Paragraph("6. Final Recommendation", styles["H2"]))
    flow.append(Paragraph(f"<b>WHAT WON</b>: {rec['what']}", body))
    flow.append(Paragraph(f"<b>WHY</b>: {rec['why']}", body))
    flow.append(Paragraph("<b>EVIDENCE</b>", body))
    flow.append(
        ListFlowable(
            [ListItem(Paragraph(e, body)) for e in rec["evidence"]],
            bulletType="bullet",
        )
    )
    flow.append(Paragraph(f"<b>RISKS</b>: {rec['risks']}", body))
    flow.append(Paragraph(f"<b>WHAT MANAGEMENT SHOULD DO</b>: {rec['action']}", body))
    flow.append(
        Paragraph(
            "Method note: no currency (USD, ZAR or ZiG) is treated as inherently superior. All "
            "monetary values are compared in the single comparison currency after conversion; "
            "scale-independent metrics (IRR, MIRR, ROI, payback, PI) are unaffected by currency choice.",
            body,
        )
    )

    # 7. Rates audit trail
    flow.append(Paragraph("7. Exchange-Rate Audit Trail", styles["H2"]))
    for line in rates_text:
        flow.append(Paragraph(line, body, bulletText="-"))

    # 8. Limitations
    flow.append(Paragraph("8. Limitations", styles["H2"]))
    flow.append(
        Paragraph(
            "Model-based decision aid, not investment advice. Results depend on input accuracy and on "
            "the exchange rates and market assumptions in force at the time of the analysis. Exchange "
            "rates move continuously; re-run the comparison when USD/ZAR/ZiG rates change materially. "
            "Terminal value, growth and discount-rate assumptions materially affect outcomes.",
            body,
        )
    )

    doc.build(flow)
    buf.seek(0)
    return buf.getvalue()


def fx_labels() -> dict[str, str]:
    from fx_rates import CCY_LABELS

    return CCY_LABELS