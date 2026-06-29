from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.checkout_contract import (
    STATE_CART,
    STATE_CART_CONFIRMATION,
    STATE_CHECKOUT,
    STATE_FINAL,
    STATE_PRODUCT,
    STATE_UNKNOWN,
    has_final_purchase_text,
    is_forbidden_text,
)

GENERIC_TAG_SELECTORS = {"a", "button", "input", "select", "span", "div", "form", "textarea", "summary"}


@dataclass
class UIElement:
    index: int
    tag: str
    text: str
    selector: str | None
    role: str | None = None
    aria_label: str | None = None
    name: str | None = None
    id: str | None = None
    type: str | None = None
    href: str | None = None
    value: str | None = None
    visible: bool = True
    enabled: bool = True
    clickable: bool = False
    interactable: bool = False
    selector_quality: str = "generic"  # stable | anchored | positional | generic | none
    selector_reason: str = ""
    tabindex: str | None = None
    in_nav_or_header: bool = False
    form_id: str | None = None
    form_action: str | None = None
    rect: dict | None = None

    @property
    def haystack(self) -> str:
        vals = [
            self.tag,
            self.text,
            self.selector or "",
            self.role or "",
            self.aria_label or "",
            self.name or "",
            self.id or "",
            self.type or "",
            self.href or "",
            self.value or "",
        ]
        return " ".join(v for v in vals if v).lower()

    @property
    def label(self) -> str:
        return self.text or self.aria_label or self.value or self.name or self.id or self.selector or self.tag

    @property
    def stable_click_selector(self) -> bool:
        return self.selector_quality in {"stable", "anchored"} and bool(self.selector)

    @property
    def can_execute(self) -> bool:
        return self.visible and self.enabled and self.clickable and self.interactable and self.stable_click_selector


@dataclass
class PageObservation:
    url: str
    title: str
    state: str
    state_scores: dict[str, float]
    state_evidence: dict[str, list[str]]
    text: str
    elements: list[UIElement]
    detected_concepts: set[str] = field(default_factory=set)
    forbidden_action_detected: bool = False
    forbidden_boundary_detected: bool = False

    def element_summary(self) -> list[str]:
        out = []
        for e in self.elements[:80]:
            out.append(
                f"[{e.index}] {e.tag} {e.label[:80]} selector={e.selector} "
                f"visible={e.visible} interactable={e.interactable} quality={e.selector_quality}"
            )
        return out


