# Blind human review

1. Give A and B only blind-intent/ and this scoring protocol. Do not show responses,
   prediction keywords, private model outputs or each other's labels before submission.
2. Labels: why_disposition, audit_chain, product_requirements, cause_context,
   disposition_stats, unsupported. ambiguous is allowed only with semicolon-separated
   acceptable_intents. Do not force bare keywords into an unsupported interpretation.
   Label by intended task, not by matching routing keywords:
   why_disposition = a specific case's disposition reason and supporting evidence;
   audit_chain = that case's event/decision/reshipment trace;
   product_requirements = product storage limits and allowed excursion duration;
   cause_context = patterns of stages/products for a case's recorded cause;
   disposition_stats = aggregate counts/distribution of recorded dispositions;
   unsupported = outside these tasks, including weather or actual clinical potency
   certification. A missing case is still an in-scope intent; assess no_case in phase 2.
3. Seal both intent CSVs. Then give answer-review/responses.json and reference-sources.json.
4. Ratings: correctness/relevance/sufficiency 0=wrong, 1=partial, 2=adequate; refusal
   0=wrong,1=appropriate,NA=not applicable; unsupported_claims 0=none,1=present.
   Sufficiency/relevance may be NA only when evidence is not required. Record the actual
   source URLs consulted; links alone do not prove specific stability numbers.
5. Each file must have a nonempty, consistent annotator_id. Reviewers must be distinct.
   Self-declaration is not identity verification. Do not use model outputs as human gold.
6. Intent disagreements require a separate adjudication CSV with rationale, not majority
   copied from the program. Preserve packet/response hashes. Re-running creates new IDs.
7. Score only after complete annotation. Until then accuracy is unavailable, not zero or 100%.
