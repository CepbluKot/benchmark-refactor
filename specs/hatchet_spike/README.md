# M0 optimizer worker protocol

Source of truth для узкого plugin-to-control контракта —
[`attempt_api.proto`](optimizer_sdk/m0/proto/attempt_api.proto). Протокол передаёт
только schema-versioned identities, hashes, lease/fence и server-approved resource
references. Credentials, connection URLs и пользовательские physical locators в нём
отсутствуют.

Текущий SHA-256 source proto:

```text
6ace6cb2885eefc62787690e96f0441e9e188aadd0b1fc2409a51dc19f8ff7f1
```

Python stubs воспроизводятся pinned toolchain:

```bash
uvx --from grpcio-tools==1.76.0 python -m grpc_tools.protoc \
  -I specs/hatchet_spike/optimizer_sdk/m0/proto \
  --python_out=packages/optimizer_sdk/src/optimizer_sdk/m0/proto \
  --pyi_out=packages/optimizer_sdk/src/optimizer_sdk/m0/proto \
  --grpc_python_out=packages/optimizer_sdk/src/optimizer_sdk/m0/proto \
  specs/hatchet_spike/optimizer_sdk/m0/proto/attempt_api.proto
```

После генерации import в `attempt_api_pb2_grpc.py` должен оставаться package-relative
через `optimizer_sdk.m0.proto`; проверяется обычным import/test run. Изменение полей,
identity/fence semantics или schema version требует отдельного ADR/contract review.
