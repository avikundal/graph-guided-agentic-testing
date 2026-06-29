from __future__ import annotations

import json
from typing import Any

try:
    from neo4j import GraphDatabase
except Exception:  # neo4j is optional for unit tests / dry runs
    GraphDatabase = None

from ..config import settings
from ..explorer.semantic_normalizer import NormalizedIntent
from ..explorer.page_observer import PageObservation


_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def _is_primitive_array(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, _PRIMITIVE_TYPES) for v in value)


def _json_safe(value: Any) -> str:
    """Serialize nested objects for Neo4j properties.

    Neo4j node properties cannot be Python dict/map values. For nested
    structures we keep the full fidelity as JSON text.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _neo4j_property_value(value: Any) -> Any:
    """Convert a Python value into a Neo4j-safe property value."""
    if isinstance(value, _PRIMITIVE_TYPES):
        return value
    if _is_primitive_array(value):
        return value
    # Arrays containing dicts or arbitrary objects are not legal properties.
    return _json_safe(value)


def _flatten_assertions(assertions: dict[str, Any]) -> dict[str, Any]:
    """Build primitive-only Run properties from assertion/provenance metadata.

    Example input:
      {
        "cart": {"cart_preexisting": True, "cart_provenance": "..."},
        "add_to_cart_validated": False,
      }

    Output:
      {
        "assertions_json": "...full JSON...",
        "assertion_keys": ["cart", "add_to_cart_validated"],
        "assertion_cart_json": "...",
        "assertion_add_to_cart_validated": False,
      }

    This avoids Neo4j's "Property values can only be primitive types" error.
    """
    assertions = assertions or {}
    props: dict[str, Any] = {
        "assertions_json": _json_safe(assertions),
        "assertion_keys": sorted([str(k) for k in assertions.keys()]),
    }
    for key, value in assertions.items():
        safe_key = "".join(ch if ch.isalnum() else "_" for ch in str(key)).strip("_").lower()
        if not safe_key:
            continue
        prop_name = f"assertion_{safe_key}"
        if isinstance(value, _PRIMITIVE_TYPES) or _is_primitive_array(value):
            props[prop_name] = value
        else:
            props[f"{prop_name}_json"] = _json_safe(value)

            # Helpful convenience flattening for common cart provenance maps.
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    sub_safe = "".join(ch if ch.isalnum() else "_" for ch in str(sub_key)).strip("_").lower()
                    if not sub_safe:
                        continue
                    flat_name = f"{prop_name}_{sub_safe}"
                    props[flat_name] = _neo4j_property_value(sub_value)
    return props


class GraphStore:
    """Small typed Neo4j writer used actively during exploration."""

    def __init__(self):
        self.driver = None
        if settings.neo4j_enabled and GraphDatabase is not None:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
            )

    @property
    def enabled(self) -> bool:
        return self.driver is not None

    def close(self):
        if self.driver:
            self.driver.close()

    def verify(self):
        if self.driver:
            self.driver.verify_connectivity()

    def reset_scope(self, scope: dict):
        """Clear the full Neo4j graph for a clean demo/prototype run.

        For the take-home assignment, --reset-graph should mean the next run starts
        from an empty graph. Constraints and indexes are preserved.
        """
        self.write(
            """
            MATCH (n)
            DETACH DELETE n
            """,
            {},
        )

    def init_run(self, scope: dict, run_id: str, product_url: str):
        params = {**scope, "run_id": run_id, "product_url": product_url}
        self.write(
            """
            MERGE (f:Feature {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            ON CREATE SET f.created_at=datetime()
            MERGE (r:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id})
            SET r.product_url=$product_url, r.started_at=datetime()
            MERGE (f)-[:HAS_RUN]->(r)
            """,
            params,
        )

    def write_observation(self, scope: dict, run_id: str, step: int, obs: PageObservation):
        params = {
            **scope,
            "run_id": run_id,
            "step": step,
            "url": obs.url,
            "title": obs.title,
            "state": obs.state,
            "text": obs.text[:1500],
            "concepts": sorted(obs.detected_concepts),
        }
        self.write(
            """
            MERGE (r:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id})
            MERGE (o:Observation {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id, step:$step})
            SET o.url=$url, o.title=$title, o.state=$state, o.text=$text, o.concepts=$concepts, o.created_at=datetime()
            MERGE (s:PageState {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key:$state})
            MERGE (r)-[:OBSERVED]->(o)
            MERGE (o)-[:ON_STATE]->(s)
            WITH o
            UNWIND $concepts AS ck
            MERGE (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key:ck})
            MERGE (o)-[:SAW_CONCEPT]->(c)
            """,
            params,
        )

    def write_intent(
        self,
        scope: dict,
        run_id: str,
        intent: NormalizedIntent,
        status: str,
        evidence: list[str] | None = None,
    ):
        params = {
            **scope,
            "run_id": run_id,
            "key": intent.canonical_key,
            "label": intent.human_label,
            "expected_state": intent.expected_state,
            "source": intent.source,
            "risk": intent.risk,
            "priority": intent.priority,
            "confidence": intent.confidence,
            "status": status,
            "selector": intent.selector_candidates[0] if intent.selector_candidates else None,
            "evidence": evidence or [],
            "observed": status in {
                "frontier_added",
                "observed_only",
                "destructive_observed_not_clicked",
                "clicked_observed",
                "validated",
                "click_failed",
                "not_executable",
                "forbidden_blocked",
            },
            "attempted": status in {"click_failed", "clicked_observed", "validated"},
            "executed": status in {"clicked_observed", "validated"},
            "validated": status == "validated",
        }
        self.write(
            """
            MERGE (r:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id})
            MERGE (i:Intent {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id, key:$key, source:$source})
            SET i.label=$label, i.expected_state=$expected_state, i.risk=$risk, i.priority=$priority,
                i.confidence=$confidence, i.status=$status, i.selector=$selector, i.evidence=$evidence,
                i.observed=$observed, i.attempted=$attempted, i.executed=$executed, i.validated=$validated,
                i.updated_at=datetime()
            MERGE (r)-[:HAS_INTENT]->(i)
            MERGE (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key:$key})
            SET c.observed = coalesce(c.observed,false) OR $observed,
                c.attempted = coalesce(c.attempted,false) OR $attempted,
                c.executed = coalesce(c.executed,false) OR $executed,
                c.validated = coalesce(c.validated,false) OR $validated,
                c.last_status = $status, c.last_selector = $selector, c.last_source=$source, c.last_evidence=$evidence
            MERGE (i)-[:TARGETS]->(c)
            """,
            params,
        )

    def write_scenario(
        self,
        scope: dict,
        run_id: str,
        key: str,
        title: str,
        status: str,
        depends_on: list[str],
        source: str,
    ):
        params = {
            **scope,
            "run_id": run_id,
            "key": key,
            "title": title,
            "status": status,
            "depends_on": depends_on,
            "source": source,
        }
        self.write(
            """
            MERGE (r:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id})
            MERGE (s:Scenario {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id, key:$key})
            SET s.title=$title, s.status=$status, s.source=$source, s.depends_on=$depends_on, s.updated_at=datetime()
            MERGE (r)-[:HAS_SCENARIO]->(s)
            WITH s
            UNWIND $depends_on AS dep
            MERGE (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key:dep})
            MERGE (s)-[:DEPENDS_ON]->(c)
            """,
            params,
        )

    def write_run_assertions(self, scope: dict, run_id: str, assertions: dict[str, Any]):
        """Write run-level assertions/provenance as Neo4j-safe primitive properties.

        Neo4j does not allow nested map/dict properties. The full object is
        stored as JSON in `assertions_json`, and useful nested values are
        flattened into primitive `assertion_*` fields.
        """
        assertion_props = _flatten_assertions(assertions)
        params = {**scope, "run_id": run_id, "assertion_props": assertion_props}
        self.write(
            """
            MERGE (r:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, run_id:$run_id})
            SET r += $assertion_props,
                r.updated_at=datetime()
            """,
            params,
        )

    def ensure_constraints(self):
        """Declare uniqueness constraints (idempotent) for a defensible schema.

        Identity of the scoped graph is (tenant_id, project_id, feature_key, key)
        for Concept/PageState and (..., run_id) for Run. Constraints make MERGE
        correct under concurrency and create the backing indexes for free.
        """
        if not self.driver:
            return
        statements = [
            "CREATE CONSTRAINT concept_identity IF NOT EXISTS FOR (c:Concept) REQUIRE (c.tenant_id, c.project_id, c.feature_key, c.key) IS NODE KEY",
            "CREATE CONSTRAINT pagestate_identity IF NOT EXISTS FOR (s:PageState) REQUIRE (s.tenant_id, s.project_id, s.feature_key, s.key) IS NODE KEY",
            "CREATE CONSTRAINT run_identity IF NOT EXISTS FOR (r:Run) REQUIRE (r.tenant_id, r.project_id, r.feature_key, r.run_id) IS NODE KEY",
        ]
        with self.driver.session(database=settings.neo4j_database) as session:
            for stmt in statements:
                try:
                    session.run(stmt).consume()
                except Exception:
                    # NODE KEY needs enterprise; fall back to a plain uniqueness/index.
                    try:
                        label = "Concept" if "Concept" in stmt else "PageState" if "PageState" in stmt else "Run"
                        session.run(
                            f"CREATE INDEX {label.lower()}_scope_idx IF NOT EXISTS FOR (n:{label}) ON (n.tenant_id, n.project_id, n.feature_key)"
                        ).consume()
                    except Exception:
                        pass

    def seed_expected_concepts(self, scope: dict, keys: list[str]):
        """Seed the feature contract so ABSENCE is a queryable graph property.

        Every expected Concept is created with expected=true. A concept that is
        expected but never validated is 'absent' in the behavioural sense and can
        be found with a single query (see missing_expected_concepts).
        """
        params = {**scope, "keys": keys}
        self.write(
            """
            UNWIND $keys AS ck
            MERGE (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key:ck})
            ON CREATE SET c.observed=false, c.validated=false
            SET c.expected=true
            """,
            params,
        )

    def infer_missed_scenarios(self, scope: dict, rules: list[dict]) -> list[dict]:
        """Graph-DRIVEN inference of scenarios the agent missed.

        For each rule, the query checks the GRAPH: every prerequisite Concept must
        exist as a node in scope, and the pivot action Concept must NOT be
        validated. What comes back are behaviours the crawler stumbled near but
        never actually exercised — surfaced by the graph, not by Python state.
        """
        if not self.driver:
            return []
        params = {**scope, "rules": rules}
        with self.driver.session(database=settings.neo4j_database) as session:
            rows = session.run(
                """
                UNWIND $rules AS rule
                OPTIONAL MATCH (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
                  WHERE c.key IN rule.requires AND coalesce(c.observed, false) = true
                WITH rule, collect(DISTINCT c.key) AS present
                // every prerequisite concept must have actually been OBSERVED in a crawl
                WHERE size(present) = size(rule.requires)
                OPTIONAL MATCH (p:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key, key: rule.pivot})
                WITH rule, p
                // ...but the pivot action that would PROVE the behaviour was never validated
                WHERE rule.pivot IS NULL OR p IS NULL OR coalesce(p.validated, false) = false
                RETURN rule.key AS key, rule.title AS title, rule.status AS status, rule.requires AS depends_on
                ORDER BY key
                """,
                params,
            ).data()
            return rows or []

    def missing_expected_concepts(self, scope: dict) -> list[str]:
        """Concepts that SHOULD exist for this feature but were never even seen.

        Absence is behavioural: an expected Concept seeded for the contract that
        the crawler never observed AND never validated. Observation concepts
        (subtotal, cart_item) count as present once observed, so they are not
        reported as missing.
        """
        if not self.driver:
            return []
        with self.driver.session(database=settings.neo4j_database) as session:
            res = session.run(
                """
                MATCH (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
                WHERE coalesce(c.expected,false) = true
                  AND coalesce(c.observed,false) = false
                  AND coalesce(c.validated,false) = false
                RETURN collect(DISTINCT c.key) AS keys
                """,
                scope,
            ).single()
            return list(res["keys"] or []) if res else []

    def blast_radius(self, scope: dict, concepts: list[str], selectors: list[str]) -> dict | None:
        """What the REAL graph says is at risk for a set of changed concepts/selectors.

        Returns the Intents (UI elements/actions actually discovered) and Scenarios
        (inferred behaviours) in this scope that depend on the changed concepts.
        """
        if not self.driver:
            return None
        params = {**scope, "concepts": list(concepts), "selectors": list(selectors)}
        with self.driver.session(database=settings.neo4j_database) as session:
            intents = session.run(
                """
                MATCH (i:Intent {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
                WHERE i.key IN $concepts
                   OR (i.selector IS NOT NULL AND size($selectors) > 0
                       AND any(s IN $selectors WHERE i.selector CONTAINS s OR s CONTAINS i.selector))
                RETURN DISTINCT i.key AS key, i.label AS label, i.selector AS selector,
                       i.source AS source, coalesce(i.validated,false) AS validated,
                       coalesce(i.executed,false) AS executed
                ORDER BY key
                """,
                params,
            ).data()
            scenarios = session.run(
                """
                MATCH (sc:Scenario {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})-[:DEPENDS_ON]->(c:Concept)
                WHERE c.key IN $concepts
                RETURN DISTINCT sc.key AS key, sc.title AS title, sc.status AS status,
                       sc.source AS source, collect(DISTINCT c.key) AS depends_on
                ORDER BY key
                """,
                params,
            ).data()
        return {"intents": intents, "scenarios": scenarios}

    def observed_keys(self, scope: dict) -> set[str]:
        if not self.driver:
            return set()
        with self.driver.session(database=settings.neo4j_database) as session:
            res = session.run(
                """
                MATCH (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
                RETURN collect(distinct c.key) AS keys
                """,
                scope,
            ).single()
            return set(res["keys"] or []) if res else set()

    def write(self, cypher: str, params: dict[str, Any]):
        if not self.driver:
            return
        with self.driver.session(database=settings.neo4j_database) as session:
            session.run(cypher, params).consume()
