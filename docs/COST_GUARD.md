# Cost guard

The concierge now classifies intent before generating a paid answer. No regex
blocklists, keyword overrides, random replies, or fail-open Laya path remain in
`cost_guard.py`. The caller's `(allowed, gate, reply)` API and
`PASSED_ESSENTIAL_NEED` emergency prompt contract are preserved.

## Default: structured micro-classifier (option C)

`COST_GUARD_BACKEND=gemini` is the default. Configure `GEMINI_API_KEY` (or
`GOOGLE_API_KEY`) in the backend environment. `COST_GUARD_MODEL` defaults to
`gemini-3.5-flash-lite`, independently of the answer-generation model.

Each valid message makes one small classification request with four possible
intents: `travel`, `emergency`, `off_topic`, `unknown`. An explicit ambiguity
signal rejects uncertain classifications. This signal is **not** a calibrated
probability or an accuracy guarantee. Only clear travel and emergency decisions
reach answer generation. The policy distinguishes romantic accommodation from
sexual services, and sexual healthcare from sexual entertainment.

The request uses a strict output schema, minimal thinking, a 128-token output
cap, no tools, no retries and no model failover. Connect/read timeouts are
1.5/3.5 seconds; these are socket timeouts, not a hard wall-clock deadline.
Eight classification requests per worker may run concurrently; excess requests
receive an immediate free unavailable response. Repeated initialization failures
have a 60-second cooldown. Runtime decisions log intent/reason rather than user
text, model responses or keys. No process-wide Hugging Face settings are mutated.

Provider refusal, truncation, invalid schema, network failure, absent credentials,
or uncertainty stops paid answer generation. Unknown requests get a clarification;
unavailable classification gets a retry message. Both include direct emergency
service guidance, because classification failure can also affect urgent users.
Classification itself is a paid call: savings depend on the rejected fraction,
prompt token count, provider pricing, and the cost of avoided answer calls.

