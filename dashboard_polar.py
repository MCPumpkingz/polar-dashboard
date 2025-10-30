import os
from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
import streamlit.components.v1 as components
from pymongo import MongoClient
import plotly.graph_objects as go

# === Auto-Refresh (every 2s) ===
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

    # Polar data
    polar_data = list(col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort("timestamp", 1))
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # Glucose data
    time_threshold_utc = (now - timedelta(minutes=window_minutes)).astimezone(pytz.UTC)
    glucose_data = list(col_glucose.find({"dateString": {"$gte": time_threshold_utc.isoformat()}}).sort("dateString", 1))
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


# === Metrics ===
def compute_metrics(df_polar, df_glucose, window_minutes):
    metrics = {}

    if not df_polar.empty:
        try:
            recent_data = df_polar.last("60s")
        except Exception:
            recent_data = df_polar.tail(1)
        try:
            long_window = df_polar.last(f"{window_minutes}min")
        except Exception:
            long_window = df_polar

        avg_hr_60s = recent_data["hr"].mean() if "hr" in df_polar.columns else None
        avg_hr_long = long_window["hr"].mean() if "hr" in df_polar.columns else None
        delta_hr = (avg_hr_60s - avg_hr_long) if avg_hr_60s and avg_hr_long else None

        avg_rmssd_60s = recent_data["hrv_rmssd"].mean() if "hrv_rmssd" in df_polar.columns else None
        avg_rmssd_long = long_window["hrv_rmssd"].mean() if "hrv_rmssd" in df_polar.columns else None
        delta_rmssd = ((avg_rmssd_60s - avg_rmssd_long) * 1000) if avg_rmssd_60s and avg_rmssd_long else None
    else:
        avg_hr_60s = avg_hr_long = delta_hr = avg_rmssd_60s = avg_rmssd_long = delta_rmssd = None

    # Glucose
    latest_glucose = None
    glucose_delta = 0.0
    direction = None
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        latest_glucose = df_glucose["sgv"].iloc[-1]
        if len(df_glucose) >= 2:
            sgv_diff = df_glucose["sgv"].iloc[-1] - df_glucose["sgv"].iloc[-2]
            time_diff = (df_glucose.index[-1] - df_glucose.index[-2]).total_seconds() / 60.0
            if time_diff > 0:
                glucose_delta = sgv_diff / time_diff
        direction = df_glucose["direction"].iloc[-1] if "direction" in df_glucose.columns else None

    metrics.update({
        "avg_hr_60s": avg_hr_60s,
        "delta_hr": delta_hr,
        "avg_rmssd_60s": avg_rmssd_60s,
        "delta_rmssd": delta_rmssd,
        "latest_glucose": latest_glucose,
        "glucose_delta": glucose_delta,
        "glucose_direction": direction
    })
    return metrics


# === Safe formatting ===
def safe_format(value, decimals=0):
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "–"
        return f"{value:.{decimals}f}"
    except Exception:
        return "–"


# === Combined Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()
    y_min, y_max = (40, 180)
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 20), min(250, g_max + 20)

    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
                                 name="Heart Rate (bpm)", mode="lines",
                                 line=dict(color="#e74c3c", width=2), yaxis="y"))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000,
                                 name="HRV RMSSD (ms)", mode="lines",
                                 line=dict(color="#2980b9", width=2), yaxis="y2"))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                 name="Glucose (mg/dL)", mode="lines",
                                 line=dict(color="#27ae60", width=3), yaxis="y3"))

    fig.update_layout(template="plotly_dark", height=460, margin=dict(l=60, r=90, t=40, b=60),
                      xaxis=dict(title="Time"),
                      yaxis=dict(title=dict(text="Heart Rate (bpm)", font=dict(color="#e74c3c")),
                                 tickfont=dict(color="#e74c3c")),
                      yaxis2=dict(title=dict(text="HRV (ms)", font=dict(color="#2980b9")),
                                  tickfont=dict(color="#2980b9"), overlaying="y", side="right", position=0.93),
                      yaxis3=dict(title=dict(text="Glucose (mg/dL)", font=dict(color="#27ae60")),
                                  tickfont=dict(color="#27ae60"), overlaying="y", side="right", position=1.0,
                                  range=[y_min, y_max]),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5))
    return fig


