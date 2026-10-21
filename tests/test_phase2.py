"""Phase 2 source, routing, profile and calendar acceptance fixtures."""

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from nexus import schema as s
from nexus.config import Settings
from nexus.domain import NexusError
from nexus.planning import PlanningService, SyncEngine
from nexus.profiles import (
    ClassificationRule,
    LinkStatus,
    OdooInstanceRef,
    PlanningProfileConfig,
    resolve_route,
)
from nexus.sources import (
    JiraCloudAdapter,
    JiraConfig,
    OdooConfig,
    OdooReadAdapter,
    SourceFailure,
    SourceItem,
    SourcePage,
    TempoCloudAdapter,
    TempoConfig,
    adf_text,
    classify_http_failure,
    group_allocations_by_issue,
    parse_ics,
)
from nexus.storage import Database, migrate

HELP_PROJECT_ID = "00000000-0000-4000-8000-000000000101"
DEV_PROJECT_ID = "00000000-0000-4000-8000-000000000102"
HELP_REPOSITORY_ID = "00000000-0000-4000-8000-000000000201"
DEV_REPOSITORY_ID = "00000000-0000-4000-8000-000000000202"
HELP_BINDING_ID = "00000000-0000-4000-8000-000000000301"
DEV_BINDING_ID = "00000000-0000-4000-8000-000000000302"


@pytest.fixture
def phase2(tmp_path):
    db = Database(Settings(state_dir=tmp_path.resolve() / "phase2"))
    migrate(db)
    actor = s.new_id()
    with db.write() as conn:
        conn.execute(
            sa.insert(s.users).values(id=actor, identity="phase2-operator", display_name="Phase 2")
        )
    yield db, PlanningService(db), actor
    db.close()


def _connection(service, adapter, instance, **extra):
    config = {
        "schema_version": 1,
        "adapter_id": adapter,
        "base_url": f"https://{instance}",
        "secret_ref": "env:NEXUS_SECRET_PHASE2",
        **extra,
    }
    result = service.save_connection(
        adapter, instance, config, (config["secret_ref"],), "fixture-build"
    )
    return {**result, "adapter_id": adapter}


def _profile(connection_ids, *, slug="developer", timezone="Europe/Brussels"):
    schedule_id, jira_id, odoo_id = connection_ids
    return PlanningProfileConfig(
        slug=slug,
        timezone=timezone,
        schedule_connection_revision_id=schedule_id,
        jira_connection_revision_id=jira_id,
        odoo_connection_revision_ids=(odoo_id,),
        odoo_instances=(
            OdooInstanceRef(
                connection_revision_id=odoo_id,
                host="odoo.example.test",
                database="client_db",
                company_ids=(4,),
                project_ids=(81,),
            ),
        ),
        allocated_account_id="tempo-account-7",
        rules=(
            ClassificationRule(
                category="helpdesk",
                jira_project_ids=("HELP",),
                issue_types=("Helpdesk",),
                requirements_source="jira",
                acceptance_field_ids=("customfield_101",),
                nexus_project_id=HELP_PROJECT_ID,
                repository_mapping_ref="helpdesk-repo-map",
                repository_binding_ids=(HELP_BINDING_ID,),
            ),
            ClassificationRule(
                category="project",
                jira_project_ids=("DEV",),
                issue_types=("Task",),
                requirements_source="odoo",
                odoo_link_field="customfield_202",
                nexus_project_id=DEV_PROJECT_ID,
                repository_mapping_ref="reviewed-repo-map",
                repository_binding_ids=(DEV_BINDING_ID,),
            ),
        ),
    )


def _profile_connections(service, *, slug="developer", timezone="Europe/Brussels"):
    _seed_project_mappings(service.db)
    tempo = _connection(
        service,
        "tempo-cloud-planner-v1",
        "api.tempo.example.test",
        allocated_account_id="tempo-account-7",
        product_id="planner",
        from_date="2026-10-01",
        to_date="2026-12-01",
        end_date_inclusive=True,
    )
    jira = _connection(
        service,
        "jira-cloud-v1",
        "jira.example.test",
        fields=[
            "summary",
            "description",
            "project",
            "issuetype",
            "assignee",
            "customfield_101",
            "customfield_202",
        ],
    )
    odoo = _connection(
        service,
        "odoo-19-read-v1",
        "odoo.example.test",
        database="client_db",
        odoo_major=19,
        company_ids=[4],
        project_ids=[81],
    )
    config = _profile(
        (
            tempo["connection_revision_id"],
            jira["connection_revision_id"],
            odoo["connection_revision_id"],
        ),
        slug=slug,
        timezone=timezone,
    )
    profile_revision = service.save_profile(config)
    return (tempo, jira, odoo), config, profile_revision


