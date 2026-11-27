# Prompt versioning guide

## Where prompts live

```
certiflow/agents/prompts/
  common_rules.v1.md        shared certified-translation rules, injected as {rules}
  intake/v1.md              page -> source blocks (vision + OCR draft)
  intake_zoom/v1.md         re-read of an uncertain region at higher resolution
  glossary/v1.md            batch glossary (names, acronyms, terms)
  translator/v1.md
  proofreader/v1.md
  qa/v1.md
  formatter/v1.md
config/agents.json          model, effort, max_tokens and prompt_version per agent
```

## Rules

1. **A prompt file is immutable once a released job used it.** To change it, copy `v1.md` to `v2.md`, edit `v2.md`,
   and switch `prompt_version` in `config/agents.json`. Every audit record stores the prompt version and the model, so any
   released translation can be traced to the exact prompt that produced it.
2. **No language is written into a prompt.** Use placeholders only. They are filled from the Language Profile and Pair
   Settings: `{source_language}`, `{target_language}`, `{style_guide}`, `{name_rule}`, `{transliteration_standard}`,
   `{foreign_script_rule}`, `{pair_conventions}`, `{glossary}`, `{rules}`.
3. **Model names live only in `config/agents.json`.** Never put one in code or in a prompt.
4. **Stable before variable.** The whole system prompt (rules, style guide, glossary) is the cached prefix, and the
   document content goes in the user message. Nothing variable, such as dates, job IDs or file names, may enter the
   system prompt, or caching stops working.
5. **Output contracts are code** (`certiflow/agents/contracts.py`). A prompt change that needs a new field also needs a
   contract change and a test. The model returns JSON validated against the contract, and on a validation error it is
   asked again with the error (`validation_retries`).
6. **Promotion.** A new version becomes active only after `certiflow golden score` passes on every language pair that
   has golden cases. Record the scores of both versions in the pull request.

## Trying a new version without switching everyone

Point `CERTIFLOW_SETTINGS` at a copy of `config/agents.json` with the new `prompt_version` and run
`certiflow golden score ... --out out/score_v2`.
