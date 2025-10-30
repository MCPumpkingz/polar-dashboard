import os
from datetime import datetime, timedelta
import pandas as pd
import pytz
import streamlit as st
import streamlit.components.v1 as components
from pymongo import MongoClient
import plotly.graph_objects as go

# === Auto-Refresh (alle 2 Sekunden) ===
try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    st_autorefresh = None


# === MongoDB Verbindung ===
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

    # Polar-Daten
    polar_data = list(col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort("timestamp", 1))
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # Glukose-Daten
    time_threshold_utc = (now - timedelta(minutes=window_minutes)).astimezone(pytz.UTC)
    glucose_data = list(col_glucose.find({"dateString": {"$gte": time_threshold_utc.isoformat()}}).sort("dateString", 1))
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce", utc=True)
        df_glucose["timestamp"] = df_glucose["timestamp"].dt.tz_convert("Europe/Zurich")
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


# === Kennzahlenberechnung ===
def compute_metrics(df_polar, df_glucose, window_minutes):
    metrics = {}
    if not df_polar.empty:
        recent_data = df_polar.last("60s")
        long_window = df_polar.last(f"{window_minutes}min")

        avg_hr_60s = recent_data["hr"].mean()
        avg_hr_long = long_window["hr"].mean()
        delta_hr = avg_hr_60s - avg_hr_long if avg_hr_long and avg_hr_60s else None

        avg_rmssd_60s = recent_data["hrv_rmssd"].mean()
        avg_rmssd_long = long_window["hrv_rmssd"].mean()
        delta_rmssd = (avg_rmssd_60s - avg_rmssd_long) * 1000 if avg_rmssd_long and avg_rmssd_60s else None

        latest_glucose = df_glucose["sgv"].iloc[-1] if not df_glucose.empty else None

        metrics.update({
            "avg_hr_60s": avg_hr_60s,
            "delta_hr": delta_hr,
            "avg_rmssd_60s": avg_rmssd_60s,
            "delta_rmssd": delta_rmssd,
            "latest_glucose": latest_glucose
        })
    return metrics


