FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8501
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home radar && mkdir -p /var/radar/data /var/radar/exports /var/radar/logs && chown -R radar:radar /app /var/radar
USER radar
ENV RADAR_DATA_DIR=/var/radar/data RADAR_EXPORT_DIR=/var/radar/exports RADAR_LOG_DIR=/var/radar/logs RADAR_REQUIRE_LOGIN=true
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8501')+'/_stcore/health',timeout=4)"
CMD ["sh", "-c", "exec python -m streamlit run ui/app.py --server.address=0.0.0.0 --server.port=$PORT --server.headless=true --browser.gatherUsageStats=false"]
