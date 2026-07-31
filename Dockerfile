FROM python:3.11-slim
WORKDIR /app

# Install & Configure SSH
RUN apt-get update && apt-get install -y openssh-client
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh && ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519

# Install Python Deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Ansible Deps
COPY ansible/requirements.yml ansible/requirements.yml
RUN ansible-galaxy collection install -r ansible/requirements.yml

# Launch Server
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]