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

    # 🕐 Jedes Mal neu berechnen, damit Query immer aktuell ist
    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    window_minutes = st.session_state.get("window_minutes", 15)
    time_threshold = now - timedelta(minutes=window_minutes)

    # CET → ISO mit Offset
    cet = pytz.timezone("Europe/Zurich")
    time_threshold_str = time_threshold.astimezone(cet).isoformat()

    # Debug-Ausgabe (optional)
    # st.write("Mongo Query from:", time_threshold_str, "to", now.isoformat())

    # 🧠 Abfrage: Alle neuen Polar-Werte seit dem Threshold
    polar_data = list(col_polar.find(
        {"timestamp": {"$gte": time_threshold_str}}
    ).sort("timestamp", 1))

    df_polar = pd.DataFrame(polar_data)

    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce", utc=True)
        df_polar["timestamp"] = df_polar["timestamp"].dt.tz_convert("Europe/Zurich")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # === Glucose ===
    time_threshold_utc = (now - timedelta(minutes=window_minutes)).astimezone(pytz.UTC)
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
    """Skaliert Power-Werte (VLF/LF/HF) aus s² in ms² für bessere Lesbarkeit"""
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
        valid = df_polar.dropna(subset=[
            "hr", "hrv_rmssd", "hrv_sdnn", "hrv_nn50", "hrv_pnn50",
            "hrv_stress_index", "hrv_lf_hf_ratio", "hrv_vlf", "hrv_lf", "hrv_hf"
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
            "hrv_stress_index", "hrv_lf_hf_ratio"
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


# === Live Cards (auto-refresh fix for Streamlit 3.13) ===
def render_live_cards(metrics):
    arrow, trend_text = map_direction(metrics.get("glucose_direction"))
    html_id = str(uuid.uuid4())  # unique ID → no cache

    html = f"<div id='{html_id}'></div>" + f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    .metric-container {{display:grid;gap:18px;margin-bottom:24px;font-family:'Inter',sans-serif;}}
    .metric-row-3 {{grid-template-columns:repeat(3,1fr);}}
    .metric-row-5 {{grid-template-columns:repeat(5,1fr);}}
    .metric-card {{position:relative;background:#161a22;border-radius:14px;
        padding:20px 22px 26px 24px;box-shadow:0 4px 16px rgba(0,0,0,0.35),
        inset 0 0 0 1px rgba(255,255,255,0.04);color:#EAECEF;min-height:120px;}}
    .metric-live {{position:absolute;top:10px;right:14px;display:flex;align-items:center;gap:6px;
        font-size:12px;color:#B7F7C4;}}
    .pulse {{width:8px;height:8px;border-radius:50%;background:#2ecc71;
        box-shadow:0 0 6px #2ecc71;animation:pulse 1.5s infinite;}}
    @keyframes pulse {{0%{{opacity:0.3;transform:scale(0.8);}}
        50%{{opacity:1;transform:scale(1.2);}}
        100%{{opacity:0.3;transform:scale(0.8);}}}}
    </style>

    <!-- Reihe 1 -->
    <div class="metric-container metric-row-3">
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>❤️ HEART RATE</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hr'),0)} bpm</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>💗 HRV (RMSSD)</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_rmssd')*1000 if metrics.get('hrv_rmssd') else None,0)} ms</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>🩸 GLUCOSE</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('glucose'),0)} mg/dL</div>
        <div style="font-size:13px;color:#C8CDD6">{arrow} {trend_text}</div>
      </div>
    </div>

    <!-- Reihe 2 -->
    <div class="metric-container metric-row-5">
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>💠 SDNN</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_sdnn')*1000 if metrics.get('hrv_sdnn') else None,0)} ms</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>🔢 NN50</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_nn50'),0)}</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>📊 pNN50</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_pnn50'),1)}%</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>🧠 STRESS INDEX</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_stress_index'),2)}</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>⚡ LF/HF RATIO</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_lf_hf_ratio'),2)}</div>
      </div>
    </div>

    <!-- Reihe 3 -->
    <div class="metric-container metric-row-3">
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>🌊 VLF</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_vlf'),2)}</div>
        <div style="font-size:13px;color:#C8CDD6">Very Low Frequency (slow recovery)</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>⚡ LF</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_lf'),2)}</div>
        <div style="font-size:13px;color:#C8CDD6">Low Frequency (sympathetic)</div>
      </div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>💨 HF</div><div style="font-size:40px;font-weight:700">{safe_format(metrics.get('hrv_hf'),2)}</div>
        <div style="font-size:13px;color:#C8CDD6">High Frequency (parasympathetic)</div>
      </div>
    </div>
    """

   components.html(html, height=980, key=f"live_cards_{uuid.uuid4()}")

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
