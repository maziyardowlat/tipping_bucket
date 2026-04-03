import streamlit as st
import pandas as pd
import numpy as np
from utils import file_manager
import os
import re
import glob


def aggregate_tips_to_15min(event_df, grid_timestamps):
    """
    Aggregate irregular tip events into 15-minute precipitation totals.

    The raw Event column is a cumulative counter (incrementing by 0.2 mm per tip).
    Algorithm:
      1. Floor each event timestamp to its 15-min bin.
      2. For each bin take the LAST cumulative value (highest).
      3. Map onto the full 15-min grid and forward-fill.
      4. Diff consecutive values → precipitation per interval.
    """
    if event_df.empty:
        return pd.DataFrame({'timestamp': grid_timestamps, 'precip': 0.0})

    ev = event_df[['timestamp', 'event']].copy()
    ev['bin'] = ev['timestamp'].dt.floor('15min')

    # Last cumulative value per bin
    bin_last = ev.groupby('bin')['event'].last().reset_index()
    bin_last.columns = ['timestamp', 'cum_event']

    grid = pd.DataFrame({'timestamp': grid_timestamps})
    grid = grid.merge(bin_last, on='timestamp', how='left')

    # Forward-fill cumulative counter through empty bins
    grid['cum_event'] = grid['cum_event'].ffill()
    # Before any tips, fill with the first known value (usually 0.0)
    first_val = bin_last['cum_event'].iloc[0] if not bin_last.empty else 0.0
    grid['cum_event'] = grid['cum_event'].fillna(first_val)

    # Diff to get per-interval precipitation
    grid['precip'] = grid['cum_event'].diff()

    # First row has no predecessor — set to 0
    grid.loc[grid.index[0], 'precip'] = 0.0

    # Negative diffs (counter reset between deployments) → 0
    grid.loc[grid['precip'] < 0, 'precip'] = 0.0

    # Round to 1 decimal (0.2 mm resolution)
    grid['precip'] = grid['precip'].round(1)

    return grid[['timestamp', 'precip']]


