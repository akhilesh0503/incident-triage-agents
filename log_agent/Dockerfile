FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared/ ./shared/
COPY log_agent/ ./log_agent/
COPY log_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8001
CMD ["uvicorn", "log_agent.main:app", "--host", "0.0.0.0", "--port", "8001"]
