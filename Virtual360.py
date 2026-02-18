import streamlit as st
import pandas as pd
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- Setup ---
st.set_page_config(page_title="Hotel Analytics", layout="wide")

# --- Custom Styling ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- Session State for Data ---
if 'hotel_data' not in st.session_state:
    st.session_state.hotel_data = pd.DataFrame(columns=["Hotel Name", "Name of Area", "Category", "Coverage (SQM)"])

# --- App Header ---
st.title("🏨 Hotel Facility & Coverage Analytics")
st.info("Capture area details and generate professional reports instantly.")

# --- Top Row: Inputs ---
with st.container():
    col1, col2, col3, col4 = st.columns([1.5, 2, 1.5, 1])
    
    with col1:
        hotel_choice = st.selectbox("Hotel Name", ["EDEN Hotel", "Thaala Hotel"])
    with col2:
        area_name = st.text_input("Name of Area", placeholder="e.g. Main Lobby")
    with col3:
        category = st.selectbox("Category", ["Suite/Room", "Restaurant & Bar", "Lobby", "Function Venue", "Outdoor", "Gym"])
    with col4:
        sqm = st.number_input("SQM", min_value=0.0, step=10.0)

    if st.button("➕ Add Area to Grid", use_container_width=True):
        if area_name:
            new_entry = pd.DataFrame({
                "Hotel Name": [hotel_choice],
                "Name of Area": [area_name],
                "Category": [category],
                "Coverage (SQM)": [sqm]
            })
            st.session_state.hotel_data = pd.concat([st.session_state.hotel_data, new_entry], ignore_index=True)
            st.toast(f"Added {area_name} successfully!")
        else:
            st.error("Please enter an Area Name.")

st.markdown("---")

# --- Middle Row: Data & Analytics ---
if not st.session_state.hotel_data.empty:
    m_col1, m_col2 = st.columns([2, 1])

    with m_col1:
        st.subheader("Current Inventory")
        # Allow users to delete or edit directly in the grid
        edited_df = st.data_editor(st.session_state.hotel_data, num_rows="dynamic", use_container_width=True, key="editor")
        st.session_state.hotel_data = edited_df

    with m_col2:
        st.subheader("Summary")
        total_sqm = st.session_state.hotel_data["Coverage (SQM)"].sum()
        st.metric("Total Coverage", f"{total_sqm:,.2f} SQM")
        
        # Mini Chart
        chart_data = st.session_state.hotel_data.groupby("Category")["Coverage (SQM)"].sum()
        st.bar_chart(chart_data)

    # --- Footer: Export Controls ---
    st.markdown("---")
    st.subheader("📄 Export Reports")
    e_col1, e_col2, e_col3 = st.columns(3)

    # CSV Export
    csv = st.session_state.hotel_data.to_csv(index=False).encode('utf-8')
    e_col1.download_button("📥 Download Excel (CSV)", csv, "hotel_report.csv", "text/csv", use_container_width=True)

    # PDF Export Function
    def generate_pdf(df):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        parts = [Paragraph("Hotel Facility Coverage Report", styles['Title']), Spacer(1, 12)]
        
        # Table data
        data = [df.columns.tolist()] + df.values.tolist()
        data.append(["", "", "TOTAL", f"{df['Coverage (SQM)'].sum():,.2f}"])
        
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2c3e50")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
        ]))
        parts.append(table)
        doc.build(parts)
        return buf.getvalue()

    pdf_bytes = generate_pdf(st.session_state.hotel_data)
    e_col2.download_button("📥 Download PDF Report", pdf_bytes, "hotel_report.pdf", "application/pdf", use_container_width=True)

    if e_col3.button("🗑️ Reset All Data", use_container_width=True):
        st.session_state.hotel_data = pd.DataFrame(columns=["Hotel Name", "Name of Area", "Category", "Coverage (SQM)"])
        st.rerun()
else:
    st.write("No data entries yet. Start by adding an area above.")