import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from utils import file_manager
import os
import pdfplumber
import re
from datetime import datetime, timedelta


def extract_times_from_pdf(pdf_file):
    times = {}
    text = ""
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
    except Exception:
        return times

    time_in_match = re.search(r"Time-in\s*[:]?\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    time_out_match = re.search(r"Time-out\s*[:]?\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)

    date_match = re.search(r"(?:Date|Visit Date)\s*[:]?\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r"(?:Date|Visit Date)\s*[:]?\s*(\d{1,2}/\d{1,2}/\d{2,4})", text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if not date_match:
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)

    if time_in_match:
        times['in'] = time_in_match.group(1)
    if time_out_match:
        times['out'] = time_out_match.group(1)
    if date_match:
        times['date'] = date_match.group(1)

    return times


def app():
    st.header("Flag & Compile Data")

    # ── 1. Load Formatted Data ──
    st.subheader("1. Select Formatted Data")

    df = None
    selected_file = "Session Data"

    if 'formatted_df' in st.session_state:
        df = st.session_state['formatted_df']
        selected_file = st.session_state.get('formatted_filename', "Session Data")
        st.success(f"Loaded data from previous step: {selected_file}")
    else:
        formatted_files = file_manager.list_files(subfolder="01_Data/01_Raw_Formatted", pattern=".csv")
        if formatted_files:
            st.info("No data in session. Select a previously formatted file (Legacy Mode).")
            selected_file = st.selectbox("Choose File", formatted_files)
            if selected_file:
                df = file_manager.load_data(selected_file, subfolder="01_Data/01_Raw_Formatted")
        else:
            st.warning("No formatted data found. Please go to 'Format Data' first.")
            return

    if df is None:
        return

    # Ensure types
    if 'timestamp' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            try:
                df['timestamp'] = pd.to_datetime(df['timestamp'], format='%y-%m-%d %H:%M:%S', errors='raise')
            except (ValueError, TypeError):
                try:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y-%m-%d %H:%M:%S', errors='raise')
                except (ValueError, TypeError):
                    df['timestamp'] = pd.to_datetime(df['timestamp'], yearfirst=True, dayfirst=False, errors='coerce')
    else:
        st.error("Column 'timestamp' not found.")
        return

    df['timestamp'] = df['timestamp'].dt.round('15min')
    if 'precip' in df.columns:
        df['precip'] = pd.to_numeric(df['precip'], errors='coerce')
    if 'air_temp' in df.columns:
        df['air_temp'] = pd.to_numeric(df['air_temp'], errors='coerce')

    st.write(f"Loaded **{len(df)}** rows.")

    # ── 2. QAQC Parameters ──
    st.subheader("2. QAQC Parameters")

    st.markdown("#### Precipitation Flags")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        precip_threshold = st.number_input("Threshold (T): mm per 15-min", value=5.0, disabled=True)
        spike_precip = st.number_input("Spike (S): isolated > mm", value=3.0, disabled=True)
    with col_p2:
        freeze_temp = st.number_input("Below Freezing (B): air temp < °C", value=0.0, disabled=True)

    st.markdown("#### Air Temperature Flags")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        atemp_min = st.number_input("Threshold Min (T): °C", value=-50.0, disabled=True)
        atemp_max = st.number_input("Threshold Max (T): °C", value=50.0, disabled=True)
    with col_t2:
        atemp_spike = st.number_input("Spike (S): °C change per 15-min", value=10.0, disabled=True)

    # ── 3. Visit Times ──
    # Calculate defaults from data
    default_in_val = ""
    default_out_val = ""
    if not df.empty and 'timestamp' in df.columns:
        try:
            last_ts = df['timestamp'].max()
            default_out_val = last_ts.strftime("%Y-%m-%d %H:%M")
            default_in_val = (last_ts - pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    # ── 4. Missing Data Padding & Processing Mode ──
    st.subheader("3. Missing Data Padding")

    processing_mode = st.radio(
        "Processing Mode:",
        options=["First Data Set", "Sequential", "Logger Swap"],
        index=1,
        help="First Data Set: No historical padding. Sequential: Matches Station & Serial. Logger Swap: Matches Station only."
    )

    enable_padding = st.checkbox("Fill Missing Timestamps", value=True)

    default_pad_start = ""
    hist_end = None

    if processing_mode in ["Sequential", "Logger Swap"]:
        try:
            current_station = df['station_code'].iloc[0] if 'station_code' in df.columns else ""
            current_serial = df['logger_serial'].iloc[0] if 'logger_serial' in df.columns else ""

            if current_station:
                tidy_files = file_manager.list_files(subfolder="01_Data/02_Tidy", pattern=".csv")

                if processing_mode == "Logger Swap":
                    matching_files = [f for f in tidy_files if f.startswith(f"{current_station}_tidy_")]
                else:
                    matching_files = [f for f in tidy_files if f.startswith(f"{current_station}_tidy_") and str(current_serial) in f]

                if matching_files:
                    def extract_date_key(f):
                        match = re.search(r"_(\d{8})\.csv$", f)
                        date_val = match.group(1) if match else "00000000"
                        return (date_val, f)

                    matching_files.sort(key=extract_date_key)
                    latest_file = matching_files[-1]

                    hist_df = file_manager.load_data(latest_file, subfolder="01_Data/02_Tidy")
                    if hist_df is not None and 'timestamp' in hist_df.columns:
                        hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])
                        hist_end = hist_df['timestamp'].max()

                        default_start_dt = hist_end + pd.Timedelta(minutes=15)
                        default_pad_start = default_start_dt.strftime("%Y-%m-%d %H:%M:%S")

                        current_start_check = df['timestamp'].min()
                        if hist_end < current_start_check:
                            st.info(f"Auto-detected start from historical file ({latest_file}): {default_pad_start}")
                        else:
                            st.warning(f"Historical file ({latest_file}) overlaps. Start set to {default_pad_start} to trim.")
                else:
                    st.warning(f"No historical files found for mode: {processing_mode}")
        except Exception:
            pass

    if enable_padding:
        col_pad1, col_pad2 = st.columns(2)
        with col_pad1:
            pad_interval = st.text_input("Interval", value="15min")
        with col_pad2:
            pad_start = st.text_input(
                "Record Start Date",
                value=default_pad_start,
                key=f"pad_start_{processing_mode}",
                help="Auto-filled from historical data. Override manually if needed."
            )

    # ── Visit Times ──
    st.subheader("Field Visit Times")

    visit_pdf = st.file_uploader("Upload PDF to populate field times", type="pdf", key="visit_pdf")
    convert_utc = st.checkbox("Convert to UTC", value=True, key="convert_utc_visit")

    if visit_pdf:
        try:
            extracted = extract_times_from_pdf(visit_pdf)
            base_date_str = default_in_val.split(" ")[0] if default_in_val else pd.Timestamp.now().strftime("%Y-%m-%d")
            if 'date' in extracted:
                try:
                    d = pd.to_datetime(extracted['date'])
                    base_date_str = d.strftime("%Y-%m-%d")
                except Exception:
                    pass
            if 'in' in extracted:
                dt_in_str = f"{base_date_str} {extracted['in']}"
                if convert_utc:
                    try:
                        dt_obj = pd.to_datetime(dt_in_str) + pd.Timedelta(hours=7)
                        default_in_val = dt_obj.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        default_in_val = dt_in_str
                else:
                    default_in_val = dt_in_str
            if 'out' in extracted:
                dt_out_str = f"{base_date_str} {extracted['out']}"
                if convert_utc:
                    try:
                        dt_obj = pd.to_datetime(dt_out_str) + pd.Timedelta(hours=7)
                        default_out_val = dt_obj.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        default_out_val = dt_out_str
                else:
                    default_out_val = dt_out_str
            st.success("Times extracted from PDF!")
        except Exception as e:
            st.error(f"Failed to extract from PDF: {e}")

    visit_col1, visit_col2 = st.columns(2)
    with visit_col1:
        datetime_in = st.text_input("Datetime In (YYYY-MM-DD HH:MM)", value=default_in_val)
    with visit_col2:
        datetime_out = st.text_input("Datetime Out (YYYY-MM-DD HH:MM)", value=default_out_val)

    # Previous Visit Times
    st.subheader("Previous Field Visit Times (Optional)")

    prev_in_val = ""
    prev_out_val = ""

    prev_visit_pdf = st.file_uploader("Upload PDF for previous visit", type="pdf", key="prev_visit_pdf")
    prev_convert_utc = st.checkbox("Convert to UTC", value=True, key="convert_utc_prev")

    if prev_visit_pdf:
        try:
            extracted = extract_times_from_pdf(prev_visit_pdf)
            base_date_str = pd.Timestamp.now().strftime("%Y-%m-%d")
            if 'date' in extracted:
                try:
                    d = pd.to_datetime(extracted['date'])
                    base_date_str = d.strftime("%Y-%m-%d")
                except Exception:
                    pass
            if 'in' in extracted:
                dt_in_str = f"{base_date_str} {extracted['in']}"
                if prev_convert_utc:
                    try:
                        dt_obj = pd.to_datetime(dt_in_str) + pd.Timedelta(hours=7)
                        prev_in_val = dt_obj.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        prev_in_val = dt_in_str
                else:
                    prev_in_val = dt_in_str
            if 'out' in extracted:
                dt_out_str = f"{base_date_str} {extracted['out']}"
                if prev_convert_utc:
                    try:
                        dt_obj = pd.to_datetime(dt_out_str) + pd.Timedelta(hours=7)
                        prev_out_val = dt_obj.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        prev_out_val = dt_out_str
                else:
                    prev_out_val = dt_out_str
            st.success("Times extracted from PDF!")
        except Exception as e:
            st.error(f"Failed to extract from PDF: {e}")

    no_fastfield = st.checkbox("No FastField Form (Auto-fill from Historical Data)")
    if no_fastfield:
        if hist_end is not None:
            base_dt = hist_end + pd.Timedelta(minutes=15)
            auto_prev_in = base_dt - pd.Timedelta(hours=1)
            auto_prev_out = auto_prev_in + pd.Timedelta(hours=1, minutes=45)
            prev_in_val = auto_prev_in.strftime("%Y-%m-%d %H:%M")
            prev_out_val = auto_prev_out.strftime("%Y-%m-%d %H:%M")
            st.success(f"Auto-filled Previous Visit Times from historical end: {hist_end}")
        else:
            st.warning("No historical data found to auto-fill.")

    prev_col1, prev_col2 = st.columns(2)
    with prev_col1:
        prev_datetime_in = st.text_input("Prev Datetime In (YYYY-MM-DD HH:MM)", value=prev_in_val)
    with prev_col2:
        prev_datetime_out = st.text_input("Prev Datetime Out (YYYY-MM-DD HH:MM)", value=prev_out_val)

    # ══════════════════════════════════════════════════
    # ── RUN QAQC ──
    # ══════════════════════════════════════════════════
    if st.button("Run QAQC"):
        try:
            dt_in = pd.to_datetime(datetime_in)
            dt_out = pd.to_datetime(datetime_out)

            df = df.sort_values('timestamp')

            # ── Padding / Trimming ──
            if enable_padding:
                current_start = df['timestamp'].min()
                current_end = df['timestamp'].max()

                if pad_start:
                    start_dt = pd.to_datetime(pad_start)

                    if start_dt > current_start:
                        st.info(f"Trimming data before {start_dt} to prevent overlap.")
                        df = df[df['timestamp'] >= start_dt].copy()
                        current_start = start_dt
                    elif start_dt < current_start:
                        st.info(f"Padding data from {start_dt} to {current_start}")
                        current_start = start_dt

                full_range = pd.date_range(start=current_start, end=current_end, freq=pad_interval)
                df_grid = pd.DataFrame({'timestamp': full_range})
                df = pd.merge(df_grid, df, on='timestamp', how='left')

                new_rows_mask = df['station_code'].isna()
                if not df.empty:
                    valid_row = df.dropna(subset=['station_code']).iloc[0]
                    for col in ['station_code', 'utc_offset', 'logger_serial', 'data_id']:
                        if col in df.columns:
                            df[col] = df[col].fillna(valid_row[col])

            # Remove duplicate timestamps
            dup_count = df.duplicated(subset=['timestamp'], keep='first').sum()
            if dup_count > 0:
                df = df.drop_duplicates(subset=['timestamp'], keep='first').reset_index(drop=True)
                st.warning(f"Dropped {dup_count} duplicate timestamp(s).")

            # ══════════════════════════════════════════
            # PRECIPITATION FLAGS
            # Concatenatable: B, S, T  |  Standalone: M, V, P
            # ══════════════════════════════════════════
            precip = df['precip'] if 'precip' in df.columns else pd.Series(np.nan, index=df.index)

            # Masks
            precip_missing = precip.isna()
            precip_threshold_mask = precip > precip_threshold
            precip_freeze_mask = pd.Series(False, index=df.index)
            if 'air_temp' in df.columns:
                precip_freeze_mask = df['air_temp'] < freeze_temp

            # Spike: precip > 3mm AND both neighbors == 0
            precip_prev = precip.shift(1)
            precip_next = precip.shift(-1)
            precip_spike_mask = (precip > spike_precip) & (precip_prev == 0) & (precip_next == 0)

            # Visit
            precip_visit_mask = (df['timestamp'] > dt_in) & (df['timestamp'] <= dt_out)

            # Previous visit
            precip_prev_visit_mask = pd.Series(False, index=df.index)
            if prev_datetime_in and prev_datetime_out:
                try:
                    prev_dt_in = pd.to_datetime(prev_datetime_in)
                    prev_dt_out = pd.to_datetime(prev_datetime_out)
                    precip_prev_visit_mask = (df['timestamp'] > prev_dt_in) & (df['timestamp'] <= prev_dt_out)
                    st.info(f"Applied 'V' flag for previous visit: {prev_dt_in} to {prev_dt_out}")
                except Exception as e:
                    st.warning(f"Could not parse Previous Visit times: {e}")

            # Build concatenated flags (alphabetical: B, S, T)
            concat_precip = pd.Series('', index=df.index)
            for flag_char, mask in sorted([('B', precip_freeze_mask), ('S', precip_spike_mask), ('T', precip_threshold_mask)]):
                concat_precip = concat_precip.where(~mask, concat_precip + flag_char + ', ')
            concat_precip = concat_precip.str.rstrip(', ')

            # Assign: default P, then concatenated, then standalone overrides
            df['precip_flag'] = concat_precip.where(concat_precip != '', 'P')
            df.loc[precip_missing, 'precip_flag'] = 'M'
            df.loc[precip_visit_mask, 'precip_flag'] = 'V'
            apply_prev_precip = precip_prev_visit_mask & (df['precip_flag'] != 'M')
            df.loc[apply_prev_precip, 'precip_flag'] = 'V'

            # ══════════════════════════════════════════
            # AIR TEMPERATURE FLAGS
            # Concatenatable: S, T  |  Standalone: M, V, P
            # ══════════════════════════════════════════
            atemp = df['air_temp'] if 'air_temp' in df.columns else pd.Series(np.nan, index=df.index)

            atemp_missing = atemp.isna()
            atemp_threshold_mask = (atemp < atemp_min) | (atemp > atemp_max)
            atemp_change = atemp.diff().abs()
            atemp_spike_mask = atemp_change > atemp_spike

            # Visit masks (same as precip)
            atemp_visit_mask = precip_visit_mask
            atemp_prev_visit_mask = precip_prev_visit_mask

            # Build concatenated flags (alphabetical: S, T)
            concat_atemp = pd.Series('', index=df.index)
            for flag_char, mask in sorted([('S', atemp_spike_mask), ('T', atemp_threshold_mask)]):
                concat_atemp = concat_atemp.where(~mask, concat_atemp + flag_char + ', ')
            concat_atemp = concat_atemp.str.rstrip(', ')

            df['atemp_flag'] = concat_atemp.where(concat_atemp != '', 'P')
            df.loc[atemp_missing, 'atemp_flag'] = 'M'
            df.loc[atemp_visit_mask, 'atemp_flag'] = 'V'
            apply_prev_atemp = atemp_prev_visit_mask & (df['atemp_flag'] != 'M')
            df.loc[apply_prev_atemp, 'atemp_flag'] = 'V'

            # ── Mark padded rows as M ──
            if enable_padding:
                # Rows that were padded (added by grid merge) have NaN precip AND NaN air_temp
                padded_mask = precip.isna() & atemp.isna()
                df.loc[padded_mask, 'precip_flag'] = 'M'
                df.loc[padded_mask, 'atemp_flag'] = 'M'

            st.success("QAQC Complete!")

            # Store in session state
            st.session_state['qaqc_df'] = df
            st.session_state['qaqc_file'] = selected_file

            st.session_state['qaqc_metadata'] = {
                'field_in': datetime_in,
                'field_out': datetime_out,
                'prev_field_in': prev_datetime_in,
                'prev_field_out': prev_datetime_out,
                'record_start': df['timestamp'].min().strftime("%Y-%m-%d %H:%M:%S"),
                'record_end': df['timestamp'].max().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            st.error(f"Error during QAQC: {e}")

    # ══════════════════════════════════════════════════
    # ── VISUALIZATION (after QAQC) ──
    # ══════════════════════════════════════════════════
    if 'qaqc_df' in st.session_state and st.session_state.get('qaqc_file') == selected_file:
        df_qaqc = st.session_state['qaqc_df']

        st.subheader("Precipitation")
        fig_precip = go.Figure()
        fig_precip.add_trace(go.Bar(
            x=df_qaqc['timestamp'], y=df_qaqc['precip'],
            name='Precipitation', marker_color='lightblue', opacity=0.5
        ))

        precip_colors = {
            'P': 'green', 'S': 'red', 'T': 'orange', 'B': 'blue',
            'M': 'darkred', 'V': 'pink'
        }
        for flag, color in precip_colors.items():
            subset = df_qaqc[df_qaqc['precip_flag'] == flag]
            if not subset.empty:
                fig_precip.add_trace(go.Scatter(
                    x=subset['timestamp'], y=subset['precip'],
                    mode='markers', name=f"Precip Flag: {flag}",
                    marker=dict(color=color, size=6)
                ))
        # Concatenated flags
        concat_mask = df_qaqc['precip_flag'].str.contains(',', na=False)
        if concat_mask.any():
            for combo in df_qaqc.loc[concat_mask, 'precip_flag'].unique():
                combo_data = df_qaqc[df_qaqc['precip_flag'] == combo]
                fig_precip.add_trace(go.Scatter(
                    x=combo_data['timestamp'], y=combo_data['precip'],
                    mode='markers', name=f"Precip Flag: {combo}",
                    marker=dict(color='brown', size=6, symbol='diamond')
                ))

        fig_precip.update_layout(title=f"Precipitation QAQC - {selected_file}",
                                  xaxis_title="Timestamp", yaxis_title="Precipitation (mm)",
                                  hovermode="x unified")
        st.plotly_chart(fig_precip, use_container_width=True)

        st.subheader("Air Temperature")
        fig_temp = go.Figure()
        fig_temp.add_trace(go.Scatter(
            x=df_qaqc['timestamp'], y=df_qaqc['air_temp'],
            mode='lines', name='Air Temperature',
            line=dict(color='gray', width=1)
        ))

        atemp_colors = {
            'P': 'green', 'S': 'red', 'T': 'orange',
            'M': 'darkred', 'V': 'pink'
        }
        for flag, color in atemp_colors.items():
            subset = df_qaqc[df_qaqc['atemp_flag'] == flag]
            if not subset.empty:
                fig_temp.add_trace(go.Scatter(
                    x=subset['timestamp'], y=subset['air_temp'],
                    mode='markers', name=f"Temp Flag: {flag}",
                    marker=dict(color=color, size=6)
                ))
        concat_mask_t = df_qaqc['atemp_flag'].str.contains(',', na=False)
        if concat_mask_t.any():
            for combo in df_qaqc.loc[concat_mask_t, 'atemp_flag'].unique():
                combo_data = df_qaqc[df_qaqc['atemp_flag'] == combo]
                fig_temp.add_trace(go.Scatter(
                    x=combo_data['timestamp'], y=combo_data['air_temp'],
                    mode='markers', name=f"Temp Flag: {combo}",
                    marker=dict(color='brown', size=6, symbol='diamond')
                ))

        fig_temp.update_layout(title=f"Air Temperature QAQC - {selected_file}",
                                xaxis_title="Timestamp", yaxis_title="Air Temperature (°C)",
                                hovermode="x unified")
        st.plotly_chart(fig_temp, use_container_width=True)

        # ── Flag Summary ──
        st.subheader("Flag Summary")
        col_fs1, col_fs2 = st.columns(2)
        with col_fs1:
            st.markdown("**Precipitation Flags**")
            st.write(df_qaqc['precip_flag'].value_counts())
        with col_fs2:
            st.markdown("**Air Temperature Flags**")
            st.write(df_qaqc['atemp_flag'].value_counts())

        # ── Save ──
        if st.button("Save Flagged Data"):
            station = df_qaqc['station_code'].iloc[0] if 'station_code' in df_qaqc.columns else "Unknown"
            serial = df_qaqc['logger_serial'].iloc[0] if 'logger_serial' in df_qaqc.columns else "Unknown"

            station = str(station).replace("/", "_").replace("\\", "_")
            serial = str(serial).replace("/", "_").replace("\\", "_")

            raw_file_date = st.session_state.get('raw_file_date', None)
            date_str = raw_file_date if raw_file_date else pd.Timestamp.now().strftime("%Y%m%d")

            save_name = f"{station}_tidy_{serial}_{date_str}.csv"

            st.session_state['qaqc_metadata'] = {
                'field_in': datetime_in,
                'field_out': datetime_out,
                'prev_field_in': prev_datetime_in,
                'prev_field_out': prev_datetime_out,
                'record_start': df_qaqc['timestamp'].min().strftime("%Y-%m-%d %H:%M:%S"),
                'record_end': df_qaqc['timestamp'].max().strftime("%Y-%m-%d %H:%M:%S")
            }

            cols_to_save = ['data_id', 'station_code', 'timestamp', 'utc_offset',
                            'logger_serial', 'precip', 'precip_flag', 'air_temp', 'atemp_flag']
            final_cols = [c for c in cols_to_save if c in df_qaqc.columns]
            df_to_save = df_qaqc[final_cols].copy()

            # Replace NaN precip/temp with "NAN" string for M-flagged rows
            if 'precip' in df_to_save.columns:
                df_to_save['precip'] = df_to_save['precip'].astype(object)
                df_to_save.loc[df_to_save['precip_flag'] == 'M', 'precip'] = "NAN"
            if 'air_temp' in df_to_save.columns:
                df_to_save['air_temp'] = df_to_save['air_temp'].astype(object)
                df_to_save.loc[df_to_save['atemp_flag'] == 'M', 'air_temp'] = "NAN"

            saved_path = file_manager.save_data(df_to_save, save_name, subfolder="01_Data/02_Tidy")
            st.success(f"Saved to {saved_path}")
            st.session_state['last_saved_tidy_file'] = save_name
            st.info("Metadata stored in Session Memory. Proceed to Review/Report in THIS SESSION.")
