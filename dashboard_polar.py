import streamlit as st
import pandas as pd
from pymongo import MongoClient
import datetime

# Titel
st.title("📊 Polar H10 Live Dashboard")

# MongoDB Verbindung
MONGO_URI = st.secrets["MONGO_URI"]
client = MongoClient(MONGO_URI)
db = client["nightscout-db"]
collection = db["polar_data"]

# Daten abrufen
data = list(collection.find().sort("timestamp", -1).limit(200))

if not data:
    st.warning("Keine Polar-Daten gefunden.")
else:
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Anzeige
    st.line_chart(df.set_index("timestamp")[["hr"]])
    st.line_chart(df.set_index("timestamp")[["hrv_rmssd", "hrv_sdnn"]])

    st.dataframe(df.tail(10))
