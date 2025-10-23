import streamlit as st
import pandas as pd
from pymongo import MongoClient
import os
from datetime import datetime, timedelta
import pytz
from streamlit_autorefresh import st_autorefresh

# === Seitenkonfiguration ===
st.set_page_config(page_title="Polar SAMAY H10 Live Dashboard", layout="wide")

# --- Weißer Hintergrund & Helvetica-Schrift ---
st.markdown("""
    <style>
        body, .stApp {
            background-color: white;
            color: black;
            font-family: Helvetica, Arial, sans-serif;
        }
        h1, h2, h3, h4 {
            color: black;
            font-family: Helvetica, Arial, sans-serif;
        }
        .stMetricLabel {
            color: black !important;
        }
    </style>
""", unsafe_allow_html=True)

# 🔁 Dashboard aktualisiert sich jede Sekunde
st_autorefresh(interval=1000, key="datarefresh")

# === Titel ===
st.title("📊 Polar SAMAY H10 Live Dashboard")

# 🕒 Aktuelle Zeit (CET)
tz = pytz.timezone("Europe/Zurich")
now = datetime.now(tz)
current_time = now.strftime("%H:%M:%S")

# Anzeige oben rechts
st.markdown(
    f"<div style='text-align:right; color:gray; font-size:16px;'>🕒 Letztes Update: {current_time} (CET)</div>",
    unsafe_allow_html=True
)

# === Infozeile ===
st.info("📡 Echtzeitdaten aktiv – Anzeigezeitraum einstellbar im Seitenmenü")

# === MongoDB Verbindung ===
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/nightscout-db?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["nightscout-db"]
collection = db["polar_data"]

# === Seitenleiste ===
st.sidebar.header("⚙️ Einstellungen")
window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)

# === Daten abrufen (letzte X Minuten) ===
now = datetime.now(tz)
time_threshold = now - timedelta(minutes=window_minutes)
data = list(
    collection.find({"timestamp": {"$gte": time_threshold.isoformat()}})
    .sort("timestamp", 1)
)

# === Verarbeitung ===
if not data:
    st.warning(f"Keine Polar-Daten in den letzten {window_minutes} Minuten gefunden.")
else:
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp"] = df["timestamp"].dt.tz_convert("Europe/Zurich")

    df = df.set_index("timestamp").sort_index()

    # Zeitfenster
    baseline_window = df.last("10min")
    recent_data = df.last("60s")

    avg_hr = recent_data["hr"].mean() if not recent_data.empty else None
    avg_rmssd = recent_data["hrv_rmssd"].mean() if not recent_data.empty else None
    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None

    # === Metriken ===
    if avg_hr:
        st.metric(label="❤️ Durchschnittliche Herzfrequenz (60s)", value=f"{avg_hr:.1f} bpm")
    if avg_rmssd:
        st.metric(label="💓 Durchschnittlicher RMSSD (60s)", value=f"{avg_rmssd:.4f}")

    # === 🧠 Neurophysiologischer Zustand (3-Spalten-Version) ===
    st.markdown("### 🧠 Neurophysiologischer Zustand")

    if baseline_rmssd and avg_rmssd:
        delta_rmssd = avg_rmssd / baseline_rmssd

        # --- Zustand bestimmen ---
        if delta_rmssd < 0.7:
            state = "High Stress"
            color = "#e74c3c"
            description = "Dein Nervensystem ist stark sympathisch aktiviert – **Fight-or-Flight-Modus**."
            recommendation = "🌬️ Empfohlen: 4-7-8-Atmung oder 6 Atemzüge/Minute zur Aktivierung des Vagusnervs."
            level = 4

        elif delta_rmssd < 1.0:
            state = "Mild Stress"
            color = "#f39c12"
            description = "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt."
            recommendation = "🫁 Empfohlen: Längeres Ausatmen (z. B. 4 Sekunden ein, 8 Sekunden aus)."
            level = 3

        elif delta_rmssd < 1.3:
            state = "Balanced"
            color = "#f1c40f"
            description = "Dein Nervensystem ist in **Balance** – gute Regulation zwischen Aktivierung und Ruhe."
            recommendation = "☯️ Empfohlen: **Box Breathing (4-4-4-4)** zur Stabilisierung."
            level = 2

        else:
            state = "Recovery / Flow"
            color = "#2ecc71"
            description = "Hohe parasympathische Aktivität – dein Körper befindet sich im **Erholungsmodus**."
            recommendation = "🧘 Meditation oder ruhige Atmung fördern Regeneration und Flow."
            level = 1

        # --- Spaltenlayout ---
        col1, col2, col3 = st.columns([1, 2, 2])

        # === Spalte 1: Ampel ===
        with col1:
            st.markdown("<h4 style='text-align:center;'>🧭 Status</h4>", unsafe_allow_html=True)
            lamp_html = "<div style='display:flex; flex-direction:column; align-items:center;'>"
            colors = ["#2ecc71", "#f1c40f", "#f39c12", "#e74c3c"]
            for i, c in enumerate(colors, start=1):
                active = (i == level)
                lamp_html += f"""
                <div style='width:40px; height:40px; border-radius:50%;
                            background-color:{c if active else "#ddd"};
                            margin:6px; box-shadow:{'0 0 12px ' + c if active else 'none'};'></div>
                """
            lamp_html += "</div>"
            st.markdown(lamp_html, unsafe_allow_html=True)

        # === Spalte 2: Zustandstext ===
        with col2:
            st.markdown(f"<h3 style='color:{color}; text-align:center;'>{state}</h3>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center; font-size:16px;'>{description}</p>", unsafe_allow_html=True)

        # === Spalte 3: Empfehlung ===
        with col3:
            st.markdown("<h4 style='text-align:center;'>Empfehlung</h4>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align:center; font-size:15px; color:#333;'>{recommendation}</div>", unsafe_allow_html=True)

    else:
        st.info("Warte auf ausreichende HRV-Daten zur neurophysiologischen Analyse …")

    # === Diagramme ===
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hr"]])

    st.subheader(f"💓 HRV Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hrv_rmssd", "hrv_sdnn"]])

    st.subheader("🕒 Letzte Messwerte")
    st.dataframe(df.tail(10))
