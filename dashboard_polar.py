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
        .stAlert {
            background-color: #f6f8fa !important;
            border-radius: 10px !important;
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

    avg_hr = recent_data["hr"].mean() if not recent_data.empty else None
    avg_rmssd = recent_data["hrv_rmssd"].mean() if not recent_data.empty else None
    baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None

    # Metriken
    colA, colB = st.columns(2)
    with colA:
        if avg_hr:
            st.metric("❤️ Durchschnittliche Herzfrequenz (60 s)", f"{avg_hr:.1f} bpm")
    with colB:
        if avg_rmssd:
            st.metric("💓 Durchschnittlicher RMSSD (60 s)", f"{avg_rmssd:.4f}")

    # Zustand bestimmen
    if baseline_rmssd and avg_rmssd:
        delta_rmssd = avg_rmssd / baseline_rmssd
        if delta_rmssd < 0.7:
            state, color, desc, reco, level = (
                "High Stress", "#e74c3c",
                "Dein Nervensystem ist stark sympathisch aktiviert – **Fight or Flight**.",
                "🌬️ 4-7-8-Atmung oder 6 Atemzüge/min zur Aktivierung des Vagusnervs.", 4)
        elif delta_rmssd < 1.0:
            state, color, desc, reco, level = (
                "Mild Stress", "#f39c12",
                "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt.",
                "🫁 Längeres Ausatmen (4 s ein, 8 s aus).", 3)
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

        # === Layout: Ampel + Textblöcke ===
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
        st.info("Warte auf ausreichende HRV-Daten zur Analyse …")

# === Gesamtdiagramm Rohdaten ===
st.subheader(f"📈 Rohdaten-Übersicht – letzte {window_minutes} Minuten")
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
    st.warning("Keine Daten zum Anzeigen gefunden.")


# === Einzelcharts ===
if not df_polar.empty:
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    st.line_chart(df_polar[["hr"]])
    st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    st.line_chart(df_polar[["hrv_rmssd", "hrv_sdnn"]])

if not df_glucose.empty:
    st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
    st.line_chart(df_glucose[["sgv"]])

# === Verlauf Neurophysiologischer Zustand ===
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

    st.subheader(f"🧠 Neurophysiologischer Zustand (Verlauf) – letzte {window_minutes} Minuten")
    fig_state = go.Figure()
    for sv, color in colors.items():
        sd = df_polar[df_polar["state_value"] == sv]
        if not sd.empty:
            fig_state.add_trace(go.Scatter(x=sd.index, y=sd["state_value"], mode="lines",
                                           line=dict(width=0.5, color=color), fill="tozeroy", fillcolor=color,
                                           name={1:"Flow",2:"Balanced",3:"Mild Stress",4:"High Stress"}[sv], opacity=0.7))
    fig_state.update_layout(
        yaxis=dict(tickvals=[1,2,3,4],ticktext=["Flow","Balanced","Mild Stress","High Stress"],range=[0.5,4.5],title="Zustand"),
        xaxis_title="Zeit", showlegend=True, template="plotly_white", height=400,
        margin=dict(l=40,r=40,t=10,b=40)
    )
    st.plotly_chart(fig_state, use_container_width=True)

# === Tabellen ===
if not df_polar.empty:
    st.subheader("🕒 Letzte Polar-Messwerte")
    st.dataframe(df_polar.tail(10))
if not df_glucose.empty:
    st.subheader("🕒 Letzte CGM-Messwerte")
    st.dataframe(df_glucose.tail(10))
