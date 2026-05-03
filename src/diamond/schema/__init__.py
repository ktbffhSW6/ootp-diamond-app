"""Diamond warehouse schema package.

Three layers of CREATE TABLE DDL:
  - l0:  raw landing — one table per dump CSV, dynamic CTAS with admin
         columns (dump_date / ingest_ts / file_seq).
  - l1:  conformed — typed/scoped/deduped entity tables (Phase B+).
  - l2:  facts — analytical-grain fact tables (Phase E).

The orchestrator entry point is `diamond.schema.build` which exposes
build_l0 today and will gain build_l1 / build_l2 in subsequent phases.

See docs/SCHEMA.md for the full design and DECISIONS.md / D12 for the
scouted-ratings-only rule that's enforced at the L0→L1 boundary.
"""

from diamond.schema.l0 import L0_CATALOG, L0_SKIP, L0Spec
from diamond.schema.l1_reference import (
    L1_REFERENCE_TABLES,
    L1RefSpec,
    build_l1_reference,
)
from diamond.schema.l1_machinery import build_l1_machinery
from diamond.schema.l1_event import (
    ALL_EVENT_SPECS,
    NATURAL_PK_EVENTS,
    SYNTHETIC_PK_EVENTS,
    L1EventSpec,
    build_l1_event,
)
from diamond.schema.l1_snapshot import (
    GENERIC_SNAPSHOTS,
    L1SnapshotSpec,
    build_l1_snapshot,
)
from diamond.schema.l2 import build_l2
from diamond.schema.l3 import build_l3
from diamond.schema.build import (
    DIAMOND_INGESTS_DDL,
    already_ingested,
    build_l0,
    build_warehouse,
    dump_name_to_date,
    ingest_dump,
    init_admin_tables,
    open_warehouse_db,
    rebuild_l1_l2,
    record_ingest_done,
    record_ingest_start,
)

__all__ = [
    "L0_CATALOG",
    "L0_SKIP",
    "L0Spec",
    "L1_REFERENCE_TABLES",
    "L1RefSpec",
    "L1EventSpec",
    "ALL_EVENT_SPECS",
    "NATURAL_PK_EVENTS",
    "SYNTHETIC_PK_EVENTS",
    "L1SnapshotSpec",
    "GENERIC_SNAPSHOTS",
    "build_l1_snapshot",
    "build_l2",
    "build_l3",
    "DIAMOND_INGESTS_DDL",
    "already_ingested",
    "build_l0",
    "build_l1_machinery",
    "build_l1_reference",
    "build_l1_event",
    "build_warehouse",
    "dump_name_to_date",
    "ingest_dump",
    "init_admin_tables",
    "open_warehouse_db",
    "rebuild_l1_l2",
    "record_ingest_done",
    "record_ingest_start",
]