def app():
    st.header("Format Raw Data")

    # Project Directory Selection
    st.sidebar.subheader("Settings")
    current_dir = file_manager.get_project_dir()
    new_dir = st.sidebar.text_input("Project Directory", value=current_dir)
    if new_dir != current_dir:
        if file_manager.set_project_dir(new_dir):
            st.sidebar.success(f"Directory set to: {new_dir}")
        else:
            st.sidebar.error("Invalid directory path")

    # File Source Selection
    file_source = st.radio("File Source", ["Upload File", "Select from Server (OneDrive)"], horizontal=True)

    uploaded_file = None
    server_file_path = None

    if file_source == "Upload File":
        uploaded_file = st.file_uploader("Choose CSV or Excel File", type=['csv', 'txt', 'xlsx'])
    else:
        # Server Selection Logic
        default_station_code = ""
        current_project_dir = file_manager.get_project_dir()
        if "02_Stations" in current_project_dir:
            folder_name = os.path.basename(current_project_dir)
            default_station_code = folder_name.split("_")[0] if "_" in folder_name else folder_name

        col_server1, col_server2 = st.columns(2)
        with col_server1:
            username_input = st.text_input("Username (for OneDrive Path)", value="dowlataba")
        with col_server2:
            station_code_input = st.text_input("Enter Station Code to Search", value=default_station_code)

        if station_code_input and username_input:
            base_stations_dir = None

            if "02_Stations" in current_project_dir:
                parts = current_project_dir.split("02_Stations")
                base_stations_dir = os.path.join(parts[0], "02_Stations")
            else:
                user_onedrive_path = os.path.join("/Users", username_input, "OneDrive - UNBC", "NHG Field - Data Management")
                base_stations_dir = os.path.join(user_onedrive_path, "02_Stations")

                if not os.path.exists(user_onedrive_path):
                    st.error(f"Could not find OneDrive folder for user '{username_input}'.")
                    base_stations_dir = None
                elif not os.path.exists(base_stations_dir):
                    st.error(f"'02_Stations' directory is missing in: {user_onedrive_path}")
                    base_stations_dir = None

            if base_stations_dir and os.path.exists(base_stations_dir):
                search_pattern = os.path.join(base_stations_dir, f"{station_code_input}*")
                matching_folders = glob.glob(search_pattern)

                if matching_folders:
                    station_folder = matching_folders[0]
                    raw_dir = os.path.join(station_folder, "01_Data", "01_Raw")

                    if os.path.exists(raw_dir):
                        raw_files = [f for f in os.listdir(raw_dir) if f.endswith((".csv", ".txt", ".xlsx"))]
                        if raw_files:
                            selected_filename = st.selectbox("Select Raw File", raw_files)
                            server_file_path = os.path.join(raw_dir, selected_filename)
                            st.success(f"Selected: {selected_filename}")

                            if current_project_dir != station_folder:
                                if st.button(f"Switch Project Directory to {os.path.basename(station_folder)}"):
                                    file_manager.set_project_dir(station_folder)
                                    st.rerun()
                        else:
                            st.warning(f"No CSV/TXT files found in {raw_dir}")
                    else:
                        st.warning(f"Raw data directory not found: {raw_dir}")
                else:
                    st.error(f"Station folder starting with '{station_code_input}' not found.")

    if uploaded_file is not None or server_file_path is not None:
        skip_rows = st.number_input("Rows to Skip (1 = skip plot title row)", min_value=0, value=1)

        try:
            # Read Data
            if uploaded_file is not None:
                file_name_for_meta = uploaded_file.name
                uploaded_file.seek(0)
                if file_name_for_meta.endswith('.xlsx'):
                    df = pd.read_excel(uploaded_file, skiprows=skip_rows)
                else:
                    try:
                        df = pd.read_csv(uploaded_file, skiprows=skip_rows, low_memory=False)
                    except (UnicodeDecodeError, pd.errors.ParserError):
                        uploaded_file.seek(0)
                        df = pd.read_excel(uploaded_file, skiprows=skip_rows)
                        st.warning("File read as Excel despite extension.")
            else:
                file_name_for_meta = os.path.basename(server_file_path)
                if file_name_for_meta.endswith('.xlsx'):
                    df = pd.read_excel(server_file_path, skiprows=skip_rows)
                else:
                    try:
                        df = pd.read_csv(server_file_path, skiprows=skip_rows, low_memory=False)
                    except (UnicodeDecodeError, pd.errors.ParserError):
                        df = pd.read_excel(server_file_path, skiprows=skip_rows)
                        st.warning("File read as Excel despite extension.")

            # Filter "Logged" rows
            mask = df.astype(str).apply(lambda x: x.str.contains("Logged", case=False, na=False)).any(axis=1)
            df = df[~mask]

            st.subheader("Raw Data Preview")
            st.dataframe(df.head(10))
            st.write(f"**{len(df)} rows** loaded.")

            # --- Column Mapping ---
            st.subheader("Column Mapping")
            st.info("Map the raw columns to their roles. The app will auto-detect based on header keywords.")

            all_columns = df.columns.tolist()

            # Auto-detect columns from HOBO header patterns
            def find_col(keywords):
                for c in all_columns:
                    if all(k.lower() in c.lower() for k in keywords):
                        return c
                return None

            default_ts = find_col(["Date", "Time"]) or all_columns[0]
            default_temp = find_col(["Temp"]) or (all_columns[1] if len(all_columns) > 1 else all_columns[0])
            default_event = find_col(["Event"]) or (all_columns[2] if len(all_columns) > 2 else all_columns[0])

            col1, col2, col3 = st.columns(3)
            with col1:
                ts_col = st.selectbox("Timestamp Column", all_columns, index=all_columns.index(default_ts))
            with col2:
                temp_col = st.selectbox("Air Temperature Column", all_columns, index=all_columns.index(default_temp))
            with col3:
                event_col = st.selectbox("Event (Cumulative Tips) Column", all_columns, index=all_columns.index(default_event))

            # --- Metadata ---
            st.subheader("Metadata")

            default_station = ""
            default_serial = ""
            try:
                parts = re.split(r'_raw_', file_name_for_meta, flags=re.IGNORECASE)
                if len(parts) > 1:
                    default_station = parts[0]
                    rest_parts = parts[1].split('_')
                    if len(rest_parts) > 0 and rest_parts[0].upper().startswith('CR'):
                        if len(rest_parts) > 1:
                            default_serial = rest_parts[1]
                    else:
                        default_serial = rest_parts[0]
            except Exception:
                pass

            col_m1, col_m2 = st.columns(2)
            with col_m1:
                station_code = st.text_input("Station Code", value=default_station, key=f"station_{file_name_for_meta}")
                logger_serial = st.text_input("Logger Serial Number", value=default_serial, key=f"serial_{file_name_for_meta}")
            with col_m2:
                utc_offset = st.number_input("UTC Offset (0 if already UTC)", value=0.0, key=f"utc_{file_name_for_meta}")
                data_id = st.number_input("Data ID", value=0)

            # --- Process & Save ---
            if st.button("Format & Process Data"):
                if not station_code or not logger_serial:
                    st.error("Please provide Station Code and Logger Serial Number.")
                else:
                    station_code = str(station_code).replace("/", "_").replace("\\", "_")
                    logger_serial = str(logger_serial).replace("/", "_").replace("\\", "_")

                    with st.spinner("Processing raw data..."):
                        # Parse timestamp
                        raw = df[[ts_col, temp_col, event_col]].copy()
                        raw.columns = ['timestamp', 'air_temp', 'event']

                        raw['air_temp'] = pd.to_numeric(raw['air_temp'], errors='coerce')
                        raw['event'] = pd.to_numeric(raw['event'], errors='coerce')

                        # Parse timestamps (YY-MM-DD or YYYY-MM-DD)
                        try:
                            raw['timestamp'] = pd.to_datetime(raw['timestamp'], format='%y-%m-%d %H:%M:%S', errors='raise')
                        except (ValueError, TypeError):
                            try:
                                raw['timestamp'] = pd.to_datetime(raw['timestamp'], format='%Y-%m-%d %H:%M:%S', errors='raise')
                            except (ValueError, TypeError):
                                raw['timestamp'] = pd.to_datetime(raw['timestamp'], yearfirst=True, dayfirst=False, errors='coerce')

                        raw = raw.dropna(subset=['timestamp'])
                        raw = raw.sort_values('timestamp')

                        # Build 15-min grid
                        grid_start = raw['timestamp'].min().floor('15min')
                        grid_end = raw['timestamp'].max().ceil('15min')
                        grid_timestamps = pd.date_range(start=grid_start, end=grid_end, freq='15min')

                        # --- Aggregate precipitation ---
                        event_rows = raw[raw['event'].notna()].copy()
                        precip_df = aggregate_tips_to_15min(event_rows, grid_timestamps)

                        # --- Extract temperature (already at 15-min marks) ---
                        temp_rows = raw[raw['air_temp'].notna()].copy()
                        temp_rows['timestamp'] = temp_rows['timestamp'].dt.round('15min')
                        # Keep last value per bin if duplicates
                        temp_rows = temp_rows.drop_duplicates(subset=['timestamp'], keep='last')
                        temp_df = temp_rows[['timestamp', 'air_temp']]

                        # --- Merge onto grid ---
                        result = precip_df.merge(temp_df, on='timestamp', how='left')

                        # Add metadata
                        result['station_code'] = station_code
                        result['logger_serial'] = logger_serial
                        result['utc_offset'] = utc_offset
                        result['data_id'] = data_id

                        # Reorder columns
                        result = result[['data_id', 'station_code', 'timestamp', 'utc_offset',
                                         'logger_serial', 'precip', 'air_temp']]

                    st.success(f"Processed {len(result)} rows on 15-min grid.")
                    st.dataframe(result.head(20))

                    # Summary
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        st.metric("Total Precipitation (mm)", f"{result['precip'].sum():.1f}")
                        st.metric("Precip Intervals > 0", f"{(result['precip'] > 0).sum()}")
                    with col_s2:
                        st.metric("Temp Range", f"{result['air_temp'].min():.1f}°C – {result['air_temp'].max():.1f}°C")
                        st.metric("Missing Temp Rows", f"{result['air_temp'].isna().sum()}")

                    # Extract date from filename for session state
                    raw_date_match = re.search(r'_(\d{8})(?:\.\w+)?$', file_name_for_meta)
                    if raw_date_match:
                        st.session_state['raw_file_date'] = raw_date_match.group(1)
                    else:
                        st.session_state['raw_file_date'] = None

                    # Store in session state
                    st.session_state['formatted_df'] = result
                    st.session_state['formatted_filename'] = f"{station_code}_formatted_{logger_serial}.csv"

                    st.success("Data formatted and ready in memory. Proceed to 'Flag & Compile'.")

        except Exception as e:
            st.error(f"Error reading file: {e}")
