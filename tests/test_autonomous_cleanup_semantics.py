from src.graph.store import GraphStore
from src.reporting.report import ExplorationEvent, ExplorationReport, render_report
from src.explorer.graph_guided_explorer import GraphGuidedExplorer
from src.explorer.browser_use_executor import BrowserUseResult, BrowserUseStepArtifact
from src.explorer.graph_expansion import expand_from_graph
from src.explorer.page_observer import PageObservation, UIElement
from src.explorer.semantic_normalizer import NormalizedIntent


def test_graph_store_treats_autonomous_statuses_as_validated(monkeypatch):
    captured = {}

    def fake_write(self, cypher, params):
        captured.update(params)

    monkeypatch.setattr(GraphStore, "write", fake_write)
    store = GraphStore()
    intent = NormalizedIntent(
        canonical_key="action.delete_item",
        human_label="Delete item",
        expected_state="shopping_cart",
        source="crawler_observed",
        risk="mutating_click",
        priority=0.5,
    )

    store.write_intent({}, "run_1", intent, "crawl_validated", ["autonomous click"])

    assert captured["observed"] is True
    assert captured["attempted"] is True
    assert captured["executed"] is True
    assert captured["validated"] is True
    assert captured["status"] == "crawl_validated"


def test_autonomous_report_stays_focused_on_crawl_and_graph_probes():
    report = ExplorationReport(
        run_id="run_1",
        feature="Amazon checkout",
        events=[
            ExplorationEvent(1, "clicked", "Delete item", "shopping_cart", "crawl_validated", "crawler_observed"),
            ExplorationEvent(2, "clicked", "Quantity", "shopping_cart", "graph_directed", "graph_inferred"),
        ],
        graph_scenarios=[],
        living_graph=None,
        coverage={"expected_total": 1, "observed": 1, "observed_pct": 100, "validated": 1, "inferred_missed": 0, "absent": []},
        graph_impact={"behaviors_validated_by_crawler_alone": 1, "scenarios_surfaced_only_by_graph": 0, "graph_directed_clicks": 1, "concept_coverage_pct": 100, "structural_gaps_flagged": []},
    )

    text = render_report(report)

    assert "AUTONOMOUS EXPLORER REPORT" in text
    assert "Autonomous crawl value" in text
    assert "Graph-directed probe clicks" in text


def test_cart_untried_surface_ignores_recommendation_junk():
    explorer = GraphGuidedExplorer(
        product_url="https://www.amazon.in/dp/B06Y2DV85R",
        tenant_id="default",
        project_id="test",
        feature_key="amazon_checkout",
    )
    obs = PageObservation(
        url="https://www.amazon.in/gp/cart/view.html",
        title="Cart",
        state="shopping_cart",
        state_scores={},
        state_evidence={},
        text="",
        detected_concepts=set(),
        elements=[
            UIElement(1, "button", "Increase quantity", None, visible=True, clickable=True, interactable=True),
            UIElement(2, "button", "Delete item", None, visible=True, clickable=True, interactable=True),
            UIElement(3, "a", "4.3 out of 5 stars, 2391 ratings", None, visible=True, clickable=True, interactable=True),
            UIElement(4, "a", "Sponsored product tile Van Heusen Solid Polo", None, visible=True, clickable=True, interactable=True),
        ],
    )

    labels = explorer._untried_visible_labels(obs)

    assert "increase quantity" in labels
    assert "delete item" in labels
    # ratings and recommendation tiles are not cart controls -> excluded from the
    # untried surface so the crawler doesn't wander into review/other-product pages
    assert all("stars" not in label and "ratings" not in label for label in labels)
    assert all("sponsored" not in label for label in labels)


def test_graph_burst_attributes_nearby_discoveries_to_graph():
    explorer = GraphGuidedExplorer(
        product_url="https://www.amazon.in/dp/B06Y2DV85R",
        tenant_id="default",
        project_id="test",
        feature_key="amazon_checkout",
    )
    obs = PageObservation(
        url="https://www.amazon.in/gp/cart/view.html",
        title="Cart",
        state="shopping_cart",
        state_scores={},
        state_evidence={},
        text="",
        detected_concepts=set(),
        elements=[],
    )
    res = BrowserUseResult(
        status="explored",
        observation=obs,
        artifacts=[
            BrowserUseStepArtifact(
                step=1,
                url=obs.url,
                title=obs.title,
                state="shopping_cart",
                action_type="click",
                target_label="Delete item",
                selector="",
                dom_excerpt="",
            ),
        ],
    )

    explorer._ingest_autonomous(res, "shopping_cart", source="graph_inferred", graph_concepts={"action.save_for_later"})

    clicked = [e for e in explorer.events if e.kind == "clicked"]
    assert clicked[0].source == "graph_inferred"
    assert clicked[0].status == "graph_directed"
    assert explorer.graph_directed_clicks == 1


def test_graph_expansion_skips_seed_only_graph():
    proposals = expand_from_graph(
        feature="amazon_checkout",
        state="shopping_cart",
        observed_concepts=[],
        validated_concepts=[],
        expected_concepts=["action.add_to_cart", "domain.cart_item"],
        absent_concepts=["action.add_to_cart", "domain.cart_item"],
        visible_affordances=[],
        graph_context={"concepts": [], "action_attempts": [], "causal_expectations": []},
        debug=True,
    )

    assert proposals == []


def test_wishlist_is_not_cart_save_for_later():
    from src.explorer.graph_guided_explorer import _action_to_concept

    assert _action_to_concept("Add to Wish List") is None
    assert _action_to_concept("Add to list") is None
    assert _action_to_concept("Save for later") == "action.save_for_later"

