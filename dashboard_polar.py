import os
from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
import streamlit.components.v1 as components
from pymongo import MongoClient
import plotly.graph_objects as go
import uuid

# === Auto-Refresh (every 2 s) ===
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

    # 🕐 Immer aktueller Zeitbereich
    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    window_minutes = st.session_state.get("window_minutes", 15)
    time_threshold = now - timedelta(minutes=window_minutes)

    # CET → ISO mit Offset
    cet = pytz.timezone("Europe/Zurich")
    time_threshold_str = time_threshold.astimezone(cet).isoformat()

    # === Polar ===
    polar_data = list(col_polar.find(
        {"timestamp": {"$gte": time_threshold_str}}
    ).sort("timestamp", 1))
    df_polar = pd.DataFrame(polar_data)

    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce", utc=True)
        df_polar["timestamp"] = df_polar["timestamp"].dt.tz_convert("Europe/Zurich")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # === Glucose ===
    time_threshold_utc = time_threshold.astimezone(pytz.UTC)
    glucose_data = list(col_glucose.find(
        {"dateString": {"$gte": time_threshold_utc.isoformat()}}
    ).sort("dateString", 1))
    df_glucose = pd.DataFrame(glucose_data)

    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce", utc=True)
        df_glucose["timestamp"] = df_glucose["timestamp"].dt.tz_convert("Europe/Zurich")
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


# === Direction Mapping ===
def map_direction(direction):
    mapping = {
        "DoubleUp": ("⬆️⬆️", "rising fast"),
        "SingleUp": ("⬆️", "rising"),
        "FortyFiveUp": ("↗️", "rising slightly"),
        "Flat": ("→", "stable"),
        "FortyFiveDown": ("↘️", "falling slightly"),
        "SingleDown": ("⬇️", "falling"),
        "DoubleDown": ("⬇️⬇️", "falling fast")
    }
    return mapping.get(direction, ("→", "stable"))


# === Safe formatting ===
def safe_format(value, decimals=0):
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "–"
        return f"{value:.{decimals}f}"
    except Exception:
        return "–"


def safe_power(value):
    try:
        if value is None or pd.isna(value):
            return "–"
        return f"{value * 1e6:.2f}"
    except Exception:
        return "–"


# === Metrics ===
def compute_metrics(df_polar, df_glucose, window_minutes):
    metrics = {}

    if not df_polar.empty:
        # ❗ VLF, LF, HF weglassen, damit Live-Update sofort läuft
        valid = df_polar.dropna(subset=[
            "hr", "hrv_rmssd", "hrv_sdnn", "hrv_nn50",
            "hrv_pnn50", "hrv_stress_index", "hrv_lf_hf_ratio"
        ])

        last_entry = valid.tail(1).iloc[0] if not valid.empty else df_polar.tail(1).iloc[0]
        metrics.update({
            "hr": last_entry.get("hr"),
            "hrv_rmssd": last_entry.get("hrv_rmssd"),
            "hrv_sdnn": last_entry.get("hrv_sdnn"),
            "hrv_nn50": last_entry.get("hrv_nn50"),
            "hrv_pnn50": last_entry.get("hrv_pnn50"),
            "hrv_stress_index": last_entry.get("hrv_stress_index"),
            "hrv_lf_hf_ratio": last_entry.get("hrv_lf_hf_ratio"),
            "hrv_vlf": last_entry.get("hrv_vlf"),
            "hrv_lf": last_entry.get("hrv_lf"),
            "hrv_hf": last_entry.get("hrv_hf"),
        })
    else:
        metrics.update({k: None for k in [
            "hr", "hrv_rmssd", "hrv_sdnn", "hrv_nn50", "hrv_pnn50",
            "hrv_stress_index", "hrv_lf_hf_ratio", "hrv_vlf", "hrv_lf", "hrv_hf"
        ]})

    if not df_glucose.empty and "sgv" in df_glucose.columns:
        latest_glucose = df_glucose["sgv"].iloc[-1]
        direction = df_glucose["direction"].iloc[-1] if "direction" in df_glucose.columns else None
    else:
        latest_glucose, direction = None, None

    metrics.update({
        "glucose": latest_glucose,
        "glucose_direction": direction
    })

    return metrics


# === Combined Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()
    y_min, y_max = (40, 180)
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 20), min(250, g_max + 20)

    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hr"],
            name="Heart Rate (bpm)", mode="lines",
            line=dict(color="#e74c3c", width=2), yaxis="y"
        ))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000,
            name="HRV RMSSD (ms)", mode="lines",
            line=dict(color="#2980b9", width=2), yaxis="y2"
        ))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(
            x=df_glucose.index, y=df_glucose["sgv"],
            name="Glucose (mg/dL)", mode="lines",
            line=dict(color="#27ae60", width=3), yaxis="y3"
        ))

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


def render_live_cards(metrics):
    """Render the live metric cards in native Streamlit (auto-refresh compatible)."""
    arrow, trend_text = map_direction(metrics.get("glucose_direction"))

    st.markdown("### 🔴 Live Biofeedback Metrics")
    st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    # === Reihe 1: Hauptmetriken ===
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("❤️ Heart Rate (bpm)", safe_format(metrics.get("hr"), 0))
    with col2:
        st.metric("💗 HRV (RMSSD, ms)", safe_format(metrics.get("hrv_rmssd") * 1000 if metrics.get("hrv_rmssd") else None, 0))
    with col3:
        st.metric("🩸 Glucose (mg/dL)", safe_format(metrics.get("glucose"), 0), f"{arrow} {trend_text}")

    # === Reihe 2: Sekundärmetriken ===
    col4, col5, col6, col7, col8 = st.columns(5)
    with col4:
        st.metric("💠 SDNN (ms)", safe_format(metrics.get("hrv_sdnn") * 1000 if metrics.get("hrv_sdnn") else None, 0))
    with col5:
        st.metric("🔢 NN50", safe_format(metrics.get("hrv_nn50"), 0))
    with col6:
        st.metric("📊 pNN50 (%)", safe_format(metrics.get("hrv_pnn50"), 1))
    with col7:
        st.metric("🧠 Stress Index", safe_format(metrics.get("hrv_stress_index"), 2))
    with col8:
        st.metric("⚡ LF/HF Ratio", safe_format(metrics.get("hrv_lf_hf_ratio"), 2))

    # === Reihe 3: Frequenzbereich (VLF, LF, HF) ===
    col9, col10, col11 = st.columns(3)
    with col9:
        st.metric("🌊 VLF", safe_format(metrics.get("hrv_vlf"), 2))
    with col10:
        st.metric("⚡ LF", safe_format(metrics.get("hrv_lf"), 2))
    with col11:
        st.metric("💨 HF", safe_format(metrics.get("hrv_hf"), 2))

    # === Hinweis, wenn FFT-Daten noch nicht da sind ===
    if pd.isna(metrics.get("hrv_vlf")) or pd.isna(metrics.get("hrv_lf")) or pd.isna(metrics.get("hrv_hf")):
        st.info("⚙️ Frequency-domain HRV (LF/HF/VLF) initializing… please wait ~3 min for full data.")


# === Main App ===
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