class PageObserver:
    """Observes the current browser page without clicking.

    State detection is multi-signal and preconditioned. A final order boundary
    cannot be inferred from a product/cart page just because the page has a Buy
    Now button. It must be a checkout/order-review surface with a final purchase
    affordance.
    """

    async def observe(self, page: Any) -> PageObservation:
        await page.wait_for_timeout(900)
        url = page.url
        try:
            title = await page.title()
        except Exception:
            title = ""
        try:
            text = (await page.inner_text("body", timeout=7000))[:24000]
        except Exception:
            text = ""
        elements = await self._extract_elements(page)
        state, scores, evidence = self.detect_state(url, text, elements)
        concepts = self.detect_concepts(text, elements, state)
        return PageObservation(
            url=url,
            title=title,
            state=state,
            state_scores=scores,
            state_evidence=evidence,
            text=text,
            elements=elements,
            detected_concepts=concepts,
            forbidden_action_detected=is_forbidden_text(text),
            forbidden_boundary_detected=(state in {STATE_CHECKOUT, STATE_FINAL} and has_final_purchase_text(text)),
        )

    def detect_state(self, url: str, text: str, elements: list[UIElement] | None = None):
        compat_state_only = elements is None
        elements = elements or []
        u = (url or "").lower()
        t = (text or "").lower()
        visible_hay = " ".join(e.haystack for e in elements if e.visible)[:30000]
        all_hay = (t + " " + visible_hay).lower()

        scores = {
            STATE_PRODUCT: 0.0,
            STATE_CART_CONFIRMATION: 0.0,
            STATE_CART: 0.0,
            STATE_CHECKOUT: 0.0,
            STATE_FINAL: 0.0,
            STATE_UNKNOWN: 0.05,
        }
        ev: dict[str, list[str]] = {k: [] for k in scores}

        def add(state: str, score: float, reason: str) -> None:
            scores[state] += score
            ev[state].append(reason)

        product_url = "/dp/" in u or "/gp/product" in u
        cart_url = "/cart" in u or "gp/cart" in u
        checkout_url = "checkout" in u or "/buy/" in u or "/gp/buy" in u

        if product_url:
            add(STATE_PRODUCT, 0.75, "product URL")
        if any("add-to-cart-button" in (e.selector or "") or "add to cart" in e.haystack for e in elements if e.visible):
            add(STATE_PRODUCT, 0.45, "visible add-to-cart affordance")
        if "added to cart" in t or "added to your cart" in t:
            add(STATE_CART_CONFIRMATION, 0.75, "added-to-cart confirmation text")
        if cart_url:
            add(STATE_CART, 0.80, "cart URL")
        if "shopping cart" in t:
            add(STATE_CART, 0.35, "shopping cart text")
        if "subtotal" in t and ("quantity" in all_hay or "proceed to checkout" in all_hay or "delete" in all_hay):
            add(STATE_CART, 0.45, "cart subtotal + cart controls")
        if any("proceedtoretailcheckout" in e.haystack or "proceed to checkout" in e.haystack for e in elements if e.visible):
            add(STATE_CART, 0.30, "visible proceed-to-checkout button")
        if checkout_url:
            add(STATE_CHECKOUT, 0.80, "checkout URL")
        if "secure checkout" in t:
            add(STATE_CHECKOUT, 0.70, "secure checkout text")
        if any(s in t for s in ["select a shipping address", "payment method", "deliver to this address", "order review"]):
            add(STATE_CHECKOUT, 0.40, "checkout form/order text")

        checkout_precondition = scores[STATE_CHECKOUT] >= 0.65 or checkout_url
        if checkout_precondition and has_final_purchase_text(t):
            add(STATE_FINAL, 0.95, "checkout + final purchase text")
        # Negative evidence: product/cart contexts suppress final boundary.
        if product_url:
            scores[STATE_FINAL] -= 0.80
            ev[STATE_FINAL].append("suppressed by product URL")
        if cart_url:
            scores[STATE_FINAL] -= 0.60
            ev[STATE_FINAL].append("suppressed by cart URL")
        # Product/cart URL are stronger than generic checkout words in hidden text.
        if product_url:
            scores[STATE_CHECKOUT] -= 0.20
            ev[STATE_CHECKOUT].append("suppressed by product URL")
        if cart_url:
            scores[STATE_CHECKOUT] -= 0.20
            ev[STATE_CHECKOUT].append("suppressed by cart URL")

        best_state = max(scores, key=lambda s: scores[s])
        if scores[best_state] < 0.20:
            best_state = STATE_UNKNOWN
        if compat_state_only:
            return best_state
        return best_state, {k: round(v, 3) for k, v in scores.items()}, ev

    def detect_concepts(self, text: str, elements: list[UIElement], state: str) -> set[str]:
        low = (text or "").lower()
        visible_hay = " ".join(e.haystack for e in elements if e.visible)
        all_hay = low + " " + visible_hay
        concepts = set()
        if state == STATE_PRODUCT or "add-to-cart-button" in visible_hay or "add to cart" in visible_hay:
            if "add to cart" in all_hay or "add-to-cart" in all_hay:
                concepts.add("action.add_to_cart")
        if "nav-cart" in all_hay or (state in {STATE_CART, STATE_CART_CONFIRMATION} and "shopping cart" in low):
            concepts.add("action.go_to_cart")
        if "proceed to checkout" in all_hay or "proceedtoretailcheckout" in all_hay:
            concepts.add("action.proceed_to_checkout")
        if state in {STATE_CART, STATE_CART_CONFIRMATION} and ("shopping cart" in low or "subtotal" in low):
            concepts.add("domain.cart_item")
        if state in {STATE_CART, STATE_CART_CONFIRMATION} and ("subtotal" in low or "order summary" in low):
            concepts.add("domain.subtotal")
        if state in {STATE_CART, STATE_CART_CONFIRMATION} and ("quantity" in all_hay or "qty" in all_hay or "a-dropdown-prompt" in all_hay):
            concepts.add("domain.quantity_control")
        if state == STATE_CART and ("delete" in all_hay or "remove" in all_hay):
            concepts.add("action.delete_item")
        if state == STATE_CART and "save for later" in all_hay:
            concepts.add("action.save_for_later")
        if state in {STATE_PRODUCT, STATE_CART} and ("in stock" in low or "out of stock" in low or "currently unavailable" in low):
            concepts.add("domain.inventory_state")
        if state in {STATE_CHECKOUT, STATE_FINAL}:
            concepts.add("domain.checkout_boundary")
        if state in {STATE_CHECKOUT, STATE_FINAL} and has_final_purchase_text(low):
            concepts.add("domain.final_order_boundary")
        return concepts



    def from_browser_use_state(self, browser_state: Any) -> PageObservation:
        """Convert browser-use BrowserStateSummary into our PageObservation.

        browser-use already fuses DOM, accessibility labels, element indices,
        and screenshot/page context. We keep that rich observation as the crawler
        artifact, then normalize it into typed graph concepts.
        """
        url = getattr(browser_state, "url", "") or ""
        title = getattr(browser_state, "title", "") or ""
        dom = ""
        try:
            dom_state = getattr(browser_state, "dom_state", None)
            if dom_state is not None:
                dom = dom_state.llm_representation() or ""
        except Exception:
            dom = ""
        text = dom[:24000]
        elements = self._extract_elements_from_browser_use_state(browser_state, dom)
        state, scores, evidence = self.detect_state(url, text, elements)
        concepts = self.detect_concepts(text, elements, state)
        return PageObservation(
            url=url,
            title=title,
            state=state,
            state_scores=scores,
            state_evidence=evidence,
            text=text,
            elements=elements,
            detected_concepts=concepts,
            forbidden_action_detected=is_forbidden_text(text),
            forbidden_boundary_detected=(state in {STATE_CHECKOUT, STATE_FINAL} and has_final_purchase_text(text)),
        )

    def _extract_elements_from_browser_use_state(self, browser_state: Any, dom_text: str = "") -> list[UIElement]:
        elements: list[UIElement] = []
        try:
            dom_state = getattr(browser_state, "dom_state", None)
            selector_map = getattr(dom_state, "selector_map", None) or {}
            items = selector_map.items() if hasattr(selector_map, "items") else []
            for idx, node in list(items)[:350]:
                attrs = getattr(node, "attributes", None) or {}
                tag = str(getattr(node, "tag_name", None) or getattr(node, "node_name", None) or attrs.get("tag") or "").lower() or "element"
                text = _node_text(node)
                selector, quality, reason = _selector_from_node(tag, attrs)
                role = attrs.get("role")
                aria = attrs.get("aria-label") or attrs.get("aria_label")
                name = attrs.get("name")
                el_id = attrs.get("id")
                typ = attrs.get("type")
                href = attrs.get("href")
                value = attrs.get("value")
                tabindex = attrs.get("tabindex")
                disabled = attrs.get("disabled") in {"true", "disabled", True} or attrs.get("aria-disabled") == "true"
                visible = not _looks_hidden(attrs, text)
                clickable = tag in {"button", "a", "input", "select", "summary"} or role == "button" or str(idx).isdigit()
                interactable = visible and not disabled and clickable and typ != "hidden" and tabindex != "-1"
                in_nav = any(k in " ".join(str(v) for v in attrs.values()).lower() for k in ["nav-", "navbar", "nav_"])
                elements.append(UIElement(
                    index=int(idx) if str(idx).isdigit() else len(elements),
                    tag=tag,
                    text=text[:220],
                    selector=selector,
                    role=role,
                    aria_label=aria,
                    name=name,
                    id=el_id,
                    type=typ,
                    href=href,
                    value=value,
                    visible=visible,
                    enabled=not disabled,
                    clickable=clickable,
                    interactable=interactable,
                    selector_quality=quality,
                    selector_reason=reason,
                    tabindex=tabindex,
                    in_nav_or_header=in_nav,
                ))
        except Exception:
            pass
        if elements:
            return elements
        # Fallback: create rough visible-text elements from the browser-use LLM representation.
        for i, line in enumerate((dom_text or "").splitlines()[:250]):
            l = line.strip()
            if len(l) < 2:
                continue
            low = l.lower()
            if any(k in low for k in ["add to cart", "cart", "checkout", "quantity", "delete", "remove", "save for later", "subtotal", "promo", "gift card"]):
                elements.append(UIElement(
                    index=i,
                    tag="text",
                    text=l[:220],
                    selector=None,
                    visible=True,
                    enabled=True,
                    clickable=any(k in low for k in ["add to cart", "cart", "checkout", "quantity", "delete", "remove", "save for later"]),
                    interactable=False,
                    selector_quality="none",
                    selector_reason="browser-use text fallback",
                ))
        return elements

    async def _extract_elements(self, page: Any) -> list[UIElement]:
        script = r"""
        () => {
          function cssPath(el) {
            if (!el || !el.tagName) return {selector:null, quality:'none', reason:'no element'};
            const tag = el.tagName.toLowerCase();
            if (el.id) return {selector:'#' + CSS.escape(el.id), quality:'stable', reason:'id'};
            const name = el.getAttribute('name');
            if (name) return {selector:tag + '[name="' + CSS.escape(name) + '"]', quality:'stable', reason:'name'};
            const dataAction = el.getAttribute('data-action');
            if (dataAction) return {selector:tag + '[data-action="' + CSS.escape(dataAction) + '"]', quality:'stable', reason:'data-action'};
            const aria = el.getAttribute('aria-label');
            if (aria && aria.length < 80) return {selector:tag + '[aria-label="' + CSS.escape(aria) + '"]', quality:'anchored', reason:'aria-label'};
            const value = el.getAttribute('value');
            const type = el.getAttribute('type');
            if (value && value.length < 80 && ['button','submit','radio','checkbox'].includes((type || '').toLowerCase())) {
              return {selector:tag + '[value="' + CSS.escape(value) + '"]', quality:'anchored', reason:'value'};
            }
            const href = el.getAttribute('href');
            if (tag === 'a' && href && href.includes('cart')) {
              return {selector:'a[href*="cart"]', quality:'anchored', reason:'cart href'};
            }
            return {selector:tag, quality:'generic', reason:'generic tag'};
          }
          const nodes = Array.from(document.querySelectorAll('button,a,input,select,textarea,[role="button"],[aria-label],[data-action],summary'));
          return nodes.slice(0, 350).map((el, idx) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const visible = !!(rect.width || rect.height) && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
            const disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
            const text = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 220);
            const path = cssPath(el);
            const tag = el.tagName.toLowerCase();
            const clickable = ['button','a','input','select','summary'].includes(tag) || el.getAttribute('role') === 'button';
            const interactable = visible && !disabled && clickable && !['hidden'].includes((el.getAttribute('type') || '').toLowerCase()) && el.getAttribute('tabindex') !== '-1';
            const form = el.closest('form');
            const nav = el.closest('nav, header, #navbar, #nav-main, #nav-belt, #nav-flyout-ya-newCust');
            return {
              index: idx,
              tag,
              text,
              selector: path.selector,
              selector_quality: path.quality,
              selector_reason: path.reason,
              role: el.getAttribute('role'),
              aria_label: el.getAttribute('aria-label'),
              name: el.getAttribute('name'),
              id: el.id || null,
              type: el.getAttribute('type'),
              href: el.getAttribute('href'),
              value: el.getAttribute('value'),
              visible,
              enabled: !disabled,
              clickable,
              interactable,
              tabindex: el.getAttribute('tabindex'),
              in_nav_or_header: !!nav,
              form_id: form ? (form.id || null) : null,
              form_action: form ? (form.getAttribute('action') || null) : null,
              rect: {width: rect.width, height: rect.height, x: rect.x, y: rect.y}
            };
          });
        }
        """
        raw = await page.evaluate(script)
        return [UIElement(**r) for r in raw]



