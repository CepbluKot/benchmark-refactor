FROM benchmark-studio-nginx-base:local
COPY deploy/benchmark_studio/homelab/ui.conf /etc/nginx/conf.d/default.conf
COPY apps/config_editor_ui/dist /usr/share/nginx/html
EXPOSE 8080
