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
        .metric-card {
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            padding: 20px 28px;
            text-align: center;
            transition: all 0.3s ease;
        }
        .metric-card:hover {
            box-shadow: 0 4px 14px rgba(0,0,0,0.12);
        }
        .metric-title {
            font-size: 18px;
            font-weight: 600;
            color: #111;
            margin-bottom: 8px;
        }
        .metric-value {
            font-size: 30px;
            font-weight: 700;
            color: #e74c3c;
        }
        .metric-sub {
            font-size: 14px;
            color: #555;
            margin-top: 6px;
            line-height: 1.6;
        }
        .state-card {
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            padding: 24px;
            text-align: center;
        }
        .state-title {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 10px;
        }
        .state-desc {
            font-size: 16px;
            color: #333;
            margin-top: 8px;
            margin-bottom: 12px;
        }
        .recommend {
            font-size: 15px;
            color: #444;
            background: #f6f8fa;
            border-radius: 8px;
            padding: 10px;
            display: inline-block;
            margin-top: 4px;
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


# === HR / HRV Berechnungen ===
if not df_polar.empty:
    baseline_window = df_polar.last("10min")
    recent_data = df_polar.last("60s")

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


# === APPLE-LIKE METRIC CARDS ===
col1, col2 = st.columns(2)
with col1:
    if avg_hr_60s:
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
    if avg_rmssd_60s:
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


# === Zustand + Empfehlung Cards ===
if baseline_rmssd and avg_rmssd_60s:
    delta_rmssd = avg_rmssd_60s / baseline_rmssd
    if delta_rmssd < 0.7:
        state, color, desc, reco = (
            "High Stress", "#e74c3c",
            "Stark sympathische Aktivierung – **Fight or Flight**.",
            "🌬️ 4-7-8-Atmung oder 6 Atemzüge/min zur Aktivierung des Vagusnervs.")
    elif delta_rmssd < 1.0:
        state, color, desc, reco = (
            "Mild Stress", "#f39c12",
            "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt.",
            "🫁 Längeres Ausatmen (4 s ein / 8 s aus).")
    elif delta_rmssd < 1.3:
        state, color, desc, reco = (
            "Balanced", "#f1c40f",
            "Dein Nervensystem ist in **Balance**.",
            "☯️ Box Breathing (4-4-4-4) zur Stabilisierung.")
    else:
        state, color, desc, reco = (
            "Recovery / Flow", "#2ecc71",
            "Hohe parasympathische Aktivität – du bist im **Erholungsmodus**.",
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


# === GESAMTSIGNAL-ÜBERSICHT ===
st.subheader(f"📈 Gesamtsignal-Übersicht – letzte {window_minutes} Minuten")
if not df_polar.empty or not df_glucose.empty:
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
    fig.update_layout(template="plotly_white", height=500,
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", position=0.9, showgrid=False),
        yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", position=1.0, showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, xanchor="center", x=0.5)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.markdown("<div class='no-data-box'>Keine Daten im aktuellen Zeitraum verfügbar.</div>", unsafe_allow_html=True)


# === EINZELCHARTS ===
st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
if not df_polar.empty and "hr" in df_polar.columns:
    st.line_chart(df_polar[["hr"]])
else:
    st.markdown("<div class='no-data-box'>Keine Herzfrequenzdaten verfügbar.</div>", unsafe_allow_html=True)

st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
if not df_polar.empty and all(col in df_polar.columns for col in ["hrv_rmssd", "hrv_sdnn"]):
    st.line_chart(df_polar[["hrv_rmssd", "hrv_sdnn"]])
else:
    st.markdown("<div class='no-data-box'>Keine HRV-Daten verfügbar.</div>", unsafe_allow_html=True)

st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
if not df_glucose.empty and "sgv" in df_glucose.columns:
    st.line_chart(df_glucose[["sgv"]])
else:
    st.markdown("<div class='no-data-box'>Keine CGM-Daten verfügbar.</div>", unsafe_allow_html=True)


# === NEUROZUSTAND-VERLAUF ===
st.subheader(f"🧠 Neurophysiologischer Zustand (Verlauf) – letzte {window_minutes} Minuten")
if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
    baseline_rmssd = df_polar["hrv_rmssd"].last("10min").mean()
    def get_state_value(rmssd, baseline):
        if not baseline or rmssd is None:
            return None
        ratio = rmssd / baseline
        if ratio < 0.7: return 4
        elif ratio < 1.0: return 3
        elif ratio < 1.3: return 2
        else: return 1

    df_polar["state_value"] = df_polar["hrv_rmssd"].apply(lambda x: get_state_value(x, baseline_rmssd))
    colors = {1:"#2ecc71",2:"#f1c40f",3:"#f39c12",4:"#e74c3c"}

    fig_state = go.Figure()
    for sv, color in colors.items():
        sd = df_polar[df_polar["state_value"] == sv]
        if not sd.empty:
            fig_state.add_trace(go.Scatter(x=sd.index, y=sd["state_value"], mode="lines",
                                           line=dict(width=0.5, color=color), fill="tozeroy", fillcolor=color,
                                           name={1:"Flow",2:"Balanced",3:"Mild Stress",4:"High Stress"}[sv], opacity=0.7))
    fig_state.update_layout(
        yaxis=dict(tickvals=[1,2,3,4],
                   ticktext=["Flow","Balanced","Mild Stress","High Stress"],
                   range=[0.5,4.5],
                   title="Zustand"),
        xaxis_title="Zeit", showlegend=True,
        template="plotly_white", height=400
    )
    st.plotly_chart(fig_state, use_container_width=True)
else:
    st.markdown("<div class='no-data-box'>Keine ausreichenden HRV-Daten zur Bestimmung des Zustandes.</div>", unsafe_allow_html=True)


# === TABELLEN ===
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
