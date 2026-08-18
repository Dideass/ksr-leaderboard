from __future__ import annotations

import re
import unicodedata


PROVIDER_ALIASES = {
    "abacus": "abacus",
    "abacus.ai": "abacus",
    "abacusai": "abacus",
    "amazon": "amazon",
    "alibaba": "alibaba",
    "anthropic": "anthropic",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "google": "google",
    "ibm": "ibm",
    "kimi": "moonshot",
    "meta": "meta",
    "minimax": "minimax",
    "mistral": "mistral",
    "mistral ai": "mistral",
    "moonshot": "moonshot",
    "moonshot ai": "moonshot",
    "ai21": "ai21",
    "ai21 labs": "ai21",
    "zai": "zhipu",
    "zhipu ai": "zhipu",
    "openai": "openai",
    "qwen": "alibaba",
    "spacexai": "xai",
    "thinking machines": "thinking-machines",
    "thinkingmachines": "thinking-machines",
    "xai": "xai",
    "z ai": "zhipu",
    "z-ai": "zhipu",
    "zhipu": "zhipu",
}


def canonical_provider(value: str, model_name: str = "") -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if normalized in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[normalized]
    name = model_name.lower()
    patterns = (
        (r"\b(?:gpt|o1|o3|o4|chatgpt)\b|gpt-oss", "openai"),
        (r"\bclaude\b", "anthropic"),
        (r"\b(?:gemini|gemma)\b", "google"),
        (r"\bgrok\b", "xai"),
        (r"\bdeepseek\b", "deepseek"),
        (r"\b(?:qwen|qwq)", "alibaba"),
        (r"\b(?:kimi|moonshot)\b", "moonshot"),
        (r"\b(?:glm|chatglm)\b", "zhipu"),
        (r"\b(?:llama|muse)\b", "meta"),
        (r"\bmistral\b|\bministral\b|\bmixtral\b", "mistral"),
        (r"\bnova\b", "amazon"),
        (r"\bminimax\b", "minimax"),
        (r"\binkling\b", "thinking-machines"),
        (r"\bsmaug\b", "abacus"),
    )
    for pattern, provider in patterns:
        if re.search(pattern, name):
            return provider
    return normalized.replace(" ", "-") or "unmapped"


def _is_product_max_tier(name: str, slug: str = "") -> bool:
    """Qwen 'Max' is a product size, not a reasoning-effort setting."""
    blob = f"{name} {slug}".lower()
    if "effort" in blob:
        return False
    return bool(re.search(r"\bqwen[\d.]*[\s-]*max\b", blob))


def reasoning_effort(name: str, slug: str = "", explicit: str = "") -> str:
    if explicit:
        value = explicit.strip().lower().replace("extra high", "xhigh")
        value = value.replace("extra-high", "xhigh")
        if value in {"none", "default", "low", "medium", "high", "xhigh", "max"}:
            return value
    lowered = name.lower()
    parenthetical = " ".join(re.findall(r"\(([^)]*)\)", lowered))
    # A label such as "Non-reasoning, High Effort" is still the
    # non-reasoning configuration.  Detect that before generic effort words.
    if "non-reasoning" in lowered or "non-thinking" in lowered:
        return "none"
    effort_text = parenthetical
    if "effort" in lowered:
        effort_text += " " + lowered
    if re.search(r"\b(?:xhigh|extra[ -]?high)\b", effort_text):
        return "xhigh"
    if re.search(r"\bmax(?:imum)?\b", effort_text):
        return "max"
    if re.search(r"\bhigh\b", effort_text):
        return "high"
    if re.search(r"\bmedium\b", effort_text):
        return "medium"
    if re.search(r"\blow\b", effort_text):
        return "low"
    compact = re.sub(r"[^a-z0-9]+", "-", f"{lowered} {slug.lower()}").strip("-")
    for suffix, effort in (
        ("-max-effort", "max"),
        ("-xhigh-effort", "xhigh"),
        ("-extra-high-effort", "xhigh"),
        ("-high-effort", "high"),
        ("-medium-effort", "medium"),
        ("-low-effort", "low"),
        ("-thinking-max", "max"),
        ("-thinking-xhigh", "xhigh"),
        ("-thinking-high", "high"),
        ("-thinking-medium", "medium"),
        ("-thinking-low", "low"),
        ("-max", "max"),
        ("-xhigh", "xhigh"),
        ("-high", "high"),
        ("-medium", "medium"),
        ("-low", "low"),
    ):
        if suffix == "-max" and _is_product_max_tier(name, slug):
            continue
        if compact.endswith(suffix):
            return effort
    return "default"


