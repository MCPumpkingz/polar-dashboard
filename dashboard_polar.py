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

    # Polar metrics
    if not df_polar.empty:
        try:
            recent_data = df_polar.last("60s")
        except Exception:
            recent_data = df_polar.tail(1)
        try:
            long_window = df_polar.last(f"{window_minutes}min")
        except Exception:
            long_window = df_polar

        avg_hr_60s = recent_data["hr"].mean() if "hr" in df_polar.columns and not recent_data.empty else None
        avg_hr_long = long_window["hr"].mean() if "hr" in df_polar.columns and not long_window.empty else None
        delta_hr = (avg_hr_60s - avg_hr_long) if (avg_hr_60s is not None and avg_hr_long is not None) else None

        avg_rmssd_60s = recent_data["hrv_rmssd"].mean() if "hrv_rmssd" in df_polar.columns and not recent_data.empty else None
        avg_rmssd_long = long_window["hrv_rmssd"].mean() if "hrv_rmssd" in df_polar.columns and not long_window.empty else None
        delta_rmssd = ((avg_rmssd_60s - avg_rmssd_long) * 1000) if (
            avg_rmssd_60s is not None and avg_rmssd_long is not None
        ) else None
    else:
        avg_hr_60s = avg_hr_long = delta_hr = avg_rmssd_60s = avg_rmssd_long = delta_rmssd = None

    # Glucose metrics
    latest_glucose = None
    glucose_delta = 0
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


# === Combined Plot (fixed layout) ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()

    # Y-range auto-adapted to glucose
    y_min, y_max = (40, 180)
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 20), min(250, g_max + 20)

    # Add signals
    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hr"], name="Heart Rate (bpm)",
            mode="lines", line=dict(color="#e74c3c", width=2), yaxis="y"
        ))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000, name="HRV RMSSD (ms)",
            mode="lines", line=dict(color="#2980b9", width=2), yaxis="y2"
        ))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(
            x=df_glucose.index, y=df_glucose["sgv"], name="Glucose (mg/dL)",
            mode="lines", line=dict(color="#27ae60", width=3), yaxis="y3"
        ))

    # Layout — corrected (no titlefont!)
    fig.update_layout(
        template="plotly_dark",
        height=460,
        margin=dict(l=60, r=90, t=40, b=60),
        xaxis=dict(title="Time"),
        yaxis=dict(
            title=dict(text="Heart Rate (bpm)", font=dict(color="#e74c3c")),
            tickfont=dict(color="#e74c3c"),
            position=0.0
        ),
        yaxis2=dict(
            title=dict(text="HRV (ms)", font=dict(color="#2980b9")),
            tickfont=dict(color="#2980b9"),
            overlaying="y",
            side="right",
            position=0.93,
            showgrid=False
        ),
        yaxis3=dict(
            title=dict(text="Glucose (mg/dL)", font=dict(color="#27ae60")),
            tickfont=dict(color="#27ae60"),
            overlaying="y",
            side="right",
            position=1.0,
            range=[y_min, y_max],
            showgrid=False
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.25,
            xanchor="center",
            x=0.5
        )
    )
    return fig


