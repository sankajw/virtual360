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
st.set_page_config(page_title="Virtual360 Cost Assessment", layout="wide")

# --- AUTO-FOCUS JAVASCRIPT ---
components.html(
    """
    <script>
    var inputs = window.parent.document.querySelectorAll("input[type=text]");
    if (inputs.length > 0) {
        inputs[0].focus(); 
    }
    </script>
    """,
    height=0,
)

# --- Initialize Data Store ---
if 'hotel_data' not in st.session_state:
    st.session_state.hotel_data = pd.DataFrame(columns=[
        "Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)"
    ])

if 'last_category' not in st.session_state:
    st.session_state.last_category = "Suite/Room"

st.title("🏨 Virtual360 Cost Assessment")

# --- DATA ENTRY SECTION ---
st.subheader("📍 Quick Data Entry")

with st.form("entry_form", clear_on_submit=True):
    f1, f2, f3, f4, f5 = st.columns([1.5, 2.5, 2, 1, 1])
    
    with f1:
        hotel_choice = st.selectbox("Hotel Name", ["EDEN Hotel", "Thaala Hotel"])
    with f2:
        area_name = st.text_input("Name of Area")
    with f3:
        categories = ["Suite/Room", "Restaurant & Bar", "Lobby", "Function Venue", "Outdoor", "Gym", "Other"]
        d_idx = categories.index(st.session_state.last_category) if st.session_state.last_category in categories else 0
        category_choice = st.selectbox("Category", categories, index=d_idx)
    with f4:
        sqm_val = st.number_input("SQM", min_value=0.0, step=1.0)
    with f5:
        st.markdown('<p style="margin-bottom: 32px;"></p>', unsafe_allow_html=True) 
        submit_clicked = st.form_submit_button("➕ Add", use_container_width=True)

    if submit_clicked:
        if area_name and sqm_val > 0:
            new_entry = pd.DataFrame({
                "Date Added": [datetime.now().strftime("%Y-%m-%d")],
                "Hotel Name": [hotel_choice],
                "Name of Area": [area_name],
                "Category": [category_choice],
                "Coverage (SQM)": [sqm_val]
            })
            st.session_state.hotel_data = pd.concat([st.session_state.hotel_data, new_entry], ignore_index=True)
            st.session_state.last_category = category_choice
            st.rerun()
        else:
            st.error("Please fill Name and SQM")

st.markdown("---")

# --- VIEWING GRID & EXPORTS ---
hotel_filter = st.sidebar.multiselect("Filter View", ["EDEN Hotel", "Thaala Hotel"], default=["EDEN Hotel", "Thaala Hotel"])
filtered_df = st.session_state.hotel_data[st.session_state.hotel_data["Hotel Name"].isin(hotel_filter)]

if not filtered_df.empty:
    st.subheader("📊 Assessment Inventory")
    
    # We use edited_df to ensure downloads capture changes made in the grid
    edited_df = st.data_editor(
        st.session_state.hotel_data, 
        num_rows="dynamic", 
        use_container_width=True,
        key="main_editor"
    )
    
    # Update master state if rows are deleted/edited in grid
    if not edited_df.equals(st.session_state.hotel_data):
        st.session_state.hotel_data = edited_df
        st.rerun()

    # Re-filter after potential grid edits
    export_df = edited_df[edited_df["Hotel Name"].isin(hotel_filter)]

    st.markdown("### 📥 Download Assessment")
    e1, e2, e3, e4 = st.columns(4)
    
    # 1. EXCEL (Matches screen content)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False, sheet_name='Assessment')
    e1.download_button("📥 Excel", buffer.getvalue(), "assessment.xlsx", use_container_width=True)

    # 2. CSV (Matches screen content)
    e2.download_button("📥 CSV", export_df.to_csv(index=False).encode('utf-8'), "assessment.csv", use_container_width=True)
    
    # 3. PDF (Matches screen content)
    def generate_pdf(df):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        data = [list(df.columns)] + df.values.tolist()
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.grey), 
            ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke), 
            ('GRID',(0,0),(-1,-1),1,colors.black),
            ('FONTSIZE', (0,0), (-1,-1), 9)
        ]))
        doc.build([table])
        return buf.getvalue()

    e3.download_button("📥 PDF", generate_pdf(export_df), "assessment_report.pdf", use_container_width=True)
    
    # 4. RESET
    if e4.button("🗑️ Clear All", use_container_width=True):
        st.session_state.hotel_data = pd.DataFrame(columns=st.session_state.hotel_data.columns)
        st.rerun()
