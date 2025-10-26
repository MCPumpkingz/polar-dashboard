import os
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st
from pymongo import MongoClient
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

# ============== Seiten-Setup ==============
st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", layout="wide")

# ============== Styles ==============
st.markdown("""
    <style>
        html, body, [class*="st-"] {
            background-color: white !important;
            color: #111 !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        h1, h2, h3, h4, h5 { color:#111; font-weight:600; }
        div.block-container { padding: 1rem 2rem; }
        .no-data-box {
            text-align:center; color:#777; background:#f9f9f9; border:1px solid #ddd;
            padding:12px; border-radius:8px; font-size:15px; margin-top:8px;
        }
        .metric-card {
            background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.06);
            padding:20px 28px; text-align:center; transition:all .3s ease;
        }
        .metric-card:hover { box-shadow:0 4px 14px rgba(0,0,0,0.12); }
        .metric-title { font-size:18px; font-weight:600; color:#111; margin-bottom:8px; }
        .metric-value { font-size:30px; font-weight:700; color:#e74c3c; }
        .metric-sub { font-size:14px; color:#555; margin-top:6px; line-height:1.6; }
        .state-card {
            background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.06);
            padding:24px; text-align:center;
        }
        .state-title { font-size:18px; font-weight:600; margin-bottom:10px; }
        .state-desc  { font-size:16px; color:#333; margin:8px 0 12px; }
        .recommend   { font-size:15px; color:#444; background:#f6f8fa; border-radius:8px; padding:10px; display:inline-block; }
    </style>
""", unsafe_allow_html=True)

# ============== Auto-Refresh (2s) ==============
st_autorefresh(interval=2000, key="datarefresh")

# ============== Header ==============
st.title("📊 Biofeedback System – Polar H10 & CGM Live Dashboard")
tz = pytz.timezone("Europe/Zurich")
now = datetime.now(tz)
st.markdown(
    f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>",
    unsafe_allow_html=True
)
st.info("📡 Echtzeitdaten aktiv – Anzeigezeitraum einstellbar im Seitenmenü")

# ============== MongoDB Verbindung ==============
# 👉 Verwende st.secrets, nicht hartcodierte Passwörter!
MONGO_URI = st.secrets.get("mongo", {}).get("uri") or os.getenv("MONGO_URI")
if not MONGO_URI:
    st.error("Keine Mongo URI gefunden. Lege sie in **.streamlit/secrets.toml** (mongo.uri) oder als ENV `MONGO_URI` an.")
    st.stop()

client = MongoClient(MONGO_URI)
db_polar = client.get_database("nightscout-db")
col_polar = db_polar.get_collection("polar_data")
db_glucose = client.get_database("nightscout")
col_glucose = db_glucose.get_collection("entries")

# ============== Sidebar ==============
st.sidebar.header("⚙️ Einstellungen")
window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
time_threshold = now - timedelta(minutes=window_minutes)

# ============== Daten laden ==============
try:
    polar_data = list(
        col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}})
                 .sort("timestamp", 1)
    )
except Exception as e:
    st.error(f"Polar-Query Fehler: {e}")
    polar_data = []

df_polar = pd.DataFrame(polar_data)
if not df_polar.empty:
    df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
    df_polar = df_polar.set_index("timestamp").sort_index()

try:
    glucose_data = list(
        col_glucose.find({"dateString": {"$gte": time_threshold.isoformat()}})
                   .sort("dateString", 1)
    )
except Exception as e:
    st.error(f"Glucose-Query Fehler: {e}")
    glucose_data = []

df_glucose = pd.DataFrame(glucose_data)
if not df_glucose.empty:
    df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce")
    df_glucose = df_glucose.set_index("timestamp").sort_index()

# ============== HR / HRV Kennzahlen ==============
if not df_polar.empty:
    baseline_window = df_polar.last("10min")
    recent_data = df_polar.last("60s")

    avg_hr_60s     = recent_data["hr"].mean()
    avg_hr_5min    = df_polar.last("5min")["hr"].mean()
    avg_hr_window  = df_polar.last(f"{window_minutes}min")["hr"].mean()

    avg_rmssd_60s    = recent_data["hrv_rmssd"].mean()
    avg_rmssd_5min   = df_polar.last("5min")["hrv_rmssd"].mean()
    avg_rmssd_window = df_polar.last(f"{window_minutes}min")["hrv_rmssd"].mean()

    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None
else:
    avg_hr_60s = avg_hr_5min = avg_hr_window = None
    avg_rmssd_60s = avg_rmssd_5min = avg_rmssd_window = baseline_rmssd = None

# ============== Metric Cards ==============
col1, col2 = st.columns(2)
with col1:
    if avg_hr_60s is not None:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">❤️ Herzfrequenz (HR)</div>
                <div class="metric-value">{avg_hr_60s:.1f} bpm</div>
                <div class="metric-sub">
                    Kurzzeit-HR (60 s): {avg_hr_60s:.1f} bpm<br>
                    Standard-HR (5 min): {avg_hr_5min:.1f} bpm<br>
                    Langzeit-HR (Fenster {window_minutes} min): {avg_hr_window:.1f} bpm
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='no-data-box'>Keine Herzfrequenzdaten verfügbar.</div>", unsafe_allow_html=True)

