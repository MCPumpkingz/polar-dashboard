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

    latest_glucose = glucose_delta = direction = None
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        latest_glucose = df_glucose["sgv"].iloc[-1]
        if len(df_glucose) >= 2:
            sgv_diff = df_glucose["sgv"].iloc[-1] - df_glucose["sgv"].iloc[-2]
            time_diff = (df_glucose.index[-1] - df_glucose.index[-2]).total_seconds() / 60
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


def safe_format(value, decimals=0):
    try:
        if value is None or pd.isna(value):
            return "–"
        return f"{value:.{decimals}f}"
    except Exception:
        return "–"


# === Combined Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()
    y_min, y_max = (40, 180)
    if not df_glucose.empty:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 20), min(250, g_max + 20)

    if "hr" in df_polar:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], name="Heart Rate (bpm)",
                                 mode="lines", line=dict(color="#e74c3c", width=2)))
    if "hrv_rmssd" in df_polar:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000, name="HRV RMSSD (ms)",
                                 mode="lines", line=dict(color="#2980b9", width=2)))
    if "sgv" in df_glucose:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], name="Glucose (mg/dL)",
                                 mode="lines", line=dict(color="#27ae60", width=3)))

    fig.update_layout(template="plotly_dark", height=460,
                      margin=dict(l=60, r=90, t=40, b=60),
                      xaxis=dict(title="Time"),
                      yaxis=dict(title=dict(text="Heart Rate (bpm)", font=dict(color="#e74c3c")),
                                 tickfont=dict(color="#e74c3c")),
                      yaxis2=dict(title=dict(text="HRV (ms)", font=dict(color="#2980b9")),
                                  overlaying="y", side="right", tickfont=dict(color="#2980b9"),
                                  position=0.93, showgrid=False),
                      yaxis3=dict(title=dict(text="Glucose (mg/dL)", font=dict(color="#27ae60")),
                                  overlaying="y", side="right", tickfont=dict(color="#27ae60"),
                                  position=1.0, range=[y_min, y_max], showgrid=False),
                      legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5))
    return fig


# === MAIN APP ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", layout="wide")

    if st_autorefresh:
        st_autorefresh(interval=2000, key="refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)

    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#AAA;'>Last Update: {now.strftime('%H:%M:%S')} (local)</div>",
                unsafe_allow_html=True)

    window_minutes = st.sidebar.slider("Window (minutes)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)
    hr, hrv, gl = metrics["avg_hr_60s"], metrics["avg_rmssd_60s"], metrics["latest_glucose"]
    delta_gl = metrics["glucose_delta"]
    dir_arrow, dir_text = map_direction(metrics["glucose_direction"])

    # === METRIC CARDS (original design) ===
    html = f"""
    <style>
        .metric-container {{
            display: flex; justify-content: space-between; gap: 20px; margin-bottom: 28px;
        }}
        .metric-card {{
            flex: 1; background: #12141C; border-radius: 14px; padding: 22px 24px; 
            box-shadow: 0 4px 16px rgba(0,0,0,0.4), inset 0 0 0 1px rgba(255,255,255,0.05);
            position: relative; color: #F3F4F6;
        }}
        .metric-card::before {{
            content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; border-radius: 14px 0 0 14px;
        }}
        .red::before {{ background: #e74c3c; }}
        .blue::before {{ background: #2980b9; }}
        .green::before {{ background: #27ae60; }}
        .metric-header {{ font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; color: #aaa; }}
        .metric-value {{ font-size: 42px; font-weight: 700; color: white; }}
        .metric-delta {{ font-size: 13px; color: #ccc; }}
    </style>

    <div class="metric-container">
        <div class="metric-card red">
            <div class="metric-header">❤️ HEART RATE</div>
            <div class="metric-value">{safe_format(hr, 0)} bpm</div>
        </div>
        <div class="metric-card blue">
            <div class="metric-header">💓 HRV (RMSSD)</div>
            <div class="metric-value">{safe_format(hrv * 1000 if hrv else None, 0)} ms</div>
        </div>
        <div class="metric-card green">
            <div class="metric-header">🩸 GLUCOSE</div>
            <div class="metric-value">{safe_format(gl, 0)} mg/dL</div>
            <div class="metric-delta">{dir_arrow} {dir_text} ({safe_format(delta_gl, 1)} mg/dL/min)</div>
        </div>
    </div>
    """
    components.html(html, height=230)

    # === Combined Chart ===
    st.subheader("Combined Signals")
    st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)

    # === HR Chart ===
    if not df_polar.empty and "hr" in df_polar.columns:
        st.subheader("Heart Rate (bpm)")
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
                                    mode="lines", line=dict(color="#e74c3c", width=2)))
        fig_hr.update_layout(template="plotly_dark", height=300, margin=dict(l=40, r=40, t=30, b=40))
        st.plotly_chart(fig_hr, use_container_width=True)

    # === HRV Chart ===
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        st.subheader("HRV (RMSSD, ms)")
        fig_hrv = go.Figure()
        fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000,
                                     mode="lines", line=dict(color="#2980b9", width=2)))
        fig_hrv.update_layout(template="plotly_dark", height=300, margin=dict(l=40, r=40, t=30, b=40))
        st.plotly_chart(fig_hrv, use_container_width=True)

    # === Glucose Chart ===
    if not df_glucose.empty:
        st.subheader("Glucose (CGM)")
        fig_gl = go.Figure()
        fig_gl.add_shape(type="rect", xref="paper", x0=0, x1=1,
                         yref="y", y0=70, y1=140,
                         fillcolor="rgba(46,204,113,0.18)", line=dict(width=0), layer="below")
        fig_gl.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                    mode="lines+markers",
                                    line=dict(color="#27ae60", width=2),
                                    marker=dict(size=4)))
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y0, y1 = min(50, g_min - 20), max(180, g_max + 40)
        fig_gl.update_layout(template="plotly_dark", height=350,
                             margin=dict(l=40, r=40, t=10, b=40),
                             yaxis=dict(range=[y0, y1], title="Glucose (mg/dL)"))
        st.plotly_chart(fig_gl, use_container_width=True)

    # === Tables ===
    st.subheader("Latest Data Samples")
    col1, col2 = st.columns(2)
    if not df_polar.empty:
        with col1:
            st.markdown("**Polar Data (last 5 entries)**")
            st.dataframe(df_polar.tail(5)[["hr", "hrv_rmssd"]])
    if not df_glucose.empty:
        with col2:
            st.markdown("**Glucose Data (last 5 entries)**")
            cols = ["sgv", "direction"] if "direction" in df_glucose.columns else ["sgv"]
            st.dataframe(df_glucose.tail(5)[cols])


if __name__ == "__main__":
    main()
