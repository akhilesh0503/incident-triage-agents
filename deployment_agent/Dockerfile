FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared/ ./shared/
COPY deployment_agent/ ./deployment_agent/
COPY deployment_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8003
CMD ["uvicorn", "deployment_agent.main:app", "--host", "0.0.0.0", "--port", "8003"]
