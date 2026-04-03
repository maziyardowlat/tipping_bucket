import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils import file_manager
import os


def app():
    st.header("Generate QAQC Report")

    # ── 1. Select Tidy Data ──
    st.subheader("1. Select Tidy Data")
    tidy_files = file_manager.list_files(subfolder="01_Data/02_Tidy", pattern=".csv")
    tidy_files = [f for f in tidy_files if not f.endswith("_notes.csv") and not f.endswith("_metadata.json")]
    if not tidy_files:
        st.warning("No data found in Tidy folder.")
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

            st.subheader(f"Report for {selected_file}")

            # ── Summary Stats ──
            st.markdown("### Summary Statistics")
            total_records = len(df)
            st.write(f"**Total Records:** {total_records}")

            col_s1, col_s2 = st.columns(2)

            with col_s1:
                if 'precip_flag' in df.columns:
                    st.markdown("**Precipitation Flags:**")
                    pf_counts = df['precip_flag'].value_counts()
                    st.bar_chart(pf_counts)
                    pass_p = pf_counts.get('P', 0)
                    st.write(f"**Precip Pass Rate:** {(pass_p / total_records) * 100:.2f}%")

                if 'precip' in df.columns:
                    st.write(f"**Total Precipitation:** {df['precip'].sum():.1f} mm")
                    st.write("**Precip Stats (All):**")
                    st.write(df['precip'].describe())

            with col_s2:
                if 'atemp_flag' in df.columns:
                    st.markdown("**Air Temperature Flags:**")
                    tf_counts = df['atemp_flag'].value_counts()
                    st.bar_chart(tf_counts)
                    pass_t = tf_counts.get('P', 0)
                    st.write(f"**Temp Pass Rate:** {(pass_t / total_records) * 100:.2f}%")

                if 'air_temp' in df.columns:
                    st.write("**Temp Stats (All):**")
                    st.write(df['air_temp'].describe())

            # ── Plots ──
            st.markdown("### Time Series Plots")

            # Precipitation
            if 'precip' in df.columns and 'precip_flag' in df.columns:
                fig_p = go.Figure()
                fig_p.add_trace(go.Bar(
                    x=df['timestamp'], y=df['precip'],
                    name='Precipitation', marker_color='lightblue', opacity=0.4
                ))

                precip_colors = {
                    'P': 'green', 'S': 'red', 'T': 'orange', 'B': 'blue',
                    'M': 'darkred', 'V': 'pink'
                }
                for flag in df['precip_flag'].unique():
                    subset = df[df['precip_flag'] == flag]
                    if ',' in str(flag):
                        color, symbol = 'brown', 'diamond'
                    else:
                        color, symbol = precip_colors.get(flag, 'black'), 'circle'
                    fig_p.add_trace(go.Scatter(
                        x=subset['timestamp'], y=subset['precip'],
                        mode='markers', name=f"Flag: {flag}",
                        marker=dict(color=color, size=6, symbol=symbol)
                    ))

                fig_p.update_layout(title=f"Precipitation - {selected_file}",
                                     xaxis_title="Timestamp", yaxis_title="Precipitation (mm)",
                                     hovermode="closest")
                st.plotly_chart(fig_p, use_container_width=True)

            # Air Temperature
            if 'air_temp' in df.columns and 'atemp_flag' in df.columns:
                fig_t = go.Figure()
                fig_t.add_trace(go.Scatter(
                    x=df['timestamp'], y=df['air_temp'],
                    mode='lines', name='Air Temperature',
                    line=dict(color='gray', width=1), hoverinfo='skip'
                ))

                atemp_colors = {
                    'P': 'green', 'S': 'red', 'T': 'orange',
                    'M': 'darkred', 'V': 'pink'
                }
                for flag in df['atemp_flag'].unique():
                    subset = df[df['atemp_flag'] == flag]
                    if ',' in str(flag):
                        color, symbol = 'brown', 'diamond'
                    else:
                        color, symbol = atemp_colors.get(flag, 'black'), 'circle'
                    fig_t.add_trace(go.Scatter(
                        x=subset['timestamp'], y=subset['air_temp'],
                        mode='markers', name=f"Flag: {flag}",
                        marker=dict(color=color, size=6, symbol=symbol)
                    ))

                fig_t.update_layout(title=f"Air Temperature - {selected_file}",
                                     xaxis_title="Timestamp", yaxis_title="Air Temperature (°C)",
                                     hovermode="closest")
                st.plotly_chart(fig_t, use_container_width=True)

            # ── Generate HTML Report ──
            if st.button("Generate HTML Report"):
                try:
                    station = df['station_code'].iloc[0] if 'station_code' in df.columns else "Unknown"
                    serial = df['logger_serial'].iloc[0] if 'logger_serial' in df.columns else "Unknown"
                    utc_offset = df['utc_offset'].iloc[0] if 'utc_offset' in df.columns else "Unknown"
                    data_id = df['data_id'].iloc[0] if 'data_id' in df.columns else "Unknown"

                    record_start = df['timestamp'].min().strftime("%Y-%m-%d %H:%M:%S")
                    record_end = df['timestamp'].max().strftime("%Y-%m-%d %H:%M:%S")

                    # Load metadata from session
                    default_field_in = "N/A"
                    default_field_out = "N/A"
                    default_prev_in = "N/A"
                    default_prev_out = "N/A"
                    default_start = record_start
                    default_end = record_end

                    if 'qaqc_metadata' in st.session_state:
                        meta = st.session_state['qaqc_metadata']
                        default_field_in = str(meta.get('field_in', "N/A"))
                        default_field_out = str(meta.get('field_out', "N/A"))
                        default_prev_in = str(meta.get('prev_field_in', "N/A"))
                        default_prev_out = str(meta.get('prev_field_out', "N/A"))
                        default_start = str(meta.get('record_start', record_start))
                        default_end = str(meta.get('record_end', record_end))
                        st.success("Loaded metadata from Session Memory.")
                    else:
                        st.info("No metadata in session. Please enter details below.")

                    with st.expander("Edit Report Metadata", expanded=True):
                        col_m1, col_m2 = st.columns(2)
                        with col_m1:
                            field_in = st.text_input("Field Time In", value=default_field_in)
                            prev_field_in = st.text_input("Prev Visit In", value=default_prev_in)
                            record_start = st.text_input("Record Start", value=default_start)
                        with col_m2:
                            field_out = st.text_input("Field Time Out", value=default_field_out)
                            prev_field_out = st.text_input("Prev Visit Out", value=default_prev_out)
                            record_end = st.text_input("Record End", value=default_end)

                    metadata_html = f"""
                    <h3>Metadata</h3>
                    <p>
                    <b>Station Code:</b> {station}<br>
                    <b>Logger Serial Number:</b> {serial}<br>
                    <b>UTC Offset:</b> {utc_offset}<br>
                    <b>Data ID:</b> {data_id}<br>
                    <b>Field time-in:</b> {field_in}<br>
                    <b>Field time-out:</b> {field_out}<br>
                    <b>Previous field time-in:</b> {prev_field_in}<br>
                    <b>Previous field time-out:</b> {prev_field_out}<br>
                    <b>Record Start Date:</b> {record_start}<br>
                    <b>Record End Date:</b> {record_end}
                    </p>
                    """

                    # ── Flag Summary Tables ──
                    flag_names = {
                        'P': 'Pass', 'M': 'Missing', 'T': 'Threshold Exceedance',
                        'B': 'Below Freezing', 'S': 'Spike (Suspect)', 'V': 'Visit'
                    }

                    def build_flag_table_html(flag_col, label):
                        if flag_col not in df.columns:
                            return f"<p>No {label} flag data.</p>"
                        fc = df[flag_col].value_counts().reset_index()
                        fc.columns = ['flag_symbol', 'flag_count']

                        def resolve_name(sym):
                            if sym in flag_names:
                                return flag_names[sym]
                            parts = [f.strip() for f in str(sym).replace(',', ' ').split() if f.strip()]
                            names = [flag_names.get(f, f) for f in parts]
                            return ' + '.join(names) if names else 'Unknown'

                        fc['flag_name'] = fc['flag_symbol'].apply(resolve_name)
                        fc['flag_prop'] = (fc['flag_count'] / total_records) * 100

                        html = f"<h4>{label}</h4>"
                        html += """<table border="1" cellpadding="5" cellspacing="0"
                                    style="border-collapse: collapse; width: 60%;">
                        <thead><tr style="background-color: #f2f2f2;">
                        <th>Flag</th><th>Name</th><th>Count</th><th>%</th></tr></thead><tbody>"""
                        for _, row in fc.iterrows():
                            html += f"""<tr>
                                <td style="text-align:center;">{row['flag_symbol']}</td>
                                <td>{row['flag_name']}</td>
                                <td style="text-align:right;">{row['flag_count']}</td>
                                <td style="text-align:right;">{row['flag_prop']:.4f}</td></tr>"""
                        html += "</tbody></table>"
                        return html

                    precip_table_html = build_flag_table_html('precip_flag', 'Precipitation Flags')
                    atemp_table_html = build_flag_table_html('atemp_flag', 'Air Temperature Flags')

                    # Plot HTML
                    plot_precip_html = ""
                    plot_temp_html = ""
                    if 'precip' in df.columns:
                        plot_precip_html = fig_p.to_html(full_html=False, include_plotlyjs='cdn')
                    if 'air_temp' in df.columns:
                        plot_temp_html = fig_t.to_html(full_html=False, include_plotlyjs='cdn')

                    # Notes
                    default_notes = "No notes entered in session."
                    if 'qaqc_notes' in st.session_state:
                        default_notes = st.session_state['qaqc_notes']

                    with st.expander("Edit QAQC Notes", expanded=True):
                        notes_content = st.text_area("Notes", value=default_notes)

                    # ── Full HTML ──
                    full_html = f"""
                    <html>
                    <head><title>QAQC Report - {station}</title></head>
                    <body style="font-family: Arial, sans-serif; margin: 40px;">
                        <h1>Tipping Bucket QAQC Report</h1>
                        <hr>
                        {metadata_html}
                        <hr>
                        <h3>Flag Summary</h3>
                        {precip_table_html}
                        <br>
                        {atemp_table_html}
                        <hr>
                        <h3>Precipitation Time Series</h3>
                        {plot_precip_html}
                        <hr>
                        <h3>Air Temperature Time Series</h3>
                        {plot_temp_html}
                        <hr>
                        <h3>QAQC Notes</h3>
                        <p>{notes_content}</p>
                    </body>
                    </html>
                    """

                    raw_file_date = st.session_state.get('raw_file_date', None)
                    date_for_filename = raw_file_date if raw_file_date else pd.Timestamp.now().strftime("%Y%m%d")
                    report_name = f"{station}_qaqcReport_{serial}_{date_for_filename}.html"

                    project_dir = file_manager.get_project_dir()
                    report_path = os.path.join(project_dir, "03_Reports", "02_QAQC", report_name)
                    os.makedirs(os.path.dirname(report_path), exist_ok=True)

                    with open(report_path, "w") as f:
                        f.write(full_html)

                    st.success(f"Report saved to: {report_path}")
                    st.session_state['generated_report_path'] = report_path

                except Exception as e:
                    st.error(f"Failed to generate report: {e}")

            # Persistent Open Button
            if 'generated_report_path' in st.session_state:
                report_path = st.session_state['generated_report_path']
                if st.button("Open Report Now"):
                    import subprocess
                    import sys
                    try:
                        if sys.platform == 'darwin':
                            subprocess.run(['open', report_path], check=True)
                        elif sys.platform == 'win32':
                            os.startfile(report_path)
                        else:
                            subprocess.run(['xdg-open', report_path], check=True)
                    except Exception as e:
                        st.error(f"Could not open file automatically: {e}")
                        st.info(f"Please open manually: {report_path}")

            st.info("You can also print this page to PDF using your browser's print function.")