# === Kombinierter Plot ===
def create_combined_plot(df_polar, df_glucose):
    fig = go.Figure()
    y_min, y_max = (40, 180)
    if not df_glucose.empty:
        g_min, g_max = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        y_min, y_max = max(40, g_min - 10), min(250, g_max + 10)

    if "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], name="HR (bpm)",
                                 mode="lines", line=dict(color="#e74c3c", width=2)))
    if "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000, name="HRV RMSSD (ms)",
                                 mode="lines", yaxis="y2", line=dict(color="#2980b9", width=2)))
    if "hrv_sdnn" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"]*1000, name="HRV SDNN (ms)",
                                 mode="lines", yaxis="y2", line=dict(color="#5dade2", width=2)))
    if not df_glucose.empty:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], name="Glukose (mg/dL)",
                                 mode="lines", yaxis="y3", line=dict(color="#27ae60", width=3)))

    fig.add_shape(type="rect", xref="paper", x0=0, x1=1, yref="y3", y0=70, y1=140,
                  fillcolor="rgba(46,204,113,0.15)", line=dict(width=0), layer="below")

    fig.update_layout(template="plotly_white", height=450,
                      margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(title="Zeit"),
                      yaxis=dict(title="HR (bpm)"),
                      yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", showgrid=False),
                      yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", showgrid=False, range=[y_min, y_max]),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5))
    return fig


# === Hauptfunktion ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="💜", layout="wide")

    # Sanfter Auto-Refresh
    if st_autorefresh:
        st_autorefresh(interval=2000, key="live_refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>",
                unsafe_allow_html=True)

    st.sidebar.header("⚙️ Einstellungen")
    window_minutes = st.sidebar.slider("Zeitfenster (Minuten)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    # Daten abrufen
    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)

    hr = metrics.get("avg_hr_60s", 0)
    delta_hr = metrics.get("delta_hr", 0)
    hrv = metrics.get("avg_rmssd_60s", 0)
    delta_hrv = metrics.get("delta_rmssd", 0)
    gl = metrics.get("latest_glucose", 0)

    # === Stil mit pulsierendem Live-Indikator ===
    html = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
    .metric-container {{
        display: flex;
        justify-content: space-between;
        gap: 26px;
        margin-bottom: 30px;
    }}
    .metric-card {{
        flex: 1;
        border-radius: 20px;
        padding: 28px;
        color: white;
        font-family: 'Poppins', sans-serif;
        background: linear-gradient(160deg, #8B5CF6 0%, #6366F1 60%, #4F46E5 100%);
        box-shadow: 0 6px 20px rgba(0,0,0,0.25);
        position: relative;
        transition: all 0.4s ease;
    }}
    .metric-title {{
        font-size: 13px;
        letter-spacing: 1px;
        opacity: 0.85;
        text-transform: uppercase;
        margin-bottom: 8px;
    }}
    .metric-value {{
        font-size: 54px;
        font-weight: 700;
        margin: 0;
        line-height: 1.1;
    }}
    .metric-unit {{
        font-size: 16px;
        font-weight: 500;
        opacity: 0.6;
        margin-left: 6px;
    }}
    .metric-delta {{
        font-size: 15px;
        margin-top: 12px;
        opacity: 0.85;
    }}
    .metric-interpret {{
        font-size: 14px;
        opacity: 0.8;
        margin-top: 4px;
    }}
    .metric-icon {{
        position: absolute;
        top: 20px;
        right: 22px;
        font-size: 22px;
        background: rgba(255,255,255,0.08);
        padding: 6px 10px;
        border-radius: 10px;
    }}
    .metric-live {{
        position: absolute;
        bottom: 14px;
        left: 22px;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 6px;
        color: #b5f5b5;
    }}
    .pulse {{
        width: 8px;
        height: 8px;
        background-color: #00ff6a;
        border-radius: 50%;
        animation: pulse 1.5s infinite;
        box-shadow: 0 0 5px #00ff6a;
    }}
    @keyframes pulse {{
        0% {{ opacity: 0.4; transform: scale(0.9); }}
        50% {{ opacity: 1; transform: scale(1.3); }}
        100% {{ opacity: 0.4; transform: scale(0.9); }}
    }}
    </style>

    <div class="metric-container">
        <div class="metric-card">
            <div class="metric-icon">❤️</div>
            <div class="metric-title">HERZFREQUENZ</div>
            <div class="metric-value">{hr:.0f}<span class="metric-unit">BPM</span></div>
            <div class="metric-delta">{'↗' if delta_hr > 0 else '↘' if delta_hr < 0 else '→'} {delta_hr:+.1f} bpm</div>
            <div class="metric-interpret">Herzaktivität aktuell</div>
            <div class="metric-live"><div class="pulse"></div>Live</div>
        </div>

        <div class="metric-card">
            <div class="metric-icon">💓</div>
            <div class="metric-title">HRV (RMSSD)</div>
            <div class="metric-value">{hrv*1000:.0f}<span class="metric-unit">MS</span></div>
            <div class="metric-delta">{'↗' if delta_hrv > 0 else '↘' if delta_hrv < 0 else '→'} {delta_hrv:+.1f} ms</div>
            <div class="metric-interpret">Vagal-Tonus / Stresslevel</div>
            <div class="metric-live"><div class="pulse"></div>Live</div>
        </div>

        <div class="metric-card">
            <div class="metric-icon">🩸</div>
            <div class="metric-title">GLUKOSE</div>
            <div class="metric-value">{gl:.0f}<span class="metric-unit">MG/DL</span></div>
            <div class="metric-delta">↗ leicht steigend</div>
            <div class="metric-interpret">Blutzucker im Normbereich</div>
            <div class="metric-live"><div class="pulse"></div>Live</div>
        </div>
    </div>
    """
    components.html(html, height=260)

    # === Charts ===
    st.subheader(f"📈 Gesamtsignal – letzte {window_minutes} Minuten")
    if not df_polar.empty or not df_glucose.empty:
        st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)
    else:
        st.info("Keine Daten im aktuellen Zeitraum verfügbar.")

    # Einzelcharts
    if not df_polar.empty:
        st.subheader("❤️ Herzfrequenz (HR)")
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
                                    mode="lines", line=dict(color="#e74c3c", width=2)))
        st.plotly_chart(fig_hr, use_container_width=True)

        st.subheader("💓 HRV (RMSSD & SDNN)")
        fig_hrv = go.Figure()
        if "hrv_rmssd" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000,
                                         mode="lines", line=dict(color="#2980b9", width=2)))
        if "hrv_sdnn" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"]*1000,
                                         mode="lines", line=dict(color="#5dade2", width=2)))
        st.plotly_chart(fig_hrv, use_container_width=True)

    if not df_glucose.empty:
        st.subheader("🩸 Glukose (CGM)")
        fig_gl = go.Figure()
        fig_gl.add_shape(type="rect", xref="paper", x0=0, x1=1,
                         yref="y", y0=70, y1=140,
                         fillcolor="rgba(46,204,113,0.2)", line=dict(width=0), layer="below")
        fig_gl.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                    mode="lines+markers", line=dict(color="#27ae60", width=2), marker=dict(size=4)))
        st.plotly_chart(fig_gl, use_container_width=True)

    # Tabellen
    if not df_polar.empty:
        st.subheader("🕒 Letzte Polar-Messwerte")
        st.dataframe(df_polar.tail(10))
    if not df_glucose.empty:
        st.subheader("🕒 Letzte CGM-Messwerte")
        st.dataframe(df_glucose.tail(10))


if __name__ == "__main__":
    main()

