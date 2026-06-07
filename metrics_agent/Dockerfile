FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared/ ./shared/
COPY metrics_agent/ ./metrics_agent/
COPY metrics_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8002
CMD ["uvicorn", "metrics_agent.main:app", "--host", "0.0.0.0", "--port", "8002"]
