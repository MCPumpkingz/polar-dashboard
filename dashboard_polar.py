import streamlit as st
import pandas as pd
from pymongo import MongoClient
import os
from datetime import datetime, timedelta
import pytz
from streamlit_autorefresh import st_autorefresh

# === Seitenkonfiguration ===
st.set_page_config(page_title="Polar H10 Live Dashboard", layout="wide")

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

# === Seitenleiste für Einstellungen ===
st.sidebar.header("⚙️ Einstellungen")
window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)

# === Daten abrufen (letzte X Minuten) ===
now = datetime.now(tz)
time_threshold = now - timedelta(minutes=window_minutes)

data = list(
    collection.find({"timestamp": {"$gte": time_threshold.isoformat()}})
    .sort("timestamp", 1)
)

# === Verarbeitung & Anzeige ===
if not data:
    st.warning(f"Keine Polar-Daten in den letzten {window_minutes} Minuten gefunden.")
else:
    df = pd.DataFrame(data)

    # Zeitstempel sicher konvertieren (auch wenn UTC oder naive)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    # Zeitzone sicherstellen
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp"] = df["timestamp"].dt.tz_convert("Europe/Zurich")

    df = df.set_index("timestamp").sort_index()

    # 💓 Durchschnitt der letzten 60 Sekunden
    recent_data = df.last("60s")
    avg_hr = recent_data["hr"].mean() if not recent_data.empty else None
    avg_rmssd = recent_data["hrv_rmssd"].mean() if not recent_data.empty else None

    if avg_hr:
        st.metric(label="❤️ Durchschnittliche Herzfrequenz (60s)", value=f"{avg_hr:.1f} bpm")
    if avg_rmssd:
        st.metric(label="💓 Durchschnittlicher RMSSD (60s)", value=f"{avg_rmssd:.4f}")

    # === 🧠 SAMAY_Style Neurophysiologischer Zustand ===
    st.markdown("### 🧠 Neurophysiologischer Zustand")

    if avg_rmssd is not None and avg_hr is not None and not df.empty:
        if avg_rmssd < 20 or avg_hr > 85:
            state = "🔴 High Stress"
            description = (
                "Dein Nervensystem ist stark sympathisch aktiviert – der Körper befindet sich im **'Fight-or-Flight'-Modus**. "
                "Empfohlen: 6 Atemzüge pro Minute oder 4-7-8-Atmung zur Aktivierung des Vagusnervs."
            )
            color = "#e74c3c"

        elif avg_rmssd < 40 or avg_hr > 75:
            state = "🟠 Mild Stress"
            description = (
                "Leichte sympathische Aktivierung. Du bist wach, fokussiert, aber nicht überlastet. "
                "Empfohlen: **langes Ausatmen** (z. B. 4 Sekunden ein, 8 Sekunden aus)."
            )
            color = "#f39c12"

        elif avg_rmssd < 60:
            state = "🟡 Balanced"
            description = (
                "Dein autonomes Nervensystem ist in **Balance**. "
                "Gute Regulation zwischen Aktivierung und Erholung. "
                "Empfohlen: **Box-Breathing (4-4-4-4)** zur Stabilisierung."
            )
            color = "#f1c40f"

        else:
            state = "🟢 Recovery / Flow"
            description = (
                "Hohe parasympathische Aktivität – dein Körper befindet sich im **Regenerationsmodus**. "
                "Optimale Bedingungen für Lernen, Erholung und Flow-Zustände."
            )
            color = "#2ecc71"

        st.markdown(
            f"""
            <div style='background-color:{color}; padding:20px; border-radius:12px;'>
              <h3 style='color:white; text-align:center;'>{state}</h3>
              <p style='color:white; font-size:16px; text-align:center;'>{description}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.info("Warte auf ausreichende HRV-Daten zur neurophysiologischen Analyse …")

    # === Diagramme ===
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hr"]])

    st.subheader(f"💓 HRV Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hrv_rmssd", "hrv_sdnn"]])

    st.subheader("🕒 Letzte Messwerte")
    st.dataframe(df.tail(10))