def _seed_project_mappings(db):
    projects = (
        (HELP_PROJECT_ID, "helpdesk", "Helpdesk", HELP_REPOSITORY_ID, HELP_BINDING_ID),
        (DEV_PROJECT_ID, "development", "Development", DEV_REPOSITORY_ID, DEV_BINDING_ID),
    )
    with db.write() as conn:
        for project_id, slug, name, repository_id, binding_id in projects:
            if conn.execute(
                sa.select(s.projects.c.id).where(s.projects.c.id == project_id)
            ).first():
                continue
            now = datetime.now(UTC)
            conn.execute(
                s.projects.insert().values(
                    id=project_id,
                    slug=slug,
                    name=name,
                    timezone="Europe/Brussels",
                    config={},
                    config_hash="a" * 64,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            conn.execute(
                s.repositories.insert().values(
                    id=repository_id,
                    canonical_root=f"/repositories/{slug}",
                    origin_identity=f"https://git.example.test/{slug}.git",
                    default_branch="main",
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            conn.execute(
                s.project_repositories.insert().values(
                    id=binding_id,
                    project_id=project_id,
                    repository_id=repository_id,
                    role="primary",
                    branch="main",
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )


def _sync_source_items(db, connection, items):
    class OnePage:
        adapter_id = connection["adapter_id"]
        build = "phase2-route-fixture"

        def fetch_page(self, cursor):
            return SourcePage("route-fixture", tuple(items), None, True)

    engine = SyncEngine(db)
    run = engine.start(connection["connection_revision_id"], "route-fixtures", "c" * 64)
    engine.execute(run, "route-fixtures", "c" * 64, OnePage())


def _source_item(connection, remote_type, remote_id, display_key, normalized, revision="1"):
    return SourceItem.build(
        adapter_id=connection["adapter_id"],
        remote_type=remote_type,
        remote_id=str(remote_id),
        display_key=display_key,
        normalized=normalized,
        revision=revision,
    )


def _activate_test_profile(db, service, actor):
    connections, config, revision = _profile_connections(service)
    _passing_read_tests(db, service, connections)
    cases = (
        {
            "allocation": {"id": "alloc-fixture", "account_id": config.allocated_account_id},
            "jira_issue": _issue(
                link={
                    "host": "https://odoo.example.test",
                    "database": "client_db",
                    "model": "project.task",
                    "id": 91,
                }
            ),
        },
    )
    preview = service.preview(
        revision["profile_revision_id"],
        cases,
        fetch_odoo=lambda *_: (
            LinkStatus.RESOLVED,
            {
                "name": "Task",
                "description": "requirements",
                "project_id": [81, "P"],
                "company_id": [4, "C"],
            },
        ),
    )
    service.activate(
        revision["profile_revision_id"], actor, preview_test_id=preview["preview_test_id"]
    )
    return connections, config, revision


def _issue(*, key="DEV-5", project="DEV", issue_type="Task", assignee="jira-person", link=None):
    fields = {
        "project": {"id": project},
        "issuetype": {"name": issue_type},
        "assignee": {"accountId": assignee},
        "description": "Jira text",
    }
    if link is not None:
        fields["customfield_202"] = link
    return {"id": "issue-55", "key": key, "fields": fields}


def test_routing_branches_and_allocated_user_is_not_replaced_by_jira_assignee(phase2):
    _, service, _ = phase2
    _, profile, _ = _profile_connections(service)
    helpdesk = resolve_route(
        profile,
        _issue(key="HELP-1", project="HELP", issue_type="Helpdesk"),
        allocated_account_id="tempo-account-7",
    )
    assert helpdesk.status == "ready" and helpdesk.requirements_source == "jira"
    assert helpdesk.allocated_account_id == "tempo-account-7"
    assert helpdesk.jira_assignee_id == "jira-person" and helpdesk.mismatch is True
    project = resolve_route(
        profile,
        _issue(
            link={
                "host": "https://odoo.example.test",
                "database": "client_db",
                "model": "project.task",
                "id": 91,
            }
        ),
        allocated_account_id="tempo-account-7",
        fetch_odoo=lambda host, task_id: (
            LinkStatus.RESOLVED,
            {
                "name": "Odoo task",
                "description": "criteria",
                "project_id": [81, "P"],
                "company_id": [4, "Company"],
            },
        ),
    )
    assert project.status == "ready" and project.requirements_source == "odoo"
    assert project.requirements == {"name": "Odoo task", "description": "criteria"}
    assert project.requirements_identity == "odoo.example.test/client_db:project.task:91"


@pytest.mark.parametrize(
    ("link", "status", "blocker"),
    [
        (None, "blocked", "odoo_link_missing"),
        (
            {
                "host": "https://odoo.example.test",
                "database": "client_db",
                "model": "project.task",
                "id": 91,
            },
            "blocked",
            "odoo_task_inaccessible",
        ),
        (
            {
                "host": "https://elsewhere.test",
                "database": "client_db",
                "model": "project.task",
                "id": 91,
            },
            "blocked",
            "odoo_link_invalid",
        ),
        (
            {
                "host": "https://odoo.example.test",
                "database": "wrong_db",
                "model": "project.task",
                "id": 91,
            },
            "blocked",
            "odoo_instance_or_database_mismatch",
        ),
    ],
)
def test_odoo_link_failures_block_without_jira_fallback(phase2, link, status, blocker):
    _, service, _ = phase2
    _, profile, _ = _profile_connections(service)
    route = resolve_route(
        profile,
        _issue(link=link),
        allocated_account_id="tempo-account-7",
        fetch_odoo=lambda *_: (LinkStatus.INACCESSIBLE, None),
    )
    assert route.status == status and blocker in route.blockers
    assert route.requirements_source == "odoo" and route.requirements is None


def test_classification_ambiguity_and_title_similarity_never_resolve_identity():
    with pytest.raises(ValidationError, match="overlapping classification rules"):
        PlanningProfileConfig(
            slug="bad",
            schedule_connection_revision_id="t",
            jira_connection_revision_id="j",
            allocated_account_id="a",
            rules=(
                ClassificationRule(
                    category="helpdesk",
                    jira_project_ids=("P",),
                    requirements_source="jira",
                    nexus_project_id=HELP_PROJECT_ID,
                    repository_mapping_ref="repo-a",
                    repository_binding_ids=(HELP_BINDING_ID,),
                ),
                ClassificationRule(
                    category="helpdesk",
                    jira_project_ids=("P",),
                    requirements_source="jira",
                    nexus_project_id=HELP_PROJECT_ID,
                    repository_mapping_ref="repo-b",
                    repository_binding_ids=(HELP_BINDING_ID,),
                ),
            ),
        )


def test_connection_profile_revisions_activation_rollback_and_invalidation(phase2):
    db, service, actor = phase2
    connections, profile, revision1 = _profile_connections(service)
    for connection in connections:
        with db.read() as conn:
            row = (
                conn.execute(
                    sa.select(s.connection_revisions).where(
                        s.connection_revisions.c.id == connection["connection_revision_id"]
                    )
                )
                .mappings()
                .one()
            )
        status = "blocked" if row["config"]["adapter_id"] == "tempo-cloud-planner-v1" else "passed"
        service.record_test(
            connection_revision_id=row["id"],
            profile_revision_id=None,
            test_kind="read",
            status=status,
            config_hash=row["config_hash"],
            adapter_build=row["adapter_build"],
            result={"provider_verification": "account_probe_required"}
            if status == "blocked"
            else {"read_only": True},
        )
    cases = (
        {
            "allocation": {"id": "a1", "account_id": "tempo-account-7"},
            "jira_issue": _issue(key="HELP-1", project="HELP", issue_type="Helpdesk"),
        },
    )
    preview = service.preview(revision1["profile_revision_id"], cases)
    with pytest.raises(NexusError, match="fresh_connection_test_required"):
        service.activate(
            revision1["profile_revision_id"], actor, preview_test_id=preview["preview_test_id"]
        )
    assert service.save_profile(profile)["revision"] == 2
    with db.read() as conn:
        active = conn.execute(sa.select(s.planning_profiles.c.active_revision_id)).scalar_one()
    assert active is None


def test_profile_activation_requires_complete_preview_and_rollback_is_new_event(phase2):
    db, service, actor = phase2
    connections, config, first = _profile_connections(service)
    _passing_read_tests(db, service, connections)
    cases = (
        {
            "allocation": {"id": "a1", "account_id": "tempo-account-7"},
            "jira_issue": _issue(key="HELP-1", project="HELP", issue_type="Helpdesk"),
        },
    )
    first_preview = service.preview(first["profile_revision_id"], cases)
    activated = service.activate(
        first["profile_revision_id"], actor, preview_test_id=first_preview["preview_test_id"]
    )
    changed = _profile(
        (
            connections[0]["connection_revision_id"],
            connections[1]["connection_revision_id"],
            connections[2]["connection_revision_id"],
        ),
        timezone="UTC",
    )
    second = service.save_profile(changed)
    incomplete = service.preview(
        second["profile_revision_id"], ({**cases[0], "source_reads_succeeded": False},)
    )
    with pytest.raises(NexusError, match="fresh_complete_preview_required"):
        service.activate(
            second["profile_revision_id"], actor, preview_test_id=incomplete["preview_test_id"]
        )
    good_preview = service.preview(second["profile_revision_id"], cases)
    second_active = service.activate(
        second["profile_revision_id"], actor, preview_test_id=good_preview["preview_test_id"]
    )
    profile_id = _profile_id(db, second["profile_revision_id"])
    rolled_back = service.rollback(
        profile_id,
        first["profile_revision_id"],
        actor,
    )
    assert activated["operation"] == "activate"
    assert second_active["operation"] == "activate"
    assert rolled_back["operation"] == "rollback" and rolled_back["resync_required"]
    with db.read() as conn:
        row = (
            conn.execute(
                sa.select(s.planning_profiles).where(s.planning_profiles.c.id == profile_id)
            )
            .mappings()
            .one()
        )
        invalidations = conn.execute(
            sa.select(sa.func.count()).select_from(s.profile_binding_invalidations)
        ).scalar_one()
        operations = (
            conn.execute(
                sa.select(s.profile_activations.c.operation).order_by(
                    s.profile_activations.c.created_at
                )
            )
            .scalars()
            .all()
        )
    assert row["active_revision_id"] == first["profile_revision_id"]
    assert invalidations == 3 and operations == ["activate", "activate", "rollback"]


def test_canonical_jira_task_tracks_requirements_and_allocation_history(phase2):
    db, service, actor = phase2
    (tempo, jira, odoo), _, revision = _activate_test_profile(db, service, actor)
    link_91 = {
        "host": "https://odoo.example.test",
        "database": "client_db",
        "model": "project.task",
        "id": 91,
    }
    jira_item = _source_item(
        jira,
        "jira.issue",
        "9001",
        "DEV-1",
        {
            "key": "DEV-1",
            "title": "Shared title",
            "description": "Jira summary",
            "project_id": "DEV",
            "issue_type": "Task",
            "assignee": "jira-user",
            "custom_fields": {"customfield_202": link_91},
        },
    )
    odoo_item = _source_item(
        odoo,
        "odoo.project_task",
        "91",
        "Odoo source",
        {
            "id": 91,
            "name": "Odoo source",
            "description": "Criteria v1",
            "project_id": [81, "P"],
            "company_id": [4, "C"],
        },
    )
    allocation_items = (
        _source_item(
            tempo,
            "tempo.allocation",
            "allocation-1",
            "DEV-1",
            {
                "account_id": "tempo-account-7",
                "resource_type": "user",
                "issue_id": "9001",
                "start_date": "2026-10-21",
                "end_date_exclusive": "2026-10-22",
                "effort_seconds": 3600,
            },
        ),
        _source_item(
            tempo,
            "tempo.allocation",
            "allocation-2",
            "DEV-1",
            {
                "account_id": "tempo-account-7",
                "resource_type": "user",
                "issue_id": "9001",
                "start_date": "2026-10-22",
                "end_date_exclusive": "2026-10-23",
                "effort_seconds": 7200,
            },
        ),
    )
    _sync_source_items(db, jira, (jira_item,))
    _sync_source_items(db, odoo, (odoo_item,))
    _sync_source_items(db, tempo, allocation_items)
    with db.read() as conn:
        jira_id = conn.execute(
            sa.select(s.external_items.c.id).where(
                s.external_items.c.source_id == jira["source_id"],
                s.external_items.c.remote_type == "jira.issue",
                s.external_items.c.remote_id == "9001",
            )
        ).scalar_one()
    first = service.resolve_task(revision["profile_revision_id"], jira_id, actor)
    assert first["status"] == "ready" and first["allocation_count"] == 2
    with db.read() as conn:
        task_source = (
            conn.execute(
                sa.select(s.task_sources).where(
                    s.task_sources.c.task_id == first["task_id"], s.task_sources.c.active.is_(True)
                )
            )
            .mappings()
            .one()
        )
        resolution = (
            conn.execute(
                sa.select(s.planning_task_resolutions).where(
                    s.planning_task_resolutions.c.id == first["resolution_id"]
                )
            )
            .mappings()
            .one()
        )
        allocation_links = (
            conn.execute(
                sa.select(s.planning_task_allocations).where(
                    s.planning_task_allocations.c.resolution_id == first["resolution_id"]
                )
            )
            .mappings()
            .all()
        )
    assert task_source["external_item_id"] == jira_id and task_source["role"] == "primary"
    assert resolution["requirements_source"] == "odoo"
    assert resolution["requirements_item_id"] is not None
    assert len({row["allocation_id"] for row in allocation_links}) == 2

    _sync_source_items(
        db,
        odoo,
        (
            _source_item(
                odoo,
                "odoo.project_task",
                "91",
                "Odoo source",
                {
                    "id": 91,
                    "name": "Odoo source",
                    "description": "Criteria v2",
                    "project_id": [81, "P"],
                    "company_id": [4, "C"],
                },
                revision="2",
            ),
            _source_item(
                odoo,
                "odoo.project_task",
                "92",
                "Second Odoo task",
                {
                    "id": 92,
                    "name": "Second Odoo task",
                    "description": "Criteria v3",
                    "project_id": [81, "P"],
                    "company_id": [4, "C"],
                },
            ),
        ),
    )
    refreshed_requirements = service.resolve_task(revision["profile_revision_id"], jira_id, actor)
    assert refreshed_requirements["task_id"] == first["task_id"]
    assert refreshed_requirements["fingerprint"] != first["fingerprint"]
    changed_link = {**link_91, "id": 92}
    _sync_source_items(
        db,
        jira,
        (
            _source_item(
                jira,
                "jira.issue",
                "9001",
                "DEV-1",
                {**jira_item.normalized, "custom_fields": {"customfield_202": changed_link}},
                revision="2",
            ),
            _source_item(
                jira,
                "jira.issue",
                "9002",
                "DEV-2",
                {**jira_item.normalized, "key": "DEV-2", "title": "Shared title"},
            ),
            _source_item(
                jira,
                "jira.issue",
                "9003",
                "DEV-3",
                {
                    **jira_item.normalized,
                    "key": "DEV-3",
                    "title": "Needs Odoo",
                    "custom_fields": {"customfield_202": None},
                },
            ),
        ),
    )
    changed = service.resolve_task(revision["profile_revision_id"], jira_id, actor)
    assert changed["task_id"] == first["task_id"]
    assert changed["resolution_id"] != refreshed_requirements["resolution_id"]
    _sync_source_items(
        db,
        tempo,
        (
            _source_item(
                tempo,
                "tempo.allocation",
                "allocation-1",
                "DEV-1",
                {
                    "account_id": "tempo-account-7",
                    "resource_type": "user",
                    "issue_id": "9001",
                    "start_date": "2026-10-23",
                    "end_date_exclusive": "2026-10-24",
                    "effort_seconds": 3600,
                },
                revision="2",
            ),
        ),
    )
    rescheduled = service.resolve_task(revision["profile_revision_id"], jira_id, actor)
    assert rescheduled["task_id"] == first["task_id"]
    with db.read() as conn:
        jira_ids = (
            conn.execute(
                sa.select(s.external_items.c.id).where(
                    s.external_items.c.source_id == jira["source_id"],
                    s.external_items.c.remote_type == "jira.issue",
                    s.external_items.c.remote_id.in_(("9002", "9003")),
                )
            )
            .scalars()
            .all()
        )
        second_issue = next(
            item_id
            for item_id in jira_ids
            if conn.execute(
                sa.select(s.external_items.c.remote_id).where(s.external_items.c.id == item_id)
            ).scalar_one()
            == "9002"
        )
        missing_link_issue = next(
            item_id
            for item_id in jira_ids
            if conn.execute(
                sa.select(s.external_items.c.remote_id).where(s.external_items.c.id == item_id)
            ).scalar_one()
            == "9003"
        )
    second_task = service.resolve_task(revision["profile_revision_id"], second_issue, actor)
    missing = service.resolve_task(revision["profile_revision_id"], missing_link_issue, actor)
    assert second_task["task_id"] != first["task_id"]
    assert missing["status"] == "blocked" and "odoo_link_missing" in missing["blockers"]
    _sync_source_items(
        db,
        jira,
        (
            _source_item(
                jira,
                "jira.issue",
                "9003",
                "DEV-3",
                {
                    **jira_item.normalized,
                    "key": "DEV-3",
                    "title": "Needs Odoo",
                    "custom_fields": {"customfield_202": link_91},
                },
                revision="2",
            ),
        ),
    )
    repaired = service.resolve_task(revision["profile_revision_id"], missing_link_issue, actor)
    assert repaired["task_id"] == missing["task_id"] and repaired["status"] == "ready"
    with db.read() as conn:
        history = (
            conn.execute(
                sa.select(s.planning_task_resolutions).where(
                    s.planning_task_resolutions.c.task_id == first["task_id"]
                )
            )
            .mappings()
            .all()
        )
        allocation_history = (
            conn.execute(
                sa.select(s.planning_task_allocations).where(
                    s.planning_task_allocations.c.task_id == first["task_id"]
                )
            )
            .mappings()
            .all()
        )
        holds = (
            conn.execute(
                sa.select(s.task_holds).where(s.task_holds.c.task_id == missing["task_id"])
            )
            .mappings()
            .all()
        )
    assert len(history) == 4 and len(allocation_history) == 8
    assert len({row["requirements_item_id"] for row in history}) == 2
    assert history[0]["requirements_snapshot_id"] != history[1]["requirements_snapshot_id"]
    assert len({row["allocation_snapshot_id"] for row in allocation_history}) == 3
    assert any(row["reason"] == "odoo_link_missing" and row["resolved_at"] for row in holds)


def _profile_id(db, revision_id):
    with db.read() as conn:
        return conn.execute(
            sa.select(s.planning_profile_revisions.c.profile_id).where(
                s.planning_profile_revisions.c.id == revision_id
            )
        ).scalar_one()


def _passing_read_tests(db, service, connections):
    for connection in connections:
        with db.read() as conn:
            row = (
                conn.execute(
                    sa.select(s.connection_revisions).where(
                        s.connection_revisions.c.id == connection["connection_revision_id"]
                    )
                )
                .mappings()
                .one()
            )
        service.record_test(
            connection_revision_id=row["id"],
            profile_revision_id=None,
            test_kind="read",
            status="passed",
            config_hash=row["config_hash"],
            adapter_build=row["adapter_build"],
            result={"fixture": True, "read_only": True},
        )


class _PagedAdapter:
    adapter_id = "jira-cloud-v1"
    build = "fixture"

    def __init__(self, items, *, fail_once=False):
        self.items, self.fail_once = items, fail_once
        self.calls = []

    def fetch_page(self, cursor):
        self.calls.append(cursor)
        if cursor == "next" and self.fail_once:
            self.fail_once = False
            raise SourceFailure("rate_limited", 429, retry_after=10)
        if cursor is None:
            return SourcePage("first", self.items[:1], "next", False)
        return SourcePage("next", tuple(self.items[1:]), None, True)


def _item(remote_id="88", key="DEV-1", title="Story"):
    return SourceItem.build(
        adapter_id="jira-cloud-v1",
        remote_type="jira.issue",
        remote_id=remote_id,
        display_key=key,
        normalized={"title": title, "key": key},
        revision="1",
    )


def test_sync_pagination_dedup_failed_page_cursor_and_restart_safe_retry(phase2):
    db, service, _ = phase2
    connection = _connection(service, "jira-cloud-v1", "jira.example.test")
    engine = SyncEngine(db)
    query_hash = "a" * 64
    run_id = engine.start(connection["connection_revision_id"], "issues", query_hash)
    adapter = _PagedAdapter((_item(), _item("89", "DEV-2")), fail_once=True)
    with pytest.raises(SourceFailure, match="rate_limited"):
        engine.execute(run_id, "issues", query_hash, adapter)
    with db.read() as conn:
        run = (
            conn.execute(sa.select(s.sync_runs).where(s.sync_runs.c.id == run_id)).mappings().one()
        )
        assert run["status"] == "retry_wait" and run["page_count"] == 1
        assert (
            run["cursor_after"] == "next"
            and conn.execute(sa.select(s.source_cursors)).first() is None
        )
        conn.execute  # transaction is read-only here
    with pytest.raises(NexusError, match="source_retry_not_before"):
        engine.execute(run_id, "issues", query_hash, adapter)
    with db.write() as conn:
        conn.execute(
            s.sync_runs.update()
            .where(s.sync_runs.c.id == run_id)
            .values(retry_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    result = engine.execute(run_id, "issues", query_hash, adapter)
    assert result["page_count"] == 2 and adapter.calls == [None, "next", "next"]
    with db.read() as conn:
        count = conn.execute(sa.select(sa.func.count()).select_from(s.external_items)).scalar_one()
        snapshot_count = conn.execute(
            sa.select(sa.func.count()).select_from(s.external_item_snapshots)
        ).scalar_one()
        cursor = conn.execute(sa.select(s.source_cursors)).mappings().one()
    assert count == snapshot_count == 2 and cursor["generation"] == 1
    replay = _PagedAdapter((_item(), _item("89", "DEV-2")))
    second_run = engine.start(connection["connection_revision_id"], "issues", query_hash)
    engine.execute(second_run, "issues", query_hash, replay)
    with db.read() as conn:
        assert (
            conn.execute(sa.select(sa.func.count()).select_from(s.external_items)).scalar_one() == 2
        )
        assert (
            conn.execute(
                sa.select(sa.func.count()).select_from(s.external_item_snapshots)
            ).scalar_one()
            == 2
        )


def test_sync_reconciliation_preserves_allocation_id_and_distinct_task_associations(phase2):
    db, service, _ = phase2
    connection = _connection(service, "tempo-cloud-planner-v1", "tempo.example.test")
    engine = SyncEngine(db)
    query_hash = "b" * 64
    allocation1 = SourceItem.build(
        adapter_id="tempo-cloud-planner-v1",
        remote_type="tempo.allocation",
        remote_id="alloc-1",
        display_key="DEV-5",
        normalized={
            "account_id": "assigned-user",
            "resource_type": "user",
            "issue_id": "issue-55",
            "start_date": "2026-10-21",
            "end_date_exclusive": "2026-10-22",
            "effort_seconds": 14400,
            "seconds_per_day": 7200,
        },
    )
    allocation2 = SourceItem.build(
        adapter_id="tempo-cloud-planner-v1",
        remote_type="tempo.allocation",
        remote_id="alloc-2",
        display_key="DEV-5",
        normalized={
            "account_id": "assigned-user",
            "resource_type": "user",
            "issue_id": "issue-55",
            "start_date": "2026-10-22",
            "end_date_exclusive": "2026-10-23",
            "effort_seconds": 3600,
        },
    )
    project = SourceItem.build(
        adapter_id="tempo-cloud-planner-v1",
        remote_type="tempo.allocation",
        remote_id="alloc-project",
        display_key="Project 3",
        normalized={
            "account_id": "assigned-user",
            "resource_type": "user",
            "project_id": "project-3",
            "start_date": "2026-10-21",
            "end_date_exclusive": "2026-10-22",
        },
    )

    class OnePage:
        def __init__(self, items):
            self.items = items

        def fetch_page(self, cursor):
            return SourcePage("one", self.items, None, True)

    run = engine.start(connection["connection_revision_id"], "allocations", query_hash)
    engine.execute(run, "allocations", query_hash, OnePage((allocation1, allocation2, project)))
    changed = SourceItem.build(
        adapter_id="tempo-cloud-planner-v1",
        remote_type="tempo.allocation",
        remote_id="alloc-1",
        display_key="DEV-5",
        normalized={
            "account_id": "reassigned-user",
            "resource_type": "user",
            "issue_id": "issue-55",
            "start_date": "2026-10-23",
            "end_date_exclusive": "2026-10-24",
            "effort_seconds": 14400,
        },
    )
    run2 = engine.start(connection["connection_revision_id"], "allocations", query_hash)
    engine.execute(run2, "allocations", query_hash, OnePage((changed, allocation2, project)))
    with db.read() as conn:
        rows = conn.execute(sa.select(s.planning_allocations)).mappings().all()
        first_item = (
            conn.execute(
                sa.select(s.external_items).where(s.external_items.c.remote_id == "alloc-1")
            )
            .mappings()
            .one()
        )
    first_allocation = next(row for row in rows if row["external_item_id"] == first_item["id"])
    assert first_allocation["allocated_account_id"] == "reassigned-user"
    assert first_allocation["start_date"] == date(2026, 10, 23)
    assert len([row for row in rows if row["item_id"] == "issue-55"]) == 2
    assert first_item["remote_id"] == "alloc-1"
    groups = group_allocations_by_issue(
        (
            {"allocation_id": "alloc-1", "issue_id": "issue-55", "account_id": "reassigned-user"},
            {"allocation_id": "alloc-2", "issue_id": "issue-55", "account_id": "assigned-user"},
            {"allocation_id": "alloc-project", "item_kind": "project"},
        )
    )
    assert len([entry for entry in groups if entry.get("jira_issue_id") == "issue-55"]) == 1
    issue_group = next(entry for entry in groups if entry.get("jira_issue_id") == "issue-55")
    assert issue_group["allocation_ids"] == ["alloc-1", "alloc-2"]
    assert any(entry.get("capacity_only") for entry in groups)


def test_jira_adapter_paginates_by_token_and_normalizes_adf_without_html(phase2):
    class Transport:
        def __init__(self):
            self.bodies = []

        def request(self, method, path, *, json_body=None):
            self.bodies.append((method, path, json_body))
            if json_body and json_body.get("nextPageToken"):
                return (
                    200,
                    {
                        "issues": [
                            {
                                "id": "88",
                                "key": "NEW-1",
                                "fields": {
                                    "summary": "Changed key",
                                    "description": {
                                        "type": "doc",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [
                                                    {"type": "text", "text": "<script>safe text"}
                                                ],
                                            }
                                        ],
                                    },
                                    "project": {"id": "2"},
                                    "issuetype": {"name": "Task"},
                                },
                            }
                        ],
                        "isLast": True,
                    },
                    None,
                )
            return (
                200,
                {
                    "issues": [
                        {
                            "id": "88",
                            "key": "OLD-1",
                            "fields": {
                                "summary": "Story",
                                "description": {"type": "doc", "content": []},
                                "project": {"id": "2"},
                                "issuetype": {"name": "Task"},
                            },
                        }
                    ],
                    "nextPageToken": "p2",
                    "isLast": False,
                },
                None,
            )

    config = JiraConfig(
        base_url="https://jira.example.test",
        site_url="https://jira.example.test",
        secret_ref="env:NEXUS_SECRET_PHASE2",
    )
    adapter = JiraCloudAdapter(config, Transport())
    first = adapter.fetch_page(None)
    second = adapter.fetch_page(first.next_cursor)
    assert first.next_cursor == "p2" and second.complete
    assert first.items[0].remote_id == second.items[0].remote_id == "88"
    assert second.items[0].display_key == "NEW-1"
    assert (
        adf_text(
            {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "<script>x"}]}
                ],
            }
        )
        == "<script>x"
    )
    assert second.items[0].normalized["description"] == "<script>safe text"


@pytest.mark.parametrize("major", [17, 18, 19])
def test_odoo_version_adapters_use_only_configured_read_contract(major):
    class Transport:
        def __init__(self):
            self.calls = []

        def request(self, method, path, *, json_body=None):
            self.calls.append((method, path, json_body))
            if path.endswith("fields_get"):
                return (
                    200,
                    {
                        field: {"type": "char"}
                        for field in (
                            "id",
                            "name",
                            "description",
                            "project_id",
                            "company_id",
                            "write_date",
                        )
                    },
                    None,
                )
            return (
                200,
                [
                    {
                        "id": 4,
                        "name": "Task",
                        "description": "<p>criteria</p>",
                        "project_id": [81, "P"],
                        "company_id": [4, "Co"],
                        "write_date": "2026-10-21 10:00:00",
                    }
                ],
                None,
            )

    config = OdooConfig(
        adapter_id=f"odoo-{major}-read-v1",
        base_url="https://odoo.example.test",
        secret_ref="env:NEXUS_SECRET_PHASE2",
        odoo_major=major,
        database="db",
        login="operator" if major < 19 else "",
        project_ids=(81,),
        company_ids=(4,),
    )
    transport = Transport()
    adapter = OdooReadAdapter(config, transport)
    assert adapter.discover()["company_scope"] is True
    page = adapter.fetch_page(None)
    assert page.complete and page.items[0].normalized["description"] == "criteria"
    assert all("project.task" in path for _, path, _ in transport.calls)
    assert all("search_read" in path or "fields_get" in path for _, path, _ in transport.calls)


def test_tempo_v4_search_pagination_account_mismatch_and_project_capacity():
    class Transport:
        def __init__(self):
            self.offsets = []

        def request(self, method, path, *, json_body=None):
            self.offsets.append(json_body["offset"])
            rows = [
                {
                    "id": n,
                    "assignee": {"id": "tempo-account-7", "type": "USER"},
                    "planItemId": "issue-55",
                    "planItemType": "ISSUE",
                    "startDate": "2026-10-21",
                    "endDate": "2026-10-21",
                    "plannedSeconds": 3600,
                    "plannedSecondsPerDay": 1800,
                    "effortPersistenceType": "SECONDS_PER_DAY",
                }
                for n in range(json_body["offset"], json_body["offset"] + json_body["limit"])
            ]
            return 200, {"metadata": {"limit": 2}, "results": rows[:2]}, None

    config = TempoConfig(
        base_url="https://api.tempo.test",
        secret_ref="env:NEXUS_SECRET_PHASE2",
        product_id="cloud-planner",
        allocated_account_id="tempo-account-7",
        page_size=2,
        from_date=date(2026, 10, 21),
        to_date=date(2026, 10, 30),
        end_date_inclusive=True,
    )
    transport = Transport()
    adapter = TempoCloudAdapter(config, transport)
    page1, page2 = adapter.fetch_page(None), adapter.fetch_page("2")
    assert page1.next_cursor == "2" and len(page1.items) == 2
    assert page2.next_cursor == "4" and transport.offsets == [0, 2]
    assert page1.items[0].normalized["end_date_exclusive"] == "2026-10-22"
    assert page1.items[0].normalized["seconds_per_day"] == 1800
    with pytest.raises(ValidationError):
        TempoConfig(
            base_url="https://api.tempo.test",
            secret_ref="env:NEXUS_SECRET_PHASE2",
            product_id="planner",
            allocated_account_id="a",
            from_date=date(2026, 1, 1),
            to_date=date(2026, 2, 1),
        )


def test_ics_recurrence_all_day_cancellation_and_dst_boundaries():
    calendar = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly
DTSTART;TZID=Europe/Brussels:20261025T013000
DTEND;TZID=Europe/Brussels:20261025T023000
RRULE:FREQ=WEEKLY;COUNT=2
SUMMARY:Review
END:VEVENT
BEGIN:VEVENT
UID:day
DTSTART;VALUE=DATE:20261026
DTEND;VALUE=DATE:20261028
SUMMARY:All day
END:VEVENT
BEGIN:VEVENT
UID:weekly
RECURRENCE-ID;TZID=Europe/Brussels:20261101T013000
DTSTART;TZID=Europe/Brussels:20261101T013000
DTEND;TZID=Europe/Brussels:20261101T020000
STATUS:CANCELLED
SUMMARY:Review
END:VEVENT
END:VCALENDAR"""
    result = parse_ics(calendar)
    cancelled = next(event for event in result if event["uid"] == "weekly" and event["cancelled"])
    day = next(event for event in result if event["uid"] == "day")
    first = next(event for event in result if event["uid"] == "weekly" and not event["cancelled"])
    assert cancelled["occurrence_key"] == "20261101T013000"
    assert day["all_day_end_exclusive"] == "2026-10-28"
    assert first["start_utc"].endswith("+00:00") and first["end_utc"].endswith("+00:00")
    with pytest.raises(NexusError, match="calendar_local_time_nonexistent"):
        parse_ics(
            """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:gap\nDTSTART;TZID=Europe/Brussels:20260329T023000\nDTEND;TZID=Europe/Brussels:20260329T033000\nEND:VEVENT\nEND:VCALENDAR"""
        )


def test_ics_import_persists_occurrences_and_reconciles_explicit_full_snapshot(phase2):
    db, service, _ = phase2
    first = """BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:meeting-1\nDTSTART;TZID=Europe/Brussels:20261021T100000\nDTEND;TZID=Europe/Brussels:20261021T110000\nSUMMARY:Planning\nEND:VEVENT\nEND:VCALENDAR"""
    result = service.import_ics("work-calendar", "Europe/Brussels", first)
    assert result["simulated"] and result["event_count"] == 1
    with db.read() as conn:
        row = conn.execute(sa.select(s.schedules)).mappings().one()
        item = conn.execute(sa.select(s.external_items)).mappings().one()
    assert row["occurrence_key"] == "single" and row["start_utc"] is not None
    changed = first.replace(
        "DTSTART;TZID=Europe/Brussels:20261021T100000",
        "DTSTART;TZID=Europe/Brussels:20261021T110000",
    ).replace(
        "DTEND;TZID=Europe/Brussels:20261021T110000", "DTEND;TZID=Europe/Brussels:20261021T120000"
    )
    service.import_ics("work-calendar", "Europe/Brussels", changed)
    with db.read() as conn:
        rows = conn.execute(sa.select(s.schedules)).mappings().all()
    assert len(rows) == 1 and rows[0]["external_item_id"] == item["id"]
    empty = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
    removed = service.import_ics("work-calendar", "Europe/Brussels", empty)
    assert removed["deleted_count"] == 1
    with db.read() as conn:
        final = conn.execute(sa.select(s.schedules)).mappings().one()
        snapshots = conn.execute(sa.select(s.external_item_snapshots)).mappings().all()
    assert final["cancelled"] is True
    assert snapshots[-1]["visibility"] == "deleted"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "credentials_or_scope_required"),
        (403, "credentials_or_scope_required"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_provider_failures_have_safe_retry_classification(status, code):
    failure = classify_http_failure(status, 17)
    retry_after = 17 if status in {429, 503} else None
    assert failure.code == code and failure.retry_after == retry_after


def test_secret_references_are_not_inline_credentials_and_unknown_config_fails():
    with pytest.raises(ValidationError):
        JiraConfig(
            base_url="https://jira.example.test",
            site_url="https://jira.example.test",
            secret_ref="env:NEXUS_SECRET_PHASE2",
            api_token="never allowed",
        )


def test_connection_revision_increments_without_changing_source_schema_version(phase2):
    db, service, _ = phase2
    first = _connection(service, "jira-cloud-v1", "jira-versioned.example.test")
    first_config = {
        "schema_version": 1,
        "adapter_id": "jira-cloud-v1",
        "base_url": "https://jira-versioned.example.test",
        "site_url": "https://jira-versioned.example.test",
        "secret_ref": "env:NEXUS_SECRET_PHASE2",
        "email": "operator@example.test",
        "fields": ["summary"],
    }
    second = service.save_connection(
        "jira-cloud-v1",
        "jira-versioned.example.test",
        {**first_config, "fields": ["summary", "description"]},
        ("env:NEXUS_SECRET_PHASE2",),
        "fixture-v1",
    )
    assert first["revision"] == 1 and second["revision"] == 2
    with db.read() as conn:
        source = (
            conn.execute(
                sa.select(s.external_sources).where(s.external_sources.c.id == first["source_id"])
            )
            .mappings()
            .one()
        )
        revisions = (
            conn.execute(
                sa.select(s.connection_revisions.c.revision)
                .where(s.connection_revisions.c.source_id == first["source_id"])
                .order_by(s.connection_revisions.c.revision)
            )
            .scalars()
            .all()
        )
    assert source["config_version"] == 1 and revisions == [1, 2]


def test_daily_projection_keeps_effort_out_of_clock_time_and_marks_stale(phase2):
    db, service, _ = phase2
    _, _, revision = _profile_connections(service)
    day = service.materialize_day(
        revision["profile_revision_id"],
        date(2026, 10, 21),
        freshness={"tempo": True, "jira": False},
        allocations=(
            {
                "allocation_id": "a",
                "start_date": "2026-10-21",
                "end_date_exclusive": "2026-10-22",
                "seconds_per_day": 7200,
            },
        ),
        schedules=(),
    )
    assert day["status"] == "stale" and day["entries"][0]["kind"] == "capacity"
    assert day["entries"][0]["exact_start"] is None and day["deadlines_are_separate"]


def test_planning_window_materializes_upcoming_and_carry_over_once(phase2):
    _, service, _ = phase2
    _, _, revision = _profile_connections(service)
    window = service.materialize_window(
        revision["profile_revision_id"],
        date(2026, 10, 21),
        3,
        freshness={"tempo": True, "jira": True},
        allocations=(
            {
                "allocation_id": "carry-1",
                "start_date": "2026-10-20",
                "end_date_exclusive": "2026-10-23",
                "seconds_per_day": None,
            },
        ),
        schedules=(
            {
                "uid": "meeting-1",
                "start_utc": "2026-10-22T09:00:00+00:00",
                "end_utc": "2026-10-22T10:00:00+00:00",
            },
        ),
    )
    assert len(window["days"]) == 3
    assert [item["allocation_id"] for item in window["carry_over"]] == ["carry-1"]
    assert [item["uid"] for item in window["upcoming"]] == ["meeting-1"]
    assert (
        service.read_window(revision["profile_revision_id"], date(2026, 10, 21), 3)["status"]
        == "fresh"
    )
