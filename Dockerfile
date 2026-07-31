FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y openssh-client
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ansible/requirements.yml ansible/requirements.yml
RUN ansible-galaxy collection install -r ansible/requirements.yml
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]