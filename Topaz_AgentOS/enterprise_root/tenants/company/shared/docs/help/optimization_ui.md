# FinOps And Optimization Help

FinOps tracks LLM usage and cost. ESAA optimization analyzes operational telemetry and recommends process improvements.

## Ask Twin Context

On FinOps, Ask Twin receives:

- active period
- tenant filter
- cost summary
- top models, skills, users
- optimization opportunities

On ESAA Optimization, Ask Twin receives:

- selected category
- current tier
- visible recommendation counts
- selected recommendation from the Discuss link
- recommendation severity, impact, and rule id

## FinOps

Filter the dashboard from the **Filters** panel: date-range presets (Today, 7d,
30d, 90d), a custom from/to range, and a tenant dropdown populated from tenants
that have cost data (plus your default tenant). Choose **All tenants** to see
everything you are entitled to. Active filters appear as chips above the
summary. **Export CSV** downloads the current view. **Live** reloads the page
every 60 seconds. The refresh icon reloads and clears the tenant filter.

The summary shows total cost, prompt tokens, completion tokens, requests,
average cost per request, and the period length. Each metric links to the
matching breakdown.

Use FinOps to understand:

- total cost
- average cost per request
- daily cost trend
- cost by purpose
- cost by model
- cost by skill
- cost by user
- optimization opportunities

## ESAA Optimization

Use `/twin/optimization` to review recommendations. The **Discuss** link opens Ask Twin in-place with that recommendation as context, so the answer can explain what the recommendation means and how to act on it.
