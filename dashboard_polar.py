import streamlit as st
import pandas as pd
from pymongo import MongoClient
import datetime
import os

st.title("📊 Polar H10 Live Dashboard")

# 🔗 MongoDB Verbindung
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/nightscout-db?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client["nightscout-db"]
collection = db["polar_data"]

data = list(collection.find().sort("timestamp", -1).limit(200))

if not data:
    st.warning("Keine Polar-Daten gefunden.")
else:
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    st.subheader("Herzfrequenz (HR)")
    st.line_chart(df.set_index("timestamp")[["hr"]])

    st.subheader("HRV Parameter (RMSSD & SDNN)")
    st.line_chart(df.set_index("timestamp")[["hrv_rmssd", "hrv_sdnn"]])

    st.subheader("Letzte Messwerte")
    st.dataframe(df.tail(10))
