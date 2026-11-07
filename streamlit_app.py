"""Streamlit Community Cloud entry point with access protection enabled."""
import os
import runpy
from pathlib import Path

import streamlit as st

os.environ.setdefault('RADAR_REQUIRE_LOGIN', 'true')
os.environ.setdefault('RADAR_EPHEMERAL', 'true')
try:
    for name in ('RADAR_TEAM_PASSWORD', 'RADAR_SYNC_URL', 'RADAR_SYNC_TOKEN', 'RADAR_SYNC_KEY',
                 'RADAR_COLLECTION_MODE', 'OPENAI_API_KEY'):
        value = st.secrets.get(name, '')
        if value:
            os.environ[name] = str(value)
except FileNotFoundError:
    pass

runpy.run_path(str(Path(__file__).parent / 'ui' / 'app.py'), run_name='__main__')
