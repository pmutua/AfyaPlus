FROM prom/prometheus:v3.12.0

COPY dashboard/railway/prometheus.yml /etc/prometheus/prometheus.yml
