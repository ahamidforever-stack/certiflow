# Prompt versioning guide

(Agents arrive in Phase 2; this fixes the convention now.)

* One folder per agent: `certiflow/agents/<agent>/prompts/system.v<N>.md`. Files are immutable once used in a
  released job. A change creates `v<N+1>`.
* Prompts are templates with placeholders only: `{source_language}`, `{target_language}`, `{style_guide}`,
  `{glossary}`, `{pair_conventions}`, `{transliteration_standard}`. No language is ever written into a prompt file.
* The active version per agent (and per pair override) is a setting: `agents.<agent>.prompt_version`, `agents.<agent>.model`.
  Model names live only in settings, never in code.
* Every agent call writes `agent, prompt_version, model, tokens_in, tokens_out, cached_tokens, cost, latency, retries`
  to the audit table, and the same IDs go to Langfuse.
* Stable prefix first (rules → profile style guide → glossary), variable content last, so prompt caching hits.
* A new version must pass the golden regression set for every pair that has one before it becomes active.
