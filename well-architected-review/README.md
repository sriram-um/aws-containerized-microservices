# Well-Architected review — aws-containerized-microservices

AWS Well-Architected review of this repository's architecture as built (before it was
decommissioned), with the **Well-Architected Framework** lens and the **Container Build Lens**,
for the pillars **Security, Reliability (incl. disaster recovery), Performance Efficiency and
Cost Optimization**.

**Result (milestone `v1.0-baseline`, 2026-11-01):** Framework 40 questions: 17 high, 12 medium,
11 no risk. Container Build Lens 23 questions: 1 high, 6 medium, 15 no risk, 1 not applicable.
Most high risks are account-level (root access key, no MFA, no CloudTrail/GuardDuty) or
production gaps (HTTP only, no notifications, recovery objectives not defined).

## Read

| Document | What it is |
|---|---|
| [Review results](02-review-results.md) | Scope, risk counts, strengths, high risks by theme (incl. DR), improvement plan with costs, accepted risks, every question |
| [How to do a review](https://github.com/sriram-um/aws-serverless-application/blob/main/well-architected-review/01-how-to-do-a-review.md) | The process guide from Project 3; this review used the same method and scripts |

## Folder layout

| Path | Contents |
|---|---|
| [`answers/`](answers/) | Answers as code: per question the selected best practices and notes with *Evidence* and *Gap* (`wellarchitected.json`, `containerbuild.json`) plus the tool's full question lists |
| [`scripts/wa_review.py`](scripts/wa_review.py) | Creates the workload, pushes the answers, saves milestones, prints risk counts, downloads reports (adapted from Project 3: the Container Build Lens is addressed by ARN) |
| [`scripts/risk_chart.py`](scripts/risk_chart.py) | Draws [`images/baseline-risks.png`](images/baseline-risks.png) from `reports/baseline-risks.json` |
| [`scripts/build_html.py`](scripts/build_html.py) | Regenerates the HTML versions of the Markdown files |
| [`reports/`](reports/) | `baseline-risks.json` (per-question risks). The official PDF reports are written here but git-ignored: they include account findings |

## Re-run

```bash
.venv/Scripts/python well-architected-review/scripts/wa_review.py apply      # push answers/*.json
.venv/Scripts/python well-architected-review/scripts/wa_review.py status
.venv/Scripts/python well-architected-review/scripts/wa_review.py milestone v1.1-<name>
.venv/Scripts/python well-architected-review/scripts/wa_review.py report v1.1
.venv/Scripts/python well-architected-review/scripts/risk_chart.py v1.1 --pillars security,reliability,performance,costOptimization
```

The workload in the Well-Architected Tool (`aws-containerized-microservices`, us-east-1) is free
and stays as the record of the review.
