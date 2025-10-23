import streamlit as st
import pandas as pd
from pymongo import MongoClient
import datetime
import os

# Titel
st.title("📊 Polar H10 Live Dashboard")

# 🔗 MongoDB Verbindung
# Versuche zuerst Railway Environment Variable (MONGO_URI),
# falls nicht vorhanden, nutze den Backup-Link direkt.
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://cocuzzam:MCETH2025@nightscout-db.21jfrwe.mongodb.net/nightscout-db?retryWrites=true&w=majority"

# Verbindung aufbauen
client = MongoClient(MONGO_URI)
db = client["nightscout-db"]
collection = db["polar_data"]

# 📥 Daten abrufen
data = list(collection.find().sort("timestamp", -1).limit(200))

if not data:
    st.warning("Keine Polar-Daten gefunden.")
else:
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # 🫀 Herzfrequenz-Chart
    st.subheader("Herzfrequenz (HR)")
    st.line_chart(df.set_index("timestamp")[["hr"]])

    # 💓 HRV Charts
    st.subheader("HRV Parameter (RMSSD & SDNN)")
    st.line_chart(df.set_index("timestamp")[["hrv_rmssd", "hrv_sdnn"]])

    # 📋 Neueste Werte
    st.subheader("Letzte Messwerte")
    st.dataframe(df.tail(10))
