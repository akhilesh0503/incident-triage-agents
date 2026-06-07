FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared/ ./shared/
COPY diagnosis_agent/ ./diagnosis_agent/
COPY diagnosis_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8004
CMD ["uvicorn", "diagnosis_agent.main:app", "--host", "0.0.0.0", "--port", "8004"]