def _slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())).strip("-")


def canonical_family_slug(
    slug: str, name: str, effort: str, release_date: str = ""
) -> str:
    base = _slugify(slug or name)
    # Endpoint dates and inference modes are configurations, not model
    # generations.  Public leaderboards use several date spellings (0424,
    # 2505, 20250805), so remove only suffixes that agree with release_date.
    date_suffixes: set[str] = set()
    date_match = re.match(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", release_date)
    if date_match:
        year, month, day = date_match.groups()
        date_suffixes.update(
            {
                f"{year}-{month}-{day}",
                f"{year}{month}{day}",
                f"{year[2:]}{month}{day}",
                f"{month}{day}",
                f"{year[2:]}{month}",
            }
        )

    configuration_suffix = re.compile(
        r"-(?:adaptive(?:-reasoning)?|fallback|"
        r"non(?:-reasoning|-thinking)?"
        r"(?:-(?:low|medium|high|xhigh|max)-effort)?|"
        r"(?:reasoning|thinking)(?:-(?:low|medium|high|xhigh|max))?|"
        r"(?:low|medium|high|xhigh|max|extra-high)-effort)$"
    )
    # Peeling in a loop handles forms such as
    # deepseek-v3-2-reasoning-0925 and model-0424-high.
    changed = True
    while changed:
        previous = base
        base = configuration_suffix.sub("", base)
        if effort not in {"default", "none"}:
            base = re.sub(rf"-{re.escape(effort)}$", "", base)
        for suffix in sorted(date_suffixes, key=len, reverse=True):
            base = re.sub(rf"-{re.escape(suffix)}(?:-v\d+)?$", "", base)
        # Some publishers encode a checkpoint date that differs by a few days
        # from the public release_date.  A trailing pure MMDD/YYMM (or longer
        # YYYYMMDD/YYMMDD) is still an endpoint tag, while sizes such as 120b
        # and product versions such as 4.20 are unaffected.
        base = re.sub(
            r"-(?:(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])|"
            r"2\d(?:0[1-9]|1[0-2])|(?:19|20)\d{6}|\d{6})(?:-v\d+)?$",
            "",
            base,
        )
        if re.search(r"\([^)]+(?:19|20)\d{2}[^)]*\)", name):
            base = re.sub(r"-\d{2}-\d{2}$", "", base)
        changed = base != previous

    lowered_name = name.lower()
    # Preview/experimental are real product variants even when a provider slug
    # omits the word; keep them separate from the final model family.
    if "preview" in lowered_name and "preview" not in base:
        base += "-preview"
    if re.search(r"\b(?:exp|experimental)\b", lowered_name) and not re.search(
        r"(?:^|-)(?:exp|experimental)(?:-|$)", base
    ):
        base += "-experimental"
    # Provider slugs encode decimal model generations with hyphens.  Converting
    # the first version pair makes AA, Scale and curated aliases converge.
    base = re.sub(r"(?<!\d)(\d+)-(\d+)(?=-|$)", r"\1.\2", base, count=1)
    return base


def public_model_identity(
    *, name: str, slug: str = "", provider: str = "", release_date: str = "", explicit_effort: str = ""
) -> dict[str, str | bool]:
    resolved_provider = canonical_provider(provider, name)
    effort = reasoning_effort(name, slug, explicit_effort)
    endpoint_slug = _slugify(slug or name)
    family_slug = canonical_family_slug(endpoint_slug, name, effort, release_date)
    return {
        "provider": resolved_provider,
        "model_id": endpoint_slug,
        "family_id": f"{resolved_provider}/{family_slug}",
        "display_name": name.strip(),
        "endpoint_date": release_date[:10],
        "reasoning_effort": effort,
        "protocol_compatible": resolved_provider != "unmapped" and bool(release_date),
        "mutable_alias": False,
    }
