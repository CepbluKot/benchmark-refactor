from pathlib import Path

from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet


def build_hatchet_client(
    *,
    token_file: str,
    host_port: str,
    server_url: str,
    tls_strategy: str = "none",
) -> Hatchet:
    token = Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Hatchet token file is empty")

    return Hatchet(
        config=ClientConfig(
            token=token,
            host_port=host_port,
            server_url=server_url,
            tls_config=ClientTLSConfig(strategy=tls_strategy),
        )
    )
