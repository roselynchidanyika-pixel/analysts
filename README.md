# Financial Engineering Investment Decision Agent

A professional, industry-independent investment decision platform. It evaluates any capital
project end-to-end: **Investment Proposal → Capital Budgeting → DCF → Returns → Risk →
Scenario & Sensitivity → Final Decision → Management Report → Email**.

Every result is computed dynamically from user inputs (manual form or CSV/Excel upload).
No calculated value is hard-coded.

---

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the URL shown in the terminal (default http://localhost:8501).

### Options

| Development | streamlit run app.py |
|---|---|
| `--server.port 8080` | run on a custom port |
| Headless server | `streamlit run app.py --server.headless true` |

---

## Tests

```bash
python test_cases.py
```

The suite verifies:

| Test | Input | Expected | Purpose |
|---|---|---|---|
| Test 1 | Normal profitable project | ACCEPT | Confirms favourable NPV/IRR/MIRR logic |
| Test 2 | Negative NPV project | REJECT | Confirms rejection reasoning |
| Test 3 | Zero/negative/incomplete inputs | Safe handling (validation blocks) | No crashes |
| Test 4 | High-risk / worst-case project | REJECT or REVIEW | Confirms risk-weighted decision |

Each test prints **Input → Expected → Actual → PASS/FAIL → Explanation**.

---

## Project Structure

| File | Responsibility |
|---|---|
| `app.py` | Streamlit dashboard and full pipeline orchestration |
| `calculations.py` | Capital-budgeting + DCF engine (NPV, IRR, MIRR, payback, PI, ROI) |
| `risk_analysis.py` | Derived risk engine (9 risk categories, composite score) |
| `scenario_analysis.py` | Best/Base/Worst scenarios + sensitivity analysis |
| `report_generator.py` | PDF (reportlab), Word (python-docx) and final-decision engine |
| `email_service.py` | SMTP e-mail delivery via environment variables |
| `data_validation.py` | Input validation and CSV/Excel parsing |
| `test_cases.py` | Automated test suite (four mandatory cases) |
| `sample_data.csv` | Example upload file |
| `requirements.txt` | Python dependencies |

---

## Email Configuration

Email uses SMTP credentials from environment variables — never in source code:

```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USERNAME="you@example.com"
export SMTP_PASSWORD="your-app-password"
export SMTP_FROM="you@example.com"
```

On Windows PowerShell:

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="you@example.com"
$env:SMTP_PASSWORD="your-app-password"
$env:SMTP_FROM="you@example.com"
```

The tool pre-fills an editable message with NPV, IRR, MIRR, ROI, payback, risk level, final
decision and the main reason, and attaches the PDF management report.

---

## Methodology (summary)

- **OCF** = EBITDA − Tax + Depreciation tax shield.
- **Net cash flow** = OCF − ΔNet Working Capital (+ terminal value in the final year).
- **Discount factor** = 1/(1+WACC)ᵗ. **NPV** = −Investment + Σ PV(cash flows).
- **IRR** solves NPV = 0 (bisection, robust to multiple sign changes).
- **MIRR** reinvests inflows at the reinvestment rate and discounts outflows at the financing rate.
- **Payback** = time to cumulative-cash-flow breakeven.
- **PI** = PV(inflows)/Investment.
- **ROI** = (total inflows − investment)/investment; annualized from holding-period return.
- **Terminal value**: user-provided, or Gordon growth model when a positive growth rate is set.

The final decision weighs NPV, IRR, MIRR, PI, ROI, payback, scenario results and the composite
risk level together — never a single metric.

All risks are derived from user inputs and calculated indicators. No external market or entity
data is fabricated or imported implicitly; users are responsible for validating external rates.

---

## Excel Output Formatting

The downloadable Excel workbook follows professional conventions:

- Blue text = user inputs; Black text = formulas; Green background = result cells.
- Currency `$#,##0;($#,##0)`, percentages `0.0%`, negatives in parentheses.
- Arial font, bordered tables, frozen panes, and clear section headers.

---

## Limitations

This tool is a decision-support model, not investment advice. Accuracy depends entirely on the
quality of the input assumptions. Terminal value and growth-rate assumptions materially affect
results; sensitivity and scenario analysis quantify, but cannot eliminate, forecast uncertainty.