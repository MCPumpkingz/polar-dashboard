import streamlit as st
import pandas as pd
from pymongo import MongoClient
import os
from datetime import datetime, timedelta
import pytz
from streamlit_autorefresh import st_autorefresh
import sys
import subprocess

# Plotly sicherstellen
try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly"])
    import plotly.graph_objects as go


# === Seitenkonfiguration ===
st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", layout="wide")

# === Styling ===
st.markdown("""
    <style>
        html, body, [class*="st-"] {
            background-color: white !important;
            color: #111 !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        h1, h2, h3, h4, h5 {
            color: #111;
            font-weight: 600;
        }
        div.block-container {
            padding: 1rem 2rem;
        }
        .no-data-box {
            text-align:center;
            color:#777;
            background:#f9f9f9;
            border:1px solid #ddd;
            padding:12px;
            border-radius:8px;
            font-size:15px;
            margin-top:8px;
        }
        .metric-table {
            margin: 0 auto;
            border-collapse: collapse;
            font-size: 15px;
            background-color: #fafafa;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 0 4px rgba(0,0,0,0.05);
        }
        .metric-table td {
            padding: 6px 12px;
            border-bottom: 1px solid #e0e0e0;
        }
        .metric-table tr:last-child td {
            border-bottom: none;
        }
        .metric-table td:first-child {
            font-weight: 500;
            color: #333;
        }
        .metric-table td:last-child {
            text-align: right;
            color: #000;
            font-weight: 500;
        }
    </style>
""", unsafe_allow_html=True)


# === Auto-Refresh ===
st_autorefresh(interval=2000, key="datarefresh")

# === Titel & Zeit ===
st.title("📊 Biofeedback System – Polar H10 & CGM Live Dashboard")

tz = pytz.timezone("Europe/Zurich")
now = datetime.now(tz)
st.markdown(f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>", unsafe_allow_html=True)
st.info("📡 Echtzeitdaten aktiv – Anzeigezeitraum einstellbar im Seitenmenü")


# === MongoDB Verbindung ===
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db_polar = client["nightscout-db"]
col_polar = db_polar["polar_data"]
db_glucose = client["nightscout"]
col_glucose = db_glucose["entries"]

# === Seitenleiste ===
st.sidebar.header("⚙️ Einstellungen")
window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
time_threshold = now - timedelta(minutes=window_minutes)

# === Daten laden ===
polar_data = list(col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort("timestamp", 1))
df_polar = pd.DataFrame(polar_data)
if not df_polar.empty:
    df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
    df_polar = df_polar.set_index("timestamp").sort_index()

glucose_data = list(col_glucose.find({"dateString": {"$gte": time_threshold.isoformat()}}).sort("dateString", 1))
df_glucose = pd.DataFrame(glucose_data)
if not df_glucose.empty:
    df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce")
    df_glucose = df_glucose.set_index("timestamp").sort_index()


# === HR/HRV Anzeige ===
if not df_polar.empty:
    baseline_window = df_polar.last("10min")
    recent_data = df_polar.last("60s")

    # Durchschnittswerte
    avg_hr_60s = recent_data["hr"].mean()
    avg_hr_5min = df_polar.last("5min")["hr"].mean()
    avg_hr_window = df_polar.last(f"{window_minutes}min")["hr"].mean()

    avg_rmssd_60s = recent_data["hrv_rmssd"].mean()
    avg_rmssd_5min = df_polar.last("5min")["hrv_rmssd"].mean()
    avg_rmssd_window = df_polar.last(f"{window_minutes}min")["hrv_rmssd"].mean()

    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None
else:
    avg_hr_60s = avg_hr_5min = avg_hr_window = None
    avg_rmssd_60s = avg_rmssd_5min = avg_rmssd_window = baseline_rmssd = None


# === Metrik-Tabellen (immer anzeigen) ===
colA, colB = st.columns(2)
with colA:
    if avg_hr_60s:
        st.markdown(f"""
        <div style='text-align:center;'>
            <div style='font-size:18px;font-weight:600;margin-bottom:4px;'>❤️ Herzfrequenz (HR)</div>
            <div style='font-size:28px;font-weight:600;color:#e74c3c;margin-bottom:6px;'>{avg_hr_60s:.1f} bpm</div>
            <table class='metric-table'>
                <tr><td>Kurzzeit-HR (60 s)</td><td>{avg_hr_60s:.1f} bpm</td></tr>
                <tr><td>Standard-HR (5 min)</td><td>{avg_hr_5min:.1f} bpm</td></tr>
                <tr><td>Langzeit-HR (Fenster {window_minutes} min)</td><td>{avg_hr_window:.1f} bpm</td></tr>
            </table>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='no-data-box'>Keine Herzfrequenzdaten verfügbar.</div>", unsafe_allow_html=True)

with colB:
    if avg_rmssd_60s:
        st.markdown(f"""
        <div style='text-align:center;'>
            <div style='font-size:18px;font-weight:600;margin-bottom:4px;'>💓 HRV – RMSSD</div>
            <div style='font-size:28px;font-weight:600;color:#2980b9;margin-bottom:6px;'>{avg_rmssd_60s*1000:.1f} ms</div>
            <table class='metric-table'>
                <tr><td>Kurzzeit-RMSSD (60 s)</td><td>{avg_rmssd_60s*1000:.1f} ms</td></tr>
                <tr><td>Standard-RMSSD (5 min)</td><td>{avg_rmssd_5min*1000:.1f} ms</td></tr>
                <tr><td>Langzeit-RMSSD (Fenster {window_minutes} min)</td><td>{avg_rmssd_window*1000:.1f} ms</td></tr>
            </table>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='no-data-box'>Keine HRV-Daten verfügbar.</div>", unsafe_allow_html=True)


# === Charts (immer sichtbar) ===
st.subheader(f"📈 Gesamtsignal-Übersicht – letzte {window_minutes} Minuten")
if not df_polar.empty or not df_glucose.empty:
    fig = go.Figure()
    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], name="Herzfrequenz (bpm)", line=dict(color="#e74c3c", width=2)))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000, name="HRV RMSSD (ms)", line=dict(color="#2980b9", width=2, dash="dot"), yaxis="y2"))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], name="Glukose (mg/dL)", line=dict(color="#27ae60", width=2), yaxis="y3"))

    fig.update_layout(
        template="plotly_white", height=500,
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", position=0.9, showgrid=False),
        yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", position=1.0, showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5),
        margin=dict(l=60, r=60, t=10, b=40)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.markdown("<div class='no-data-box'>Keine Daten im aktuellen Zeitraum verfügbar.</div>", unsafe_allow_html=True)
