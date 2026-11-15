"""Intent classification.

Deterministic regex rules run first and always produce an answer, so the
application works with no AI provider installed. A language model is consulted
only when the rules are unsure, and its answer is validated against the intent
registry before it is trusted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.ai.routing.model_router import ModelRouter
from app.ai.schemas.intent_schema import (
    INTENT_DEFINITIONS,
    ClassifiedBy,
    Intent,
    IntentResult,
)
from app.ai.validators.security import sanitise_command
from app.core.logging_config import get_logger

logger = get_logger("ai.intent")


@dataclass(frozen=True)
class IntentRule:
    intent: Intent
    patterns: tuple[str, ...]
    weight: float = 1.0


#: Rules are scored, not first-match-wins, so several weak signals can add up
#: while a specific phrase (e.g. "sales report") outranks a generic one ("sales").
RULES: tuple[IntentRule, ...] = (
    # --- Phase 5: multi-agent collaborations (highest specificity) ---
    IntentRule(
        Intent.KNOWLEDGE_SEARCH,
        (
            r"\b(find|search|look for|show)\b.{0,40}\b(documents?|agreements?|contracts?|polic(?:y|ies)|files?)\b",
            r"\bwhich documents? (mention|contain|say)\b",
            r"\bdocuments? (mentioning|containing|about)\b",
            r"\bsearch (my |the )?(documents?|knowledge base|files?)\b",
        ),
        4.9,
    ),
    IntentRule(
        Intent.DOCUMENT_QUESTION,
        (
            r"\baccording to (the |our |my )?(agreement|contract|policy|document)\b",
            r"\bwhat (does|do) (the |our |my )?(agreement|contract|policy|document)\b",
            r"\bpayment terms\b",
            r"\b(agreement|contract|policy) (says?|states?|stipulates?)\b",
            r"\bpenalty clauses?\b",
        ),
        4.7,
    ),
    IntentRule(
        Intent.ANALYTICS_SIMULATION,
        (
            r"\bsimulat(e|ion)\b",
            r"\bwhat (would|if) happen\b",
            r"\bwhat happens if\b",
            r"\b(if|when) my (monthly )?sales (decrease|drop|fall)\b",
        ),
        4.8,
    ),
    IntentRule(
        Intent.ANALYTICS_FORECAST,
        (
            r"\bforecast\b",
            r"\bpredict\b.{0,30}\b(sales|revenue|expenses?|cash|demand)\b",
            r"\bnext month'?s? (sales|revenue|cash)\b",
            r"\bhow much cash (might|will|could) (be available|i have)\b",
        ),
        4.7,
    ),
    IntentRule(
        Intent.ANALYTICS_ANOMALIES,
        (
            r"\bunusual (expenses?|transactions?|spending)\b",
            r"\b(identify|find|detect|show)\b.{0,25}\banomal(y|ies)\b",
            r"\banomal(y|ies)\b",
            r"\bduplicate (expenses?|payments?|transactions?)\b",
        ),
        4.6,
    ),
    IntentRule(
        Intent.ANALYTICS_RISK,
        (
            r"\b(biggest|main|top|key) (business )?risks?\b",
            r"\brisk (assessment|analysis|report)\b",
            r"\bat risk of (becoming )?inactive\b",
            r"\bcustomers? (are|at) risk\b",
        ),
        4.5,
    ),
    IntentRule(
        Intent.ANALYTICS_PERFORMANCE,
        (
            r"\bhow did (my|the) business perform\b",
            r"\bbusiness (performance|health)\b.{0,20}\b(this|last|current) (month|quarter|week|year)\b",
            r"\bcompare (this|current) (month|quarter|week|year) with (last|previous)\b",
            r"\b(show|give) me (my |the )?(kpis?|key performance indicators?)\b",
            r"\bwhich products? (are )?(losing|declining) (demand|sales)\b",
            r"\bwhich products? may face stock shortages?\b",
            r"\bmanagement report\b",
        ),
        4.4,
    ),
    IntentRule(
        Intent.COLLAB_DECLINING_SALES,
        (
            r"\bwhy\b.{0,25}\bsales\b.{0,25}\b(decreas|declin|drop|fall|down)\b",
            r"\bsales (are|is|have)\b.{0,15}\b(decreasing|declining|dropping|falling|down)\b",
            r"\bwhy are my sales\b",
        ),
        4.6,
    ),
    IntentRule(
        Intent.COLLAB_SALES_GROWTH,
        (
            r"\b(increase|grow|boost|double|raise)\b.{0,25}\bmy sales\b",
            r"\bsales growth\b",
            r"\bgrow (my )?(sales|revenue)\b",
        ),
        4.5,
    ),
    IntentRule(
        Intent.COLLAB_REORDER_CASHFLOW,
        (
            r"\breorder\b.{0,40}\bcash\b",
            r"\bwithout affecting my cash\b",
            r"\brestock\b.{0,30}\bcash\b",
        ),
        4.5,
    ),
    IntentRule(
        Intent.COLLAB_SUPPLIER_CASHFLOW,
        (
            r"\b(purchase|buy|order)\b.{0,30}\bfrom my suppliers?\b",
            r"\bsuppliers?\b.{0,25}\bthis week\b",
            r"\bpurchase inventory from\b",
        ),
        4.5,
    ),
    IntentRule(
        Intent.COLLAB_BUSINESS_HEALTH,
        (
            r"\b(complete|full|whole|overall)\b.{0,20}\bbusiness performance\b",
            r"\banaly[sz]e my (complete |whole |entire )?business\b",
            r"\bbusiness performance\b",
            r"\bcomplete business (analysis|review)\b",
        ),
        4.4,
    ),
    # --- Phase 4: agent-routed analysis intents (most specific first) ---
    IntentRule(
        Intent.BUSINESS_HEALTH_REPORT,
        (
            r"\b(complete|full|overall|whole)\b.{0,25}\bhealth\b",
            r"\bbusiness health\b",
            r"\bhealth (report|check|summary)\b",
            r"\bhow healthy\b",
        ),
        3.5,
    ),
    IntentRule(
        Intent.BUSINESS_RISK_ANALYSIS,
        (
            r"\b(business )?risks?\b",
            r"\bidentify\b.{0,20}\b(risk|problem|issue)",
            r"\bwhat should i worry\b",
            r"\bpotential (problems?|issues?)\b",
        ),
        3.4,
    ),
    IntentRule(
        Intent.COMPARE_SALES_INVENTORY,
        (
            r"\bcompare\b.{0,30}\b(sales|demand|revenue)\b.{0,25}\b(inventory|stock)\b",
            r"\b(sales|demand)\b.{0,15}\b(vs\.?|versus|and|against)\b.{0,15}\b(inventory|stock)\b",
            r"\bstock\b.{0,15}\b(vs\.?|versus)\b.{0,15}\bsales\b",
        ),
        3.4,
    ),
    IntentRule(
        Intent.ANALYZE_EXPENSE_ANOMALIES,
        (
            r"\b(unusual|strange|abnormal|suspicious|unexpected|anomal\w*)\b.{0,25}\bexpense",
            r"\bexpense\w*\b.{0,20}\b(anomal\w*|unusual|strange|outlier|odd)\b",
            r"\bodd (spending|expense)",
        ),
        3.2,
    ),
    IntentRule(
        Intent.FINANCIAL_ANALYSIS,
        (
            r"\b(analy[sz]e|review|assess|check)\b.{0,25}\bfinanc\w*",
            r"\bfinancial (analysis|health|performance|review)\b",
            r"\bmonthly finances?\b",
            r"\bmy finances\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.GENERATE_FINANCIAL_REPORT,
        (
            r"(generate|prepare|create|make|build)\b.{0,30}\b(financial|finance|profit and loss|p&l|monthly financial)\b.{0,20}\breport\b",
            r"\bfinancial report\b",
            r"\bp&l\b",
        ),
        3.5,
    ),
    IntentRule(
        Intent.GENERATE_SALES_REPORT,
        (
            r"(generate|prepare|create|make|build)\b.{0,30}\bsales?\b.{0,20}\breport\b",
            r"\bsales report\b",
        ),
        3.5,
    ),
    IntentRule(
        Intent.GENERATE_INVENTORY_REPORT,
        (
            r"(generate|prepare|create|make|build)\b.{0,30}\b(inventory|stock)\b.{0,20}\breport\b",
            r"\b(inventory|stock) report\b",
        ),
        3.5,
    ),
    IntentRule(
        Intent.GET_INACTIVE_CUSTOMERS,
        (
            r"\binactive\b",
            r"\bdormant\b",
            r"\blapsed\b",
            r"(haven'?t|have not|has not|not)\b.{0,20}\bpurchas",
            r"not bought",
            r"stopped buying",
            r"no recent (purchase|order)",
            r"customers? (who|that) (haven'?t|have not|didn'?t)",
        ),
        3.2,
    ),
    IntentRule(
        Intent.CREATE_PURCHASE_RECOMMENDATION,
        (
            r"(purchase|buy|reorder|order)\b.{0,40}\b(recommend|suggest|should i|can i|how many|enough)",
            r"\bpurchase recommendation\b",
            r"\bshould i (buy|purchase|order)\b",
            r"\bcan i (buy|purchase|order)\b",
            r"\bhow many\b.{0,30}\b(should i|to) (buy|order|purchase)",
            r"\b(can|should|could|do) i\b.{0,40}\b(buy|purchase|order|reorder|afford)\b",
            r"\bwhether i (can|could|should)\b.{0,40}\b(buy|purchase|order)\b",
            r"\bafford\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.GET_TOP_PRODUCTS,
        (
            r"\b(top|best|most)\b.{0,20}\b(selling|sold|products?|items?)\b",
            r"\bbest ?sellers?\b",
            r"\bwhich products?\b.{0,20}\b(sell|selling|sold)\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.LOW_STOCK_ANALYSIS,
        (
            r"\blow[\s-]?stock\b",
            r"\bout of stock\b",
            r"\brunning (out|low)\b",
            r"\breorder\b",
            r"\bbelow minimum\b",
            r"\bstock ?out\b",
            r"\bneed(s)? restock",
        ),
        3.8,
    ),
    IntentRule(
        Intent.GET_CASH_FLOW,
        (
            r"\bcash\s*flow\b",
            r"\bcash position\b",
            r"\bliquidity\b",
            r"\bcash on hand\b",
            r"\bcash balance\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.CREATE_EXPENSE,
        (
            r"(record|add|create|log|enter|book)\b.{0,25}\bexpense\b",
            r"\bexpense of\b",
            r"\bspent\b.{0,20}\b(on|for)\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.CREATE_SALES_ORDER,
        (
            r"(create|new|make|add|place|book)\b.{0,25}\b(sale|sales order|order for)\b",
            r"\bsell\b",
            r"\binvoice for\b",
        ),
        3.0,
    ),
    IntentRule(
        Intent.CALCULATE_PROFIT,
        (r"\bprofit\b", r"\bmargin\b", r"\bearnings\b", r"\bprofitab"),
        2.6,
    ),
    IntentRule(
        Intent.GET_REVENUE,
        (r"\brevenue\b", r"\bturnover\b", r"\bincome\b", r"\bsales value\b", r"\btakings\b"),
        2.5,
    ),
    IntentRule(
        Intent.GET_EXPENSES,
        (r"\bexpenses?\b", r"\bspending\b", r"\bcosts?\b", r"\boverheads?\b", r"\bbills?\b"),
        2.5,
    ),
    IntentRule(
        Intent.GET_SUPPLIER_DETAILS,
        (
            r"\bsuppliers?\b",
            r"\bvendors?\b",
            r"\bpurchase order status\b",
        ),
        2.2,
    ),
    IntentRule(
        Intent.GENERAL_BUSINESS_ANALYSIS,
        (
            r"how('?s| is)\b.{0,15}\bbusiness\b",
            r"\bbusiness (overview|summary|health|doing|performance)\b",
            r"\boverall (performance|summary)\b",
            r"\bsummar(y|ise|ize)\b.{0,20}\bbusiness\b",
            r"\bhow am i doing\b",
        ),
        2.0,
    ),
    IntentRule(
        Intent.CHECK_STOCK,
        (
            r"(check|show|what'?s|what is|how much)\b.{0,25}\bstock\b",
            r"\bstock (level|of|for|on hand)\b",
            r"\binventory (level|of|for)\b",
            r"\bhow many\b.{0,25}\b(in stock|left)\b",
            r"\bdo i have\b.{0,25}\bin stock\b",
        ),
        2.0,
    ),
    IntentRule(
        Intent.ANALYZE_SALES,
        (r"\bsales\b", r"\borders?\b", r"\bselling\b"),
        1.5,
    ),
    IntentRule(
        Intent.CUSTOMER_ANALYSIS,
        (r"\bcustomers?\b", r"\bclients?\b", r"\bbuyers?\b"),
        1.5,
    ),
)

_PERIOD_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\blast month\b", "last_month"),
    (r"\bthis month\b|\bmonth to date\b|\bcurrent month\b", "this_month"),
    (r"\btoday\b", "today"),
    (r"\bthis week\b|\bweek to date\b", "this_week"),
    (r"\bthis year\b|\byear to date\b", "this_year"),
    (r"\blast 30 days\b|\bpast month\b|\blast four weeks\b", "last_30_days"),
)

_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brent\b", "RENT"),
    (r"\bsalar(y|ies)\b|\bwages?\b", "SALARY"),
    (r"\belectricity\b|\butilit(y|ies)\b|\bwater bill\b", "UTILITIES"),
    (r"\btransport\b|\bfreight\b|\bdelivery cost\b", "TRANSPORT"),
    (r"\bmarketing\b|\badvertis", "MARKETING"),
    (r"\bmaintenance\b|\brepair", "MAINTENANCE"),
    (r"\bstock purchase\b|\bpurchases?\b", "PURCHASE"),
)

_QUOTED_RE = re.compile(r"[\"']([^\"']{2,60})[\"']")
_PRODUCT_RE = re.compile(
    r"\b(?:product|item|sku)\s+([A-Za-z0-9][\w &\-]{1,40})", re.IGNORECASE
)
_OF_RE = re.compile(r"\bof\s+([A-Za-z0-9][\w &\-]{1,40}?)(?=\s+(?:for|to|at|on|in)\b|[.,?!]|$)", re.IGNORECASE)
_CUSTOMER_RE = re.compile(
    r"\b(?:customer|client|for|to)\s+([A-Z][\w]*(?:\s+[A-Z][\w]*){0,3})"
)
_SUPPLIER_RE = re.compile(
    r"\b(?:supplier|vendor)\s+([A-Za-z0-9][\w &\-]{1,40})", re.IGNORECASE
)
_QUANTITY_RE = re.compile(
    r"(\d{1,7})\s*(?:units?|pcs|pieces?|packs?|bottles?|boxes?|kg|litres?|liters?)",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(?:rs\.?|₹|inr)\s*(\d{1,9}(?:[.,]\d{1,2})?)"
    r"|(\d{1,9}(?:\.\d{1,2})?)\s*(?:rupees|rs|inr)"
    r"|\b(?:expense|spent|spend|paid|pay|cost)\b[^\d]{0,20}(\d{1,9}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

AMBIGUITY_MARGIN = 0.12
LLM_THRESHOLD = 0.62


class IntentClassifier:
    """Classifies a natural-language command into one registry intent."""

    def __init__(self, router: ModelRouter | None = None) -> None:
        self._router = router

    # -- public API --------------------------------------------------------
    def classify(self, command: str) -> IntentResult:
        text, flagged = sanitise_command(command)
        if not text:
            return IntentResult(
                intent=Intent.UNKNOWN_INTENT,
                confidence=0.0,
                rationale="The command was empty.",
            )

        scores = self._score(text)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_score = ranked[0] if ranked else (None, 0.0)
        runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0

        entities = self._extract_entities(text)
        rule_confidence = min(0.95, 0.55 + 0.12 * top_score) if top_score > 0 else 0.0

        result = IntentResult(
            intent=top_intent or Intent.UNKNOWN_INTENT,
            confidence=round(rule_confidence, 2),
            classified_by=ClassifiedBy.RULES,
            rationale=(
                f"Matched {top_score:.1f} rule weight for "
                f"{INTENT_DEFINITIONS[top_intent].label}."
                if top_intent
                else "No business intent pattern matched."
            ),
            entities=entities,
            alternatives=[
                (intent.value, round(min(0.95, 0.55 + 0.12 * score), 2))
                for intent, score in ranked[:3]
            ],
        )

        # Ambiguity: two intents scoring almost the same.
        if (
            top_intent is not None
            and runner_up_score >= top_score * (1 - AMBIGUITY_MARGIN)
            and runner_up_score > 0
        ):
            second = ranked[1][0]
            result.requires_clarification = True
            result.confidence = round(min(result.confidence, 0.5), 2)
            result.clarification_question = (
                f"Did you mean “{INTENT_DEFINITIONS[top_intent].label}” or "
                f"“{INTENT_DEFINITIONS[second].label}”? "
                "Please rephrase with a little more detail."
            )
            result.rationale += " Two intents scored almost equally."
            return result

        # Consult a model only when the rules are unsure and the text is clean.
        if rule_confidence < LLM_THRESHOLD and not flagged:
            assisted = self._classify_with_model(text, rule_confidence)
            if assisted is not None:
                assisted.entities = entities or assisted.entities
                return assisted

        if top_intent is None:
            result.requires_clarification = False
            result.rationale = (
                "I could not map that to a supported business operation. "
                "Try asking about revenue, expenses, profit, stock, sales, customers or reports."
            )
        return result

    # -- rules -------------------------------------------------------------
    @staticmethod
    def _score(text: str) -> dict[Intent, float]:
        lowered = text.lower()
        scores: dict[Intent, float] = {}
        for rule in RULES:
            hits = 0
            for pattern in rule.patterns:
                if re.search(pattern, lowered, re.IGNORECASE):
                    hits += 1
            if hits:
                # Additional matching patterns for the same intent add a little.
                scores[rule.intent] = rule.weight + 0.15 * (hits - 1)
        return scores

    # -- model assist ------------------------------------------------------
    def _classify_with_model(self, text: str, rule_confidence: float) -> IntentResult | None:
        if self._router is None:
            return None
        allowed = [intent.value for intent in INTENT_DEFINITIONS if intent is not Intent.UNKNOWN_INTENT]
        prompt = (
            "Classify this business command into exactly one intent.\n"
            f"Allowed intents: {', '.join(allowed)}\n"
            f"Command: \"{text}\"\n"
            'Reply with JSON: {"intent": "<INTENT>", "confidence": 0.0-1.0, "rationale": "<short>"}'
        )
        reply = self._router.classify(prompt)
        if reply is None:
            return None
        payload = _parse_json(reply.text)
        if not payload:
            logger.debug("Discarding unparseable classifier reply")
            return None

        raw_intent = str(payload.get("intent", "")).strip().upper()
        try:
            intent = Intent(raw_intent)
        except ValueError:
            logger.warning("Model returned an unregistered intent: %r", raw_intent)
            return None
        if intent is Intent.UNKNOWN_INTENT:
            return None

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        if confidence <= rule_confidence:
            return None

        return IntentResult(
            intent=intent,
            confidence=round(confidence, 2),
            classified_by=ClassifiedBy(reply.provider)
            if reply.provider in {member.value for member in ClassifiedBy}
            else ClassifiedBy.FALLBACK,
            rationale=str(payload.get("rationale", ""))[:200]
            or f"Classified by {reply.provider}.",
            alternatives=[],
        )

    # -- entities ----------------------------------------------------------
    @staticmethod
    def _extract_entities(text: str) -> dict[str, object]:
        entities: dict[str, object] = {}
        lowered = text.lower()

        for pattern, period in _PERIOD_PATTERNS:
            if re.search(pattern, lowered):
                entities["period"] = period
                break

        for pattern, category in _CATEGORY_PATTERNS:
            if re.search(pattern, lowered):
                entities["expense_category"] = category
                break

        quoted = _QUOTED_RE.search(text)
        if quoted:
            entities["product_name"] = quoted.group(1).strip()

        if "product_name" not in entities:
            match = _PRODUCT_RE.search(text) or _OF_RE.search(text)
            if match:
                candidate = match.group(1).strip(" .,-")
                if candidate and not candidate.lower().startswith(("the ", "my ", "our ")):
                    entities["product_name"] = candidate

        customer = _CUSTOMER_RE.search(text)
        if customer:
            entities["customer_name"] = customer.group(1).strip()

        supplier = _SUPPLIER_RE.search(text)
        if supplier:
            entities["supplier_name"] = supplier.group(1).strip()

        quantity = _QUANTITY_RE.search(text)
        if quantity:
            entities["quantity"] = int(quantity.group(1))

        amount = _AMOUNT_RE.search(text)
        if amount:
            raw = (amount.group(1) or amount.group(2) or amount.group(3) or "").replace(",", ".")
            try:
                entities["amount"] = str(Decimal(raw).quantize(Decimal("0.01")))
            except (InvalidOperation, ValueError):
                pass

        return entities


def _parse_json(text: str) -> dict | None:
    """Parse JSON from a model reply, tolerating code fences."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
