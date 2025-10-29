import os
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st
from pymongo import MongoClient

# Plotly sicherstellen
try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly"])
    import plotly.graph_objects as go

# Auto-Refresh für Live-Daten
try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    st_autorefresh = None


def connect_to_mongo():
    """Stellt Verbindung zu MongoDB her und gibt Polar- & Glukose-Datenframes zurück."""
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


def compute_metrics(df_polar, df_glucose, window_minutes):
    """Berechnet Durchschnittswerte & Deltas."""
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


def create_combined_plot(df_polar, df_glucose):
    """Erstellt kombinierten Plot für HR, HRV & Glukose."""
    fig = go.Figure()

    # Auto-Range für Glukose
    y_min, y_max = (40, 180)
    if not df_glucose.empty:
        g_min = df_glucose["sgv"].min()
        g_max = df_glucose["sgv"].max()
        padding = 10
        y_min = max(40, g_min - padding)
        y_max = min(250, g_max + padding)

    # Herzfrequenz (rot)
    if "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hr"], name="Herzfrequenz (bpm)",
            mode="lines", line=dict(color="#e74c3c", width=2)
        ))

    # HRV RMSSD (blau)
    if "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000, name="HRV RMSSD (ms)",
            mode="lines", yaxis="y2", line=dict(color="#2980b9", width=2)
        ))

    # HRV SDNN (hellblau)
    if "hrv_sdnn" in df_polar.columns:
        fig.add_trace(go.Scatter(
            x=df_polar.index, y=df_polar["hrv_sdnn"], name="HRV SDNN (ms)",
            mode="lines", yaxis="y2", line=dict(color="#5dade2", width=2, dash="dot")
        ))

    # Glukose (grün)
    if not df_glucose.empty:
        fig.add_trace(go.Scatter(
            x=df_glucose.index, y=df_glucose["sgv"], name="Glukose (mg/dL)",
            mode="lines", yaxis="y3", line=dict(color="#27ae60", width=3, shape="spline")
        ))

    # Zielbereich
    fig.add_shape(type="rect", xref="paper", x0=0, x1=1,
                  yref="y3", y0=70, y1=140,
                  fillcolor="rgba(46, 204, 113, 0.15)", line=dict(width=0), layer="below")

    fig.update_layout(
        template="plotly_white",
        height=450,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", position=0.9, showgrid=False),
        yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", position=1.0, showgrid=False,
                    range=[y_min, y_max]),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5)
    )
    return fig


def main():
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="💓", layout="wide")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>",
                unsafe_allow_html=True)

    st.sidebar.header("⚙️ Einstellungen")
    window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    if st_autorefresh:
        st_autorefresh(interval=2000, key="datarefresh")

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)

    # === METRIC OVERVIEW ===
    st.markdown("### 🔍 Live-Übersicht")
    cols = st.columns(3)
    with cols[0]:
        hr = metrics.get("avg_hr_60s")
        delta = metrics.get("delta_hr")
        st.metric("❤️ Herzfrequenz (60 s)", f"{hr:.1f} bpm" if hr else "–",
                  f"{delta:+.1f} bpm" if delta else None)
    with cols[1]:
        hrv = metrics.get("avg_rmssd_60s")
        delta_hrv = metrics.get("delta_rmssd")
        st.metric("💓 HRV RMSSD (60 s)",
                  f"{hrv * 1000:.1f} ms" if hrv else "–",
                  f"{delta_hrv:+.1f} ms" if delta_hrv else None)
    with cols[2]:
        gl = metrics.get("latest_glucose")
        st.metric("🩸 Glukose", f"{gl:.0f} mg/dL" if gl else "–")

    # === COMBINED PLOT ===
    st.subheader(f"📈 Gesamtsignal – letzte {window_minutes} Minuten")
    if not df_polar.empty or not df_glucose.empty:
        st.container(border=True).plotly_chart(create_combined_plot(df_polar, df_glucose),
                                               use_container_width=True)
    else:
        st.info("Keine Daten im aktuellen Zeitraum verfügbar.")

    # === EINZEL-CHARTS ===
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    if not df_polar.empty:
        fig_hr = go.Figure()
        fig_hr.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], mode="lines",
                                    line=dict(color="#e74c3c", width=2), name="Herzfrequenz (bpm)"))
        fig_hr.update_layout(template="plotly_white", height=300, margin=dict(l=0, r=0, t=0, b=0),
                             xaxis=dict(title="Zeit", range=[df_polar.index.min(), df_polar.index.max()]),
                             yaxis=dict(title="HR (bpm)"))
        st.container(border=True).plotly_chart(fig_hr, use_container_width=True)

    st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    if not df_polar.empty:
        fig_hrv = go.Figure()
        if "hrv_rmssd" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"],
                                         mode="lines", line=dict(color="#2980b9", width=2), name="HRV RMSSD"))
        if "hrv_sdnn" in df_polar.columns:
            fig_hrv.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_sdnn"],
                                         mode="lines", line=dict(color="#5dade2", width=2, dash="dot"),
                                         name="HRV SDNN"))
        fig_hrv.update_layout(template="plotly_white", height=300, margin=dict(l=0, r=0, t=0, b=0),
                              xaxis=dict(title="Zeit", range=[df_polar.index.min(), df_polar.index.max()]),
                              yaxis=dict(title="HRV (s)"))
        st.container(border=True).plotly_chart(fig_hrv, use_container_width=True)

    st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
    if not df_glucose.empty:
        min_val, max_val = df_glucose["sgv"].min(), df_glucose["sgv"].max()
        padding = 10
        y_min, y_max = max(40, min_val - padding), min(250, max_val + padding)
        fig_glucose = go.Figure()
        fig_glucose.add_shape(type="rect", xref="paper", x0=0, x1=1,
                              yref="y", y0=70, y1=140,
                              fillcolor="rgba(46,204,113,0.2)", line=dict(width=0), layer="below")
        fig_glucose.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], mode="lines+markers",
                                         line=dict(color="#27ae60", width=2),
                                         marker=dict(size=4), name="Glukose (mg/dL)"))
        fig_glucose.update_layout(template="plotly_white", height=300,
                                  margin=dict(l=0, r=0, t=0, b=0),
                                  xaxis=dict(title="Zeit",
                                             range=[df_polar.index.min(), df_polar.index.max()]),
                                  yaxis=dict(title="Glukose (mg/dL)", range=[y_min, y_max]))
        st.container(border=True).plotly_chart(fig_glucose, use_container_width=True)
        st.markdown(f"<small>Y-Achse auto ({y_min:.0f}–{y_max:.0f} mg/dL), Zielbereich 70–140 mg/dL (grün)</small>",
                    unsafe_allow_html=True)

    # === TABELLEN ===
    if not df_polar.empty:
        st.subheader("🕒 Letzte Polar-Messwerte")
        st.dataframe(df_polar.tail(10))
    if not df_glucose.empty:
        st.subheader("🕒 Letzte CGM-Messwerte")
        st.dataframe(df_glucose.tail(10))


if __name__ == "__main__":
    main()
