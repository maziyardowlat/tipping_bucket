import streamlit as st
import pandas as pd
from utils import file_manager


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

                st.dataframe(final_df.head(20))
