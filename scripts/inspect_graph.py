#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

from neo4j import GraphDatabase
from src.config import settings


def _parse_assertions(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    return {"raw": str(raw)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-id", default="default")
    p.add_argument("--project-id", default="amazon_demo")
    p.add_argument("--feature", default="amazon_checkout")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    if not settings.neo4j_enabled:
        print("Neo4j env vars missing; graph disabled.")
        return
    feature_key = args.feature if args.feature.startswith("feature.") else f"feature.{args.feature}"
    params = {
        "tenant_id": args.tenant_id,
        "project_id": args.project_id,
        "feature_key": feature_key,
        "run_id": args.run_id,
    }

    drv = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password))
    with drv.session(database=settings.neo4j_database) as s:
        print("Actions:")
        for r in s.run("""
            MATCH (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE c.key STARTS WITH 'action.' OR c.key STARTS WITH 'capability.'
            OPTIONAL MATCH (i:Intent {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})-[:TARGETS]->(c)
            WHERE $run_id IS NULL OR i.run_id=$run_id
            WITH c, collect(i) AS intents
            RETURN c.key AS key,
                   coalesce(c.observed,false) AS observed,
                   coalesce(c.attempted,false) AS attempted,
                   coalesce(c.executed,false) AS executed,
                   coalesce(c.validated,false) AS validated,
                   c.last_status AS last_status,
                   c.last_selector AS last_selector,
                   c.last_source AS last_source,
                   size(intents) AS intent_writes
            ORDER BY key
        """, params):
            print(
                f" - {r['key']} observed={r['observed']} attempted={r['attempted']} "
                f"executed={r['executed']} validated={r['validated']} "
                f"last_status={r['last_status']} selector={r['last_selector']} source={r['last_source']} writes={r['intent_writes']}"
            )

        print("\nDomain concepts:")
        for r in s.run("""
            MATCH (c:Concept {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE c.key STARTS WITH 'domain.'
            RETURN c.key AS key,
                   coalesce(c.observed,false) AS observed,
                   coalesce(c.executed,false) AS executed,
                   coalesce(c.validated,false) AS validated,
                   c.last_status AS last_status
            ORDER BY key
        """, params):
            print(
                f" - {r['key']} observed={r['observed']} executed={r['executed']} "
                f"validated={r['validated']} last_status={r['last_status']}"
            )

        print("\nScenarios:")
        for r in s.run("""
            MATCH (sc:Scenario {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE $run_id IS NULL OR sc.run_id=$run_id
            RETURN sc.title AS title, sc.status AS status, sc.source AS source ORDER BY title
        """, params):
            print(f" - {r['title']} [{r['status']}] source={r['source']}")

        print("\nGraph probes:")
        for r in s.run("""
            MATCH (p:GraphProbe {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE $run_id IS NULL OR p.run_id=$run_id
            OPTIONAL MATCH (p)-[:PROBES]->(c:Concept)
            RETURN p.key AS key, p.title AS title, p.status AS status,
                   p.target_state AS target_state, collect(DISTINCT c.key) AS concepts
            ORDER BY p.round_no, p.key
        """, params):
            print(f" - {r['key']}: {r['title']} [{r['status']}] state={r['target_state']} concepts={r['concepts']}")

        print("\nAction attempts:")
        for r in s.run("""
            MATCH (a:ActionAttempt {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE $run_id IS NULL OR a.run_id=$run_id
            OPTIONAL MATCH (a)-[:TARGETS]->(c:Concept)
            RETURN a.step AS step, a.source AS source, a.action_type AS action_type,
                   a.target_label AS target_label, a.status AS status,
                   a.page_state_before AS before_state, a.page_state_after AS after_state,
                   collect(DISTINCT c.key) AS concepts
            ORDER BY a.step LIMIT 80
        """, params):
            print(
                f" - {r['step']}: [{r['source']}] {r['action_type']} {r['target_label']} "
                f"{r['before_state']}->{r['after_state']} status={r['status']} concepts={r['concepts']}"
            )

        print("\nCausal expectations:")
        for r in s.run("""
            MATCH (ce:CausalExpectation {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            RETURN ce.key AS key, ce.title AS title, ce.cause AS cause,
                   ce.effect AS effect, ce.state AS state
            ORDER BY ce.key
        """, params):
            print(f" - {r['key']}: {r['cause']} SHOULD_CAUSE {r['effect']} on {r['state']} - {r['title']}")

        print("\nRun assertions:")
        for r in s.run("""
            MATCH (run:Run {tenant_id:$tenant_id, project_id:$project_id, feature_key:$feature_key})
            WHERE $run_id IS NULL OR run.run_id=$run_id
            RETURN run.run_id AS run_id,
                   run.assertions_json AS assertions_json,
                   run.assertion_cart_preflight_cart_preexisting AS cart_preexisting,
                   run.assertion_cart_preflight_cart_provenance AS cart_provenance,
                   run.assertion_add_to_cart_validated AS add_to_cart_validated,
                   run.assertion_proceed_to_checkout_validated AS proceed_to_checkout_validated,
                   run.assertion_end_to_end_checkout_flow_validated AS end_to_end_checkout_flow_validated
            ORDER BY run.started_at DESC LIMIT 5
        """, params):
            assertions = _parse_assertions(r["assertions_json"])
            print(f" - {r['run_id']}:")
            print(f"     cart_preexisting={r['cart_preexisting']} provenance={r['cart_provenance']}")
            print(f"     add_to_cart_validated={r['add_to_cart_validated']}")
            print(f"     proceed_to_checkout_validated={r['proceed_to_checkout_validated']}")
            print(f"     end_to_end_checkout_flow_validated={r['end_to_end_checkout_flow_validated']}")
            if assertions:
                print(f"     assertions_json={json.dumps(assertions, ensure_ascii=False)}")
    drv.close()


if __name__ == "__main__":
    main()
