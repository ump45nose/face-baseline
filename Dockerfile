# syntax=docker/dockerfile:1
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS native
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
COPY --from=ofiq source/OFIQlib/include /headers
COPY --from=ofiq releases/ubuntu_x86_64/libofiq_lib.so /libofiq/libofiq_lib.so
COPY --from=ofiq releases/ubuntu_x86_64/libonnxruntime.so.1.18.0 /libofiq/libonnxruntime.so.1.18.0
COPY backend/ofiq_runner.cpp /runner.cpp
RUN g++ -O2 -std=c++17 -I/headers /runner.cpp -L/libofiq -lofiq_lib -Wl,-rpath,/opt/ofiq/lib -o /ofiq-runner

FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv libimage-exiftool-perl libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY --from=native --chown=1000:1001 /ofiq-runner /app/ofiq-runner
COPY --from=native --chown=1000:1001 /libofiq /opt/ofiq/lib
COPY --from=ofiq --chown=1000:1001 source/data/ofiq_config.jaxn /opt/ofiq/data/ofiq_config.jaxn
COPY --from=ofiq --chown=1000:1001 source/data/models /opt/ofiq/data/models
COPY --from=ofiq --chown=1000:1001 source/LICENSE.md /opt/ofiq/LICENSE.md
COPY --from=ofiq --chown=1000:1001 yunet /opt/ofiq/yunet
COPY --chown=1000:1001 backend /app/backend
COPY --chown=1000:1001 web/dist /app/web
ENV PATH=/opt/venv/bin:$PATH LD_LIBRARY_PATH=/opt/ofiq/lib PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=2
WORKDIR /app
USER 1000:1001
EXPOSE 8080
CMD ["uvicorn", "backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
