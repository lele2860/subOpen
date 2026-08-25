FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY subscription_gate.py /app/subscription_gate.py
RUN chmod 0555 /app/subscription_gate.py

# Match the standard www-data UID/GID so a host file owned by root:www-data
# with mode 0640 can be mounted read-only.
USER 33:33

EXPOSE 8080
ENTRYPOINT ["python3", "/app/subscription_gate.py"]
CMD ["--config", "/etc/subscription-gate/gate.conf"]
