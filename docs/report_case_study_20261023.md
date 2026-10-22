# Report case study evidence 23 October 2026

This is a curated summary of a fresh isolated software run, not a human quality review.

A fresh isolated API run on 23 October 2026 used simulated operating date 1 October 2026, seed 41, four ordinary vaccine orders, one urgent insertion and three available vehicles. The case was R20261023-001308-994369-2b56602c, linked to order SIM-20261001-e813eb7885-O001 in operation PLAN-DEMO-DAY1. All quantities and observations are simulated. The event was entered as a scalar summary, so this example does not claim a new sensor-series/M2 evaluation [19].

The vaccine_2_8 event occurred at W-WESTGATE for delivery to H-NTFGH: 20 C for 90 min, MKT 19 C and intact packaging. The configured duration allowance is 30 min and MKT ceiling 10 C. Rule 3 fires first because 90 >= 2 times 30 and 19 >= 10 + 3, yielding scrap. An explicit review request keeps the effective decision pending and replacement preview returns HTTP 422. The script then submits an explicitly labelled AUTOMATED-DEMO-NOT-A-HUMAN review transaction retaining scrap, exercising the review API without claiming that a real quality reviewer approved medicine [19].

![Figure 2. One isolated case from observation through review gating, replacement delivery and closure. The review transaction is automated test input, not a human assessment; graph verification is outside this run.|6.7](figures/final-case-flow.png)

After that transaction, four feasible replacement candidates were returned. V01/V02/V03 abbreviate the corresponding vehicle suffixes. ETA is minutes after midnight on the simulated day; distance is the candidate schedule distance returned by the API, not extra distance saved against a common baseline [19].

| Candidate | Vehicle | Schedule km | ETA min | Other orders affected |
|---|---|---:|---:|---:|
| Spare vehicle, selected | V02 | 23.22 | 556.14 | 0 |
| Spare vehicle | V03 | 23.22 | 556.14 | 0 |
| Insert into in-transit route | V01 | 37.13 | 556.14 | 4 |
| Return to depot | V01 | 37.13 | 571.14 | 4 |

All four had zero predicted lateness. The two spare vehicles tie on the displayed metrics; choosing V02 demonstrates an accepted feasible option, not a claim that it is uniquely optimal. The accepted replacement RO-R20261023-001308-994369-2b56602c was subsequently recorded as delivered while the original order remained scrapped. The case progressed to handled and then closed; retrying registration retained the same case identity, and closing before replacement delivery was rejected [19].

The day-one snapshot contains six orders: five delivered (three unaffected ordinary orders, one urgent order and one replacement) and one scrapped original. No vehicle remained on its return trip. Parking was completed before day two inherited the actual vehicle locations; temporary urgent/replacement jobs were not copied into the next fixed daily batch. The example passed 27 assertions. The stored reference IDs remain visible in the case record, but graph writing was explicitly disabled and graph coverage was not verified. These API/state checks are not browser acceptance, M6 answer-quality scores or a real operational-benefit trial [19].

## Reproduce

Run `python scripts/run_report_case_study.py --output /absolute/new-directory` with the runtime/evaluation dependencies installed. The output must not already exist. The script creates temporary case storage, never writes or queries Neo4j and labels its review actor AUTOMATED-DEMO-NOT-A-HUMAN. The generated databases and full report.json are not committed.

Recorded report.json SHA-256: 41f3691e4f6a8950d82fe175c7a144403fd5f4bda52c6ba6282e5b0ef3514558

Recorded environment: {"python": "3.12.14", "platform": "macOS-26.5.2-arm64-arm-64bit", "packages": {"fastapi": "0.159.1", "httpx": "0.28.1", "ortools": "9.15.6755", "numpy": "2.5.4", "scikit-learn": "1.9.1"}}.

The report bundle includes the generated JSON as supplementary evidence. It is distinct from historical M3/M4/M5/M6 model evaluations. The existing run_demo_acceptance.py separately passed 33 checks with graph_mode=not_verified in the same task-local environment.
