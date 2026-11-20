# Regional Sales Playbook

Use this when a request asks for a regional sales summary, a rollup across
stores, or a "board readiness" check before a leadership review.

## Structure a regional summary

1. Pull orders for the requested region and date range with
   `get_regional_sales`.
2. Group by `product_category` and report both units and revenue — a
   category with high units but low revenue is a discounting signal worth
   calling out on its own.
3. Compare the requested period to the prior period of the same length if
   the user has not already given you a comparison window. State the
   percentage change; do not just list two numbers and leave the comparison
   to the reader. Compute the percentage change with the code tool, not
   inline arithmetic — a reported figure needs a calculation a reader can
   check independently of the prose around it.
4. If a store or category is missing from the results entirely, say so
   rather than assuming it had zero activity — a missing row and a zero-sales
   row are different things and the tools do not distinguish them for you.

## Board readiness check

Use the code tool for a chart when one is asked for, styled to match the
rest of the report — no fixed template, just consistent fonts and a clear
legend.

## Common mistakes

- Reporting revenue in the store's local currency instead of USD. All
  `sales.revenue` values are already USD.
- Treating `country` as the grouping key when the user asked for a regional
  view — group by `region`, drill into `country` only if asked.