# === Main App ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="🧪", layout="wide")

    if st_autorefresh:
        st_autorefresh(interval=2000, key="live_refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#AAA;'>Last Update: {now.strftime('%H:%M:%S')} (local)</div>",
                unsafe_allow_html=True)

    st.sidebar.header("Settings")
    window_minutes = st.sidebar.slider("Window (minutes)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)

    hr = metrics.get("avg_hr_60s")
    delta_hr = metrics.get("delta_hr")
    hrv = metrics.get("avg_rmssd_60s")
    delta_hrv = metrics.get("delta_rmssd")
    gl = metrics.get("latest_glucose")
    gl_delta = metrics.get("glucose_delta")
    gl_dir = metrics.get("glucose_direction")
    arrow, trend_text = map_direction(gl_dir)

    # === Metric Cards ===
    html = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    .metric-container {{
        display: flex; justify-content: space-between; gap: 18px; margin-bottom: 24px;
        font-family: 'Inter', system-ui, sans-serif;
    }}
    .metric-card {{
        flex: 1; position: relative; background: #161a22; border-radius: 14px;
        padding: 20px 22px 26px 24px; box-shadow: 0 4px 16px rgba(0,0,0,0.35), inset 0 0 0 1px rgba(255,255,255,0.04);
        color: #EAECEF; overflow: hidden;
    }}
    .accent-red::before, .accent-blue::before, .accent-green::before {{
        content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; border-radius: 14px 0 0 14px;
    }}
    .accent-red::before {{ background: #e74c3c; box-shadow: 0 0 12px rgba(231,76,60,0.35); }}
    .accent-blue::before {{ background: #2980b9; box-shadow: 0 0 12px rgba(41,128,185,0.35); }}
    .accent-green::before {{ background: #27ae60; box-shadow: 0 0 12px rgba(39,174,96,0.35); }}
    .metric-header {{ display: flex; align-items: center; gap: 8px; font-size: 12px;
        letter-spacing: .08em; text-transform: uppercase; color: #AAB2C0; margin-bottom: 8px;
    }}
    .metric-icon {{ font-size: 16px; }}
    .metric-value {{ display: flex; align-items: baseline; gap: 8px; font-size: 40px;
        font-weight: 700; color: #F3F4F6; margin: 2px 0 0 0;
    }}
    .metric-unit {{ font-size: 14px; color: #9AA3B2; font-weight: 600; }}
    .metric-delta {{ margin-top: 10px; font-size: 13px; color: #C8CDD6; }}
    .metric-live {{
        position: absolute; top: 10px; right: 14px; display: flex; align-items: center; gap: 6px;
        font-size: 12px; color: #B7F7C4;
    }}
    .pulse {{ width: 8px; height: 8px; border-radius: 50%; background: #2ecc71; box-shadow: 0 0 6px #2ecc71;
        animation: pulse 1.5s infinite; }}
    @keyframes pulse {{
        0% {{ opacity: .4; transform: scale(.9); }}
        50% {{ opacity: 1; transform: scale(1.25); }}
        100% {{ opacity: .4; transform: scale(.9); }}
    }}
    </style>

    <div class="metric-container">
        <div class="metric-card accent-red">
            <div class="metric-live"><div class="pulse"></div>Live</div>
            <div class="metric-header"><span class="metric-icon">❤️</span><span>Heart Rate</span></div>
            <div class="metric-value">{safe_format(hr, 0)} <span class="metric-unit">bpm</span></div>
            <div class="metric-delta">{'↑' if delta_hr and delta_hr > 0 else '↓' if delta_hr and delta_hr < 0 else '→'} {safe_format(delta_hr, 1)} vs mean({window_minutes}m)</div>
        </div>

        <div class="metric-card accent-blue">
            <div class="metric-live"><div class="pulse"></div>Live</div>
            <div class="metric-header"><span class="metric-icon">💓</span><span>HRV (RMSSD)</span></div>
            <div class="metric-value">{safe_format((hrv*1000) if hrv is not None else None, 0)} <span class="metric-unit">ms</span></div>
            <div class="metric-delta">{'↑' if delta_hrv and delta_hrv > 0 else '↓' if delta_hrv and delta_hrv < 0 else '→'} {safe_format(delta_hrv, 1)} vs mean({window_minutes}m)</div>
        </div>

        <div class="metric-card accent-green">
            <div class="metric-live"><div class="pulse"></div>Live</div>
            <div class="metric-header"><span class="metric-icon">🩸</span><span>Glucose</span></div>
            <div class="metric-value">{safe_format(gl, 0)} <span class="metric-unit">mg/dL</span></div>
            <div class="metric-delta">{arrow} {trend_text} ({safe_format(gl_delta, 1)} mg/dL/min)</div>
        </div>
    </div>
    """
    components.html(html, height=230)

    # === Charts ===
    st.subheader(f"Combined Signals — last {window_minutes} minutes")
    if not df_polar.empty or not df_glucose.empty:
        st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)
    else:
        st.info("No data in the current time window.")

    # Glucose (CGM) chart with green zone
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        st.subheader("Glucose (CGM)")
        fig_gl = go.Figure()
        fig_gl.add_shape(type="rect", xref="paper", x0=0, x1=1,
                         yref="y", y0=70, y1=140,
                         fillcolor="rgba(46,204,113,0.18)", line=dict(width=0), layer="below")
        fig_gl.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                    mode="lines+markers",
                                    line=dict(color="#27ae60", width=2),
                                    marker=dict(size=4),
                                    name="Glucose (mg/dL)"))
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y0, y1 = min(60, g_min - 10), max(150, g_max + 10)
        fig_gl.update_layout(template="plotly_dark", margin=dict(l=0, r=0, t=10, b=0),
                             height=300, yaxis=dict(range=[y0, y1]))
        st.plotly_chart(fig_gl, use_container_width=True)


if __name__ == "__main__":
    main()
