🗺️ Tennessee Property Map App

A Streamlit-based analytics application for analyzing off-market real estate deals across Tennessee, with a focus on pricing discipline, conversion performance, and county-level profitability.

📌 What It Does

Deal & Market Analysis
- Visualizes off-market property deals on an interactive county map of Tennessee
- Breaks down deal volume by Sold vs Cut Loose status
- Surfaces conversion rates, pricing distributions, and deal outcomes by county

Profitability & Performance Metrics
- Computes total and average gross profit (GP) by county
- Ranks counties and buyers based on deal performance
- Highlights pricing thresholds that correlate with higher close rates

Admin / Sales Manager Insights
- Gated admin view for advanced analytics
- County-level GP summaries and rankings
- Buyer performance context and acquisition guidance
- Foundation for rep scorecards tied to pricing discipline

Data Reliability & Usability
- Normalizes and validates incoming data on load to prevent missing-column errors
- Caches data loading for faster app performance
- Provides fast lookup tools for county-level deal context

Direction & Roadmap
The app is actively evolving toward:
- Hard pricing thresholds by county
- Rep scorecards based on discipline vs outcomes
- Deeper conversion analysis by price band
- Mobile-friendly and responsive layouts

🛠️ How It’s Built
Tech Stack

Python
- Streamlit for UI and app state
- Pandas for data manipulation and aggregation
- Folium for interactive map rendering
- GeoJSON for Tennessee county boundaries

Architecture Overview
The app follows a modular, service-oriented structure:
- app.py
    Thin entrypoint responsible only for bootstrapping the app and routing control flow.
- app_controller.py
    Main orchestration layer that wires together data, services, and views without heavy business logic.
- data.py
    Handles data loading, caching, and normalization to ensure consistent schemas across the app.
- controller_services.py
    Core business logic and aggregations (deal counts, rankings, GP metrics).
- map_view.py
    Isolated rendering logic for the interactive county map and detail panels.
- filters.py / controls.py / ui_sidebar.py
    UI components and filtering logic, kept separate from data computation.
- admin.py / admin_view.py
    Admin authentication and gated analytics views.

Design Principles
- Thin controllers, fat services – business logic lives outside UI code
- Single-source normalization – all schema cleanup happens once at load
- Cache-first data access – expensive operations are cached where possible
- Explicit separation of concerns – UI, data, and analytics are isolated

Current Technical Focus
- Consolidating duplicated metrics into single source-of-truth services
- Optimizing pandas aggregations for larger datasets
- Hardening admin authentication and session handling
- Improving responsiveness and mobile usability
