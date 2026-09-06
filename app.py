"""Financial Engineering Investment Decision Agent — Streamlit dashboard.

Run:  streamlit run app.py
"""

from __future__ import annotations

import io
import time
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import data_validation as dv
import email_service
import fx_rates as fx
import report_generator as rg
import three_project as tp
from calculations import (
    ProjectInputs,
    decision_for_irr,
    decision_for_mirr,
    decision_for_npv,
    decision_for_payback,
    decision_for_pi,
    decision_for_roi,
    run_analysis,
)
from risk_analysis import assess_risks
from scenario_analysis import (
    build_scenarios,
    run_sensitivity,
    sensitivity_interpretation,
)

st.set_page_config(page_title="Financial Engineering Investment Decision Agent", layout="wide")
st.markdown(
    """
<style>
div.stButton > button { width: 100%; }
.metric-card { border:1px solid #ccc; border-radius:8px; padding:14px 18px; margin-bottom:10px; }
.metric-card h4 { margin: 0 0 4px 0; }
.accept { border-left: 6px solid #2e7d32; background:#e8f5e9; }
.reject { border-left: 6px solid #c62828; background:#ffebee; }
.review { border-left: 6px solid #f9a825; background:#fff8e1; }
</style>
""",
    unsafe_allow_html=True,
)


def fmt_money(v: float | None) -> str:
    if v is None or not np.isfinite(v):
        return "N/A"
    return f"${v:,.0f}" if v >= 0 else f"(${abs(v):,.0f})"


def fmt_pct(v: float | None) -> str:
    if v is None or not np.isfinite(v):
        return "N/A"
    return f"{v:.2f}%"


def fmt_num(v: float | None) -> str:
    if v is None or not np.isfinite(v):
        return "N/A"
    return f"{v:,.2f}"


def metric_card(title: str, value: str, status: str, reason: str):
    cls = status.lower()
    st.markdown(
        f"""<div class="metric-card {cls}">
        <h4>{title}: {value} <span style="float:right">[{status}]</span></h4>
        <p style="margin:6px 0 0 0">{reason}</p>
        </div>""",
        unsafe_allow_html=True,
    )


def status_color(status: str) -> str:
    return {"ACCEPT": "#2e7d32", "REJECT": "#c62828", "REVIEW": "#f57f17"}.get(status, "#333")


def display_metric(decision: dict[str, str], value: str, heading: str):
    metric_card(heading, value, decision["status"], decision["reason"])


