import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytz
import streamlit as st
import streamlit.components.v1 as components
from pymongo import MongoClient
import plotly.graph_objects as go

# === Auto-Refresh ===
try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    st_autorefresh = None


# === MongoDB Verbindung ===
def connect_to_mongo(window_minutes):
    MONGO_URI = os.getenv("MONGO_URI") or \
        "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/?retryWrites=true&w=majority"
    client = MongoClient(MONGO_URI)
    db_polar = client["nightscout-db"]
    db_glucose = client["nightscout"]
    col_polar = db_polar["polar_data"]
    col_glucose = db_glucose["entries"]

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)

    # Zeitraum bestimmen
    time_threshold_polar = now - timedelta(minutes=window_minutes)
    time_threshold_glucose = now - timedelta(minutes=window_minutes)

    # Polar-Daten abrufen
    polar_data = list(col_polar.find({"timestamp": {"$gte": time_threshold_polar.isoformat()}}).sort("timestamp", 1))
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # Glukose-Daten abrufen
    glucose_data = list(col_glucose.find({"dateString": {"$gte": time_threshold_glucose.isoformat()}}).sort("dateString", 1))
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce", utc=True)
        df_glucose["timestamp"] = df_glucose["timestamp"].dt.tz_convert("Europe/Zurich")
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


# === Kennzahlenberechnung ===
def compute_metrics(df_polar, df_glucose):
    metrics = {}

    if not df_polar.empty:
        hr = df_polar["hr"].iloc[-1]
        hr_mean = df_polar["hr"].mean()
        delta_hr = hr - hr_mean

        rmssd = df_polar["hrv_rmssd"].iloc[-1] * 1000 if "hrv_rmssd" in df_polar.columns else np.nan
        sdnn = df_polar["hrv_sdnn"].iloc[-1] * 1000 if "hrv_sdnn" in df_polar.columns else np.nan
        cv_hrv = (sdnn / rmssd * 100) if rmssd and sdnn else np.nan

        metrics.update({
            "hr": hr,
            "hr_mean": hr_mean,
            "delta_hr": delta_hr,
            "rmssd": rmssd,
            "sdnn": sdnn,
            "cv_hrv": cv_hrv
        })

    if not df_glucose.empty:
        gl_now = df_glucose["sgv"].iloc[-1]
        gl_15min = df_glucose["sgv"].iloc[0]
        delta_gl = gl_now - gl_15min
        gl_mean = df_glucose["sgv"].mean()
        gl_cv = (df_glucose["sgv"].std() / gl_mean * 100) if gl_mean else np.nan

        metrics.update({
            "gl_now": gl_now,
            "delta_gl": delta_gl,
            "gl_mean": gl_mean,
            "gl_cv": gl_cv
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
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"],
                                 mode="lines", name="Herzfrequenz (bpm)",
                                 line=dict(color="#e74c3c", width=2)))
    if "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000,
                                 mode="lines", name="HRV RMSSD (ms)",
                                 yaxis="y2", line=dict(color="#2980b9", width=2)))
    if "hrv_sdnn" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"]*1000,
                                 mode="lines", name="HRV SDNN (ms)",
                                 yaxis="y2", line=dict(color="#5dade2", width=2)))
    if not df_glucose.empty:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"],
                                 mode="lines", name="Glukose (mg/dL)",
                                 yaxis="y3", line=dict(color="#27ae60", width=3)))

    fig.add_shape(type="rect", xref="paper", x0=0, x1=1, yref="y3",
                  y0=70, y1=140, fillcolor="rgba(46,204,113,0.15)", line=dict(width=0))

    fig.update_layout(template="plotly_white", height=450, margin=dict(l=0, r=0, t=0, b=0),
                      xaxis=dict(title="Zeit"),
                      yaxis=dict(title="HR (bpm)"),
                      yaxis2=dict(title="HRV (ms)", overlaying="y", side="right"),
                      yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", range=[y_min, y_max]),
                      legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5))
    return fig


