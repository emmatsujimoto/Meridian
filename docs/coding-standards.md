# Coding standards for review

These rules apply to new and changed code in `src/meridian`, `tests/meridian` and
`scripts`. They adapt the team's general coding best-practices guide to this Python
repository. Vendored code under `src/stockpyl` keeps its upstream style.

## Readability and structure

1. A function performs one task. Split functions that validate, compute, format and
   write in one body.
2. Avoid deep nesting. More than three levels of indentation inside a function body
   should be flattened with early returns or helpers.
3. Do not repeat yourself. Logic copied between branches or functions belongs in one
   helper.
4. Do not hardcode values that belong in settings, inputs or a single named constant
   (thresholds, URLs, product lists, service targets, day counts).
5. Keep lines at or below 100 characters (enforced by Ruff).

## Names

6. Use `snake_case` for functions, variables and modules, `PascalCase` for classes and
   `UPPER_SNAKE_CASE` for module constants.
7. Names describe purpose and units where relevant, for example `holding_cost_per_kg_day`.
8. One identifier, one purpose. Do not reassign a variable to hold a different kind of
   value later in the same scope.

## Comments and documentation

9. Public functions have a docstring stating purpose, units and important assumptions.
10. Comments and docstrings must agree with the code. An inaccurate comment is a defect.
11. Remove debugging comments and dead or unreachable code before review.

## Error handling and robustness

12. Raise `InputError` for invalid user input with an actionable message.
13. Never silence exceptions with a bare `except` or `except Exception: pass`.
14. Calls to external systems (network, subprocesses, files outside the result folder)
    use explicit timeouts, check results and report failures.
15. Guard edge cases: empty collections, zero denominators, missing optional values.

## Security and dependencies

16. Never commit credentials, keys, tokens or connection strings. Read them from the
    environment or a secret store.
17. Authentication must fail closed and compare secrets in constant time.
18. Do not deserialize untrusted data into arbitrary objects.
19. Pin dependencies to maintained versions without known vulnerabilities.

## Efficiency

20. Avoid repeated identical computation inside loops; compute once and reuse.
21. Preserve the kg, kg/day and USD unit conventions or add explicit, tested conversions.