# === Live Cards ===
def render_live_cards(hr, delta_hr, hrv, delta_hrv, gl, gl_delta, gl_dir, window_minutes):
    arrow, trend_text = map_direction(gl_dir)
    html = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    .metric-container {{
        display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; margin-bottom: 24px;
        font-family: 'Inter', sans-serif;
    }}
    .metric-card {{
        position: relative; background: #161a22; border-radius: 14px;
        padding: 20px 22px 26px 24px; box-shadow: 0 4px 16px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.04);
        color: #EAECEF;
    }}
    .metric-live {{
        position: absolute; top: 10px; right: 14px; display: flex; align-items: center;
        gap: 6px; font-size: 12px; color: #B7F7C4;
    }}
    .pulse {{
        width: 8px; height: 8px; border-radius: 50%; background: #2ecc71;
        box-shadow: 0 0 6px #2ecc71; animation: pulse 1.5s infinite;
    }}
    @keyframes pulse {{
        0% {{ opacity: 0.3; transform: scale(0.8); }}
        50% {{ opacity: 1; transform: scale(1.2); }}
        100% {{ opacity: 0.3; transform: scale(0.8); }}
    }}
    </style>
    <div class="metric-container">
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>❤️ HEART RATE</div><div style="font-size:40px;font-weight:700">{safe_format(hr,0)} bpm</div>
        <div style="font-size:13px;color:#C8CDD6">{'↑' if (delta_hr or 0)>0 else '↓' if (delta_hr or 0)<0 else '→'} {safe_format(delta_hr,1)} vs mean({window_minutes}m)</div></div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>💗 HRV (RMSSD)</div><div style="font-size:40px;font-weight:700">{safe_format((hrv*1000) if hrv else None,0)} ms</div>
        <div style="font-size:13px;color:#C8CDD6">{'↑' if (delta_hrv or 0)>0 else '↓' if (delta_hrv or 0)<0 else '→'} {safe_format(delta_hrv,1)} vs mean({window_minutes}m)</div></div>
      <div class="metric-card"><div class="metric-live"><div class="pulse"></div>Live</div>
        <div>🩸 GLUCOSE</div><div style="font-size:40px;font-weight:700">{safe_format(gl,0)} mg/dL</div>
        <div style="font-size:13px;color:#C8CDD6">{arrow} {trend_text} ({safe_format(gl_delta,1)} mg/dL/min)</div></div>
    </div>"""
    components.html(html, height=230)


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

    # 1️⃣ Live Cards
    render_live_cards(metrics["avg_hr_60s"], metrics["delta_hr"],
                      metrics["avg_rmssd_60s"], metrics["delta_rmssd"],
                      metrics["latest_glucose"], metrics["glucose_delta"],
                      metrics["glucose_direction"], window_minutes)

    # 2️⃣ Combined Chart
    st.subheader(f"Combined Signals — last {window_minutes} minutes")
    if not df_polar.empty or not df_glucose.empty:
        st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)

    # 3️⃣ HR Chart
    if not df_polar.empty and "hr" in df_polar.columns:
        st.subheader("Heart Rate (HR)")
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
                                    mode="lines", line=dict(color="#e74c3c", width=2),
                                    name="HR (bpm)"))
        fig_hr.update_layout(template="plotly_dark", margin=dict(l=0, r=0, t=10, b=0),
                             height=300, yaxis=dict(title="bpm"))
        st.plotly_chart(fig_hr, use_container_width=True)

    # 4️⃣ HRV Chart (RMSSD + SDNN)
    if not df_polar.empty and ("hrv_rmssd" in df_polar.columns or "hrv_sdnn" in df_polar.columns):
        st.subheader("HRV (RMSSD & SDNN)")
        fig_hrv = go.Figure()
        if "hrv_rmssd" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000,
                                         mode="lines", line=dict(color="#2980b9", width=2),
                                         name="RMSSD (ms)"))
        if "hrv_sdnn" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"]*1000,
                                         mode="lines", line=dict(color="#5dade2", width=2, dash="dot"),
                                         name="SDNN (ms)"))
        fig_hrv.update_layout(template="plotly_dark", height=300,
                              margin=dict(l=0, r=0, t=10, b=0),
                              yaxis=dict(title="ms"))
        st.plotly_chart(fig_hrv, use_container_width=True)

    # 5️⃣ Glucose Chart
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        st.subheader("Glucose (CGM)")
        fig_gl = go.Figure()
        fig_gl.add_shape(type="rect", xref="paper", x0=0, x1=1,
                         yref="y", y0=70, y1=140,
                         fillcolor="rgba(46,204,113,0.18)", line=dict(width=0))
        fig_gl.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                    mode="lines+markers", line=dict(color="#27ae60", width=2),
                                    marker=dict(size=4), name="Glucose (mg/dL)"))
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        fig_gl.update_layout(template="plotly_dark", height=300,
                             margin=dict(l=0, r=0, t=10, b=0),
                             yaxis=dict(range=[min(60, g_min-10), max(160, g_max+15)], title="mg/dL"))
        st.plotly_chart(fig_gl, use_container_width=True)

    # 6️⃣ Tables
    if not df_polar.empty:
        st.subheader("Recent Polar Samples")
        st.dataframe(df_polar.tail(10))
    if not df_glucose.empty:
        st.subheader("Recent CGM Samples")
        st.dataframe(df_glucose.tail(10))


if __name__ == "__main__":
    main()