Current implementation follows Google's [structured output REST format](https://ai.google.dev/gemini-api/docs/generate-content/structured-output),
[Flash-Lite API changes](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6),
and [thinking level configuration](https://ai.google.dev/gemini-api/docs/generate-content/thinking).
Model substitution needs compatibility and language-matrix validation.

## Verification

```sh
python -m unittest discover -s backend -p test_cost_guard_contract.py -v
python backend/test_cost_guard_matrix.py --backend gemini --report /tmp/guard-gemini.json
```

The matrix checks the public entry point with actual model inference and never
mocks intent predictions. The separate contract suite mocks HTTP/persistence to
verify rejection boundaries, provider failures, concurrency and actual concierge
prompt selection. It does **not** establish multilingual accuracy.

The matrix exits `0` only when all expectations pass, `1` for routing failures,
and `2` when the classifier cannot initialize. An unavailable classifier cannot
inflate the off-topic pass count. For off-topic inputs, explicit deflection or
low-confidence clarification is acceptable; clarification is reported separately.
For genuine travel and emergencies, clarification is a **failure**. Unknown
queries must remain unknown. Anchors, calibration examples and test utterances
are disjoint; test cases are never used by the calibration script.

Measured in this workspace (2026-10-24):

| Check | Result |
| --- | --- |
| Original four-case regression before refactor | 2/4; romance became emergency or failed open |
| Policy, transport and concierge integration | 22/22 pass |
| Real optional CPU matrix | **49/67 pass, 18 fail** |
| CPU cold initialization, cached weights | 2.07 s |
| CPU warm p50 / p95, single-query inference | 6.44 / 8.57 ms |
| Live Gemini matrix | **Unavailable: no API key; 0/67 evaluated** |

These are development measurements, not production SLOs. The default remote
classifier's accuracy and latency remain unverified until the live matrix runs
with credentials. Do not interpret passing mocked transport tests as approval to
deploy an unmeasured language classifier.

## CPU evaluation (option A)

The optional FastEmbed multilingual MiniLM ONNX router has an exact cosine index
over a finite labelled utterance corpus, including negative/chitchat anchors.
Each class score averages its two strongest anchors. The winning class must
exceed both its absolute similarity cutoff and its margin over the runner-up.
Failing either returns unknown; it never tries the second-best route.
Threshold enforcement is independent of semantic-router index defaults.

Boundaries are fitted on 50 separate calibration examples with zero false class
acceptances on that calibration set, maximizing accepted positives. This is a
small development calibration, not a statistical reliability guarantee. Model
weights, tokenizer, corpus, scoring rule and FastEmbed version are bound to the
policy; changes invalidate it. Serving requires cached weights and rejects token
overflow instead of classifying a silently truncated query.

```sh
pip install -r backend/requirements-cost-guard-local.txt
export COST_GUARD_MODEL_CACHE=/path/to/model-cache
python backend/cost_guard.py --download
python backend/calibrate_cost_guard.py
python backend/test_cost_guard_matrix.py --backend semantic --report /tmp/guard-local.json
```

`COST_GUARD_BACKEND=semantic` is available for explicit evaluation. It is **not**
an automatic fallback when Gemini fails. The held-out CPU matrix is deliberately
red: this encoder still maps one euphemism to emergency, despite both cutoffs.
Increasing anchor lists or adjusting thresholds to this test would hide the
model limitation rather than establish generalization.

| CPU category | Pass | Fail | Clarified |
| --- | ---: | ---: | ---: |
| Hinglish travel | 1 | 2 | 2 |
| Bhojpuri travel | 1 | 2 | 2 |
| Maithili travel | 1 | 2 | 2 |
| Transit | 4 | 1 | 1 |
| Other travel | 2 | 5 | 5 |
| Routine essentials | 1 | 1 | 1 |
| Emergencies | 8 | 2 | 2 |
| Bhojpuri / Maithili emergencies | 0 | 2 | 2 |
| Romance | 4 | 0 | 2 |
| Adult | 4 | 1 | 2 |
| Bhojpuri / Maithili deflections | 3 | 0 | 2 |
| Chitchat | 4 | 0 | 1 |
| Coding / homework / finance | 5 | 0 | 1 |
| Privacy / couple accommodation | 6 | 0 | 0 |
| Unknown | 3 | 0 | 3 |
| Instruction injection | 2 | 0 | 1 |

The 18 failures comprise 17 rejected legitimate requests and one adult euphemism
incorrectly routed to emergency: “Koi maal pata de, tan ki garmi mitani hai”.
The latter scores emergency 0.790 versus off-topic 0.608. This demonstrates why
an encoder's strong cosine score is not reliable intent confidence. Every failed
utterance is retained in `test_cost_guard_matrix.py` and the JSON report.

## Concrete next choices

1. **C: validate the default Flash-Lite classifier.** Run the live matrix with
   the existing production key; collect p50/p95, unknown rate, false paid accepts
   and emergency recall on a larger native-speaker-labelled holdout. This adds a
   network round trip and one small paid call per message. Its language quality
   is a hypothesis pending that evaluation, not a measured improvement here.
2. **B: distil a supervised intent classifier to ONNX.** Train a multilingual
   encoder plus classification head on labelled travel, safety and dialectal
   counterexamples. Use speaker-disjoint validation and temperature calibration,
   with an unknown threshold. This avoids per-query API charges but requires
   training data, a reproducible model artifact and ongoing drift evaluation.
3. **A: retain embeddings only for high-precision traffic after a larger audit.**
   Evaluate a stronger multilingual encoder with held-out hard negatives, then
   route uncertain inputs to the micro-classifier. Validate accepted local
   emergency decisions too: escalating only unknown inputs would preserve the
   observed confidently wrong emergency classification. Current MiniLM results
   do not justify enabling that hybrid.
