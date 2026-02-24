import logging
import os
import threading
from typing import Optional
import clickhouse_connect
from clickhouse_connect import common
from clickhouse_connect.driver import httputil
from clickhouse_connect.driver.client import Client
logger = logging.getLogger(__name__)
class ClickhouseManager:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        max_pool_connections: int = 8,
        num_pools: int = 1,
        max_concurrent_streams: int = 1,
        send_receive_timeout: int | None = None,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._max_pool_connections = max_pool_connections
        self._num_pools = num_pools
        self._client: Client | None = None
        self._pool_mgr = None
        self._semaphore: threading.BoundedSemaphore | None = None
        self._init_lock = threading.Lock()
        self._max_streams = max_concurrent_streams
        self._send_receive_timeout = send_receive_timeout
    def init(self):
        if self._client is not None:
            return
        with self._init_lock:
            if self._client is not None:
                return
            logger.info(
                "ClickhouseManager.init(): creating pool_mgr and client in pid=%s", os.getpid()
            )
            self._pool_mgr = httputil.get_pool_manager(
                maxsize=self._max_pool_connections, num_pools=self._num_pools
            )
            try:
                common.set_setting("autogenerate_session_id", False)
            except Exception as e:
                logger.error(
                    f"common.set_setting('autogenerate_session_id', False) not available: {e}"
                )
            if self._send_receive_timeout:
                self._client = clickhouse_connect.get_client(
                    host=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    pool_mgr=self._pool_mgr,
                    send_receive_timeout=self._send_receive_timeout,
                    # autogenerate_session_id=False
                )
            else:
                self._client = clickhouse_connect.get_client(
                    host=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    pool_mgr=self._pool_mgr,
                    # autogenerate_session_id=False
                )
            # семафор для ограничения concurrent raw_stream внутри процесса
            self._semaphore = threading.BoundedSemaphore(value=self._max_streams)
    def get_client(self) -> Client:
        """
        Возвращает готовый клиент. Если ещё не инициализирован — выполнит lazy init.
        """
        if self._client is None:
            # lazy init
            self.init()
        return self._client
    def acquire_stream_slot(self, timeout: Optional[float] = None) -> bool:
        if self._semaphore is None:
            # lazy init
            self.init()
        return self._semaphore.acquire(timeout=timeout)
    def release_stream_slot(self):
        if self._semaphore:
            try:
                self._semaphore.release()
            except ValueError:
                logger.warning("release_stream_slot called too many times")
    def close(self):
        try:
            if self._client:
                self._client.close()
        except Exception as e:
            logger.exception(f"Error while closing ClickHouseManager: {e}")
        finally:
            self._client = None
            self._pool_mgr = None
            self._semaphore = None