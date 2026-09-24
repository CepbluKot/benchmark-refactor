FROM benchmark-studio-api-base:local
USER root
COPY apps/realtime_control_api/src /app/apps/realtime_control_api/src
ENV PYTHONPATH=/app/apps/realtime_control_api/src
USER 10001:10001
CMD ["python", "-m", "realtime_control_api.main"]
