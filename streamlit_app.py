"""Streamlit Community Cloud entry point with access protection enabled."""
import os
import runpy
from pathlib import Path

import streamlit as st

os.environ.setdefault('RADAR_REQUIRE_LOGIN', 'true')
os.environ.setdefault('RADAR_EPHEMERAL', 'true')
try:
    password = st.secrets.get('RADAR_TEAM_PASSWORD', '')
    if password:
        os.environ['RADAR_TEAM_PASSWORD'] = str(password)
except FileNotFoundError:
    pass

runpy.run_path(str(Path(__file__).parent / 'ui' / 'app.py'), run_name='__main__')
