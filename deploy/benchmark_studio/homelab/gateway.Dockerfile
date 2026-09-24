FROM benchmark-studio-nginx-base:local
COPY deploy/benchmark_studio/homelab/gateway.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
