"""
Загрузка project-конфига и сборка `BenchmarkRootConfig`.

Модуль отвечает за multi-file конфигурацию:
  - читает project JSON;
  - подгружает отдельные файлы connections/rule_banks/benchmarks;
  - валидирует ссылочную целостность.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from pydantic import ValidationError

from src.models import (
    BenchmarkConfig,
    BenchmarkProjectConfig,
    BenchmarkRootConfig,
    BenchmarksFileConfig,
    CeleryConfig,
    ConnectionsFileConfig,
    RuleBanksFileConfig,
)


class ConfigLoader:
    """
    Обёртка над проектной загрузкой конфигурации.

    Pipeline:
      1) парсинг `BenchmarkProjectConfig`;
      2) чтение вложенных JSON-файлов;
      3) сборка `BenchmarkRootConfig`;
      4) проверка ссылок (connection_id, rule_bank, default_rule_banks).
    """

    def load(self, path: Union[str, Path]) -> BenchmarkRootConfig:
        """Загружает и валидирует project-конфиг из файла."""
        config_path = Path(path)
        raw = self._read_json(config_path)
        return self.parse(raw, base_dir=config_path.parent)

    def parse(
        self,
        raw: Dict[str, Any],
        base_dir: Optional[Union[str, Path]] = None,
    ) -> BenchmarkRootConfig:
        """Парсит уже загруженный dict project-конфига."""
        return self._parse_project_config(
            raw,
            base_dir=Path(base_dir) if base_dir is not None else Path.cwd(),
        )

    def parse_parts(
        self,
        celery_raw: Dict[str, Any],
        connections_raw: Dict[str, Any],
        rule_banks_raw: Dict[str, Any],
        benchmarks_raw: Dict[str, Any],
    ) -> BenchmarkRootConfig:
        """
        Собирает `BenchmarkRootConfig` из уже загруженных секций JSON.

        Используется, когда проект не читает файлы напрямую, а получает
        независимые JSON-секции (например, через env base64).
        """
        try:
            celery = CeleryConfig.model_validate(celery_raw)
        except ValidationError as e:
            raise ValueError("Ошибки в celery-конфиге:\n" + str(e)) from e

        try:
            connections_data = ConnectionsFileConfig.model_validate(connections_raw)
        except ValidationError as e:
            raise ValueError("Ошибки в connections-конфиге:\n" + str(e)) from e

        try:
            rule_banks_data = RuleBanksFileConfig.model_validate(rule_banks_raw)
        except ValidationError as e:
            raise ValueError("Ошибки в rule_banks-конфиге:\n" + str(e)) from e

        try:
            benchmarks_data = BenchmarksFileConfig.model_validate(benchmarks_raw)
        except ValidationError as e:
            raise ValueError("Ошибки в benchmarks-конфиге:\n" + str(e)) from e

        assembled = BenchmarkRootConfig(
            connections=connections_data.connections,
            benchmarks=benchmarks_data.benchmarks,
            rule_banks=rule_banks_data.rule_banks,
            default_rule_banks=rule_banks_data.default_rule_banks,
            celery=celery,
        )
        self._validate_references(assembled)
        return assembled

    def _parse_project_config(
        self,
        raw: Dict[str, Any],
        base_dir: Path,
    ) -> BenchmarkRootConfig:
        """Собирает `BenchmarkRootConfig` из project-конфига и связанных файлов."""
        try:
            project = BenchmarkProjectConfig.model_validate(raw)
        except ValidationError as e:
            raise ValueError(f"Ошибки в project-конфиге:\n{e}") from e

        connections_path = self._resolve_file_path(base_dir, project.connections_file)
        rule_banks_path = self._resolve_file_path(base_dir, project.rule_banks_file)

        try:
            connections_data = ConnectionsFileConfig.model_validate(
                self._read_json(connections_path)
            )
        except ValidationError as e:
            raise ValueError(f"Ошибки в connections файле {connections_path}:\n{e}") from e

        try:
            rule_banks_data = RuleBanksFileConfig.model_validate(
                self._read_json(rule_banks_path)
            )
        except ValidationError as e:
            raise ValueError(f"Ошибки в rule_banks файле {rule_banks_path}:\n{e}") from e

        if project.benchmarks_file is not None:
            benchmarks_path = self._resolve_file_path(base_dir, project.benchmarks_file)
            try:
                benchmarks_data = BenchmarksFileConfig.model_validate(
                    self._read_json(benchmarks_path)
                )
            except ValidationError as e:
                raise ValueError(
                    f"Ошибки в benchmarks файле {benchmarks_path}:\n{e}"
                ) from e
            benchmarks = benchmarks_data.benchmarks
        else:
            benchmarks = project.benchmarks or []

        assembled = BenchmarkRootConfig(
            connections=connections_data.connections,
            benchmarks=benchmarks,
            rule_banks=rule_banks_data.rule_banks,
            default_rule_banks=rule_banks_data.default_rule_banks,
            celery=project.celery,
        )
        self._validate_references(assembled)
        return assembled

    @staticmethod
    def _resolve_file_path(base_dir: Path, ref: str) -> Path:
        """Резолвит относительный путь к файлу относительно `base_dir`."""
        path = Path(ref)
        if path.is_absolute():
            return path
        return (base_dir / path).resolve()

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        """Читает JSON-файл и преобразует ошибки в понятные ValueError."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as e:
            raise ValueError(f"Файл не найден: {path}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Некорректный JSON в файле {path}: {e}") from e

    def _validate_references(self, config: BenchmarkRootConfig) -> None:
        """
        Валидирует кросс-ссылки между секциями конфига.

        Проверяет:
          - `default_rule_banks` ссылаются на существующие bank id;
          - каждый `benchmark.connection_id` существует;
          - `rule_bank` в global/table rules существует.
        """
        connection_ids = {c.id for c in config.connections}
        bank_ids = set(config.rule_banks.keys())

        for dbms, bank_id in config.default_rule_banks.items():
            if bank_id not in bank_ids:
                raise ValueError(
                    f"default_rule_banks[{dbms!r}]={bank_id!r} "
                    f"не найден в rule_banks"
                )

        for bench in config.benchmarks:
            if bench.connection_id not in connection_ids:
                raise ValueError(
                    f"benchmark {bench.id!r}: "
                    f"connection_id={bench.connection_id!r} не найден в connections"
                )

            all_rules = [bench.global_rules] + [tr.rules for tr in bench.table_rules]
            for rules in all_rules:
                if rules.rule_bank is not None and rules.rule_bank not in bank_ids:
                    raise ValueError(
                        f"benchmark {bench.id!r}: "
                        f"rule_bank={rules.rule_bank!r} не найден в rule_banks"
                    )

            self._validate_table_rule_scope(bench)

    @staticmethod
    def _validate_table_rule_scope(bench: BenchmarkConfig) -> None:
        """Проверяет, что table-level override не выходят за selector `databases`."""
        if bench.databases == "*":
            return

        allowed_databases = set(bench.databases)
        for tr in bench.table_rules:
            if tr.database not in allowed_databases:
                raise ValueError(
                    f"benchmark {bench.id!r}: table_rules для {tr.database}.{tr.table} "
                    f"не совпадает с databases={bench.databases}"
                )


def load_config(path: Union[str, Path]) -> BenchmarkRootConfig:
    """Публичный helper: загрузка project-конфига из файла."""
    return ConfigLoader().load(path)


def parse_config(
    raw: Dict[str, Any],
    base_dir: Optional[Union[str, Path]] = None,
) -> BenchmarkRootConfig:
    """Публичный helper: парсинг project-конфига из уже загруженного dict."""
    return ConfigLoader().parse(raw, base_dir=base_dir)


def parse_config_parts(
    celery_raw: Dict[str, Any],
    connections_raw: Dict[str, Any],
    rule_banks_raw: Dict[str, Any],
    benchmarks_raw: Dict[str, Any],
) -> BenchmarkRootConfig:
    """
    Публичный helper: сборка root-конфига из отдельных JSON-секций.

    Подходит для запуска, где конфиги передаются не файлами, а через env.
    """
    return ConfigLoader().parse_parts(
        celery_raw=celery_raw,
        connections_raw=connections_raw,
        rule_banks_raw=rule_banks_raw,
        benchmarks_raw=benchmarks_raw,
    )
