import os
from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
from pymongo import MongoClient
import plotly.graph_objects as go
import uuid

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
    time_threshold_str = time_threshold.astimezone(tz).isoformat()

    polar_data = list(col_polar.find({"timestamp": {"$gte": time_threshold_str}}).sort("timestamp", 1))
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce", utc=True)
        df_polar["timestamp"] = df_polar["timestamp"].dt.tz_convert("Europe/Zurich")
        df_polar = df_polar.set_index("timestamp").sort_index()

    time_threshold_utc = time_threshold.astimezone(pytz.UTC)
    glucose_data = list(col_glucose.find({"dateString": {"$gte": time_threshold_utc.isoformat()}}).sort("dateString", 1))
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce", utc=True)
        df_glucose["timestamp"] = df_glucose["timestamp"].dt.tz_convert("Europe/Zurich")
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


# === Mapping & Formatting ===
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


def safe_power(value):
    try:
        if value is None or pd.isna(value):
            return "⏳"

        # fast alle Polar-Power-Werte sind in s² → Umrechnen in ms²
        if value < 1:  
            scaled = value * 1e6
            unit = "ms²"
        else:
            scaled = value
            unit = "a.u."  # falls absolute Einheit
        return f"{scaled:.0f} {unit}"
    except Exception:
        return "⏳"


# === Metrics ===
def compute_metrics(df_polar, df_glucose, window_minutes):
    def sanitize(v):
        if v is None or pd.isna(v) or (isinstance(v, str) and v.lower() in ["na", "n/a", "nan"]):
            return None
        return v

    metrics = {}
    if not df_polar.empty:
        last = df_polar.iloc[-1]
        metrics.update({
            "hr": sanitize(last.get("hr")),
            "hrv_rmssd": sanitize(last.get("hrv_rmssd")),
            "hrv_sdnn": sanitize(last.get("hrv_sdnn")),
            "hrv_nn50": sanitize(last.get("hrv_nn50")),
            "hrv_pnn50": sanitize(last.get("hrv_pnn50")),
            "hrv_stress_index": sanitize(last.get("hrv_stress_index")),
            "hrv_lf_hf_ratio": sanitize(last.get("hrv_lf_hf_ratio")),
            "hrv_vlf": sanitize(last.get("hrv_vlf")),
            "hrv_lf": sanitize(last.get("hrv_lf")),
            "hrv_hf": sanitize(last.get("hrv_hf")),
        })
    else:
        metrics.update({k: None for k in [
            "hr", "hrv_rmssd", "hrv_sdnn", "hrv_nn50", "hrv_pnn50",
            "hrv_stress_index", "hrv_lf_hf_ratio", "hrv_vlf", "hrv_lf", "hrv_hf"
        ]})

    if not df_glucose.empty and "sgv" in df_glucose.columns:
        latest_glucose = sanitize(df_glucose["sgv"].iloc[-1])
        direction = sanitize(df_glucose["direction"].iloc[-1] if "direction" in df_glucose.columns else None)
    else:
        latest_glucose, direction = None, None

    metrics.update({
        "glucose": latest_glucose,
        "glucose_direction": direction
    })
    return metrics


