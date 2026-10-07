FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "backtesting", "-c", "config/freqtrade_compat.json", "--csv", "tests/fixtures/btcusdt_1m_sample.csv"]
