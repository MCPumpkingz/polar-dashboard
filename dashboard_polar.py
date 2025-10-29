import os
from datetime import datetime, timedelta

import pandas as pd
import pytz
import streamlit as st
from pymongo import MongoClient

# Attempt to import plotly; if unavailable install it on the fly.
try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly"])
    import plotly.graph_objects as go

# We use streamlit_autorefresh to periodically refresh the data.
try:
    from streamlit_autorefresh import st_autorefresh
except ModuleNotFoundError:
    st_autorefresh = None


def connect_to_mongo() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Connect to MongoDB and return the polar and glucose dataframes."""
    MONGO_URI = os.getenv(
        "MONGO_URI"
    ) or "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/?retryWrites=true&w=majority"

    client = MongoClient(MONGO_URI)
    db_polar = client["nightscout-db"]
    col_polar = db_polar["polar_data"]
    db_glucose = client["nightscout"]
    col_glucose = db_glucose["entries"]

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    window_minutes = st.session_state.get("window_minutes", 15)
    time_threshold = now - timedelta(minutes=window_minutes)

    # === Polar Data ===
    polar_data = list(
        col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort("timestamp", 1)
    )
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # === Glucose Data (Nightscout) ===
    time_threshold_utc = (now - timedelta(minutes=window_minutes)).astimezone(pytz.UTC)
    glucose_data = list(
        col_glucose.find({"dateString": {"$gte": time_threshold_utc.isoformat()}}).sort("dateString", 1)
    )
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(df_glucose["dateString"], errors="coerce", utc=True)
        df_glucose["timestamp"] = df_glucose["timestamp"].dt.tz_convert("Europe/Zurich")
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


def compute_metrics(df_polar: pd.DataFrame, df_glucose: pd.DataFrame, window_minutes: int) -> dict:
    """Compute summary statistics for HR, HRV and glucose."""
    metrics = {}
    if not df_polar.empty:
        baseline_window = df_polar.last("10min")
        recent_data = df_polar.last("60s")
        long_window = df_polar.last(f"{window_minutes}min")

        # Heart rate means
        avg_hr_60s = recent_data["hr"].mean()
        avg_hr_long = long_window["hr"].mean()
        delta_hr = None
        if avg_hr_long and avg_hr_60s:
            delta_hr = avg_hr_60s - avg_hr_long

        # HRV RMSSD means (in seconds, convert to ms when displayed)
        avg_rmssd_60s = recent_data["hrv_rmssd"].mean()
        avg_rmssd_long = long_window["hrv_rmssd"].mean()
        delta_rmssd = None
        if avg_rmssd_long and avg_rmssd_60s:
            delta_rmssd = (avg_rmssd_60s - avg_rmssd_long) * 1000

        avg_sdnn_60s = None
        avg_sdnn_long = None
        if "hrv_sdnn" in df_polar.columns:
            avg_sdnn_60s = recent_data["hrv_sdnn"].mean()
            avg_sdnn_long = long_window["hrv_sdnn"].mean()

        # Latest glucose value
        latest_glucose = None
        if not df_glucose.empty and "sgv" in df_glucose.columns:
            latest_glucose = df_glucose["sgv"].iloc[-1]

        metrics.update(
            {
                "avg_hr_60s": avg_hr_60s,
                "avg_hr_long": avg_hr_long,
                "delta_hr": delta_hr,
                "avg_rmssd_60s": avg_rmssd_60s,
                "avg_rmssd_long": avg_rmssd_long,
                "delta_rmssd": delta_rmssd,
                "avg_sdnn_60s": avg_sdnn_60s,
                "avg_sdnn_long": avg_sdnn_long,
                "latest_glucose": latest_glucose,
            }
        )
    return metrics


def create_combined_plot(df_polar: pd.DataFrame, df_glucose: pd.DataFrame) -> go.Figure:
    """Create a combined Plotly figure for HR, HRV and Glucose."""
    fig = go.Figure()
    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hr"], name="Herzfrequenz (bpm)", mode="lines"))
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(go.Scatter(x=df_polar.index, y=df_polar["hrv_rmssd"] * 1000, name="HRV RMSSD (ms)", mode="lines", yaxis="y2"))
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(go.Scatter(x=df_glucose.index, y=df_glucose["sgv"], name="Glukose (mg/dL)", mode="lines", yaxis="y3"))

    fig.update_layout(
        template="plotly_white",
        height=450,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(title="HRV (ms)", overlaying="y", side="right", position=0.9, showgrid=False),
        yaxis3=dict(title="Glukose (mg/dL)", overlaying="y", side="right", position=1.0, showgrid=False),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
    )
    return fig


def main() -> None:
    """Run the Streamlit app."""
    st.set_page_config(page_title="Biofeedback Dashboard – Polar & CGM", page_icon="💓", layout="wide")

    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("Biofeedback Dashboard – Polar & CGM")
    st.markdown(f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>", unsafe_allow_html=True)

    st.sidebar.header("⚙️ Einstellungen")
    window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
    st.session_state["window_minutes"] = window_minutes

    if st_autorefresh:
        st_autorefresh(interval=2000, key="datarefresh")

    df_polar, df_glucose = connect_to_mongo()
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)

    # === Summary metrics ===
    with st.container(horizontal=True, gap="medium"):
        cols = st.columns(3, gap="medium")
        # HR
        with cols[0]:
            hr_value = metrics.get("avg_hr_60s")
            delta_hr = metrics.get("delta_hr")
            st.metric("❤️ Herzfrequenz (60 s)", f"{hr_value:.1f} bpm" if hr_value else "–",
                      f"{delta_hr:+.1f} bpm" if delta_hr else None)
        # HRV
        with cols[1]:
            rmssd_value = metrics.get("avg_rmssd_60s")
            delta_rmssd = metrics.get("delta_rmssd")
            st.metric("💓 HRV RMSSD (60 s)",
                      f"{rmssd_value * 1000:.1f} ms" if rmssd_value else "–",
                      f"{delta_rmssd:+.1f} ms" if delta_rmssd else None)
        # Glucose + Trend
        with cols[2]:
            glucose_value = metrics.get("latest_glucose")
            glucose_delta = df_glucose["delta"].iloc[-1] if not df_glucose.empty and "delta" in df_glucose.columns else None
            glucose_direction = df_glucose["direction"].iloc[-1] if not df_glucose.empty and "direction" in df_glucose.columns else None

            if glucose_value is not None:
                arrow = {"DoubleUp": "⬆️⬆️", "SingleUp": "⬆️", "FortyFiveUp": "↗️",
                         "Flat": "➡️", "FortyFiveDown": "↘️", "SingleDown": "⬇️", "DoubleDown": "⬇️⬇️"}.get(glucose_direction, "➡️")
                delta_str = f"{glucose_delta:+.1f} mg/dL/min" if glucose_delta else None
                st.metric(f"🩸 Glukose {arrow}", f"{glucose_value:.0f} mg/dL", delta_str)
            else:
                st.metric("🩸 Glukose", "–", None)

    # === Combined signal ===
    st.subheader(f"📈 Gesamtsignal – letzte {window_minutes} Minuten")
    if not df_polar.empty or not df_glucose.empty:
        st.container(border=True, height="stretch").plotly_chart(create_combined_plot(df_polar, df_glucose), use_container_width=True)
    else:
        st.info("Keine Daten im aktuellen Zeitraum verfügbar.")

    # === Einzelcharts ===
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    if not df_polar.empty and "hr" in df_polar.columns:
        st.container(border=True, height="stretch").line_chart(df_polar[["hr"]])
    else:
        st.info("Keine Herzfrequenzdaten verfügbar.")

    st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    if not df_polar.empty and any(col in df_polar.columns for col in ["hrv_rmssd", "hrv_sdnn"]):
        cols_to_plot = [c for c in ["hrv_rmssd", "hrv_sdnn"] if c in df_polar.columns]
        st.container(border=True, height="stretch").line_chart(df_polar[cols_to_plot])
    else:
        st.info("Keine HRV-Daten verfügbar.")

    st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        st.container(border=True, height="stretch").line_chart(df_glucose[["sgv"]])
    else:
        st.info("Keine CGM-Daten verfügbar.")

    # === Data tables ===
    if not df_polar.empty:
        st.subheader("🕒 Letzte Polar-Messwerte")
        st.container(border=True, height="stretch").dataframe(df_polar.tail(10))
    else:
        st.info("Keine Polar-Messwerte verfügbar.")

    if not df_glucose.empty:
        st.subheader("🕒 Letzte CGM-Messwerte")
        st.container(border=True, height="stretch").dataframe(df_glucose.tail(10))
    else:
        st.info("Keine CGM-Messwerte verfügbar.")


if __name__ == "__main__":
    main()
