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
    # st_autorefresh is part of streamlit‑extras; if it isn't installed
    # the dashboard will run without auto refresh.
    st_autorefresh = None


def connect_to_mongo() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Connect to MongoDB and return the polar and glucose dataframes.

    Returns
    -------
    tuple of two pandas.DataFrame
        The first dataframe contains Polar data with a datetime index.
        The second dataframe contains CGM glucose data with a datetime index.
    """
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

    # Fetch Polar data
    polar_data = list(
        col_polar.find({"timestamp": {"$gte": time_threshold.isoformat()}}).sort(
            "timestamp", 1
        )
    )
    df_polar = pd.DataFrame(polar_data)
    if not df_polar.empty:
        df_polar["timestamp"] = pd.to_datetime(df_polar["timestamp"], errors="coerce")
        df_polar = df_polar.set_index("timestamp").sort_index()

    # Fetch glucose data
    glucose_data = list(
        col_glucose.find({"dateString": {"$gte": time_threshold.isoformat()}}).sort(
            "dateString", 1
        )
    )
    df_glucose = pd.DataFrame(glucose_data)
    if not df_glucose.empty:
        df_glucose["timestamp"] = pd.to_datetime(
            df_glucose["dateString"], errors="coerce"
        )
        df_glucose = df_glucose.set_index("timestamp").sort_index()

    return df_polar, df_glucose


def compute_metrics(df_polar: pd.DataFrame, df_glucose: pd.DataFrame, window_minutes: int) -> dict:
    """Compute summary statistics for HR, HRV and glucose.

    Parameters
    ----------
    df_polar : pandas.DataFrame
        Polar data indexed by timestamp.
    df_glucose : pandas.DataFrame
        CGM data indexed by timestamp.
    window_minutes : int
        The length of the window over which to compute long term averages.

    Returns
    -------
    dict
        Dictionary of calculated averages, baseline values and deltas.
    """
    metrics = {}
    if not df_polar.empty:
        # Define windows
        baseline_window = df_polar.last("10min")
        recent_data = df_polar.last("60s")
        long_window = df_polar.last(f"{window_minutes}min")

        # Heart rate means
        avg_hr_60s = recent_data["hr"].mean()
        avg_hr_long = long_window["hr"].mean()
        baseline_hr = baseline_window["hr"].mean() if not baseline_window.empty else None
        delta_hr = None
        if avg_hr_long and avg_hr_60s:
            delta_hr = avg_hr_60s - avg_hr_long

        # HRV RMSSD means (in seconds, convert to ms when displayed)
        avg_rmssd_60s = recent_data["hrv_rmssd"].mean()
        avg_rmssd_long = long_window["hrv_rmssd"].mean()
        baseline_rmssd = baseline_window["hrv_rmssd"].mean() if not baseline_window.empty else None
        delta_rmssd = None
        if avg_rmssd_long and avg_rmssd_60s:
            delta_rmssd = (avg_rmssd_60s - avg_rmssd_long) * 1000  # convert to ms

        # HRV SDNN means (if available)
        avg_sdnn_60s = None
        avg_sdnn_long = None
        if "hrv_sdnn" in df_polar.columns:
            avg_sdnn_60s = recent_data["hrv_sdnn"].mean()
            avg_sdnn_long = long_window["hrv_sdnn"].mean()

        # Determine neurophysiological state
        state = None
        state_desc = None
        recommendation = None
        state_color = None
        if baseline_rmssd and avg_rmssd_60s:
            ratio = avg_rmssd_60s / baseline_rmssd
            if ratio < 0.7:
                state = "High Stress"
                state_desc = "Stark sympathische Aktivierung – **Fight or Flight**."
                recommendation = "🌬️ 4-7-8-Atmung oder 6 Atemzüge/min zur Aktivierung des Vagusnervs."
                state_color = "#e74c3c"
            elif ratio < 1.0:
                state = "Mild Stress"
                state_desc = "Leichte sympathische Aktivierung – du bist **fokussiert**, aber angespannt."
                recommendation = "🫁 Längeres Ausatmen (4 s ein / 8 s aus)."
                state_color = "#f39c12"
            elif ratio < 1.3:
                state = "Balanced"
                state_desc = "Dein Nervensystem ist in **Balance**."
                recommendation = "☯️ Box Breathing (4-4-4-4) zur Stabilisierung."
                state_color = "#f1c40f"
            else:
                state = "Recovery / Flow"
                state_desc = "Hohe parasympathische Aktivität – du bist im **Erholungsmodus**."
                recommendation = "🧘 Meditation oder ruhige Atmung fördern Flow & Regeneration."
                state_color = "#2ecc71"

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
                "state": state,
                "state_desc": state_desc,
                "recommendation": recommendation,
                "state_color": state_color,
                "latest_glucose": latest_glucose,
            }
        )

    return metrics


def create_combined_plot(df_polar: pd.DataFrame, df_glucose: pd.DataFrame) -> go.Figure:
    """Create a combined Plotly figure for HR, HRV and Glucose."""
    fig = go.Figure()
    # Heart Rate
    if not df_polar.empty and "hr" in df_polar.columns:
        fig.add_trace(
            go.Scatter(
                x=df_polar.index,
                y=df_polar["hr"],
                name="Herzfrequenz (bpm)",
                mode="lines",
            )
        )
    # HRV RMSSD (converted to ms)
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        fig.add_trace(
            go.Scatter(
                x=df_polar.index,
                y=df_polar["hrv_rmssd"] * 1000,
                name="HRV RMSSD (ms)",
                mode="lines",
                yaxis="y2",
            )
        )
    # Glucose
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        fig.add_trace(
            go.Scatter(
                x=df_glucose.index,
                y=df_glucose["sgv"],
                name="Glukose (mg/dL)",
                mode="lines",
                yaxis="y3",
            )
        )

    # Layout with multiple y axes similar to the original dashboard.
    fig.update_layout(
        template="plotly_white",
        height=450,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(title="Zeit"),
        yaxis=dict(title="HR (bpm)"),
        yaxis2=dict(
            title="HRV (ms)",
            overlaying="y",
            side="right",
            position=0.9,
            showgrid=False,
        ),
        yaxis3=dict(
            title="Glukose (mg/dL)",
            overlaying="y",
            side="right",
            position=1.0,
            showgrid=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="center",
            x=0.5,
        ),
    )
    return fig


def create_state_timeline(df_polar: pd.DataFrame) -> go.Figure:
    """Create a timeline figure for the neurophysiological state over time."""
    fig = go.Figure()
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        baseline_rmssd = df_polar["hrv_rmssd"].last("10min").mean()
        # Map ratio to discrete state values
        def get_state_value(rmssd: float, baseline: float) -> int | None:
            if not baseline or rmssd is None:
                return None
            ratio = rmssd / baseline
            if ratio < 0.7:
                return 4  # High Stress
            elif ratio < 1.0:
                return 3  # Mild Stress
            elif ratio < 1.3:
                return 2  # Balanced
            else:
                return 1  # Flow / Recovery

        df_polar = df_polar.copy()
        df_polar["state_value"] = df_polar["hrv_rmssd"].apply(
            lambda x: get_state_value(x, baseline_rmssd)
        )
        state_colors = {1: "#2ecc71", 2: "#f1c40f", 3: "#f39c12", 4: "#e74c3c"}
        state_names = {
            1: "Flow / Recovery",
            2: "Balanced",
            3: "Mild Stress",
            4: "High Stress",
        }
        for value, color in state_colors.items():
            subset = df_polar[df_polar["state_value"] == value]
            if not subset.empty:
                fig.add_trace(
                    go.Scatter(
                        x=subset.index,
                        y=subset["state_value"],
                        mode="lines",
                        line=dict(width=0.5, color=color),
                        fill="tozeroy",
                        fillcolor=color,
                        name=state_names[value],
                        opacity=0.7,
                    )
                )
        fig.update_layout(
            template="plotly_white",
            height=350,
            yaxis=dict(
                tickvals=[1, 2, 3, 4],
                ticktext=[
                    "Flow / Recovery",
                    "Balanced",
                    "Mild Stress",
                    "High Stress",
                ],
                range=[0.5, 4.5],
                title="Zustand",
            ),
            xaxis=dict(title="Zeit"),
            showlegend=True,
        )
    return fig


def main() -> None:
    """Run the Streamlit app with a layout inspired by the Seattle Weather demo."""
    st.set_page_config(
        page_title="Biofeedback Dashboard – Polar & CGM",
        page_icon="💓",
        layout="wide",
    )

    # Title and last update time
    tz = pytz.timezone("Europe/Zurich")
    now = datetime.now(tz)
    st.title("📊 Biofeedback System – Polar H10 & CGM Live Dashboard")
    st.markdown(
        f"<div style='text-align:right;color:#777;'>🕒 Letztes Update: {now.strftime('%H:%M:%S')} (CET)</div>",
        unsafe_allow_html=True,
    )

    # Sidebar settings
    st.sidebar.header("⚙️ Einstellungen")
    window_minutes = st.sidebar.slider("Zeitfenster (in Minuten)", 5, 60, 15)
    # Save to session state for use in data loading
    st.session_state["window_minutes"] = window_minutes

    # Auto refresh every 2 seconds if st_autorefresh is available
    if st_autorefresh:
        st_autorefresh(interval=2000, key="datarefresh")

    # Informational message
    st.info("📡 Echtzeitdaten aktiv – Anzeigezeitraum einstellbar im Seitenmenü")

    # Load data
    df_polar, df_glucose = connect_to_mongo()

    # Compute metrics
    metrics = compute_metrics(df_polar, df_glucose, window_minutes)

    # Summary metrics container
    with st.container(horizontal=True, gap="medium"):
        cols = st.columns(3, gap="medium")
        # Heart Rate metric
        with cols[0]:
            hr_value = metrics.get("avg_hr_60s")
            hr_long = metrics.get("avg_hr_long")
            delta_hr = metrics.get("delta_hr")
            if hr_value is not None:
                st.metric(
                    label="❤️ Herzfrequenz (60 s)",
                    value=f"{hr_value:.1f} bpm",
                    delta=f"{delta_hr:+.1f} bpm" if delta_hr is not None else None,
                )
            else:
                st.metric(label="❤️ Herzfrequenz (60 s)", value="–", delta=None)

        # HRV metric
        with cols[1]:
            rmssd_value = metrics.get("avg_rmssd_60s")
            rmssd_long = metrics.get("avg_rmssd_long")
            delta_rmssd = metrics.get("delta_rmssd")
            if rmssd_value is not None:
                st.metric(
                    label="💓 HRV RMSSD (60 s)",
                    value=f"{rmssd_value * 1000:.1f} ms",
                    delta=f"{delta_rmssd:+.1f} ms" if delta_rmssd is not None else None,
                )
            else:
                st.metric(label="💓 HRV RMSSD (60 s)", value="–", delta=None)

        # Glucose metric
        with cols[2]:
            glucose_value = metrics.get("latest_glucose")
            if glucose_value is not None:
                st.metric(
                    label="🩸 Glukose", value=f"{glucose_value:.0f} mg/dL", delta=None
                )
            else:
                st.metric(label="🩸 Glukose", value="–", delta=None)

    # Neurophysiological state and recommendation
    state = metrics.get("state")
    state_desc = metrics.get("state_desc")
    recommendation = metrics.get("recommendation")
    state_color = metrics.get("state_color")

    if state:
        cols_state = st.columns(2)
        with cols_state[0].container(border=True, height="stretch"):
            st.subheader("🧠 Neurophysiologischer Zustand")
            st.markdown(
                f"<h3 style='color:{state_color}; font-weight:700; margin-top:4px;'>{state}</h3>",
                unsafe_allow_html=True,
            )
            st.markdown(state_desc)
        with cols_state[1].container(border=True, height="stretch"):
            st.subheader("💡 Empfehlung")
            st.markdown(recommendation)
    else:
        st.warning("Warte auf ausreichende HRV-Daten zur Analyse …")

    # Combined signals overview
    st.subheader(f"📈 Gesamtsignal-Übersicht – letzte {window_minutes} Minuten")
    if not df_polar.empty or not df_glucose.empty:
        fig = create_combined_plot(df_polar, df_glucose)
        st.container(border=True, height="stretch").plotly_chart(fig, use_container_width=True)
    else:
        st.info("Keine Daten im aktuellen Zeitraum verfügbar.")

    # Individual charts
    # Heart Rate
    st.subheader(f"❤️ Herzfrequenz (HR) – letzte {window_minutes} Minuten")
    if not df_polar.empty and "hr" in df_polar.columns:
        with st.container(border=True, height="stretch"):
            st.line_chart(df_polar[["hr"]])
    else:
        st.info("Keine Herzfrequenzdaten verfügbar.")

    # HRV parameters
    st.subheader(f"💓 HRV-Parameter (RMSSD & SDNN) – letzte {window_minutes} Minuten")
    if not df_polar.empty and all(col in df_polar.columns for col in ["hrv_rmssd", "hrv_sdnn"]):
        with st.container(border=True, height="stretch"):
            st.line_chart(df_polar[["hrv_rmssd", "hrv_sdnn"]])
    else:
        st.info("Keine HRV-Daten verfügbar.")

    # Glucose
    st.subheader(f"🩸 Glukose (CGM) – letzte {window_minutes} Minuten")
    if not df_glucose.empty and "sgv" in df_glucose.columns:
        with st.container(border=True, height="stretch"):
            st.line_chart(df_glucose[["sgv"]])
    else:
        st.info("Keine CGM-Daten verfügbar.")

    # Neuro state timeline
    st.subheader(
        f"🧠 Neurophysiologischer Zustand (Verlauf) – letzte {window_minutes} Minuten"
    )
    if not df_polar.empty and "hrv_rmssd" in df_polar.columns:
        timeline_fig = create_state_timeline(df_polar)
        st.container(border=True, height="stretch").plotly_chart(
            timeline_fig, use_container_width=True
        )
    else:
        st.info("Keine ausreichenden HRV-Daten zur Bestimmung des Zustandes.")

    # Data tables
    if not df_polar.empty:
        st.subheader("🕒 Letzte Polar-Messwerte")
        with st.container(border=True, height="stretch"):
            st.dataframe(df_polar.tail(10))
    else:
        st.info("Keine Polar-Messwerte verfügbar.")

    if not df_glucose.empty:
        st.subheader("🕒 Letzte CGM-Messwerte")
        with st.container(border=True, height="stretch"):
            st.dataframe(df_glucose.tail(10))
    else:
        st.info("Keine CGM-Messwerte verfügbar.")


if __name__ == "__main__":
    main()
