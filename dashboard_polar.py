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


# === Neurophysiologischer Zustand berechnen ===
if not df_polar.empty:
    baseline_window = df_polar.last("10min")
    recent_data = df_polar.last("60s")

    # --- HR / HRV Werte (60s, 5min, Fenster) ---
    avg_hr_60s = recent_data["hr"].mean() if not recent_data.empty else None
    avg_hr_5min = df_polar.last("5min")["hr"].mean()
    avg_hr_window = df_polar.last(f"{window_minutes}min")["hr"].mean()

    avg_rmssd_60s = recent_data["hrv_rmssd"].mean()
    avg_rmssd_5min = df_polar.last("5min")["hrv_rmssd"].mean()
    avg_rmssd_window = df_polar.last(f"{window_minutes}min")["hrv_rmssd"].mean()

    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None

    # --- Metriken anzeigen ---
    colA, colB = st.columns(2)
    with colA:
        if avg_hr_60s:
            st.metric(
                "❤️ Herzfrequenz (HR)",
                f"{avg_hr_60s:.1f} bpm",
                help=f"HR(60 s): {avg_hr_60s:.1f} bpm | HR(5 min): {avg_hr_5min:.1f} bpm | HR({window_minutes} min): {avg_hr_window:.1f} bpm"
            )
    with colB:
        if avg_rmssd_60s:
            st.metric(
                "💓 HRV – RMSSD",
                f"{avg_rmssd_60s*1000:.1f} ms",
                help=f"RMSSD(60 s): {avg_rmssd_60s*1000:.1f} ms | RMSSD(5 min): {avg_rmssd_5min*1000:.1f} ms | RMSSD({window_minutes} min): {avg_rmssd_window*1000:.1f} ms"
            )

    # --- Zustand bestimmen ---
    if baseline_rmssd and avg_rmssd_60s:
        delta_rmssd = avg_rmssd_60s / baseline_rmssd
        if delta_rmssd < 0.7:
            state, color, desc, reco, level = (
                "High Stress", "#e74c3c",
                "Stark sympathische Aktivierung – **Fight or Flight**.",
                "🌬️ 4-7-8-Atmung oder 6 Atemzüge/min zur Aktivierung des Vagusnervs.", 4)
        elif delta_rmssd < 1.0:
            state, color, desc, reco, level = (
                "Mild Stress", "#f39c12",
                "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt.",
                "🫁 Längeres Ausatmen (4 s ein / 8 s aus).", 3)
        elif delta_rmssd < 1.3:
            state, color, desc, reco, level = (
                "Balanced", "#f1c40f",
                "Dein Nervensystem ist in **Balance**.",
                "☯️ Box Breathing (4-4-4-4) zur Stabilisierung.", 2)
        else:
            state, color, desc, reco, level = (
                "Recovery / Flow", "#2ecc71",
                "Hohe parasympathische Aktivität – du bist im **Erholungsmodus**.",
                "🧘 Meditation oder ruhige Atmung fördern Flow & Regeneration.", 1)

        # --- Layout: Ampel + Textblöcke ---
        st.markdown("### 🧠 Neurophysiologischer Zustand (aktuell)")
        col1, col2, col3 = st.columns([2, 3, 3])
        header = "font-size:18px;font-weight:600;text-align:center;color:#111;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;"

        # Ampel
        with col1:
            st.markdown(f"<div style='{header}'>🧭 Status</div>", unsafe_allow_html=True)
            colors = ["#2ecc71", "#f1c40f", "#f39c12", "#e74c3c"]
            circles = []
            for i, c in enumerate(colors, start=1):
                active = (i == level)
                circles.append(
                    f"<div style='width:42px;height:42px;border-radius:50%;background-color:{c if active else '#e6e6e6'};"
                    f"box-shadow:{'0 0 16px ' + c if active else 'inset 0 0 4px #ccc'};opacity:{'1' if active else '0.5'};'></div>"
                )
            lamp_html = "<div style='display:flex;justify-content:center;align-items:center;gap:16px;margin-top:12px;'>" + "".join(circles) + "</div>"
            st.markdown(lamp_html, unsafe_allow_html=True)

        # Zustand
        with col2:
            st.markdown(f"<div style='{header}'>🧠 Zustand</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align:center;'><h3 style='color:{color};margin-bottom:6px;'>{state}</h3>"
                        f"<p style='font-size:16px;color:#333;line-height:1.5;max-width:90%;margin:0 auto;'>{desc}</p></div>",
                        unsafe_allow_html=True)

        # Empfehlung
        with col3:
            st.markdown(f"<div style='{header}'>💡 Empfehlung</div>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align:center;'><p style='font-size:15px;color:#444;line-height:1.5;max-width:90%;margin:0 auto;'>{reco}</p></div>",
                        unsafe_allow_html=True)
    else:
        st.markdown("<div class='no-data-box'>Warte auf ausreichende HRV-Daten zur Analyse …</div>", unsafe_allow_html=True)
else:
    st.markdown("<div class='no-data-box'>Keine Polar-Daten im angegebenen Zeitraum gefunden.</div>", unsafe_allow_html=True)
