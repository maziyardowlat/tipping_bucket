import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils import file_manager
import os


def app():
    st.header("Review Data")

    # ── 1. Select Tidy Data File ──
    st.subheader("1. Select Tidy Data")

    current_dir = file_manager.get_project_dir()
    tidy_dir = os.path.join(current_dir, "01_Data/02_Tidy")
    st.caption(f"Looking for files in: {tidy_dir}")

    if st.button("Refresh File List"):
        st.rerun()

    tidy_files = file_manager.list_files(subfolder="01_Data/02_Tidy", pattern=".csv")
    if not tidy_files:
        st.warning("No tidy files found. Please go to 'Flag & Compile' first.")
        return

    selected_file = st.selectbox("Choose File", tidy_files)

    if selected_file:
        df = file_manager.load_data(selected_file, subfolder="01_Data/02_Tidy")
        if df is not None:
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            if 'precip' in df.columns:
                df['precip'] = pd.to_numeric(df['precip'], errors='coerce')
            if 'air_temp' in df.columns:
                df['air_temp'] = pd.to_numeric(df['air_temp'], errors='coerce')

            st.write(f"Loaded {len(df)} rows.")

            # Check for required columns
            has_precip_flag = 'precip_flag' in df.columns
            has_atemp_flag = 'atemp_flag' in df.columns
            if not has_precip_flag and not has_atemp_flag:
                st.error("No flag columns found. Is this a valid Tidy file?")
                return

            # ── 2. Visual Review ──
            st.subheader("2. Visual Review")

            # --- Precipitation Plot ---
            if has_precip_flag and 'precip' in df.columns:
                st.markdown("#### Precipitation")

                all_precip_flags = df['precip_flag'].unique().tolist()
                sel_precip_flags = st.multiselect("Filter Precip Flags", all_precip_flags, default=all_precip_flags, key="precip_filter")
                filt_precip = df[df['precip_flag'].isin(sel_precip_flags)]

                fig_p = go.Figure()
                fig_p.add_trace(go.Bar(
                    x=filt_precip['timestamp'], y=filt_precip['precip'],
                    name='Precipitation', marker_color='lightblue', opacity=0.4
                ))

                precip_colors = {
                    'P': 'green', 'S': 'red', 'T': 'orange', 'B': 'blue',
                    'M': 'darkred', 'V': 'pink'
                }
                for flag in filt_precip['precip_flag'].unique():
                    subset = filt_precip[filt_precip['precip_flag'] == flag]
                    if ',' in str(flag):
                        color, symbol = 'brown', 'diamond'
                    else:
                        color, symbol = precip_colors.get(flag, 'black'), 'circle'
                    fig_p.add_trace(go.Scatter(
                        x=subset['timestamp'], y=subset['precip'],
                        mode='markers', name=f"Flag: {flag}",
                        marker=dict(color=color, size=6, symbol=symbol)
                    ))

                fig_p.update_layout(title=f"Precipitation Review: {selected_file}",
                                     xaxis_title="Timestamp", yaxis_title="Precipitation (mm)",
                                     hovermode="closest")
                st.plotly_chart(fig_p, use_container_width=True)

            # --- Air Temperature Plot ---
            if has_atemp_flag and 'air_temp' in df.columns:
                st.markdown("#### Air Temperature")

                all_atemp_flags = df['atemp_flag'].unique().tolist()
                sel_atemp_flags = st.multiselect("Filter Temp Flags", all_atemp_flags, default=all_atemp_flags, key="atemp_filter")
                filt_atemp = df[df['atemp_flag'].isin(sel_atemp_flags)]

                fig_t = go.Figure()
                fig_t.add_trace(go.Scatter(
                    x=filt_atemp['timestamp'], y=filt_atemp['air_temp'],
                    mode='lines', name='Air Temperature',
                    line=dict(color='gray', width=1)
                ))

                atemp_colors = {
                    'P': 'green', 'S': 'red', 'T': 'orange',
                    'M': 'darkred', 'V': 'pink'
                }
                for flag in filt_atemp['atemp_flag'].unique():
                    subset = filt_atemp[filt_atemp['atemp_flag'] == flag]
                    if ',' in str(flag):
                        color, symbol = 'brown', 'diamond'
                    else:
                        color, symbol = atemp_colors.get(flag, 'black'), 'circle'
                    fig_t.add_trace(go.Scatter(
                        x=subset['timestamp'], y=subset['air_temp'],
                        mode='markers', name=f"Flag: {flag}",
                        marker=dict(color=color, size=6, symbol=symbol)
                    ))

                fig_t.update_layout(title=f"Air Temperature Review: {selected_file}",
                                     xaxis_title="Timestamp", yaxis_title="Air Temperature (°C)",
                                     hovermode="closest")
                st.plotly_chart(fig_t, use_container_width=True)

            # ── 3. Manual Editing ──
            st.subheader("3. Edit Flags")
            st.info("Edit the 'precip_flag' and/or 'atemp_flag' columns directly below.")

            cols_to_show = ['timestamp']
            if 'precip' in df.columns:
                cols_to_show.append('precip')
            if 'precip_flag' in df.columns:
                cols_to_show.append('precip_flag')
            if 'air_temp' in df.columns:
                cols_to_show.append('air_temp')
            if 'atemp_flag' in df.columns:
                cols_to_show.append('atemp_flag')
            if 'station_code' in df.columns:
                cols_to_show.append('station_code')

            edited_df = st.data_editor(df[cols_to_show], num_rows="fixed", key="editor")
            df.update(edited_df)

            # ── 4. Save ──
            if st.button("Save Reviewed Data"):
                df_to_save = df.copy()
                if 'precip' in df_to_save.columns:
                    df_to_save['precip'] = df_to_save['precip'].astype(object)
                    df_to_save['precip'] = df_to_save['precip'].fillna("NAN").infer_objects(copy=False)
                if 'air_temp' in df_to_save.columns:
                    df_to_save['air_temp'] = df_to_save['air_temp'].astype(object)
                    df_to_save['air_temp'] = df_to_save['air_temp'].fillna("NAN").infer_objects(copy=False)

                saved_path = file_manager.save_data(df_to_save, selected_file, subfolder="01_Data/02_Tidy", overwrite=True)
                st.success(f"Reviewed data saved (overwritten) to {saved_path}")
                st.info("Notes saved to Session Memory.")
