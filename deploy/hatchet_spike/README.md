# M0 Hatchet architecture spike

Статус: **M0-PARTIAL**, только локальный architecture spike. Это не production
baseline и не разрешение удалять legacy runtime. Актуальная матрица доказательств —
в [отчёте M0](../../docs/M0_HATCHET_SPIKE_REPORT.md).

## Что проверяет spike

Путь исполнения выглядит так:

```text
client -> Control API -> product PostgreSQL + outbox
                              |
                         command starter
                              |
                         Hatchet Engine
                              |
                  durable core task -> toy plugin task
                                           |
                                     Attempt gRPC API
                                           |
                                  attempts/fences/results
                                           |
                                  product PostgreSQL

                  core finalize task -> Finalization gRPC API
                    (separate network)          |
                                          terminal outcome

independent Reaper -> expired attempt-scoped resources / cancelled studies
```

Hatchet владеет progression и delivery. Product PostgreSQL владеет Study state,
attempt/fence, accepted result, resources и terminal outcome. Toy plugin запущен
отдельным Python 3.12 worker, общается только через узкий Protobuf API и не содержит
PostgreSQL driver. Plugin network не имеет маршрута к Finalization API или product
PostgreSQL. RabbitMQ не используется: Hatchet queue и pub/sub работают через его
PostgreSQL database.

Один физический PostgreSQL допустим только для M0: Hatchet и product state находятся
в разных databases, с разными owners, application role и migration path.

## Локальный запуск

Нужны Docker Engine с Compose v2 и свободные loopback-порты `18800` и, для
operator UI, `18880`.

```bash
cp deploy/hatchet_spike/.env.example deploy/hatchet_spike/.env
# Заменить все REPLACE_* значения; пароли должны быть URL-safe.

docker compose \
  --env-file deploy/hatchet_spike/.env \
  -f deploy/hatchet_spike/compose.yaml \
  up -d --build --wait
```

Пример Study:

```bash
curl --fail-with-body \
  --header 'Content-Type: application/json' \
  --data '{
    "idempotency_key":"manual-001",
    "core_release_id":"m0-a",
    "plugin_release_id":"m0-a",
    "input_ref":"artifact://sha256/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "input_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "deadline_profile_ref":"m0.default"
  }' \
  http://127.0.0.1:18800/v1/studies
```

Полученный `study_id` проверяется через
`GET http://127.0.0.1:18800/v1/studies/{study_id}`. Product status никогда не
читается из внутренних таблиц или UI Hatchet.

Воспроизводимый HTTP full-path test:

```bash
M0_E2E_BASE_URL=http://127.0.0.1:18800 \
  uv run --all-packages pytest -q \
  tests/e2e/m0/test_hatchet_compose_full_path.py
```

## Fault injection

Toy worker понимает `M0_TOY_FAULT_POINT=before_side_effect`,
`after_side_effect` или `after_commit`. Значение задаётся в окружении Compose, после
чего worker пересоздаётся. Это только test hook: процесс намеренно завершается с
кодом `86`, а Hatchet доставляет task повторно.

```bash
M0_TOY_FAULT_POINT=after_commit docker compose \
  --env-file deploy/hatchet_spike/.env \
  -f deploy/hatchet_spike/compose.yaml \
  up -d --force-recreate toy-worker
```

Worker token создаётся один раз в named volume и не ротируется при частичном
`compose up`. Он истекает через семь дней. Безопасная недеструктивная production
rotation в M0 ещё не реализована.

## Operator UI

UI необязателен и запускается профилем `operator-ui`:

```bash
docker compose \
  --env-file deploy/hatchet_spike/.env \
  -f deploy/hatchet_spike/compose.yaml \
  --profile operator-ui up -d --wait
```

Адрес: `http://127.0.0.1:18880`. Caddy запрещает public scripts/fonts через CSP,
но текущий Hatchet Frontend всё ещё содержит public/CDN references. Поэтому UI с
заблокированным egress и весь HAT-09 пока **не пройдены**.

## Остановка

`down` сохраняет PostgreSQL, Hatchet config и token volumes:

```bash
docker compose \
  --env-file deploy/hatchet_spike/.env \
  -f deploy/hatchet_spike/compose.yaml down
```

`down -v` удаляет все локальные M0 данные, конфигурацию Hatchet и worker token. Его
можно использовать только для осознанного сброса disposable spike.

Сборка сейчас получает Python wheels и `uv` из доступного package source. Для
закрытого контура ещё нужны internal registry/wheelhouse, imported trust metadata и
полный прогон с deny-all public egress; локальная успешная сборка этого не доказывает.