with col2:
    if avg_rmssd_60s is not None:
        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title">💓 HRV – RMSSD</div>
                <div class="metric-value" style="color:#2980b9;">{avg_rmssd_60s*1000:.1f} ms</div>
                <div class="metric-sub">
                    Kurzzeit-RMSSD (60 s): {avg_rmssd_60s*1000:.1f} ms<br>
                    Standard-RMSSD (5 min): {avg_rmssd_5min*1000:.1f} ms<br>
                    Langzeit-RMSSD (Fenster {window_minutes} min): {avg_rmssd_window*1000:.1f} ms
                </div>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<div class='no-data-box'>Keine HRV-Daten verfügbar.</div>", unsafe_allow_html=True)

# ============== Zustand + Empfehlung ==============
if baseline_rmssd and avg_rmssd_60s:
    delta_rmssd = avg_rmssd_60s / baseline_rmssd
    if delta_rmssd < 0.7:
        state, color, desc, reco = (
            "High Stress", "#e74c3c",
            "Stark sympathische Aktivierung – <b>Fight or Flight</b>.",
            "🌬️ 4-7-8-Atmung oder 6 Atemzüge/min zur Aktivierung des Vagusnervs.")
    elif delta_rmssd < 1.0:
        state, color, desc, reco = (
            "Mild Stress", "#f39c12",
            "Leichte sympathische Aktivierung – du bist <b>fokussiert</b>, aber angespannt.",
            "🫁 Längeres Ausatmen (4 s ein / 8 s aus).")
    elif delta_rmssd < 1.3:
        state, color, desc, reco = (
            "Balanced", "#f1c40f",
            "Dein Nervensystem ist in <b>Balance</b>.",
            "☯️ Box Breathing (4-4-4-4) zur Stabilisierung.")
    else:
        state, color, desc, reco = (
            "Recovery / Flow", "#2ecc71",
            "Hohe parasympathische Aktivität – du bist im <b>Erholungsmodus</b>.",
            "🧘 Meditation oder ruhige Atmung fördern Flow & Regeneration.")

    st.markdown("<br>", unsafe_allow_html=True)
    col3, col4 = st.columns(2)
    with col3:
        st.markdown(f"""
            <div class="state-card">
                <div class="state-title">🧠 Neurophysiologischer Zustand</div>
                <h3 style="color:{color}; font-weight:700; margin-top:4px;">{state}</h3>
                <div class="state-desc">{desc}</div>
            </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
            <div class="state-card">
                <div class="state-title">💡 Empfehlung</div>
                <div class="recommend">{reco}</div>
            </div>
        """, unsafe_allow_html=True)
else:
    st.markdown("<div class='no-data-box'>Warte auf ausreichende HRV-Daten zur Analyse …</div>", unsafe_allow_html=True)

# ============== Gesamtsignal-Übersicht ==============
st.subheader(f"📈 Gesamtsignal-Übersicht – letzte {window_minutes} Minuten")
if (not df_polar.empty) or (not df_glucose.empty):
    fig = go.Figure()
    if "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], name="Herzfrequenz (bpm)",
                                 line=dict(color="#e74c3c", width=2)))
    if "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"]*1000,
                                 name="HRV RMSSD (ms)", line=dict(color="#2980b9", width=2, dash="dot"), yaxis="y2"))
    if "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], name="Glukose (mg/dL)",
                                 line=dict(color="#27ae60", width=2), yaxis="y3"))
    fig.update_layout(
        template="plotly_white", height=500,
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", position=0.9, showgrid=False),
        yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", position=1.0, showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.markdown("<div class='no-data-box'>Keine Daten im aktuellen Zeitraum verfügbar.</div>", unsafe_allow_html=True)

# ============== Einzelcharts ==============
st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
if not df_polar.empty and "hr" in df_polar.columns:
    st.line_chart(df_polar[["hr"]])
else:
    st.markdown("<div class='no-data-box'>Keine Herzfrequenzdaten verfügbar.</div>", unsafe_allow_html=True)

st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
if not df_polar.empty and all(c in df_polar.columns for c in ["hrv_rmssd", "hrv_sdnn"]):
    st.line_chart(df_polar[["hrv_rmssd", "hrv_sdnn"]])
else:
    st.markdown("<div class='no-data-box'>Keine HRV-Daten verfügbar.</div>", unsafe_allow_html=True)

st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
if not df_glucose.empty and "sgv" in df_glucose.columns:
    st.line_chart(df_glucose[["sgv"]])
else:
    st.markdown("<div class='no-data-box'>Keine CGM-Daten verfügbar.</div>", unsafe_allow_html=True)

# ============== Tabellen ==============
if not df_polar.empty:
    st.subheader("🕒 Letzte Polar-Messwerte")
    st.dataframe(df_polar.tail(10))
else:
    st.markdown("<div class='no-data-box'>Keine Polar-Messwerte verfügbar.</div>", unsafe_allow_html=True)

if not df_glucose.empty:
    st.subheader("🕒 Letzte CGM-Messwerte")
    st.dataframe(df_glucose.tail(10))
else:
    st.markdown("<div class='no-data-box'>Keine CGM-Messwerte verfügbar.</div>", unsafe_allow_html=True)
