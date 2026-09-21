FROM benchmark-m0-control:local

USER root
COPY deploy/benchmark_studio/offline-wheels /offline-wheels
COPY deploy/benchmark_studio/requirements.lock /requirements.lock
RUN python -m ensurepip --upgrade \
    && python -m pip install --no-index --find-links=/offline-wheels --require-hashes -r /requirements.lock \
    && rm -rf /offline-wheels /requirements.lock

COPY apps/realtime_control_api/src /app/apps/realtime_control_api/src
ENV PYTHONPATH=/app/apps/realtime_control_api/src
USER 10001:10001
CMD ["python", "-m", "realtime_control_api.main"]
