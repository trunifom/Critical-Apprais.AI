# templates/

Starter data for Critical Apprais.AI. Nothing here is executed; files are read by the application (or copied into a
new project folder by `crapai init`).

| File | Purpose | Status |
|---|---|---|
| `project.example.yaml` | Complete example of `project.yaml` (plan chapter 16) | Spec, not yet validated by code |
| `models.yaml` | Model catalog (providers, models, capabilities) | Values are EXAMPLES, `context_tokens` unknown |
| `pricing.example.csv` | Price table in the format of `crapai.cost.estimator.CSVPriceSource` (+ two info columns) | Prices ILLUSTRATIVE |
| `prompts/*.yaml` | The five prompt variants of SARA-App (text unchanged, YAML container) | Legacy output format `XXX/YYY` |

The structured JSON-schema output (recommended default) is specified in `docs/PROJEKTPLAN.md` chapter 10
and has to be implemented by task `T-M3-05`/`T-M3-06`.
