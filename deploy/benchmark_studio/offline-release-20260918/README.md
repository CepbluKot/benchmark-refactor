# DB Benchmark: offline deployment

To create a fresh image archive from this checkout, run:

```sh
./deploy/benchmark_studio/build-offline-image-bundle.sh \
  --output ./benchmark-studio-images.tar.gz
```

The script builds the local UI and Control API images, includes all images from
the deployment Compose file, and prints the SHA-256 checksum of the resulting
single archive.

Copy `.env.example` to `.env`, set a unique database password and the browser-visible UI address. Set `apiBaseUrl` in `runtime-config.js` to the browser-visible Control API address. Then run:

```sh
docker load -i benchmark-studio-images.tar.gz
docker compose --env-file .env up -d
```

The UI and API use separate host ports; this Compose file has no build instructions, registry pulls, or reverse proxy. PostgreSQL and ClickHouse remain internal Docker services.
