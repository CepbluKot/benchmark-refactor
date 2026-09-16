/// <reference types="vite/client" />

/** Настройки контура из public/runtime-config.js. */
interface DdlBenchRuntimeConfig {
  /** Базовый адрес будущего внутреннего API; null — серверная интеграция выключена. */
  apiBaseUrl: string | null;
}

interface Window {
  __DDL_BENCH_CONFIG__?: DdlBenchRuntimeConfig;
}