# === Styled Live Cards ===
def render_live_cards(metrics):
    arrow, trend_text = map_direction(metrics.get("glucose_direction"))
    g_val = safe_format(metrics.get("glucose"), 0)

    html = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    .metrics-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        font-family: 'Inter', sans-serif;
        margin-bottom: 24px;
    }}
    .metrics-grid-5 {{
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 14px;
        margin-bottom: 24px;
        font-family: 'Inter', sans-serif;
    }}
    .metric-card {{
        background: #161a22;
        border-radius: 14px;
        padding: 14px 18px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.3),
                    inset 0 0 0 1px rgba(255,255,255,0.05);
        color: #fff;
        transition: all 0.2s ease-in-out;
    }}
    .metric-card:hover {{
        transform: scale(1.02);
        box-shadow: 0 6px 16px rgba(0,0,0,0.45);
    }}
    .metric-label {{
        font-size: 13px;
        color: #aaa;
        margin-bottom: 4px;
        white-space: nowrap;
    }}
    .metric-value {{
        font-size: 22px;
        font-weight: 600;
        color: #fff;
        text-align: left;
    }}
    </style>

    <div class="metrics-grid">
        <div class="metric-card"><div class="metric-label">❤️ Heart Rate (bpm)</div><div class="metric-value">{safe_format(metrics.get("hr"),0)}</div></div>
        <div class="metric-card"><div class="metric-label">💗 HRV (RMSSD, ms)</div><div class="metric-value">{safe_format(metrics.get("hrv_rmssd")*1000 if metrics.get("hrv_rmssd") else None,0)}</div></div>
        <div class="metric-card"><div class="metric-label">🩸 Glucose (mg/dL)</div><div class="metric-value">{g_val} {arrow} {trend_text}</div></div>
    </div>

    <div class="metrics-grid-5">
        <div class="metric-card"><div class="metric-label">💠 SDNN (ms)</div><div class="metric-value">{safe_format(metrics.get("hrv_sdnn")*1000 if metrics.get("hrv_sdnn") else None,0)}</div></div>
        <div class="metric-card"><div class="metric-label">🔢 NN50</div><div class="metric-value">{safe_format(metrics.get("hrv_nn50"),0)}</div></div>
        <div class="metric-card"><div class="metric-label">📊 pNN50 (%)</div><div class="metric-value">{safe_format(metrics.get("hrv_pnn50"),0)}</div></div>
        <div class="metric-card"><div class="metric-label">🧠 Stress Index</div><div class="metric-value">{safe_format(metrics.get("hrv_stress_index"),0)}</div></div>
        <div class="metric-card"><div class="metric-label">⚡ LF/HF Ratio</div><div class="metric-value">{safe_format(metrics.get("hrv_lf_hf_ratio"),2)}</div></div>
    </div>

    <div class="metrics-grid">
        <div class="metric-card"><div class="metric-label">🌊 VLF Power</div><div class="metric-value">{safe_power(metrics.get("hrv_vlf"))}</div></div>
        <div class="metric-card"><div class="metric-label">⚡ LF Power</div><div class="metric-value">{safe_power(metrics.get("hrv_lf"))}</div></div>
        <div class="metric-card"><div class="metric-label">💨 HF Power</div><div class="metric-value">{safe_power(metrics.get("hrv_hf"))}</div></div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# === Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()
    y_min, y_max = (40, 180)
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 20), min(250, g_max + 20)

    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
            name="Heart Rate (bpm)", mode="lines", line=dict(color="#e74c3c", width=2), yaxis="y"))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000,
            name="HRV RMSSD (ms)", mode="lines", line=dict(color="#2980b9", width=2), yaxis="y2"))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
            name="Glucose (mg/dL)", mode="lines", line=dict(color="#27ae60", width=3), yaxis="y3"))

    fig.update_layout(
        template="plotly_dark",
        height=460,
        margin=dict(l=60, r=90, t=40, b=60),
        xaxis=dict(title="Time"),
        yaxis=dict(title=dict(text="Heart Rate (bpm)", font=dict(color="#e74c3c")),
                   tickfont=dict(color="#e74c3c")),
        yaxis2=dict(title=dict(text="HRV (ms)", font=dict(color="#2980b9")),
                    tickfont=dict(color="#2980b9"),
                    overlaying="y", side="right", position=0.93),
        yaxis3=dict(title=dict(text="Glucose (mg/dL)", font=dict(color="#27ae60")),
                    tickfont=dict(color="#27ae60"),
                    overlaying="y", side="right", position=1.0,
                    range=[y_min, y_max]),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5)
    )
    return fig


# === Main ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="🧪", layout="wide")
    if st_autorefresh:
        st_autorefresh(interval=2000, key="live_refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#AAA;'>Last Update: {now.strftime('%H:%M:%S')} (local)</div>", unsafe_allow_html=True)

    st.sidebar.header("Settings")
    window_minutes = st.sidebar.slider("Window (minutes)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)
    render_live_cards(metrics)

    st.subheader(f"Combined Signals — last {window_minutes} minutes")
    if not df_polar.empty or not df_glucose.empty:
        st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)

    if not df_polar.empty:
        st.subheader("Recent Polar Samples")
        st.dataframe(df_polar.tail(10))
    if not df_glucose.empty:
        st.subheader("Recent CGM Samples")
        st.dataframe(df_glucose.tail(10))


if __name__ == "__main__":
    main()
