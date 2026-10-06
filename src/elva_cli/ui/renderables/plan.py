from __future__ import annotations

import json

from rich.text import Text

from elva_cli.core.services.plan_result import AppliedPlan, PlanResult  # noqa: TC001
from elva_cli.safe_text import printable
from elva_cli.ui.renderables.base import render


@render.register
def _(result: PlanResult) -> Text:
    plan = result.plan
    review = plan["review"]
    lines = [f"Plan {plan['planId']} · {review['kind']} · workspace {review['companyId']}"]
    for source in review["sources"]:
        lines.append(f"Source: {source['name']} ({source['collectionId']}) · {source['hash']}")
    if review.get("mcpAuth"):
        lines.append("Customer authentication: " + json.dumps(review["mcpAuth"]))
    lines.append(json.dumps(review["contract"], indent=2, ensure_ascii=False))
    lines.extend(review.get("messages", []))
    lines.extend("BLOCKED: " + b for b in review.get("blockers", []))
    lines.extend(review.get("nextActions", []))
    lines.append("Use --out FILE to save a review copy, then elva apply FILE.")
    return Text(printable("\n".join(lines)))


@render.register
def _(result: AppliedPlan) -> Text:
    return Text(printable(json.dumps(result.result, indent=2, ensure_ascii=False)))
