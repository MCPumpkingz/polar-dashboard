import os
from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
from pymongo import MongoClient
import plotly.graph_objects as go

try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    st_autorefresh = None


# === MongoDB Connection ===
def connect_to_mongo():
    MONGO_URI = os.getenv("MONGO_URI") or \
        "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/?retryWrites=true&w=majority"
    client = MongoClient(MONGO_URI)

    db_polar = client["nightscout-db"]
    db_glucose = client["nightscout"]

    col_polar = db_polar["polar_data"]
    col_glucose = db_glucose["entries"]

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    window_minutes = st.session_state.get("window_minutes", 15)
    time_threshold = now - timedelta(minutes=window_minutes)

    polar_data = list(
        col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}})
        .sort("timestamp", 1)
    )
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], utc=True)
        df_polar = df_polar.set_index("timestamp").tz_convert("Europe/Zurich")

    glucose_data = list(
        col_glucose.find({"dateString": {"$gte": time_threshold.astimezone(pytz.UTC).isoformat()}})
        .sort("dateString", 1)
    )
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], utc=True)
        df_glucose = df_glucose.set_index("timestamp").tz_convert("Europe/Zurich")

    return df_polar, df_glucose


# === Helpers ===
def map_direction(direction):
    mapping = {
        "DoubleUp": ("⬆️⬆️", "rising fast"),
        "SingleUp": ("⬆️", "rising"),
        "FortyFiveUp": ("↗️", "rising slightly"),
        "Flat": ("→", "stable"),
        "FortyFiveDown": ("↘️", "falling slightly"),
        "SingleDown": ("⬇️", "falling"),
        "DoubleDown": ("⬇️⬇️", "falling fast"),
    }
    return mapping.get(direction, ("→", "stable"))


def safe_format(value, decimals=0):
    try:
        if value is None or pd.isna(value):
            return "⏳"
        return f"{value:.{decimals}f}"
    except Exception:
        return "⏳"


# === Metrics ===
def compute_metrics(df_polar, df_glucose):
    metrics = {}

    if not df_polar.empty:
        last = df_polar.iloc[-1]
        metrics["hr"] = last.get("hr")
        metrics["hrv_rmssd"] = last.get("hrv_rmssd")

        # ---- kept for later use, but not shown ----
        # metrics["hrv_sdnn"] = last.get("hrv_sdnn")
        # metrics["hrv_nn50"] = last.get("hrv_nn50")
        # metrics["hrv_pnn50"] = last.get("hrv_pnn50")
        # metrics["hrv_stress_index"] = last.get("hrv_stress_index")
        # metrics["hrv_lf_hf_ratio"] = last.get("hrv_lf_hf_ratio")
        # metrics["hrv_vlf"] = last.get("hrv_vlf")
        # metrics["hrv_lf"] = last.get("hrv_lf")
        # metrics["hrv_hf"] = last.get("hrv_hf")
    else:
        metrics["hr"] = None
        metrics["hrv_rmssd"] = None

    if not df_glucose.empty and "sgv" in df_glucose.columns:
        metrics["glucose"] = df_glucose["sgv"].iloc[-1]
        metrics["glucose_direction"] = df_glucose.get("direction", pd.Series([None])).iloc[-1]
    else:
        metrics["glucose"] = None
        metrics["glucose_direction"] = None

    return metrics


# === Top Cards (ONLY HR / HRV / Glucose) ===
def render_live_cards(metrics):
    arrow, trend_text = map_direction(metrics.get("glucose_direction"))

    html = f"""
    <style>
    .metrics-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        margin-bottom: 24px;
    }}
    .metric-card {{
        background: #161a22;
        border-radius: 14px;
        padding: 14px 18px;
        color: #fff;
    }}
    .metric-label {{
        font-size: 13px;
        color: #aaa;
    }}
    .metric-value {{
        font-size: 22px;
        font-weight: 600;
    }}
    </style>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">❤️ Heart Rate (bpm)</div>
            <div class="metric-value">{safe_format(metrics.get("hr"),0)}</div>
        </div>

        <div class="metric-card">
            <div class="metric-label">💗 HRV (RMSSD, ms)</div>
            <div class="metric-value">{safe_format(metrics.get("hrv_rmssd")*1000 if metrics.get("hrv_rmssd") else None,0)}</div>
        </div>

        <div class="metric-card">
            <div class="metric-label">🩸 Glucose (mg/dL)</div>
            <div class="metric-value">{safe_format(metrics.get("glucose"),0)} {arrow} {trend_text}</div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# === Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()

    if not df_polar.empty:
        fig.add_trace(go.Scatter(
            x=df_polar.index,
            y=df_polar["hr"],
            name="Heart Rate (bpm)",
            line=dict(color="#e74c3c", width=2)
        ))

        fig.add_trace(go.Scatter(
            x=df_polar.index,
            y=df_polar["hrv_rmssd"] * 1000,
            name="HRV RMSSD (ms)",
            yaxis="y2",
            line=dict(color="#2980b9", width=2)
        ))

    if not df_glucose.empty:
        fig.add_trace(go.Scatter(
            x=df_glucose.index,
            y=df_glucose["sgv"],
            name="Glucose (mg/dL)",
            yaxis="y3",
            line=dict(color="#27ae60", width=3)
        ))

    fig.update_layout(
        template="plotly_dark",
        height=460,
        xaxis=dict(title="Time"),
        yaxis=dict(title="Heart Rate (bpm)"),
        yaxis2=dict(overlaying="y", side="right", title="HRV (ms)", position=0.92),
        yaxis3=dict(overlaying="y", side="right", title="Glucose (mg/dL)", position=1.0),
        legend=dict(orientation="h", y=-0.25)
    )

    return fig


# === Main ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", layout="wide")

    if st_autorefresh:
        st_autorefresh(interval=2000, key="live_refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)

    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(
        """
        <div style="color:#888; font-size:14px; margin-top:-8px; margin-bottom:12px;">
        Part of the MAS ETH thesis <em>“Development of a Biofeedback System for Blood Glucose Regulation 
        through Personalized Breathing Techniques”</em><br>
        Marco Cocuzza · MAS ETH in Applied Technology · Supervisor: Prof. Dr. Sarah Meissner · 2025
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        f"<div style='text-align:right;color:#AAA;'>Last Update: {now.strftime('%H:%M:%S')} (local)</div>",
        unsafe_allow_html=True
    )

    st.sidebar.header("Settings")
    st.session_state["window_minutes"] = st.sidebar.slider("Window (minutes)", 5, 60, 15)

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose)

    render_live_cards(metrics)

    st.subheader("Combined Signals — last 15 minutes")
    st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)


if __name__ == "__main__":
    main()
