import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils import file_manager
import os


def app():
    st.header("Annual Compilation")

    # ── 1. Select Files to Compile ──
    st.subheader("1. Select Files to Compile")
    all_files = file_manager.list_files(subfolder="01_Data/02_Tidy", pattern=".csv")

    if not all_files:
        st.warning("No files found.")
        return

    selected_files = st.multiselect("Choose files to merge (usually for one station)", all_files)

    if selected_files:
        if st.button("Compile"):
            dfs = []
            for f in selected_files:
                d = file_manager.load_data(f, subfolder="01_Data/02_Tidy")
                if d is not None:
                    if 'timestamp' in d.columns:
                        d['timestamp'] = pd.to_datetime(d['timestamp'])
                    if 'precip' in d.columns:
                        d['precip'] = pd.to_numeric(d['precip'], errors='coerce')
                    if 'air_temp' in d.columns:
                        d['air_temp'] = pd.to_numeric(d['air_temp'], errors='coerce')
                    dfs.append(d)

            if dfs:
                combined_df = pd.concat(dfs, ignore_index=True)

                if 'data_id' in combined_df.columns:
                    combined_df = combined_df.sort_values(['timestamp', 'data_id'])
                else:
                    combined_df = combined_df.sort_values('timestamp')

                st.write(f"Combined {len(combined_df)} records.")

                # ════════════════════════════════════════════
                # Handle Duplicates — Multi-Logger Averaging
                # Ported from water temp R logic
                # ════════════════════════════════════════════

                st.write("Handling duplicate timestamps...")

                # Step A: Same-logger dedup
                before_dedup = len(combined_df)
                combined_df = combined_df.drop_duplicates(
                    subset=['timestamp', 'logger_serial'], keep='first'
                )
                same_logger_dupes = before_dedup - len(combined_df)
                if same_logger_dupes > 0:
                    st.info(f"Removed {same_logger_dupes} same-logger duplicate records.")

                # Step B: Multi-logger averaging
                dupes_mask = combined_df.duplicated(subset=['timestamp'], keep=False)

                if dupes_mask.any():
                    dupe_count = dupes_mask.sum()
                    st.info(f"Found {dupe_count} records with multi-logger overlap. Resolving...")

                    non_dupe_df = combined_df[~dupes_mask].copy()
                    dupe_df = combined_df[dupes_mask].copy()

                    # For precip + air_temp, we check both precip_flag and atemp_flag
                    # "Both P" means BOTH precip_flag and atemp_flag are P for all records in group

                    # Case 1: All flags P → average both, flag = "AVG"
                    def all_pass(g):
                        precip_all_p = (g['precip_flag'] == 'P').all() if 'precip_flag' in g.columns else True
                        atemp_all_p = (g['atemp_flag'] == 'P').all() if 'atemp_flag' in g.columns else True
                        return precip_all_p and atemp_all_p

                    case1_groups = dupe_df.groupby('timestamp').filter(all_pass)

                    if not case1_groups.empty:
                        case1_resolved = case1_groups.groupby('timestamp').agg(
                            precip=('precip', 'mean'),
                            air_temp=('air_temp', 'mean'),
                            logger_serial=('logger_serial', lambda x: '.'.join(str(s) for s in x)),
                            data_id=('data_id', lambda x: '.'.join(str(int(s)) if pd.notna(s) else 'NA' for s in x)),
                            station_code=('station_code', 'first'),
                            utc_offset=('utc_offset', 'first'),
                        ).reset_index()
                        case1_resolved['precip_flag'] = 'AVG'
                        case1_resolved['atemp_flag'] = 'AVG'
                    else:
                        case1_resolved = pd.DataFrame()

                    # Case 2: Some P, some not → keep P record
                    def some_pass(g):
                        has_p = False
                        all_p = True
                        for _, row in g.iterrows():
                            row_p = True
                            if 'precip_flag' in g.columns and row.get('precip_flag') != 'P':
                                row_p = False
                            if 'atemp_flag' in g.columns and row.get('atemp_flag') != 'P':
                                row_p = False
                            if row_p:
                                has_p = True
                            else:
                                all_p = False
                        return has_p and not all_p

                    case2_groups = dupe_df.groupby('timestamp').filter(some_pass)

                    if not case2_groups.empty:
                        # Keep rows where both flags are P
                        def is_full_pass(row):
                            p_ok = row.get('precip_flag') == 'P' if 'precip_flag' in row.index else True
                            t_ok = row.get('atemp_flag') == 'P' if 'atemp_flag' in row.index else True
                            return p_ok and t_ok

                        pass_mask = case2_groups.apply(is_full_pass, axis=1)
                        case2_resolved = case2_groups[pass_mask].copy()
                        case2_resolved = case2_resolved.drop_duplicates(subset=['timestamp'], keep='first')
                    else:
                        case2_resolved = pd.DataFrame()

                    # Case 3: No P records → average with caution flag
                    def no_pass(g):
                        for _, row in g.iterrows():
                            row_p = True
                            if 'precip_flag' in g.columns and row.get('precip_flag') != 'P':
                                row_p = False
                            if 'atemp_flag' in g.columns and row.get('atemp_flag') != 'P':
                                row_p = False
                            if row_p:
                                return False
                        return True

                    case3_groups = dupe_df.groupby('timestamp').filter(no_pass)

                    if not case3_groups.empty:
                        def resolve_no_pass(group):
                            row = group.iloc[0].copy()

                            if 'precip' in group.columns:
                                if group['precip'].isna().all():
                                    row['precip'] = pd.NA
                                else:
                                    row['precip'] = group['precip'].mean(skipna=True)

                            if 'air_temp' in group.columns:
                                if group['air_temp'].isna().all():
                                    row['air_temp'] = pd.NA
                                else:
                                    row['air_temp'] = group['air_temp'].mean(skipna=True)

                            # Determine flags
                            if 'precip_flag' in group.columns:
                                if (group['precip_flag'] == 'M').all():
                                    row['precip_flag'] = 'M'
                                else:
                                    row['precip_flag'] = 'C'

                            if 'atemp_flag' in group.columns:
                                if (group['atemp_flag'] == 'M').all():
                                    row['atemp_flag'] = 'M'
                                else:
                                    row['atemp_flag'] = 'C'

                            row['logger_serial'] = '_'.join(str(s) for s in group['logger_serial'])
                            row['data_id'] = '.'.join(str(int(s)) if pd.notna(s) else 'NA' for s in group['data_id'])
                            return row

                        case3_resolved = case3_groups.groupby('timestamp').apply(
                            resolve_no_pass
                        ).reset_index(drop=True)
                    else:
                        case3_resolved = pd.DataFrame()

                    # Combine
                    resolved_parts = [non_dupe_df]
                    case_counts = []
                    if not case1_resolved.empty:
                        resolved_parts.append(case1_resolved)
                        case_counts.append(f"{len(case1_resolved)} averaged (AVG)")
                    if not case2_resolved.empty:
                        resolved_parts.append(case2_resolved)
                        case_counts.append(f"{len(case2_resolved)} kept P record")
                    if not case3_resolved.empty:
                        resolved_parts.append(case3_resolved)
                        case_counts.append(f"{len(case3_resolved)} averaged with caution (C)")

                    final_df = pd.concat(resolved_parts, ignore_index=True).sort_values('timestamp')
                    st.success(f"Multi-logger merge: {', '.join(case_counts)}")

                    remaining_dupes = final_df.duplicated(subset=['timestamp'], keep=False).sum()
                    if remaining_dupes > 0:
                        st.error(f"WARNING: {remaining_dupes} duplicate timestamps remain!")
                    else:
                        st.info("No remaining duplicates — merge successful.")
                else:
                    final_df = combined_df
                    st.info("No multi-logger overlap — no averaging needed.")

                st.success(f"Compilation Complete. Final records: {len(final_df)}")

                # ── Save Compiled ──
                final_df_to_save = final_df.copy()
                if 'precip' in final_df_to_save.columns:
                    final_df_to_save['precip'] = final_df_to_save['precip'].astype(object)
                    final_df_to_save['precip'] = final_df_to_save['precip'].fillna("NAN")
                if 'air_temp' in final_df_to_save.columns:
                    final_df_to_save['air_temp'] = final_df_to_save['air_temp'].astype(object)
                    final_df_to_save['air_temp'] = final_df_to_save['air_temp'].fillna("NAN")

                station = final_df['station_code'].iloc[0] if 'station_code' in final_df.columns else "Unknown"
                if 'timestamp' in final_df.columns:
                    year_start = final_df['timestamp'].dt.year.min()
                    year_end = final_df['timestamp'].dt.year.max()
                    year = f"{year_start}-{year_end}" if year_start != year_end else str(year_start)
                else:
                    year = str(pd.Timestamp.now().year)

                date_today = pd.Timestamp.now().strftime("%Y-%m-%d")
                save_name = f"{station}_compiled_{date_today}.csv"
                saved_path = file_manager.save_data(final_df_to_save, save_name, subfolder="01_Data/03_Compiled")
                st.write(f"Saved compiled data to {saved_path}")

                # ══════════════════════════════════════════
                # Annual Plots
                # ══════════════════════════════════════════

                final_df['date'] = final_df['timestamp'].dt.date

                # Daily precipitation totals
                if 'precip' in final_df.columns:
                    st.subheader("Daily Precipitation")
                    daily_precip = final_df.groupby('date')['precip'].sum().reset_index()
                    fig_dp = px.bar(daily_precip, x='date', y='precip',
                                    title=f"Daily Precipitation - {station}")
                    fig_dp.update_layout(xaxis_title="Date", yaxis_title="Precipitation (mm)")
                    st.plotly_chart(fig_dp, use_container_width=True)

                # Daily mean temperature
                if 'air_temp' in final_df.columns:
                    st.subheader("Daily Mean Air Temperature")
                    daily_temp = final_df.groupby('date')['air_temp'].mean().reset_index()
                    fig_dt = px.line(daily_temp, x='date', y='air_temp',
                                     title=f"Daily Mean Air Temperature - {station}")
                    fig_dt.update_layout(xaxis_title="Date", yaxis_title="Air Temperature (°C)")
                    st.plotly_chart(fig_dt, use_container_width=True)

                # ── Statistics ──
                st.subheader("Flag Summary")
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    if 'precip_flag' in final_df.columns:
                        st.markdown("**Precipitation Flags**")
                        pf_counts = final_df['precip_flag'].value_counts()
                        pf_props = final_df['precip_flag'].value_counts(normalize=True) * 100
                        pf_summary = pd.DataFrame({'Count': pf_counts, '%': pf_props})
                        pf_summary['%'] = pf_summary['%'].map('{:.2f}'.format)
                        st.write(pf_summary)
                with col_f2:
                    if 'atemp_flag' in final_df.columns:
                        st.markdown("**Air Temperature Flags**")
                        tf_counts = final_df['atemp_flag'].value_counts()
                        tf_props = final_df['atemp_flag'].value_counts(normalize=True) * 100
                        tf_summary = pd.DataFrame({'Count': tf_counts, '%': tf_props})
                        tf_summary['%'] = tf_summary['%'].map('{:.2f}'.format)
                        st.write(tf_summary)

                # Temperature stats
                def get_stats(data, col, label):
                    if data.empty or col not in data.columns:
                        return pd.DataFrame()
                    desc = data[col].describe(percentiles=[.05, .25, .50, .75, .95])
                    stats = {
                        'Metric': ['Mean', 'SD', 'Min', 'Max', 'Median', 'P05', 'P25', 'P75', 'P95', 'Count'],
                        'Value': [desc['mean'], desc['std'], desc['min'], desc['max'], desc['50%'],
                                  desc['5%'], desc['25%'], desc['75%'], desc['95%'], desc['count']]
                    }
                    df_stats = pd.DataFrame(stats).set_index('Metric')
                    df_stats.columns = [label]
                    return df_stats

                if 'precip' in final_df.columns:
                    st.subheader("Precipitation Statistics")
                    col_ps1, col_ps2 = st.columns(2)
                    with col_ps1:
                        st.markdown("**All Data**")
                        st.write(get_stats(final_df, 'precip', 'All'))
                    with col_ps2:
                        st.markdown("**Passed Only**")
                        passed_p = final_df[final_df['precip_flag'] == 'P']
                        st.write(get_stats(passed_p, 'precip', 'Passed'))
                    st.write(f"**Total Precipitation (All):** {final_df['precip'].sum():.1f} mm")
                    st.write(f"**Total Precipitation (Passed):** {passed_p['precip'].sum():.1f} mm")

                if 'air_temp' in final_df.columns:
                    st.subheader("Air Temperature Statistics")
                    col_ts1, col_ts2 = st.columns(2)
                    with col_ts1:
                        st.markdown("**All Data**")
                        st.write(get_stats(final_df, 'air_temp', 'All'))
                    with col_ts2:
                        st.markdown("**Passed Only**")
                        passed_t = final_df[final_df['atemp_flag'] == 'P']
                        st.write(get_stats(passed_t, 'air_temp', 'Passed'))

                # ── Generate HTML Report ──
                try:
                    # Build plot HTML
                    plots_html = ""
                    if 'precip' in final_df.columns:
                        plots_html += "<h3>Daily Precipitation</h3>" + fig_dp.to_html(full_html=False, include_plotlyjs='cdn')
                    if 'air_temp' in final_df.columns:
                        plots_html += "<h3>Daily Mean Air Temperature</h3>" + fig_dt.to_html(full_html=False, include_plotlyjs='cdn')

                    # Flag tables HTML
                    flag_tables_html = ""
                    if 'precip_flag' in final_df.columns:
                        flag_tables_html += "<h4>Precipitation Flags</h4>" + pf_summary.to_html(classes='table')
                    if 'atemp_flag' in final_df.columns:
                        flag_tables_html += "<h4>Air Temperature Flags</h4>" + tf_summary.to_html(classes='table')

                    full_html = f"""
                    <html>
                    <head>
                        <title>Annual Report - {station} {year}</title>
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 40px; color: #333; }}
                            h1, h2, h3 {{ color: #2c3e50; }}
                            hr {{ border: 1px solid #eee; margin: 20px 0; }}
                            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                            th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }}
                            th {{ background-color: #f2f2f2; }}
                        </style>
                    </head>
                    <body>
                        <h1>Annual Tipping Bucket Report</h1>
                        <h2>Station: {station} | Year: {year}</h2>
                        <hr>
                        <div>{flag_tables_html}</div>
                        <hr>
                        {plots_html}
                    </body>
                    </html>
                    """

                    report_name = f"{station}_annualReport_{date_today}.html"
                    project_dir = file_manager.get_project_dir()
                    report_path = os.path.join(project_dir, "03_Reports", "03_Annual", report_name)
                    os.makedirs(os.path.dirname(report_path), exist_ok=True)

                    with open(report_path, "w") as f:
                        f.write(full_html)

                    st.success(f"Annual Report saved to: {report_path}")
                    st.session_state['generated_annual_report_path'] = report_path

                except Exception as e:
                    st.error(f"Failed to generate HTML report: {e}")

    # Persistent Open Button
    if 'generated_annual_report_path' in st.session_state:
        report_path = st.session_state['generated_annual_report_path']
        if st.button("Open Annual Report Now"):
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
                st.error(f"Could not open: {e}")
                st.info(f"Open manually: {report_path}")
