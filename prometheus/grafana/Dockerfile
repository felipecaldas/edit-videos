# Use the official Grafana image as a base
FROM grafana/grafana:latest

# Temporarily switch to the root user to create directories and set permissions
USER root

# Create a directory for our dashboards and ensure it's owned by the grafana user/group (UID/GID 472)
RUN mkdir -p /app/dashboards && chown -R 472:472 /app/dashboards

# Switch back to the non-root 'grafana' user
USER grafana

# Copy the dashboard JSON files into our dedicated directory
COPY ./dashboards/grafana-dashboard.json /app/dashboards/grafana-dashboard.json

# Copy the dashboard provider to tell Grafana where to look
COPY ./provisioning/dashboards/dashboard.yml /etc/grafana/provisioning/dashboards/dashboard.yml

# Copy the datasource provider
COPY ./provisioning/datasources/prometheus.yml /etc/grafana/provisioning/datasources/prometheus.yml