def _node_text(node: Any) -> str:
    for attr in ("text", "text_content", "inner_text", "all_text", "element_text"):
        val = getattr(node, attr, None)
        if isinstance(val, str) and val.strip():
            return " ".join(val.strip().split())
    try:
        fn = getattr(node, "get_all_text_till_next_clickable_element", None)
        if callable(fn):
            val = fn()
            if isinstance(val, str) and val.strip():
                return " ".join(val.strip().split())
    except Exception:
        pass
    attrs = getattr(node, "attributes", None) or {}
    for key in ("aria-label", "title", "value", "alt", "name", "id"):
        if attrs.get(key):
            return str(attrs[key])
    return ""


def _selector_from_node(tag: str, attrs: dict) -> tuple[str | None, str, str]:
    if attrs.get("id"):
        return f"#{attrs['id']}", "stable", "browser-use id"
    if attrs.get("name"):
        return f"{tag}[name=\"{attrs['name']}\"]", "stable", "browser-use name"
    if attrs.get("data-action"):
        return f"{tag}[data-action=\"{attrs['data-action']}\"]", "stable", "browser-use data-action"
    if attrs.get("aria-label"):
        return f"{tag}[aria-label=\"{attrs['aria-label']}\"]", "anchored", "browser-use aria-label"
    if attrs.get("value") and attrs.get("type") in {"button", "submit"}:
        return f"{tag}[value=\"{attrs['value']}\"]", "anchored", "browser-use value"
    return tag if tag else None, "generic", "browser-use generic"


def _looks_hidden(attrs: dict, text: str) -> bool:
    if attrs.get("hidden") in {"true", True, "hidden"}:
        return True
    if attrs.get("aria-hidden") == "true":
        return True
    style = str(attrs.get("style") or "").lower()
    if "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", ""):
        return True
    return False
