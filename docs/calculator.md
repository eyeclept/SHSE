# Calculator Answer Cards

Inline answer cards for mathematical expressions. Evaluated locally using
Python's `ast` module — `eval()` is never called directly. Results appear above
BM25 search results and are also injected into `ai_context`.

---

## Supported Operators

| Operator | Symbol | Example | Result |
|---|---|---|---|
| Addition | `+` | `2 + 2` | `4` |
| Subtraction | `-` | `10 - 3` | `7` |
| Multiplication | `*` | `5 * 8` | `40` |
| Division | `/` | `10 / 4` | `2.5` |
| Floor division | `//` | `10 // 3` | `3` |
| Exponentiation | `**` or `^` | `2 ** 10` | `1024` |
| Modulo | `%` | `17 % 5` | `2` |

---

## Supported Functions

| Function | Example | Result |
|---|---|---|
| `sqrt(n)` | `sqrt(144)` | `12` |
| `abs(n)` | `abs(-7)` | `7` |
| `round(n)` | `round(3.7)` | `4` |
| `floor(n)` | `floor(3.9)` | `3` |
| `ceil(n)` | `ceil(3.1)` | `4` |
| `factorial(n)` | `factorial(10)` | `3628800` |
| `log(n)` | `log(e)` | `1.0` |
| `log10(n)` | `log10(1000)` | `3.0` |
| `sin(n)` | `sin(0)` | `0` |
| `cos(n)` | `cos(0)` | `1` |
| `tan(n)` | `tan(0)` | `0` |

---

## Detection Patterns

| Pattern | Example | Extracted expression |
|---|---|---|
| `what is <expr>` | `what is 2 + 2` | `2 + 2` |
| `calculate <expr>` | `calculate 5 * 8` | `5 * 8` |
| `compute <expr>` | `compute 10 / 2` | `10 / 2` |
| `eval <expr>` | `eval 3 ** 4` | `3 ** 4` |
| `<expr> =` | `12 / 4 =` | `12 / 4` |
| bare expression | `3 ** 10` | `3 ** 10` |
| `<n> factorial` | `10 factorial` | `factorial(10)` |
| `<n>!` | `10!` | `factorial(10)` |

A query qualifies as a calculator expression when it contains at least one
digit and at least one operator character or recognised function name.
Plain words like `"human anatomy"` are never detected as expressions.

---

## AST Whitelist

All input is parsed with `ast.parse(mode="eval")` before any numeric evaluation.
The AST walker rejects every node type not on the following whitelist:

- `Constant` (numbers only — strings and booleans are rejected)
- `BinOp` with operators: `Add Sub Mul Div Mod Pow FloorDiv`
- `UnaryOp` with operators: `USub UAdd`
- `Call` — only functions listed in the supported functions table above
- `Name` — only `pi`, `e`, `tau`, `inf`

Any other node type (attribute access, subscripts, imports, list/dict literals,
lambda, etc.) raises `ValueError` immediately, and `evaluate_expression` returns
`None`. This means `__import__('os')`, `open(...)`, and similar injections are
blocked at the parse stage — `eval()` is never reached.

---

## `ai_context` Injection

When a calculator card is shown, the result is prepended to `ai_context` as:

```
Calculator: <expression> = <result>
```

---

## Known Limitations

- No variable assignment (`x = 5; x + 3` is not supported).
- No string operations — only numeric constants are permitted.
- `factorial()` requires a non-negative integer argument; floats like `3.5!`
  are rejected by `math.factorial`.
- Very large exponents (e.g. `9999 ** 9999`) will raise `OverflowError`, which
  is treated the same as `ZeroDivisionError` — the card is suppressed and no
  result is shown.
