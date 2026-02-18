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

# --- Initialize Data Store & Category Memory ---
if 'hotel_data' not in st.session_state:
    st.session_state.hotel_data = pd.DataFrame(columns=[
        "Date Added", "Hotel Name", "Name of Area", "Category", "Coverage (SQM)"
    ])

# Set a default category if it doesn't exist
if 'last_category' not in st.session_state:
    st.session_state.last_category = "Suite/Room"

st.title("🏨 Virtual360 Cost Assessment")

# --- SINGLE ROW DATA ENTRY SECTION ---
st.subheader("📍 Quick Data Entry")

# Using a standard container instead of form clear_on_submit 
# so we can manually control the "Memory" of the Category field.
with st.container():
    f1, f2, f3, f4, f5 = st.columns([1.5, 2.5, 2, 1, 1])
    
    with f1:
        hotel_choice = st.selectbox("Hotel Name", ["EDEN Hotel", "Thaala Hotel"])
    with f2:
        # We use a key that we can clear manually
        area_name = st.text_input("Name of Area", key="input_area")
    with f3:
        # This field recalls the last used category
        categories = ["Suite/Room", "Restaurant & Bar", "Lobby", "Function Venue", "Outdoor", "Gym", "Other"]
        default_index = categories.index(st.session_state.last_category)
        category = st.selectbox("Category", categories, index=default_index)
    with f4:
        # SQM input
        sqm = st.number_input("SQM", min_value=0.0, step=1.0, key="input_sqm")
    with f5:
        st.write(" ") 
        # Using a regular button to allow manual state management
        submit = st.button("➕ Add", use_container_width=True)

    # Logic to trigger on Button Click OR Enter Key (Enter key works on number_input by default)
    if submit or (st.session_state.input_sqm > 0 and area_name != "" and st.session_state.get('prev_sqm') != st.session_state.input_sqm):
        if area_name and sqm > 0:
            new_entry = pd.DataFrame({
                "Date Added": [datetime.now().strftime("%Y-%m-%d")],
                "Hotel Name": [hotel_choice],
                "Name of Area": [area_name],
                "Category": [category],
                "Coverage (SQM)": [sqm]
            })
            st.session_state.hotel_data = pd.concat([st.session_state.hotel_data, new_entry], ignore_index=True)
            
            # Update the Memory
            st.session_state.last_category = category
            
            # Clear the text and number fields for next entry
            st.session_state.input_area = ""
            st.session_state.input_sqm = 0.0
            
            st.rerun()

# --- UNDO LAST ENTRY ---
if not st.session_state.hotel_data.empty:
    if st.button("↩️ Undo Last Entry"):
        st.session_state.hotel_data = st.session_state.hotel_data.iloc[:-1]
        st.rerun()

st.markdown("---")

# --- VIEWING GRID & FILTERS ---
hotel_filter = st.sidebar.multiselect("Filter View", ["EDEN Hotel", "Thaala Hotel"], default=["EDEN Hotel", "Thaala Hotel"])
filtered_df = st.session_state.hotel_data[st.session_state.hotel_data["Hotel Name"].isin(hotel_filter)]

if not filtered_df.empty:
    st.subheader("📊 Assessment Inventory")
    st.data_editor(filtered_df, num_rows="dynamic", use_container_width=True)
    
    e1, e2, e3 = st.columns(3)
    e1.download_button("📥 Export CSV", filtered_df.to_csv(index=False), "assessment.csv", use_container_width=True)
    
    def generate_pdf(df):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        data = [["Date", "Hotel", "Area", "Category", "SQM"]] + df.values.tolist()
        table = Table(data)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey), ('GRID',(0,0),(-1,-1),1,colors.black)]))
        doc.build([table])
        return buf.getvalue()

    e2.download_button("📥 Export PDF", generate_pdf(filtered_df), "report.pdf", use_container_width=True)
    
    if e3.button("🗑️ Clear All", use_container_width=True):
        st.session_state.hotel_data = pd.DataFrame(columns=st.session_state.hotel_data.columns)
        st.rerun()
