FROM grafana/grafana:13.1.0

COPY dashboard/railway/datasources /etc/grafana/provisioning/datasources
COPY dashboard/grafana/provisioning/dashboards /etc/grafana/provisioning/dashboards
COPY dashboard/grafana/dashboards /var/lib/grafana/dashboards
