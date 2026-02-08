# RHD Deal Intelligence

A Streamlit analytics app for RHD that turns your deals sheet into an interactive Tennessee county map, performance breakdowns (Sold vs Cut Loose), and an Acquisitions feasibility calculator (“Should we contract this?”) powered by your historical outcomes.

This app has **three team views**:
- **Dispo**: county activity + outcomes + quick lookups
- **Acquisitions**: county view + buyer depth + feasibility calculator
- **Admin**: password-gated financial dashboard (GP metrics) + map

---

## What it does

### 1) Interactive Tennessee county map
- Renders a Folium-based county map using `tn_counties.geojson`
- Colors + tooltips adapt to the selected team view and filters
- Click a county to see details in the below-map panel

### 2) Dispo view (operations / outcomes)
- Tracks **Sold vs Cut Loose** counts by county
- Filters by **year**, **status mode** (Sold / Cut / Both), **buyer**, and **rep**
  - Dispo Rep filter
  - Acquisition Rep filter (for Dispo analysis)
- Includes a county quick lookup tool in the sidebar

### 3) Acquisitions view (buyers + feasibility)
- Shows county buyer depth (how many unique buyers have purchased in that county)
- Includes a dedicated tab:
  - **RHD Feasibility Calculator** (“Should we contract this?”)
    - Minimal inputs: county + proposed contract price
    - Uses historical **Effective Contract Price** (Amended if present, otherwise Contract)
    - Uses **county-specific sold ceiling** (highest sold effective price in that county)
    - Uses tail cut-rate behavior to avoid “higher price becomes safer” artifacts

### 4) Admin view (financial dashboard + map)
- Password-gated via Streamlit Secrets or environment variable
- Dashboard focuses on **sold-only** performance:
  - Total GP and Avg GP by county
  - County GP table and headline metrics
- Map view also includes GP-based tooltips/overlays where relevant

---

## Data source

The app pulls data from a **public Google Sheet** (CSV export):
- **Main deals tab** (configured via `SHEET_ID` + `DATA_GID`)
- **“MAO Tiers” tab** (configured via `MAO_TIERS_SHEET_NAME`)

Configuration lives in `config.py`.

### Required minimum columns
The app is defensive and will add missing optional columns, but at minimum it expects these core fields to exist in your deals data:
- `Address`
- `City`
- `County`
- `Salesforce_URL`

### Important normalized fields (created during load)
`data.normalize_inputs()` generates and standardizes:
- `County_clean_up`, `County_key`
- `Status_norm` (sold / cut, normalized)
- `Date_dt`, `Year`
- `Buyer_clean`
- `Dispo_Rep_clean`
- `Market_clean`
- `Acquisition_Rep_clean`
- Numeric financial fields + derived:
  - `Contract_Price_num`, `Amended_Price_num`, `Wholesale_Price_num`
  - `Effective_Contract_Price`
  - `Gross_Profit`

### MAO tiers sheet
`data.normalize_tiers()` outputs a standardized tiers table:
- `County_clean_up`, `County_key`
- `MAO_Tier`
- `MAO_Range_Str` (built from range or min/max)

---

## Running locally

### 1) Install dependencies
```bash
pip install -r requirements.txt
