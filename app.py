import streamlit as st
from modules import format_data, flag_compile, review, annual

st.set_page_config(page_title="Tipping Bucket QAQC", layout="wide")

from utils import file_manager
import os
import glob

st.sidebar.title("Navigation")

# OneDrive Integration
use_onedrive = st.sidebar.checkbox("Use with UNBC OneDrive")
if use_onedrive:
    username = st.sidebar.text_input("Username", value="dowlataba")
    station_code = st.sidebar.text_input("Station Code (e.g. 03NE004)")

    if username and station_code:
        base_path = os.path.join("/Users", username, "OneDrive - UNBC", "NHG Field - Data Management", "02_Stations")
        search_pattern = os.path.join(base_path, f"{station_code}*")
        matching_folders = glob.glob(search_pattern)

        if matching_folders:
            station_folder = matching_folders[0]
            if file_manager.set_project_dir(station_folder):
                st.sidebar.success(f"Connected: {os.path.basename(station_folder)}")
            else:
                st.sidebar.error("Failed to set directory.")
        else:
            st.sidebar.warning(f"No folder found for {station_code} in OneDrive.")

pages = {
    "Format Data": format_data.app,
    "Flag & Compile": flag_compile.app,
    "Review Data": review.app,
    "Annual Report": annual.app
}

selection = st.sidebar.radio("Go to", list(pages.keys()))

pages[selection]()
