import streamlit as st
import pandas as pd
from pymongo import MongoClient
import os
from datetime import datetime, timedelta
import pytz
from streamlit_autorefresh import st_autorefresh

# === Seitenkonfiguration ===
st.set_page_config(page_title="Polar SAMAY H10 Live Dashboard", layout="wide")

# --- Weißes minimalistisches Design & Helvetica ---
st.markdown("""
    <style>
        html, body, [class*="st-"] {
            background-color: white !important;
            color: #111 !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }

        h1, h2, h3, h4, h5 {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #111;
            font-weight: 600;
        }

        .stApp {
            background-color: white !important;
        }

        .metric-value {
            font-size: 24px !important;
            color: #111 !important;
        }

        .metric-label {
            color: #666 !important;
        }

        div.block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }

        /* Info-Box neutraler */
        .stAlert {
            background-color: #f6f8fa !important;
            border-radius: 10px !important;
            color: #222 !important;
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

st.markdown(
    f"<div style='text-align:right; color:#777; font-size:14px;'>🕒 Letztes Update: {current_time} (CET)</div>",
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

# === Daten abrufen ===
now = datetime.now(tz)
time_threshold = now - timedelta(minutes=window_minutes)
data = list(collection.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort("timestamp", 1))

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

    baseline_window = df.last("10min")
    recent_data = df.last("60s")

    avg_hr = recent_data["hr"].mean() if not recent_data.empty else None
    avg_rmssd = recent_data["hrv_rmssd"].mean() if not recent_data.empty else None
    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None

    # === Metriken ===
    colA, colB = st.columns(2)
    with colA:
        if avg_hr:
            st.metric(label="❤️ Durchschnittliche Herzfrequenz (60s)", value=f"{avg_hr:.1f} bpm")
    with colB:
        if avg_rmssd:
            st.metric(label="💓 Durchschnittlicher RMSSD (60s)", value=f"{avg_rmssd:.4f}")

    # === 🧠 Neurophysiologischer Zustand (3-Spalten-Layout) ===
    st.markdown("### 🧠 Neurophysiologischer Zustand")

    if baseline_rmssd and avg_rmssd:
        delta_rmssd = avg_rmssd / baseline_rmssd

        if delta_rmssd < 0.7:
            state, color, description, recommendation, level = (
                "High Stress", "#e74c3c",
                "Dein Nervensystem ist stark sympathisch aktiviert – **Fight-or-Flight-Modus**.",
                "🌬️ 4-7-8-Atmung oder 6 Atemzüge/Minute zur Aktivierung des Vagusnervs.",
                4
            )
        elif delta_rmssd < 1.0:
            state, color, description, recommendation, level = (
                "Mild Stress", "#f39c12",
                "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt.",
                "🫁 Längeres Ausatmen (4 Sek. ein, 8 Sek. aus).",
                3
            )
        elif delta_rmssd < 1.3:
            state, color, description, recommendation, level = (
                "Balanced", "#f1c40f",
                "Dein Nervensystem ist in **Balance** – gute Regulation zwischen Aktivierung und Ruhe.",
                "☯️ Box Breathing (4-4-4-4) zur Stabilisierung.",
                2
            )
        else:
            state, color, description, recommendation, level = (
                "Recovery / Flow", "#2ecc71",
                "Hohe parasympathische Aktivität – dein Körper ist im **Erholungsmodus**.",
                "🧘 Meditation oder ruhige Atmung fördern Flow & Regeneration.",
                1
            )

                # --- Layout: Ampel | Beschreibung | Empfehlung ---
        col1, col2, col3 = st.columns([1, 2, 2])

        # === Spalte 1: Ampel ===
        with col1:
            st.markdown("<h4 style='text-align:center;'>🧭 Status</h4>", unsafe_allow_html=True)

            colors = ["#2ecc71", "#f1c40f", "#f39c12", "#e74c3c"]
            lamp_html = """
            <div style='display:flex; flex-direction:column; align-items:center; justify-content:center; margin-top:10px;'>
            """
            for i, c in enumerate(colors, start=1):
                active = (i == level)
                lamp_html += f"""
                    <div style='width:42px; height:42px; border-radius:50%;
                                background-color:{c if active else "#e6e6e6"};
                                margin:8px 0;
                                box-shadow:{'0 0 14px ' + c if active else 'inset 0 0 4px #ccc'};
                                transition:all 0.3s ease;
                                opacity:{'1' if active else '0.4'};'></div>
                """
            lamp_html += "</div>"
            st.markdown(lamp_html, unsafe_allow_html=True)

        # === Spalte 2: Zustand ===
        with col2:
            st.markdown(f"""
                <div style='text-align:center;'>
                    <h3 style='color:{color}; margin-bottom:4px;'>{state}</h3>
                    <p style='font-size:16px; color:#333; line-height:1.5; margin:0 auto; max-width:90%;'>
                        {description}
                    </p>
                </div>
            """, unsafe_allow_html=True)

        # === Spalte 3: Empfehlung ===
        with col3:
            st.markdown(f"""
                <div style='text-align:center;'>
                    <h4 style='margin-bottom:4px;'>💡 Empfehlung</h4>
                    <p style='font-size:15px; color:#444; line-height:1.5; margin:0 auto; max-width:90%;'>
                        {recommendation}
                    </p>
                </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown(f"<h3 style='color:{color}; text-align:center; margin-bottom:0;'>{state}</h3>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center; font-size:16px; color:#333; margin-top:6px;'>{description}</p>", unsafe_allow_html=True)

        with col3:
            st.markdown("<h4 style='text-align:center;'>💡 Empfehlung</h4>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align:center; font-size:15px; color:#444;'>{recommendation}</p>", unsafe_allow_html=True)

    else:
        st.info("Warte auf ausreichende HRV-Daten zur neurophysiologischen Analyse …")

    # === Diagramme ===
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hr"]])

    st.subheader(f"💓 HRV Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    st.line_chart(df[["hrv_rmssd", "hrv_sdnn"]])

    st.subheader("🕒 Letzte Messwerte")
    st.dataframe(df.tail(10))
