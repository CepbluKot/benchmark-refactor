from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID


metadata = MetaData()

studies = Table(
    "studies",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("state", String(24), nullable=False),
    Column("desired_state", String(16), nullable=False),
    Column("terminal_outcome", String(32)),
    Column("core_release_id", String(64), nullable=False),
    Column("plugin_release_id", String(64), nullable=False),
    Column("input_ref", String(256), nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("deadline_profile_ref", String(128), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("length(input_sha256) = 64", name="ck_studies_input_sha256"),
)

logical_jobs = Table(
    "logical_jobs",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column(
        "study_id",
        UUID(as_uuid=False),
        ForeignKey("studies.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("logical_key", String(128), nullable=False),
    Column("operation_contract_sha256", String(64), nullable=False),
    Column("state", String(24), nullable=False),
    Column("current_fence", BigInteger, nullable=False, server_default="0"),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint("study_id", "logical_key", name="uq_logical_jobs_study_key"),
)

workflow_projection = Table(
    "workflow_projection",
    metadata,
    Column(
        "study_id",
        UUID(as_uuid=False),
        ForeignKey("studies.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("start_command_id", UUID(as_uuid=False), nullable=False, unique=True),
    Column("workflow_route", String(192), nullable=False),
    Column("hatchet_run_id", String(128), unique=True),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
)

outbox_commands = Table(
    "outbox_commands",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column(
        "study_id",
        UUID(as_uuid=False),
        ForeignKey("studies.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "logical_job_id",
        UUID(as_uuid=False),
        ForeignKey("logical_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String(32), nullable=False),
    Column("idempotency_key", String(192), nullable=False, unique=True),
    Column("status", String(16), nullable=False),
    Column("core_release_id", String(64), nullable=False),
    Column("plugin_release_id", String(64), nullable=False),
    Column("operation_contract_sha256", String(64), nullable=False),
    Column("input_ref", String(256), nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("continuation_no", Integer, nullable=False, server_default="0"),
    Column("deadline_profile_ref", String(128), nullable=False),
    Column("claim_token", UUID(as_uuid=False)),
    Column("claim_until", DateTime(timezone=True)),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_error_code", String(64)),
    Column("hatchet_run_id", String(128)),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("dispatched_at", DateTime(timezone=True)),
    CheckConstraint("continuation_no >= 0", name="ck_outbox_continuation_nonnegative"),
)
Index(
    "ix_outbox_pending_claim",
    outbox_commands.c.status,
    outbox_commands.c.claim_until,
    outbox_commands.c.created_at,
)

attempts = Table(
    "attempts",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column(
        "study_id",
        UUID(as_uuid=False),
        ForeignKey("studies.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "logical_job_id",
        UUID(as_uuid=False),
        ForeignKey("logical_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("begin_request_id", String(256), nullable=False, unique=True),
    Column("physical_invocation_id", String(256), nullable=False),
    Column("fence_token", BigInteger, nullable=False),
    Column("state", String(32), nullable=False),
    Column("lease_expires_at", DateTime(timezone=True), nullable=False),
    Column("hatchet_workflow_run_id", String(128), nullable=False),
    Column("hatchet_task_run_id", String(128), nullable=False),
    Column("plugin_release_id", String(64), nullable=False),
    Column("operation_contract_sha256", String(64), nullable=False),
    Column("worker_id", String(128), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    UniqueConstraint("logical_job_id", "fence_token", name="uq_attempt_job_fence"),
)
Index("ix_attempts_active_lease", attempts.c.state, attempts.c.lease_expires_at)

accepted_results = Table(
    "accepted_results",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column(
        "logical_job_id",
        UUID(as_uuid=False),
        ForeignKey("logical_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "attempt_id",
        UUID(as_uuid=False),
        ForeignKey("attempts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("fence_token", BigInteger, nullable=False),
    Column("result_sha256", String(64), nullable=False),
    Column("summary", JSONB, nullable=False),
    Column(
        "accepted_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    CheckConstraint("length(result_sha256) = 64", name="ck_results_sha256"),
)

resources = Table(
    "resources",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column(
        "study_id",
        UUID(as_uuid=False),
        ForeignKey("studies.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "logical_job_id",
        UUID(as_uuid=False),
        ForeignKey("logical_jobs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "attempt_id",
        UUID(as_uuid=False),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("fence_token", BigInteger, nullable=False),
    Column("resource_key", String(128), nullable=False),
    Column("resource_kind", String(64), nullable=False),
    Column("locator_ref", Text, nullable=False),
    Column("locator_sha256", String(64), nullable=False, unique=True),
    Column("state", String(24), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("released_at", DateTime(timezone=True)),
    UniqueConstraint("attempt_id", "resource_key", name="uq_resource_attempt_key"),
)
Index("ix_resources_reap", resources.c.state, resources.c.expires_at)