# === Hauptfunktion ===
def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="💜", layout="wide")

    # === Sidebar ===
    st.sidebar.header("⚙️ Einstellungen")
    window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
    auto_refresh = st.sidebar.toggle("Auto-Refresh aktivieren", True)

    if auto_refresh and st_autorefresh:
        st_autorefresh(interval=2000, key="refresh")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)

    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')}</div>",
                unsafe_allow_html=True)

    # Daten abrufen
    df_polar, df_glucose = connect_to_mongo(window_minutes)
    metrics = compute_metrics(df_polar, df_glucose)

    hr = metrics.get("hr", 0)
    delta_hr = metrics.get("delta_hr", 0)
    hrv = metrics.get("rmssd", 0)
    gl = metrics.get("gl_now", 0)

    # === Live Cards (Design) ===
    components.html(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
    .metric-container {{
        display: flex; justify-content: space-between; gap: 26px; margin-bottom: 30px;
    }}
    .metric-card {{
        flex: 1; border-radius: 20px; padding: 28px; color: white;
        font-family: 'Poppins', sans-serif;
        background: linear-gradient(135deg, #8B5CF6 0%, #6366F1 60%, #4F46E5 100%);
        box-shadow: 0 8px 20px rgba(0,0,0,0.25); position: relative;
        transition: transform 0.3s ease;
    }}
    .metric-card:hover {{ transform: translateY(-3px); }}
    .metric-title {{ font-size: 14px; opacity: 0.85; text-transform: uppercase; margin-bottom: 8px; }}
    .metric-value {{ font-size: 54px; font-weight: 700; margin: 0; }}
    .metric-delta {{ font-size: 16px; margin-top: 10px; opacity: 0.9; }}
    .metric-interpret {{ font-size: 13px; opacity: 0.8; margin-top: 4px; }}
    .pulse {{ width: 8px; height: 8px; background:#00ff6a; border-radius:50%;
        animation:pulse 2s infinite; box-shadow:0 0 6px #00ff6a; display:inline-block; }}
    @keyframes pulse {{ 0%{{opacity:.4;transform:scale(.9);}} 50%{{opacity:1;transform:scale(1.3);}} 100%{{opacity:.4;transform:scale(.9);}} }}
    </style>

    <div class="metric-container">
        <div class="metric-card">
            <div class="metric-title">❤️ HERZFREQUENZ</div>
            <div class="metric-value">{hr:.0f}</div>
            <div class="metric-delta">{'↗' if delta_hr > 0 else '↘' if delta_hr < 0 else '→'} {delta_hr:+.1f} bpm</div>
            <div class="metric-interpret">Herzaktivität aktuell</div>
            <div><span class="pulse"></span> Live</div>
        </div>

        <div class="metric-card">
            <div class="metric-title">💓 HRV (RMSSD)</div>
            <div class="metric-value">{hrv:.0f}</div>
            <div class="metric-delta">ms</div>
            <div class="metric-interpret">Vagal-Tonus / Stresslevel</div>
            <div><span class="pulse"></span> Live</div>
        </div>

        <div class="metric-card">
            <div class="metric-title">🩸 GLUKOSE</div>
            <div class="metric-value">{gl:.0f}</div>
            <div class="metric-delta">mg/dL</div>
            <div class="metric-interpret">Blutzucker im Normbereich</div>
            <div><span class="pulse"></span> Live</div>
        </div>
    </div>
    """, height=260)

    # === Erweiterte KPIs ===
    st.markdown("## 📊 Erweiterte physiologische Kennzahlen")
    data = []
    if not df_polar.empty:
        data += [
            ["Autonomes NS", "RMSSD", f"{metrics.get('rmssd', np.nan):.1f} ms", "5-15 min", "Parasympathische Aktivität"],
            ["Autonomes NS", "SDNN", f"{metrics.get('sdnn', np.nan):.1f} ms", "5-15 min", "Gesamt-HRV"],
            ["Autonomes NS", "CV% HRV", f"{metrics.get('cv_hrv', np.nan):.1f} %", "5-15 min", "Variabilität"],
            ["Kardiovaskulär", "HR Mittelwert", f"{metrics.get('hr_mean', np.nan):.1f} bpm", "5-15 min", "Herzaktivität"],
        ]
    if not df_glucose.empty:
        data += [
            ["Glukose", "Δ Glukose", f"{metrics.get('delta_gl', np.nan):+.1f} mg/dL", "15-60 min", "Trend"],
            ["Glukose", "Mittelwert", f"{metrics.get('gl_mean', np.nan):.1f} mg/dL", "15-60 min", "Kurzzeitniveau"],
            ["Glukose", "CV%", f"{metrics.get('gl_cv', np.nan):.1f} %", "15-60 min", "Stabilität"],
        ]
    df_kpi = pd.DataFrame(data, columns=["Kategorie", "KPI", "Wert", "Fenster", "Interpretation"])
    with st.expander("📊 Erweiterte Kennzahlen anzeigen"):
        st.table(df_kpi)

    # === Charts ===
    st.subheader(f"📈 Gesamtsignal – letzte {window_minutes} Minuten")
    if not df_polar.empty or not df_glucose.empty:
        st.plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)

    if not df_polar.empty:
        st.subheader("❤️ Herzfrequenz (HR)")
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], mode="lines", line=dict(color="#e74c3c", width=2)))
        st.plotly_chart(fig_hr, use_container_width=True)

        st.subheader("💓 HRV (RMSSD & SDNN)")
        fig_hrv = go.Figure()
        if "hrv_rmssd" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000, mode="lines", line=dict(color="#2980b9", width=2)))
        if "hrv_sdnn" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"]*1000, mode="lines", line=dict(color="#5dade2", width=2)))
        st.plotly_chart(fig_hrv, use_container_width=True)

    if not df_glucose.empty:
        st.subheader("🩸 Glukose (CGM)")
        fig_gl = go.Figure()
        fig_gl.add_shape(type="rect", xref="paper", x0=0, x1=1, yref="y", y0=70, y1=140,
                         fillcolor="rgba(46,204,113,0.2)", line=dict(width=0), layer="below")
        fig_gl.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], mode="lines+markers",
                                    line=dict(color="#27ae60", width=2), marker=dict(size=4)))
        st.plotly_chart(fig_gl, use_container_width=True)

    # === Tabellen ===
    if not df_polar.empty:
        st.subheader("🕒 Letzte Polar-Messwerte")
        st.dataframe(df_polar.tail(10))
    if not df_glucose.empty:
        st.subheader("🕒 Letzte CGM-Messwerte")
        st.dataframe(df_glucose.tail(10))


if __name__ == "__main__":
    main()
