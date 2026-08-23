from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text

from benchmark_adapters.postgres import (
    PostgresProductRepository,
    create_product_engine,
)
from experiment_domain.m0 import (
    AcceptedResultConflict,
    CapacityExhausted,
    EntityNotFound,
    InvalidTransition,
    Study,
)
from runtime_services.m0 import ControlService, ProductRepository, SubmitStudy

from benchmark_m0_control.settings import ProductSettings


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitStudyRequest(ApiModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    core_release_id: str = Field(default="m0-a", pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    plugin_release_id: str = Field(
        default="m0-a", pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"
    )
    input_ref: str = Field(pattern=r"^artifact://sha256/[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deadline_profile_ref: Literal["m0.default"] = "m0.default"

    @model_validator(mode="after")
    def require_matching_reference(self) -> Self:
        if self.input_ref != f"artifact://sha256/{self.input_sha256}":
            raise ValueError("input_ref must match input_sha256")
        return self


class StudyResponse(ApiModel):
    study_id: str
    logical_job_id: str
    state: str
    desired_state: str
    terminal_outcome: str | None
    core_release_id: str
    plugin_release_id: str
    operation_contract_sha256: str
    input_ref: str
    input_sha256: str
    hatchet_run_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, study: Study) -> StudyResponse:
        return cls(
            study_id=study.study_id,
            logical_job_id=study.logical_job_id,
            state=study.state.value,
            desired_state=study.desired_state.value,
            terminal_outcome=(
                study.terminal_outcome.value if study.terminal_outcome else None
            ),
            core_release_id=study.core_release_id,
            plugin_release_id=study.plugin_release_id,
            operation_contract_sha256=study.operation_contract_sha256,
            input_ref=study.input_ref,
            input_sha256=study.input_sha256,
            hatchet_run_id=study.hatchet_run_id,
            created_at=study.created_at,
            updated_at=study.updated_at,
        )


class ErrorResponse(ApiModel):
    error_code: str


def create_app(
    *,
    repository: ProductRepository | None = None,
    settings: ProductSettings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        effective_settings = settings or ProductSettings.from_env()
        engine: Engine | None = None
        effective_repository = repository
        if effective_repository is None:
            engine = create_product_engine(effective_settings.database_url)
            effective_repository = PostgresProductRepository(engine)

        app.state.product_settings = effective_settings
        app.state.product_engine = engine
        app.state.control_service = ControlService(
            effective_repository,
            active_study_limit=effective_settings.active_study_limit,
        )
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="Benchmark Experiment Control API",
        version="0.0.1-m0",
        lifespan=lifespan,
    )

    def service(request: Request) -> ControlService:
        return request.app.state.control_service

    def product_settings(request: Request) -> ProductSettings:
        return request.app.state.product_settings

    @app.exception_handler(CapacityExhausted)
    async def capacity_handler(
        request: Request, exception: CapacityExhausted
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": "1"},
            content={"error_code": "CAPACITY_EXHAUSTED"},
        )

    @app.exception_handler(EntityNotFound)
    async def not_found_handler(
        request: Request, exception: EntityNotFound
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error_code": "NOT_FOUND"},
        )

    @app.exception_handler(AcceptedResultConflict)
    async def conflict_handler(
        request: Request, exception: AcceptedResultConflict
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error_code": "IDEMPOTENCY_CONFLICT"},
        )

    @app.exception_handler(InvalidTransition)
    async def transition_handler(
        request: Request, exception: InvalidTransition
    ) -> JSONResponse:
        del request, exception
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error_code": "INVALID_TRANSITION"},
        )

    @app.get("/health/live", status_code=status.HTTP_204_NO_CONTENT)
    def live() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/health/ready", status_code=status.HTTP_204_NO_CONTENT)
    def ready(request: Request) -> Response:
        engine: Engine | None = request.app.state.product_engine
        if engine is not None:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/v1/studies",
        response_model=StudyResponse,
        responses={
            409: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
        },
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_study(
        payload: SubmitStudyRequest,
        control: ControlService = Depends(service),
        config: ProductSettings = Depends(product_settings),
    ) -> StudyResponse | JSONResponse:
        if (
            payload.core_release_id,
            payload.plugin_release_id,
        ) not in config.allowed_release_pairs:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"error_code": "RELEASE_NOT_APPROVED"},
            )
        study = control.submit(
            SubmitStudy(
                idempotency_key=payload.idempotency_key,
                core_release_id=payload.core_release_id,
                plugin_release_id=payload.plugin_release_id,
                input_ref=payload.input_ref,
                input_sha256=payload.input_sha256,
                deadline_profile_ref=payload.deadline_profile_ref,
            )
        )
        return StudyResponse.from_domain(study)

    @app.get(
        "/v1/studies/{study_id}",
        response_model=StudyResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def get_study(
        study_id: UUID,
        control: ControlService = Depends(service),
    ) -> StudyResponse:
        return StudyResponse.from_domain(control.status(str(study_id)))

    @app.post(
        "/v1/studies/{study_id}/cancel",
        response_model=StudyResponse,
        responses={404: {"model": ErrorResponse}},
        status_code=status.HTTP_202_ACCEPTED,
    )
    def cancel_study(
        study_id: UUID,
        control: ControlService = Depends(service),
    ) -> StudyResponse:
        return StudyResponse.from_domain(control.cancel(str(study_id)))

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "benchmark_m0_control.control_api:app",
        host="0.0.0.0",
        port=8000,
        access_log=False,
    )