def sidebar_input_form() -> ProjectInputs:
    with st.sidebar:
        st.header("Investment Inputs")
        with st.form("input_form"):
            project_name = st.text_input("Project Name", "Growth Facility Expansion")
            project_desc = st.text_area("Project Description", "Expansion of production capacity.", height=70)

            st.subheader("Core Assumptions")
            c1, c2 = st.columns(2)
            initial_investment = c1.number_input("Initial Investment ($)", min_value=0.0, value=1_000_000.0, step=50_000.0, format="%.0f")
            project_life = c2.number_input("Project Life (years)", min_value=1.0, max_value=100.0, value=10.0, step=1.0)
            annual_revenues = c1.number_input("Annual Revenues ($)", min_value=0.0, value=350_000.0, step=10_000.0, format="%.0f")
            operating_costs = c2.number_input("Operating Costs ($)", min_value=0.0, value=80_000.0, step=10_000.0, format="%.0f")
            tax_rate = c1.number_input("Tax Rate (%)", min_value=0.0, max_value=100.0, value=25.0, step=0.5)
            discount_rate = c2.number_input("WACC / Discount Rate (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5)
            financing_rate = c1.number_input("Financing Rate (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5)
            reinvestment_rate = c2.number_input("Reinvestment Rate (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5)

            st.subheader("Additional Assumptions")
            working_capital = c1.number_input("Initial Working Capital ($)", min_value=0.0, value=0.0, step=10_000.0, format="%.0f")
            terminal_value = c2.number_input("Terminal Value ($)", min_value=0.0, value=0.0, step=50_000.0, format="%.0f")
            rev_growth = c1.number_input("Revenue Growth (%/yr)", value=0.0, step=0.5)
            cost_growth = c2.number_input("Cost Growth (%/yr)", value=0.0, step=0.5)
            terminal_growth = c1.number_input("Terminal Growth (%/yr)", value=0.0, step=0.25)

            submitted = st.form_submit_button("Run Analysis", type="primary")

        if submitted:
            return ProjectInputs(
                project_name=project_name,
                project_description=project_desc,
                initial_investment=float(initial_investment),
                project_life=float(project_life),
                annual_revenues=float(annual_revenues),
                revenue_growth_rate=float(rev_growth),
                operating_costs=float(operating_costs),
                cost_growth_rate=float(cost_growth),
                tax_rate=float(tax_rate),
                working_capital=float(working_capital),
                terminal_value=float(terminal_value),
                terminal_growth_rate=float(terminal_growth),
                discount_rate=float(discount_rate),
                financing_rate=float(financing_rate),
                reinvestment_rate=float(reinvestment_rate),
            )
        st.markdown("---")
        st.caption("Requires Streamlit ≥ 1.30, pandas, numpy, plotly, openpyxl, reportlab, python-docx.")


def upload_input_form() -> ProjectInputs | None:
    with st.sidebar:
        st.header("Upload Inputs")
        f = st.file_uploader("CSV / Excel file", type=["csv", "xlsx", "xls"])
        if f is not None:
            try:
                if f.name.lower().endswith(".csv"):
                    df = pd.read_csv(f)
                else:
                    df = pd.read_excel(f)
                vres, data = dv.validate_csv_upload(df)
                if not vres.is_valid:
                    st.error("Validation failed:" + "\n".join(f"- {e}" for e in vres.errors))
                    return None
                for w in vres.warnings:
                    st.warning(w)
                if data:
                    st.success("Inputs parsed from uploaded file (first row used).")
                    return ProjectInputs(
                        project_name=str(data.get("project_name", "Uploaded Project")),
                        initial_investment=float(data["initial_investment"]),
                        project_life=float(data["project_life"]),
                        annual_revenues=float(data["annual_revenues"]),
                        operating_costs=float(data["operating_costs"]),
                        tax_rate=float(data["tax_rate"]),
                        working_capital=float(data.get("working_capital", 0)),
                        terminal_value=float(data.get("terminal_value", 0)),
                        discount_rate=float(data["discount_rate"]),
                        financing_rate=float(data.get("financing_rate", data["discount_rate"])),
                        reinvestment_rate=float(data.get("reinvestment_rate", data["discount_rate"])),
                        revenue_growth_rate=float(data.get("growth_rate", 0)),
                    )
            except Exception as e:  # noqa: BLE001
                st.error(f"Failed to parse file: {e}")
                return None
    return None


def build_cashflow_chart(results: dict[str, Any]):
    d = results["chart_data"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=d["years"], y=d["net_cash_flows"], name="Net Cash Flow (with terminal value)", marker_color="#1F4E78"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=d["years"], y=d["cumulative_cash_flows"], name="Cumulative Cash Flow", mode="lines+markers",
                   line=dict(color="#C62828", width=3)),
        secondary_y=True,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#999")
    fig.update_layout(title="Annual & Cumulative Cash Flows", height=420, hovermode="x unified", template="plotly_white")
    return fig


def build_pv_chart(results: dict[str, Any]):
    d = results["chart_data"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["years"], y=d["present_values"], name="Present Value", marker_color="#1565c0"))
    fig.add_trace(
        go.Scatter(x=d["years"], y=d["cumulative_present_values"], name="Cumulative PV", mode="lines+markers",
                   line=dict(color="#ef6c00", width=3))
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#999")
    fig.update_layout(title="Present Values of Cash Flows", height=420, hovermode="x unified", template="plotly_white")
    return fig


def build_scenario_chart(scenarios: dict[str, Any]):
    labels = [s["label"] for s in scenarios.values()]
    npvs = [s["summary"]["npv"] for s in scenarios.values()]
    colors = ["#2e7d32", "#1F4E78", "#c62828"]
    fig = go.Figure(go.Bar(x=labels, y=npvs, marker_color=colors, text=[fmt_money(v) for v in npvs], textposition="outside"))
    fig.add_hline(y=0, line_dash="dash", line_color="#999")
    fig.update_layout(title="Scenario Comparison — NPV ($)", height=420, template="plotly_white")
    return fig


def build_sensitivity_chart(sens_df: pd.DataFrame):
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=sens_df["Variable"],
            x=sens_df["Spread"],
            orientation="h",
            marker_color="#1F4E78",
            text=[fmt_money(v) for v in sens_df["Spread"]],
            textposition="outside",
            name="Spread",
        )
    )
    fig.update_layout(title="Sensitivity — NPV Swing by Variable", height=380, template="plotly_white",
                      xaxis_title="NPV Swing ($)", yaxis_title="")
    return fig


def build_risk_chart(risk_results: dict[str, Any]):
    risks = risk_results["risks"]
    names = [r.risk for r in risks]
    scores = [r.score for r in risks]
    colors = ["#2e7d32", "#f9a825", "#ef6c00", "#c62828"]
    bar_colors = [colors[min(s, 4) - 1] for s in scores]
    fig = go.Figure(go.Bar(x=scores, y=names, orientation="h", marker_color=bar_colors))
    fig.update_layout(title="Risk Heat — Severity Scores", height=460, template="plotly_white",
                      xaxis_title="Severity (1 = Low → 4 = Very High)", yaxis_title="")
    return fig


def excel_download(results: dict[str, Any], scenarios: dict[str, Any], sensitivity_df: pd.DataFrame, risk_results: dict[str, Any]) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()

    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    blue = Font(name="Arial", color="1F4E78")
    black = Font(name="Arial", color="000000")
    green_fill = PatternFill("solid", fgColor="C6EFCE")
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(name="Arial", color="FFFFFF", bold=True)

    def style_sheet(ws, df, user_input_cols=None, result_idx=None):
        ws.append(list(df.columns))
        for c in ws[1]:
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center")
        for _, row in df.iterrows():
            ws.append([v for v in row.tolist()])
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.border = border
                c.font = black
                if isinstance(c.value, float):
                    c.number_format = "$#,##0;($#,##0)"
        if user_input_cols:
            for idx, col in enumerate(df.columns, start=1):
                if col in user_input_cols:
                    for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                        for c in row:
                            c.font = blue
        if result_idx is not None:
            for col_idx, col in enumerate(df.columns, start=1):
                if col in result_idx:
                    for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
                        for c in row:
                            c.fill = green_fill
        ws.freeze_panes = "A2"
        for c in ws[1]:
            c.border = border

    ws = wb.active
    ws.title = "Capital Budgeting"
    user_cols = {"Initial Investment", "Working Capital", "Terminal Value", "Annual Revenues"}
    style_sheet(ws, results["cash_flow_table"], user_input_cols=user_cols)

    ws2 = wb.create_sheet("DCF Valuation")
    style_sheet(ws2, results["dcf_table"], result_idx={"Present Value", "Cumulative Present Value"})

    rows_metrics = [
        ["Initial Investment", results["metrics"]["initial_investment"]],
        ["NPV", results["metrics"]["npv"]],
        ["IRR (%)", results["metrics"]["irr"]],
        ["MIRR (%)", results["metrics"]["mirr"]],
        ["Payback (years)", results["metrics"]["payback"]],
        ["Profitability Index", results["metrics"]["pi"]],
        ["ROI (%)", results["metrics"]["roi"]],
        ["Total Project Value", results["metrics"]["total_project_value"]],
        ["PV of Terminal Value", results["metrics"]["pv_terminal"]],
    ]
    ws3 = wb.create_sheet("Key Metrics")
    ws3.append(["Metric", "Value"])
    for name, val in rows_metrics:
        ws3.append([name, val])
    for r in ws3.iter_rows(min_row=2, min_col=2):
        for c in r:
            if isinstance(c.value, float):
                if c.value > 100:
                    c.number_format = "$#,##0;($#,##0)"
                else:
                    c.number_format = "0.00%"
            c.font = black
            c.border = border
    ws3["B1"].font = header_font

    ws4 = wb.create_sheet("Scenarios")
    scen_rows = [["Scenario", "NPV", "IRR (%)", "MIRR (%)", "ROI (%)", "Payback", "PI", "Decision"]]
    for key, s in scenarios.items():
        sm = s["summary"]
        scen_rows.append([s["label"], sm["npv"], sm["irr"], sm["mirr"], sm["roi"], sm["payback"], sm["pi"], sm["decision"]])
    for row in scen_rows:
        ws4.append(row)
    style_sheet(ws4, pd.DataFrame(scen_rows[1:], columns=scen_rows[0]))

    ws5 = wb.create_sheet("Sensitivity")
    style_sheet(ws5, sensitivity_df)

    ws6 = wb.create_sheet("Risk Analysis")
    ws6.append(["Risk", "Severity", "Impact", "Explanation", "Mitigation"])
    for r in risk_results["risks"]:
        ws6.append([r.risk, r.severity, r.impact, r.explanation, r.mitigation])
    for c in ws6[1]:
        c.font = header_font
        c.fill = header_fill
    ws6.append([])
    ws6.append(["Overall Risk Level", risk_results["overall_risk"]])
    ws6.append(["Overall Explanation", risk_results["overall_explanation"]])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def render_results(results: dict[str, Any], scenarios: dict[str, Any], sensitivity_summary: dict[str, Any], sens_df: pd.DataFrame, risk_results: dict[str, Any]):
    metrics = results["metrics"]
    decisions = results["decisions"]
    final = rg.decision_final(results, risk_results)

    # ------------------------------------------------------------------ 1. Exec Summary
    st.subheader("Executive Summary")
    cols = st.columns(6)
    cols[0].metric("Final Decision", final["decision"])
    cols[1].metric("Investment", f"${metrics['initial_investment']:,.0f}")
    cols[2].metric("NPV", fmt_money(metrics["npv"]))
    cols[3].metric("IRR", fmt_pct(metrics["irr"]))
    cols[4].metric("MIRR", fmt_pct(metrics["mirr"]))
    cols[5].metric("ROI", fmt_pct(metrics["roi"]))

    cols2 = st.columns(3)
    cols2[0].metric("Payback", f"{fmt_num(metrics['payback'])} yrs")
    cols2[1].metric("Profitability Index", fmt_num(metrics["pi"]))
    cols2[2].metric("Risk Level", risk_results["overall_risk"])

    st.markdown(final["reason"])

    # ------------------------------------------------------------------ 2. Financial Analysis
    with st.expander("Capital Budgeting — Cash Flow Table", expanded=True):
        st.dataframe(results["cash_flow_table"], width='stretch')

    with st.expander("DCF Valuation Table", expanded=True):
        st.dataframe(results["dcf_table"], width='stretch')
        st.markdown(
            f"**DCF Value = {fmt_money(metrics['total_project_value'])}.** "
            "Interpretation: the estimated present value of the project's future cash flows, "
            "discounted at the WACC, is this amount."
        )
        if metrics["total_project_value"] < metrics["initial_investment"]:
            st.markdown(
                f"The DCF value is below the investment cost of {fmt_money(metrics['initial_investment'])}. "
                "This is unfavourable: the project's total present value of cash flows does not cover "
                "the capital outlay, so the investment is expected to destroy value."
            )
        else:
            st.markdown(
                f"The DCF value exceeds the investment cost of {fmt_money(metrics['initial_investment'])}, "
                "indicating the project is expected to generate more present value than it costs."
            )

    # ------------------------------------------------------------------ 3. Charts
    st.subheader("Interactive Charts")
    tabs = st.tabs(["Cash Flows", "Present Value", "Scenario Comparison", "Sensitivity", "Risk Indicators"])
    with tabs[0]:
        st.plotly_chart(build_cashflow_chart(results), width='stretch')
    with tabs[1]:
        st.plotly_chart(build_pv_chart(results), width='stretch')
    with tabs[2]:
        st.plotly_chart(build_scenario_chart(scenarios), width='stretch')
    with tabs[3]:
        st.plotly_chart(build_sensitivity_chart(sens_df), width='stretch')
    with tabs[4]:
        st.plotly_chart(build_risk_chart(risk_results), width='stretch')

    # ------------------------------------------------------------------ 4. Metrics with reasons
    st.subheader("Capital Budgeting — Metrics & Interpretation")

    display_metric(decisions["npv"], fmt_money(metrics["npv"]), "NPV")
    display_metric(decisions["irr"], fmt_pct(metrics["irr"]), "IRR")
    display_metric(decisions["mirr"], fmt_pct(metrics["mirr"]), "MIRR")

    metric_card(
        "ROI",
        f"{fmt_pct(metrics['roi'])}",
        decisions["roi"]["status"],
        decisions["roi"]["reason"] + f" Holding-period return: {fmt_pct(metrics['holding_period_return'])}; "
        f"annualized return: {fmt_pct(metrics['annualized_return'])}.",
    )
    metric_card("Payback Period", f"{fmt_num(metrics['payback'])} years", decisions["payback"]["status"], decisions["payback"]["reason"])
    metric_card(
        "Profitability Index",
        fmt_num(metrics["pi"]),
        decisions["pi"]["status"],
        decisions["pi"]["reason"] + f" (PV of inflows = {fmt_money(metrics['total_project_value'])} / investment = {fmt_money(metrics['initial_investment'])}).",
    )

    # ------------------------------------------------------------------ 5. Scenarios
    st.subheader("Scenario Analysis")
    for key in ["best", "base", "worst"]:
        s = scenarios[key]
        sm = s["summary"]
        st.markdown(
            f"""<div class="metric-card">
            <h4>{s['label']}: NPV {fmt_money(sm['npv'])} — Decision: <span style="color:{status_color(sm['decision'])}">{sm['decision']}</span></h4>
            <p>{sm['explanation']}</p>
            <p style="font-size:0.9em">IRR {fmt_pct(sm['irr'])} | MIRR {fmt_pct(sm['mirr'])} | ROI {fmt_pct(sm['roi'])} |
            Payback {fmt_num(sm['payback'])} yrs | PI {fmt_num(sm['pi'])}</p>
            </div>""",
            unsafe_allow_html=True,
        )

    # ------------------------------------------------------------------ 6. Sensitivity
    st.subheader("Sensitivity Analysis")
    st.dataframe(sens_df, width='stretch')
    st.info(sensitivity_interpretation(sensitivity_summary))
    for item in sensitivity_summary["sensitivities"]:
        st.markdown(
            f"**{item['variable']}**: NPV swings from {fmt_money(item['npv_low'])} to {fmt_money(item['npv_high'])} "
            f"around the base {fmt_money(item['npv_base'])}. {item['explanation']}"
        )

    # ------------------------------------------------------------------ 7. Risk
    st.subheader("Risk Analysis")
    for r in risk_results["risks"]:
        metric_card(
            f"{r.risk}: {r.severity}",
            f"Impact: {r.impact}",
            r.severity,
            f"{r.explanation} **Possible mitigation:** {r.mitigation}",
        )
    st.markdown(
        f"**Overall Risk Level: {risk_results['overall_risk']}** — {risk_results['overall_explanation']}"
    )

    # ------------------------------------------------------------------ 8. Final Decision
    st.subheader("Final Investment Decision")
    fa = {"ACCEPT": "🟢 ACCEPT", "REJECT": "🔴 REJECT", "REVIEW": "🟡 REVIEW"}[final["decision"]]
    st.markdown(f"<h2 style='color:{status_color(final['decision'])}'>{fa}</h2>", unsafe_allow_html=True)
    st.markdown(final["reason"])
    st.markdown(f"**Recommendation:** {final['recommendation']}")

    return final


def render_email_tab(results: dict[str, Any], final: dict[str, str], risk_results: dict[str, Any], scenarios: dict[str, Any], sens_summary: dict[str, Any]):
    st.subheader("Email Management Report")

    env_default = email_service.default_smtp_from_env()
    env_set = email_service.env_status()

    with st.expander("SMTP Settings (pre-filled from environment variables)", expanded=False):
        st.caption(
            "Enter your e-mail SMTP details below to send to any recipient address. "
            "Values are used only for this send and are never stored in the code. "
            "Status: " + ", ".join(f"{k}={'set' if v else 'empty'}" for k, v in env_set.items())
        )
        e1, e2 = st.columns(2)
        smtp_host = e1.text_input("SMTP Host", env_default.get("host", ""), placeholder="smtp.gmail.com")
        smtp_port = e2.text_input("SMTP Port", env_default.get("port", "587"), placeholder="587")
        smtp_user = e1.text_input("SMTP Username (sender login)", env_default.get("username", ""), placeholder="you@example.com")
        smtp_pass = e2.text_input("SMTP Password / App password", env_default.get("password", ""), type="password")
        smtp_from = st.text_input("From address", env_default.get("from_addr", ""), placeholder="you@example.com")

    smtp_config = {
        "host": smtp_host,
        "port": smtp_port,
        "username": smtp_user,
        "password": smtp_pass,
        "from_addr": smtp_from,
    }
    configured = email_service.is_configured(smtp_config)
    if not configured:
        st.warning(
            "SMTP is not configured yet. Enter complete SMTP settings in the expander above "
            "(or set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM as "
            "environment variables). The recipient can be any e-mail address you type."
        )

    default_body = email_service.build_email_body(
        results["metrics"],
        risk_results["overall_risk"],
        final["decision"],
        final["reason"],
        results["inputs"].project_name,
    )

    c1, c2 = st.columns([2, 1])
    to_email = c1.text_input("Recipient email (any address)", placeholder="analyst@example.com")
    subject = c2.text_input("Subject", f"Investment Decision Report — {results['inputs'].project_name}")
    body = st.text_area("Email message (editable)", default_body, height=300)

    if st.button("Send Email", type="primary"):
        if not to_email or "@" not in to_email or "." not in to_email:
            st.error("Please provide a valid recipient email address (e.g. name@company.com).")
        else:
            report_bytes = generate_report(results, scenarios, sens_summary, risk_results, kind="pdf")
            ok, msg = email_service.send_email(
                to_email=to_email,
                subject=subject,
                body_text=body,
                attachments=[("investment_decision_report.pdf", report_bytes)],
                smtp_config=smtp_config,
            )
            if ok:
                st.success(msg)
            else:
                st.error(msg)


def generate_report(results: dict[str, Any], scenarios: dict[str, Any], sens: dict[str, Any], risk_results: dict[str, Any], kind: str) -> bytes:
    if kind == "pdf":
        return rg.build_pdf_report(results, scenarios, sens, risk_results)
    return rg.build_word_report(results, scenarios, sens, risk_results)


def render_docs_tab():
    st.subheader("Assumptions")
    st.markdown(
        """
- **Operating cash flow** uses the standard formulation: `OCF = EBITDA - Tax + Depreciation tax shield`,
  where tax is charged on EBIT (EBITDA less straight-line depreciation) when positive.
- **Straight-line depreciation** spreads the initial investment uniformly across the project life.
- **Net working capital** is deployed in year 1 and is not recovered elsewhere (user-provided).
- **WACC** is used as the discount rate. **Financing rate** and **reinvestment rate** feed the MIRR.
- **Terminal value** is user-provided or, if absent but a terminal growth rate > 0 is set, computed via the
  Gordon growth model `TV = (OCF_last × (1+g)) / (WACC − g)`. The growth rate must be below the WACC.
- **Revenue and cost growth** are modelled as geometric compounding from year one.
"""
    )
    st.subheader("Data Sources")
    st.markdown(
        """
| Source | What it provides |
|---|---|
| User input | All assumptions entered in the form or uploaded file. |
| Uploaded file | First row of a CSV/Excel file mapping to project inputs. |
| External data | None is imported automatically — the user is responsible for validating WACC, tax, inflation and FX assumptions externally. |
| Model assumptions | Corporate-finance conventions: straight-line depreciation, nominal cash flows, end-of-year discounting conventions described above. |
"""
    )
    st.subheader("Financial Logic")
    st.markdown(
        """
**NPV** = −Investment + Σₜ CFₜ/(1+WACC)ᵗ. *Accept if > 0.*

**IRR** = discount rate making NPV = 0. *Accept if IRR > WACC.*

**MIRR** = (FV₊/PV₋)^(1/n) − 1, with inflows reinvested at the reinvestment rate and outflows financed at the financing rate. *Accept if MIRR > WACC.*

**Payback** = time until cumulative cash flow ≥ 0. *Accept if ≤ project life.*

**PI** = PV(positive inflows) / Investment. *Accept if ≥ 1.*

**ROI** = (total inflows − investment) / investment. *Accept if > 0.*

The **final decision** weighs all metrics and the risk level together rather than relying on any single indicator.
"""
    )


def render_testing_tab():
    import test_cases

    st.subheader("Automated Test Suite")
    st.markdown(
        "Run the tests from a terminal with `python test_cases.py`. The suite covers a profitable "
        "project (expect ACCEPT), a negative-NPV project (expect REJECT), invalid/edge inputs (expect "
        "safe handling), and a high-risk project (expect REJECT or REVIEW)."
    )
    if st.button("Run Tests Now"):
        import io as _io
        import contextlib

        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = test_cases.main()
        st.code(buf.getvalue())
        st.success(f"Tests finished with exit code {code}")


def render_workflow_summary():
    st.subheader("Workflow")
    st.markdown(
        "**Investment Proposal → Capital Budgeting → DCF → Returns → Risk → Scenario & Sensitivity → "
        "Final Decision → Management Report → Email**"
    )
    st.markdown(
        "This is a professional analysis tool. Every metric is calculated, compared against a "
        "threshold, converted into a decision and explained in plain financial language."
    )


# ---------------------------------------------------------------------------
# Tab 2 — Live Exchange Rate Board (USD / ZAR / ZiG)
# ---------------------------------------------------------------------------

def _fx_session_ratemap() -> dict[str, fx.FxRate]:
    return st.session_state.setdefault("fx_ratemap", {})


def _refresh_fx(fetch: bool = False, show_feedback: bool = True) -> None:
    st.session_state.setdefault("fx_ratemap", {})
    st.session_state.setdefault("fx_last_fetch", 0.0)
    if fetch:
        with st.spinner("Fetching live exchange rates..."):
            live = fx.fetch_live_rates()
        if live:
            fx.store_live_rates(live)
            st.session_state["fx_ratemap"] = live
            st.session_state["fx_last_fetch"] = time.time()
            if show_feedback:
                st.success(f"Live rates updated from {next(iter(live.values())).source}.")
        else:
            forumla = fx.all_effective_rates(_fx_session_ratemap())
            st.session_state["fx_ratemap"] = forumla
            if show_feedback:
                st.warning(
                    "Live rate unavailable (network or provider down). The board now shows stored "
                    "rates (labelled STORED/STALE) or manual overrides — never a silently outdated rate."
                )
    else:
        ratemap = st.session_state.get("fx_ratemap")
        if not ratemap:
            st.session_state["fx_ratemap"] = fx.all_effective_rates()


def _maybe_autorefresh(interval_minutes: float) -> None:
    if interval_minutes <= 0:
        return
    last = float(st.session_state.get("fx_last_fetch", 0.0))
    if last <= 0:
        return  # no fresh fetch yet this session; wait for a manual refresh or button click
    if time.time() - last >= interval_minutes * 60:
        _refresh_fx(fetch=True, show_feedback=False)


def render_fx_board():
    st.subheader("Live Exchange Rate Board — USD / ZAR / ZiG")
    st.caption(
        "All six currency pairs. Live source: open.er-api.com (fallback: frankfurter.app/ECB). "
        "Manual overrides and stored-rate history are explicitly labelled; an outdated stored rate "
        "is never silently used (it is shown as STALE)."
    )

    c1, c2 = st.columns([2, 1])
    interval = c1.select_slider(
        "Auto-refresh interval",
        options=[0, 5, 10, 15, 30, 60],
        value=int(st.session_state.get("fx_interval", 15)),
        format_func=lambda v: "Off" if v == 0 else f"Every {v} minutes",
    )
    st.session_state["fx_interval"] = int(interval)
    if c2.button("Refresh Live Rates Now", type="primary"):
        _refresh_fx(fetch=True)

    _maybe_autorefresh(int(interval))
    ratemap = _fx_session_ratemap()
    if not ratemap:
        _refresh_fx(fetch=False)

    board = fx.build_board_frame(ratemap)
    st.dataframe(board, width="stretch")
    st.caption(
        "Status legend — LIVE: fresh from provider · MANUAL OVERRIDE: user-entered, always wins · "
        "STORED: last fetched value, still valid · STALE: stored value older than 24h · UNAVAILABLE: no rate."
    )

    # Manual overrides
    with st.expander("Manual Rate Overrides", expanded=False):
        st.caption(
            "A manual override takes priority over live and stored rates and is marked "
            "MANUAL OVERRIDE in every report. Use it when you have a better rate than the provider."
        )
        pairs = [f"{a}/{b}" for a, b in fx.PAIRS]
        o1, o2, o3 = st.columns([2, 2, 1])
        override_pair = o1.selectbox("Pair", pairs, key="fx_ov_pair")
        override_rate = o2.number_input(
            f"Manual rate for {override_pair}",
            min_value=0.0000001,
            value=float(st.session_state.get("fx_ov_val", 1.0)),
            step=0.01,
            format="%.6f",
            key="fx_ov_rate",
        )
        st.session_state["fx_ov_val"] = override_rate
        o3.markdown("")
        b1, b2 = st.columns(2)
        if b1.button("Set Manual Override"):
            try:
                fx.set_manual_override(override_pair, float(override_rate))
                st.success(f"Manual override stored for {override_pair} = {override_rate:,.6f}.")
                _refresh_fx(fetch=False)
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if b2.button("Clear Manual Override"):
            fx.clear_manual_override(override_pair)
            st.success(f"Manual override cleared for {override_pair}.")
            _refresh_fx(fetch=False)

    with st.expander("Rate History (audit trail)", expanded=False):
        limit = st.slider("History rows", min_value=5, max_value=200, value=30, step=5)
        hist = fx.get_history(limit=min(limit, 200))
        if hist:
            st.dataframe(
                pd.DataFrame(hist).rename(columns={"pair": "Pair", "rate": "Rate", "source": "Source", "status": "Status", "ts": "Timestamp"}),
                width="stretch",
            )
        else:
            st.info("No rate history recorded yet. Fetch live rates to populate the audit trail.")


# ---------------------------------------------------------------------------
# Tab 3 — Three-Project Multi-Currency Comparison & Optimisation
# ---------------------------------------------------------------------------

def _tp_ratemap_ready(config: tp.ComparisonConfig) -> list[str]:
    """Return list of missing pair descriptions; empty when everything can convert."""
    missing = []
    currencies = [p.currency for p in config.projects.values()]
    currencies.append(config.comparison_currency)
    for ccy in set(currencies):
        if ccy == config.comparison_currency:
            continue
        direct = f"{ccy}/{config.comparison_currency}"
        inverse = f"{config.comparison_currency}/{ccy}"
        has_direct = config.ratemap.get(direct) is not None and config.ratemap.get(direct).rate == config.ratemap.get(direct).rate
        has_inv = config.ratemap.get(inverse) is not None and config.ratemap.get(inverse).rate == config.ratemap.get(inverse).rate
        ok = has_direct or has_inv
        if ccy != "USD" and not ok:
            via = f"{ccy}/USD"
            vu = f"USD/{config.comparison_currency}" if config.comparison_currency != "USD" else None
            has_via = config.ratemap.get(via) is not None and config.ratemap.get(via).rate == config.ratemap.get(via).rate
            has_vu = vu is None or (config.ratemap.get(vu) is not None and config.ratemap.get(vu).rate == config.ratemap.get(vu).rate)
            ok = has_via and has_vu
        if not ok:
            missing.append(f"{ccy} → {config.comparison_currency}")
    return list(dict.fromkeys(missing))


def _tp_spec_from_widgets(letter: str, name: str) -> tp.ProjectSpec:
    k = letter.lower()
    return tp.ProjectSpec(
        name=name,
        description=str(st.session_state.get(f"{k}_desc", "")),
        currency=str(st.session_state[f"{k}_ccy"]),
        initial_investment=float(st.session_state[f"{k}_inv"]),
        annual_revenues=float(st.session_state[f"{k}_rev"]),
        operating_costs=float(st.session_state[f"{k}_cost"]),
        tax_rate=float(st.session_state[f"{k}_tax"]),
        discount_rate=float(st.session_state[f"{k}_disc"]),
        financing_rate=float(st.session_state[f"{k}_fin"]),
        reinvestment_rate=float(st.session_state[f"{k}_rein"]),
        project_life=float(st.session_state[f"{k}_life"]),
        working_capital=float(st.session_state[f"{k}_wc"]),
        terminal_value=float(st.session_state[f"{k}_tv"]),
        revenue_growth_rate=float(st.session_state[f"{k}_revg"]),
        cost_growth_rate=float(st.session_state[f"{k}_costg"]),
        terminal_growth_rate=float(st.session_state[f"{k}_tvg"]),
    )


def _tp_input_player(letter: str):
    k = letter.lower()
    name = st.text_input(f"Project {letter} — name", f"Project {letter}", key=f"{k}_name")
    st.caption("All monetary inputs below are in the project's own currency.")
    c1, c2 = st.columns(2)
    with c1:
        ccy = st.selectbox(
            "Project currency",
            fx.CURRENCIES,
            format_func=lambda c: fx.CCY_LABELS[c],
            key=f"{k}_ccy",
        )
        inv = st.number_input("Initial investment", min_value=0.0, value=1_000_000.0, step=50_000.0, format="%.0f", key=f"{k}_inv")
        rev = st.number_input("Annual revenues", min_value=0.0, value=350_000.0, step=10_000.0, format="%.0f", key=f"{k}_rev")
        cost = st.number_input("Operating costs", min_value=0.0, value=80_000.0, step=10_000.0, format="%.0f", key=f"{k}_cost")
        tax = st.number_input("Tax rate (%)", min_value=0.0, max_value=100.0, value=25.0, step=0.5, key=f"{k}_tax")
        disc = st.number_input("Discount rate / WACC (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5, key=f"{k}_disc")
        fin = st.number_input("Financing rate (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5, key=f"{k}_fin")
    with c2:
        life = st.number_input("Project life (years)", min_value=1.0, max_value=100.0, value=10.0, step=1.0, key=f"{k}_life")
        rein = st.number_input("Reinvestment rate (%)", min_value=0.01, max_value=100.0, value=10.0, step=0.5, key=f"{k}_rein")
        wc = st.number_input("Initial working capital", min_value=0.0, value=0.0, step=10_000.0, format="%.0f", key=f"{k}_wc")
        tv = st.number_input("Terminal value", min_value=0.0, value=0.0, step=50_000.0, format="%.0f", key=f"{k}_tv")
        revg = st.number_input("Revenue growth (%/yr)", value=0.0, step=0.5, key=f"{k}_revg")
        costg = st.number_input("Cost growth (%/yr)", value=0.0, step=0.5, key=f"{k}_costg")
        tvg = st.number_input("Terminal growth (%/yr)", value=0.0, step=0.25, key=f"{k}_tvg")
    desc = st.text_area(f"Project {letter} — description", height=60, key=f"{k}_desc")


def _render_tp_result(out: dict[str, Any], ccy: str):
    rec = out["recommendation"]
    comp_df = out["comparison_df"].sort_values("Project").reset_index(drop=True)
    ranking = out["ranking_df"]
    optimism = out["optimisation"]

    st.subheader("Comparison of Results")
    show_cols = [
        "Project", "Name", "DCF Value", "NPV", "IRR", "MIRR", "ROI", "Holding Period Return",
        "Annualized Return", "Payback", "Profitability Index", "WACC", "Risk", "Base Case NPV",
    ]
    st.dataframe(comp_df[show_cols], width="stretch")

    st.subheader("Ranking (1st → 3rd)")
    st.dataframe(ranking[["Rank", "Project", "Name", "Composite Score", "Risk"]], width="stretch")
    for _, r in ranking.iterrows():
        st.markdown(
            f"""<div class="metric-card {"accept" if int(r["Rank"]) == 1 else "review"}">
            <h4>{int(r['Rank'])}{'st' if int(r['Rank'])==1 else 'nd' if int(r['Rank'])==2 else 'rd'} — Project {r['Project']} ({r['Name']}) · Score {r['Composite Score']:.3f} · Risk {r['Risk']}</h4>
            <p>{rec.get(f'explanation_rank{int(r["Rank"])}', '')}</p>
            </div>""",
            unsafe_allow_html=True,
        )

    st.subheader(f"Capital Optimisation — {optimism['type']}")
    st.markdown(optimism["explanation"])
    if optimism["type"] == "Divisible":
        st.dataframe(optimism["allocation_df"], width="stretch")
    else:
        st.dataframe(optimism["combinations_df"], width="stretch")
        st.markdown(f"**Best combination: {optimism.get('best_combination') or 'none within budget'}**")

    st.subheader("Final Recommendation")
    st.markdown(f"**WHAT WON:** {rec['what']}")
    st.markdown(f"**WHY:** {rec['why']}")
    st.markdown("**EVIDENCE:**")
    for e in rec["evidence"]:
        st.markdown(f"- {e}")
    st.markdown(f"**RISKS:** {rec['risks']}")
    st.markdown(f"**WHAT MANAGEMENT SHOULD DO:** {rec['action']}")
    st.info(
        "Method note: no currency (USD, ZAR or ZiG) is treated as inherently superior. Monetary "
        "values are compared in a single comparison currency after conversion; scale-independent "
        "metrics (IRR, MIRR, ROI, payback, PI) do not depend on the currency choice."
    )

    st.subheader("Exchange Rates Used")
    st.markdown("Every monetary input was converted using the rates below. Manual overrides and "
                "live/stored status are stated explicitly.")
    rate_rows = []
    for pair, fr in out["rates"].items():
        rate_rows.append(
            {
                "Currency Pair": pair,
                "Rate Used": (None if fr.rate != fr.rate else fr.rate),
                "Source": fr.source,
                "Timestamp": (str(fr.ts)[:19].replace("T", " ") if fr.ts else "N/A"),
                "Live or Manual": fr.status,
            }
        )
    st.dataframe(pd.DataFrame(rate_rows), width="stretch")

    st.subheader("Management Report & Email")
    rcol1, rcol2 = st.columns(2)
    pdf_bytes = rg.build_three_project_pdf_report(out)
    rcol1.download_button(
        "Download Three-Project PDF Report",
        data=pdf_bytes,
        file_name="three_project_comparison_report.pdf",
        mime="application/pdf",
    )

    with st.expander("Email the comparison report", expanded=False):
        env_default = email_service.default_smtp_from_env()
        e1, e2 = st.columns(2)
        smtp_host = e1.text_input("SMTP Host", env_default.get("host", ""), key="tp_smtp_host")
        smtp_port = e2.text_input("SMTP Port", env_default.get("port", "587"), key="tp_smtp_port")
        smtp_user = e1.text_input("SMTP Username", env_default.get("username", ""), key="tp_smtp_user")
        smtp_pass = e2.text_input("SMTP Password", env_default.get("password", ""), type="password", key="tp_smtp_pass")
        smtp_from = st.text_input("From address", env_default.get("from_addr", ""), key="tp_smtp_from")
        tc1, tc2 = st.columns([2, 1])
        to_email = tc1.text_input("Recipient email (any address)", key="tp_to")
        subject = tc2.text_input("Subject", "Three-Project Comparison Report", key="tp_subject")
        body = st.text_area(
            "Email message",
            (
                f"{rec['what']}\n\n{rec['why']}\n\nRISKS: {rec['risks']}\n\n"
                f"WHAT MANAGEMENT SHOULD DO: {rec['action']}\n\n"
                f"Rates used and full evidence are in the attached PDF report."
            ),
            height=200,
            key="tp_body",
        )
        if st.button("Send Comparison Report Email", type="primary"):
            if not to_email or "@" not in to_email or "." not in to_email:
                st.error("Please provide a valid recipient email address.")
            else:
                ok, msg = email_service.send_email(
                    to_email=to_email,
                    subject=subject,
                    body_text=body,
                    attachments=[("three_project_comparison_report.pdf", pdf_bytes)],
                    smtp_config={
                        "host": smtp_host,
                        "port": smtp_port,
                        "username": smtp_user,
                        "password": smtp_pass,
                        "from_addr": smtp_from,
                    },
                )
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


def render_three_project():
    st.subheader("Three-Project Comparison & Optimisation")
    st.caption(
        "Compare Projects A, B and C in USD / ZAR / ZiG. All monetary inputs are converted into one "
        "comparison currency using the Exchange Rate Board schedules before analysis."
    )

    with st.expander("Comparison Configuration", expanded=True):
        ccfg = st.columns(3)
        comparison_currency = ccfg[0].selectbox(
            "Comparison currency",
            fx.CURRENCIES,
            index=0,
            format_func=lambda c: fx.CCY_LABELS[c],
            key="tp_cmpccy",
        )
        investment_type = ccfg[1].selectbox(
            "Investment type",
            ["Divisible", "Indivisible"],
            index=0,
            key="tp_invtype",
        )
        budget = ccfg[2].number_input(
            f"Investment budget ({comparison_currency})",
            min_value=0.0,
            value=0.0,
            step=100_000.0,
            format="%.0f",
            key="tp_budget",
        )
        methods_sel = st.multiselect(
            "Financial methods used for ranking",
            tp.METHODS,
            default=["NPV", "IRR", "MIRR", "ROI", "PI", "Payback"],
            key="tp_methods",
        )
        include_risk = st.checkbox("Include risk & scenario analysis in the ranking", value=True, key="tp_risk")

    st.markdown("#### Project Inputs (each in its own currency)")
    for letter in ("A", "B", "C"):
        with st.expander(f"Project {letter} — Inputs", expanded=True if letter == "A" else False):
            _tp_input_player(letter)

    if st.button("Run Comparison", type="primary"):
        if not methods_sel:
            st.error("Select at least one financial method.")
        else:
            ratemap = fx.all_effective_rates(_fx_session_ratemap())
            specs = {
                letter: _tp_spec_from_widgets(letter, str(st.session_state.get(f"{letter.lower()}_name", f"Project {letter}")))
                for letter in ("A", "B", "C")
            }
            config = tp.ComparisonConfig(
                projects=specs,
                comparison_currency=comparison_currency,
                methods=methods_sel,
                include_risk_and_scenarios=include_risk,
                investment_type=investment_type,
                budget=float(budget),
                ratemap=ratemap,
            )
            missing = _tp_ratemap_ready(config)
            if missing:
                st.error(
                    "Cannot run the comparison — exchange rates unavailable for: "
                    + ", ".join(missing)
                    + ". Refresh the Exchange Rate Board or set manual overrides first."
                )
                return
            with st.spinner("Running the three-project comparison and optimisation..."):
                out = tp.compare_projects(config)
            st.session_state["tp_result"] = out
            st.session_state["tp_result_ccy"] = fx.CCY_LABELS[comparison_currency]

    result = st.session_state.get("tp_result")
    if result is not None:
        _render_tp_result(result, st.session_state.get("tp_result_ccy", "USD"))


# ---------------------------------------------------------------------------
# Tab 1 — Single-Project Analysis
# ---------------------------------------------------------------------------

def render_single_project_tab():
    # Global results container
    results = None
    scenarios = None
    sens_df = None
    sens_summary = None
    risk_results = None
    final = None

    # Input acquisition
    inputs = None
    up_inputs = upload_input_form()
    if up_inputs is not None:
        inputs = up_inputs
    else:
        inputs = sidebar_input_form()

    if inputs is None:
        st.info("Please enter project details in the sidebar or upload a file. Analysis runs after submitting the form.")
        return

    # Validate
    validation_data = {
        "project_name": inputs.project_name,
        "project_life": inputs.project_life,
        "initial_investment": inputs.initial_investment,
        "annual_revenues": inputs.annual_revenues,
        "operating_costs": inputs.operating_costs,
        "tax_rate": inputs.tax_rate,
        "discount_rate": inputs.discount_rate,
        "working_capital": inputs.working_capital,
        "terminal_value": inputs.terminal_value,
        "growth_rate": inputs.revenue_growth_rate,
    }
    vres = dv.validate_project_inputs(validation_data)
    if not vres.is_valid:
        st.error("Input validation failed — please correct the following:" + "\n".join(f"\n- {e}" for e in vres.errors))
        return
    for w in vres.warnings:
        st.warning(w)

    # Run the full pipeline
    with st.spinner("Running the full financial analysis..."):
        results = run_analysis(inputs)
        risk_results = assess_risks(results)
        scenarios = build_scenarios(results)
        sens_df, sens_summary = run_sensitivity(inputs, results)
        final = rg.decision_final(results, risk_results)

    render_workflow_summary()
    st.markdown(f"### Analyzing: {inputs.project_name}")
    render_results(results, scenarios, sens_summary, sens_df, risk_results)

    # ------------------------------------------------------------------ Report & Email
    st.subheader("Management Report")
    rcol1, rcol2, rcol3 = st.columns(3)
    pdf_bytes = rg.build_pdf_report(results, scenarios, sens_summary, risk_results)
    word_bytes = rg.build_word_report(results, scenarios, sens_summary, risk_results)
    excel_bytes = excel_download(results, scenarios, sens_df, risk_results)

    rcol1.download_button("Download PDF Report", data=pdf_bytes, file_name="investment_decision_report.pdf", mime="application/pdf")
    rcol2.download_button("Download Word Report", data=word_bytes, file_name="investment_decision_report.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    rcol3.download_button("Download Excel Workbook", data=excel_bytes, file_name="investment_analysis.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("---")
    render_email_tab(results, final, risk_results, scenarios, sens_summary)

    st.markdown("---")
    tabs = st.tabs(["Assumptions, Data Sources & Logic", "Testing", "About"])
    with tabs[0]:
        render_docs_tab()
    with tabs[1]:
        render_testing_tab()
    with tabs[2]:
        st.markdown(
            """
            **Financial Engineering Investment Decision Agent**

            A professional, industry-independent decision-support tool for evaluating capital projects.

            * Modules: `app.py`, `calculations.py`, `risk_analysis.py`, `scenario_analysis.py`,
              `report_generator.py`, `email_service.py`, `data_validation.py`, `fx_rates.py`,
              `three_project.py`, `test_cases.py`.
            * No results are hard-coded — every figure is computed dynamically from the inputs.
            * Reports are generated as PDF, Word, and Excel; email delivery uses SMTP credentials
              supplied via the SMTP settings form or environment variables. The report can be
              emailed to any recipient address.
            """
        )


def main():
    st.title("Financial Engineering Investment Decision Agent")
    st.caption("Industry-independent capital budgeting, DCF, risk, scenario and decision engine.")

    tab_single, tab_fx, tab_three = st.tabs(
        [
            "Single-Project Analysis",
            "Exchange Rate Board (USD/ZAR/ZiG)",
            "Three-Project Comparison",
        ]
    )
    with tab_single:
        render_single_project_tab()
    with tab_fx:
        render_fx_board()
    with tab_three:
        render_three_project()


if __name__ == "__main__":
    main()