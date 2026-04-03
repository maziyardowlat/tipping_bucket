import streamlit as st
import os
import pandas as pd

def get_project_dir():
    if 'project_dir' not in st.session_state:
        st.session_state.project_dir = os.getcwd()
    return st.session_state.project_dir

def set_project_dir(path):
    if os.path.isdir(path):
        st.session_state.project_dir = path
        return True
    return False

def save_data(df, filename, subfolder="01_Data/01_Raw_Formatted", overwrite=False):
    project_dir = get_project_dir()
    full_path_dir = os.path.join(project_dir, subfolder)
    os.makedirs(full_path_dir, exist_ok=True)

    file_path = os.path.join(full_path_dir, filename)

    if not overwrite and os.path.exists(file_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filename = f"{base}_{counter}{ext}"
        new_file_path = os.path.join(full_path_dir, new_filename)

        while os.path.exists(new_file_path):
            counter += 1
            new_filename = f"{base}_{counter}{ext}"
            new_file_path = os.path.join(full_path_dir, new_filename)

        st.warning(f"File '{filename}' already exists. Saving as '{new_filename}' instead.")
        file_path = new_file_path

    df.to_csv(file_path, index=False)
    return file_path

def load_data(filename, subfolder="01_Data/01_Raw_Formatted"):
    project_dir = get_project_dir()
    file_path = os.path.join(project_dir, subfolder, filename)
    if os.path.exists(file_path):
        try:
            return pd.read_csv(file_path)
        except (UnicodeDecodeError, pd.errors.ParserError):
            try:
                df = pd.read_excel(file_path)
                st.warning(f"File '{filename}' appears to be an Excel file renamed to '.csv'.")
                return df
            except Exception:
                st.error(f"Error reading file '{filename}'.")
                return None
    return None

def list_files(subfolder="01_Data/01_Raw_Formatted", pattern=None):
    project_dir = get_project_dir()
    full_path = os.path.join(project_dir, subfolder)
    if not os.path.exists(full_path):
        return []
    files = os.listdir(full_path)
    if pattern:
        files = [f for f in files if pattern in f]
    return files
