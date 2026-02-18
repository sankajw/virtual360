import streamlit as st
import pandas as pd
import io
import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import streamlit.components.v1 as components

# --- Setup ---
st.set_page_config(page_title="Virtual360 Cost Assessment", layout="wide")

# --- DATABASE LOGIC ---
DB_FILE = "database.csv"

def load_data():
    if os.path.exists(DB_FILE):
        return pd.read_csv(DB_FILE)
    return pd.DataFrame(columns=["Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)"])

def save_data(df):
    df.to_csv(DB_FILE, index=False)

# Load data into the app session
if 'hotel_data' not in st.session_state:
    st.session_state.hotel_data = load_data()

# --- CURSOR AUTO-FOCUS ---
components.html(
    """<script>window.parent.document.querySelectorAll("input[type=text]")[0].focus();</script>""",
    height=0,
)

st.title("🏨 Virtual360 Cost Assessment")

# --- DATA ENTRY ---
with st.container():
    st.subheader("📍 Quick Data Entry")
    with st.form("quick_entry_form", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([1.5, 2, 1.5, 1])
        with f1:
            hotel_choice = st.selectbox("Hotel Name", ["EDEN Hotel", "Thaala Hotel"])
        with f2:
            area_name = st.text_input("Name of Area")
        with f3:
            category = st.selectbox("Category", ["Suite/Room", "Restaurant & Bar", "Lobby", "Function Venue", "Outdoor", "Gym", "Other"])
        with f4:
            sqm = st.number_input("Coverage (SQM)", min_value=0.0, step=1.0)
        
        submit = st.form_submit_button("➕ Save to Database", use_container_width=True)
        
        if submit and area_name and sqm > 0:
            new_entry = pd.DataFrame({
                "Date Added": [datetime.now().strftime("%Y-%m-%d")],
                "Hotel Name": [hotel_choice],
                "Name of Area": [area_name],
                "Category": [category],
                "Coverage (SQM)": [sqm]
            })
            # Update Session and Save to CSV File
            st.session_state.hotel_data = pd.concat([st.session_state.hotel_data, new_entry], ignore_index=True)
            save_data(st.session_state.hotel_data)
            st.rerun()

st.markdown("---")

# --- VIEWING PURPOSE (RECALL) ---
st.sidebar.header("📂 Recall & Filter")
hotel_filter = st.sidebar.multiselect("View Selected Hotels", ["EDEN Hotel", "Thaala Hotel"], default=["EDEN Hotel", "Thaala Hotel"])
filtered_df = st.session_state.hotel_data[st.session_state.hotel_data["Hotel Name"].isin(hotel_filter)]

if not filtered_df.empty:
    st.subheader("📊 Saved Assessment Data")
    
    # Editable Grid - Changes here are saved when you hit the button
    edited_df = st.data_editor(filtered_df, num_rows="dynamic", use_container_width=True)
    
    if st.button("💾 Permanent Save Changes"):
        # Update the master data with edits
        st.session_state.hotel_data.update(edited_df)
        save_data(st.session_state.hotel_data)
        st.success("Database Updated!")

    # Exports
    e1, e2, e3 = st.columns(3)
    e1.download_button("📥 Export CSV", filtered_df.to_csv(index=False), "assessment.csv", use_container_width=True)
    
    # PDF Logic
    def generate_pdf(df):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        data = [["Date", "Hotel", "Area", "Category", "SQM"]] + df.values.tolist()
        table = Table(data)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey), ('GRID',(0,0),(-1,-1),1,colors.black)]))
        doc.build([Table(data)])
        return buf.getvalue()
    
    e2.download_button("📥 Export PDF", generate_pdf(filtered_df), "report.pdf", use_container_width=True)
    
    if e3.button("🗑️ Factory Reset Database", use_container_width=True):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        st.session_state.hotel_data = pd.DataFrame(columns=["Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)"])
        st.rerun()
