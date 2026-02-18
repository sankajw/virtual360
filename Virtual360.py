import streamlit as st
import pandas as pd
import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import streamlit.components.v1 as components

# --- Setup ---
# Updated the browser tab title
st.set_page_config(page_title="Virtual360 Cost Assessment", layout="wide")

# --- CURSOR AUTO-FOCUS JAVASCRIPT ---
components.html(
    """
    <script>
    var input = window.parent.document.querySelectorAll("input[type=text]")[0];
    input.focus();
    </script>
    """,
    height=0,
)

# --- Initialize Data Store ---
if 'hotel_data' not in st.session_state:
    st.session_state.hotel_data = pd.DataFrame(columns=[
        "Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)", "Cost per SQM", "Total Cost"
    ])

# Updated the main heading
st.title("🏨 Virtual360 Cost Assessment")

# --- QUICK ENTRY FORM ---
with st.container():
    st.subheader("📍 Quick Data Entry")
    
    with st.form("quick_entry_form", clear_on_submit=True):
        f1, f2, f3, f4, f5 = st.columns([1.5, 2, 1.5, 1, 1])
        
        with f1:
            hotel_choice = st.selectbox("Hotel Name", ["EDEN Hotel", "Thaala Hotel"])
        
        with f2:
            area_name = st.text_input("Name of Area")
            
        with f3:
            category = st.selectbox("Category", ["Suite/Room", "Restaurant & Bar", "Lobby", "Function Venue", "Outdoor", "Gym"])
        
        with f4:
            sqm = st.number_input("Coverage (SQM)", min_value=0.0, step=1.0)
            
        with f5:
            cost_sqm = st.number_input("Cost / SQM", min_value=0.0, step=1.0)
        
        submit = st.form_submit_button("➕ Add Area to Assessment (Press Enter)", use_container_width=True)
        
        if submit:
            if area_name and sqm > 0:
                total_cost = sqm * cost_sqm
                new_entry = pd.DataFrame({
                    "Date Added": [datetime.now().strftime("%Y-%m-%d")],
                    "Hotel Name": [hotel_choice],
                    "Name of Area": [area_name],
                    "Category": [category],
                    "Coverage (SQM)": [sqm],
                    "Cost per SQM": [cost_sqm],
                    "Total Cost": [total_cost]
                })
                st.session_state.hotel_data = pd.concat([st.session_state.hotel_data, new_entry], ignore_index=True)
                st.rerun() 
            else:
                st.error("Please provide Area Name and SQM.")

st.markdown("---")

# --- FILTERS & DISPLAY ---
hotel_filter = st.sidebar.multiselect("View Specific Hotel", ["EDEN Hotel", "Thaala Hotel"], default=["EDEN Hotel", "Thaala Hotel"])
filtered_df = st.session_state.hotel_data[st.session_state.hotel_data["Hotel Name"].isin(hotel_filter)]

if not filtered_df.empty:
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Area", f"{filtered_df['Coverage (SQM)'].sum():,.1f} SQM")
    m2.metric("Total Estimated Cost", f"${filtered_df['Total Cost'].sum():,.2f}")
    m3.metric("Items in Assessment", len(filtered_df))

    st.subheader("📊 Assessment Inventory")
    st.data_editor(filtered_df, num_rows="dynamic", use_container_width=True)
    
    e1, e2, e3 = st.columns(3)
    csv = filtered_df.to_csv(index=False).encode('utf-8')
    e1.download_button("📥 Export CSV", csv, "cost_assessment.csv", "text/csv", use_container_width=True)
    
    def generate_pdf(df):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        # Updated PDF title inside the document
        parts = [Paragraph("Virtual360 Cost Assessment Report", styles['Title']), Spacer(1, 12)]
        data = [["Area", "Category", "SQM", "Cost"]] + df[["Name of Area", "Category", "Coverage (SQM)", "Total Cost"]].values.tolist()
        table = Table(data)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey), ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke), ('GRID',(0,0),(-1,-1),1,colors.black)]))
        parts.append(table)
        doc.build(parts)
        return buf.getvalue()

    pdf = generate_pdf(filtered_df)
    e2.download_button("📥 Export PDF Report", pdf, "assessment_report.pdf", "application/pdf", use_container_width=True)
    
    if e3.button("🗑️ Clear Assessment", use_container_width=True):
        st.session_state.hotel_data = pd.DataFrame(columns=st.session_state.hotel_data.columns)
        st.rerun()
