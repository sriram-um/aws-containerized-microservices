# Cost estimate (exercise 11)

Monthly cost of the architecture **as deployed at the end of Phase 10**: the Product Service on
ECS Fargate (+ Fargate Spot) behind an ALB in private subnets with VPC endpoints, an Aurora
PostgreSQL Global Database in **us-east-1 and us-west-2**, the CodePipeline/CodeBuild/CodeDeploy
pipeline and the monitoring. Prices are on-demand list prices **from the AWS Price List API on
2026-11-01** (marked ✓; us-east-1 and us-west-2 are identical for every item checked) or from the
public pricing pages (marked ◦). The 12-month free tier is ignored; permanent free allowances are
mentioned where they apply. A month = 730 hours.

## Unit prices used

| Item | Price | Source |
|---|---|---|
| Fargate ARM64 (Linux) | $0.03238 per vCPU-hour, $0.00356 per GB-hour | ✓ |
| Fargate Spot | variable, "up to 70 % off"; **assumed 70 %** (not in the Price List API) | ◦ |
| One task (0.25 vCPU, 0.5 GB) | on-demand $0.00988/h; Spot ≈ $0.00296/h | derived |
| Application Load Balancer | $0.0225/h + $0.008 per LCU-hour | ✓ |
| Interface VPC endpoint | $0.01 per endpoint per AZ per hour + $0.01/GB processed | ✓ |
| Aurora Serverless v2 (Aurora PostgreSQL, standard) | $0.12 per ACU-hour (I/O-Optimized: $0.16) | ✓ |
| Aurora storage / I/O | $0.10 per GB-month, $0.20 per million I/O | ✓ |
| Aurora Global Database replicated writes | $0.20 per million replicated write I/Os | ◦ |
| Inter-Region data transfer (us-east-1 → us-west-2) | $0.02/GB | ◦ |
| Secrets Manager | $0.40 per secret-month + $0.05 per 10 000 API calls | ✓ |
| CloudWatch metrics / alarms / logs | $0.30 per metric-month (first 10 000), $0.10 per alarm, $0.50/GB ingested, $0.03/GB-month stored | ✓ |
| CloudWatch dashboard | $3/month (3 dashboards per account are free) | ◦ |
| ECR storage | $0.10 per GB-month | ✓ |
| CodePipeline V2 | $0.002 per action execution minute (first 100 minutes/month free ◦) | ✓ |
| CodeBuild `arm1.small` (BUILD_GENERAL1_SMALL ARM) | $0.0034 per build minute | ◦ |
| CodeConnections, CodeDeploy (ECS), ECS control plane | no charge | ◦ |

## What runs all the time (independent of traffic)

| Service | Calculation | Monthly |
|---|---|---|
| **Aurora Serverless v2** floor | 0.5 ACU × 2 Regions × $0.12 × 730 h ✓ | **$87.60** |
| **VPC interface endpoints** | 5 (ecr.api, ecr.dkr, logs, xray, secretsmanager) × 2 AZs × $0.01 × 730 h ✓ | **$73.00** |
| **ALB** | $0.0225 × 730 h ✓ | $16.43 |
| **Fargate** (2 tasks: 1 FARGATE base + 1 FARGATE_SPOT) | ($0.00988 + $0.00296) × 730 h | $9.37 |
| **Container Insights** | ~30 metrics × $0.30 ✓ (+ performance log events, ~$0.50) | ≈ $9.50 |
| CloudWatch dashboard + 3 alarms | $3 ◦ + 3 × $0.10 ✓ | $3.30 |
| Secrets Manager | 1 secret ✓ | $0.40 |
| Aurora storage | < 1 GB × 2 Regions × $0.10 ✓ | ≈ $0.20 |
| ECR storage | ~13 images × 60 MB + collector cache ≈ 0.9 GB × $0.10 ✓ | ≈ $0.09 |
| S3 (artifact + template buckets, lifecycle 7/14 days) | cents | ≈ $0.01 |
| **Total fixed** | | **≈ $200 / month** |

## Scenario A: 10 million requests / month (~4 req/s average)

| Usage on top of the fixed cost | Calculation | Monthly |
|---|---|---|
| ALB LCU | ~4 req/s, small responses → ~0.2 LCU on average × 730 h × $0.008 ✓ | $1.17 |
| Aurora primary above the floor | reads mostly from the buffer cache; ~+0.5 ACU on average × 730 h × $0.12 ✓ | $43.80 |
| Aurora I/O + replicated writes | read-only traffic: ~1 M I/O × $0.20 ✓; almost no writes to replicate | ≈ $0.20 |
| Fargate | 2 tasks handle ~470 req/s (measured), so no scale-out | $0.00 |
| Logs | uvicorn access log ~1 GB × $0.50 ✓ | $0.50 |
| Traces (10 % sampled, 2 spans each) | ~2 M spans × ~1.5 KB ≈ 3 GB ingested into `aws/spans` × $0.50 ◦ | ≈ $1.50 |
| Endpoint data processing | image pulls + logs + traces ≈ 6 GB × $0.01 ✓ | $0.06 |
| **Total (fixed + usage)** | | **≈ $247 / month** |

## Scenario B: 100 million requests / month (~40 req/s average, peaks ~200 req/s)

| Usage | Calculation | Monthly |
|---|---|---|
| Fargate | average 3 tasks (1 on-demand + 2 Spot) → +1 Spot task × 730 h | +$2.16 |
| ALB LCU | ~1.6 LCU on average | $9.34 |
| Aurora primary | ~2 ACU average × 730 h × $0.12 (AWS recommends ≥ 8 ACU minimum for a busy global primary: that alone would be $700) | $175.20 (instead of the $43.80 floor) |
| Logs + traces | access logs 10 GB → $5; spans 30 GB → $15 (lower the sampling to 1 % → $1.50) | $20.00 |
| **Total** | fixed ≈ $200 − $43.80 (primary floor counted in the line above) + usage | **≈ $360 / month** |

## What drives the bill

| Group (scenario A) | Monthly | Share |
|---|---|---|
| Aurora Global Database (2 Regions, floor + reads) | ≈ $132 | 53 % |
| VPC interface endpoints | $73 | 30 % |
| ALB | ≈ $18 | 7 % |
| Monitoring (Container Insights, dashboard, alarms, logs, traces) | ≈ $15 | 6 % |
| **Fargate compute** | **≈ $9** | **4 %** |
| Everything else (secret, ECR, S3, pipeline) | < $2 | < 1 % |

The containers themselves are the **cheapest** part. The bill is dominated by two design choices:
**cross-Region DR for the database** (the second Region costs at least $43.80 even when idle) and
**no internet egress** (5 interface endpoints in 2 AZs). Both were deliberate requirements of this
project; both are listed below as the first things to revisit for a cost-sensitive deployment.

## How the architecture's cost changed during the project

| Phase | Running cost while switched on | What changed |
|---|---|---|
| 3 | ≈ $0.16/h | 6 endpoints, 1 t4g.small host, RDS t4g.micro |
| 4 | ≈ $0.20/h | + ALB, + 2nd host (one per AZ) |
| 5 | ≈ $0.24/h | + X-Ray endpoint, Container Insights |
| 7 | ≈ $0.15/h | Fargate: EC2 hosts and 3 ECS-agent endpoints removed |
| 8 | ≈ $0.15/h | Fargate Spot (−$0.007/h at 2 tasks) |
| 9 | ≈ $0.17/h | + Secrets Manager endpoint |
| 10 | **≈ $0.27/h** (≈ $200/month fixed) | RDS → Aurora Global Database in 2 Regions |

## Cheapest improvements (not applied)

1. **Headless secondary cluster** (storage only, no instance in us-west-2): saves **$43.80**.
   The cost: during a regional failover an instance has to be added first, which adds roughly
   10 minutes to the database RTO (the drill measured ~45 s *with* an instance).
2. **Interface endpoints in one AZ** instead of two: saves **$36.50**. Tasks in the other AZ then
   cross AZs ($0.01/GB) and lose endpoint access if that one AZ fails.
3. **One NAT gateway instead of the 5 endpoints**: $32.85 + $0.045/GB processed ◦, saves about
   **$40** at low traffic but adds internet egress (the opposite of this project's requirement)
   and a single-AZ dependency; two NAT gateways cost about the same as the endpoints.
4. **Container Insights off** (keep the free `AWS/ECS` service metrics): saves **≈ $9.50**; the
   task-count widget would need the `AWS/ECS` running-task metrics instead.
5. **Trace sampling 1 %** at scenario-B volumes: saves ≈ $13.50.
6. **Turn the stack off between demos** (what this project does): `EnableCompute=false` removes
   the endpoints, ALB, service and pipeline; `EnableDatabase=false` removes Aurora (data is demo
   data). What remains costs about **$1/month** (secret, ECR images, S3, log storage).

## What this project actually cost to build

Everything ran for about 11 hours on 2026-11-01. At the hourly rates above (≈ $0.16-0.27/h over
the day), plus ~15 pipeline runs (≈ $0.035 each: ~1.5 build minutes + ~15 action minutes, most
within CodePipeline's free 100 minutes), load tests (a few LCU-hours) and Aurora at its 2-ACU
maximum during the write test, the estimate is **≈ $3-4 for the day**.

This can't be confirmed per project yet:
- Cost Explorer lags by up to 24 hours (no ECS data for 2026-11-01 when this was written);
- the cost-allocation tag **`project` is inactive** in this account (`ce list-cost-allocation-tags`),
  so Cost Explorer can't filter by it. Activating it (Billing → Cost allocation tags) only applies
  to costs from then on;
- the account also runs other workloads, so per-service totals include them.

The actual **Fargate Spot** rate (usage type `USE1-SpotUsage-ARM-…` in Cost Explorer) should be
checked the next day against the 70 % assumption.

## Reproducing this in the AWS Pricing Calculator

Create an estimate at <https://calculator.aws/#/estimate>, Region **US East (N. Virginia)**
unless noted:

- **AWS Fargate**: Linux/ARM, 0.25 vCPU, 0.5 GB, 1 task × 730 h (on-demand) + 1 task × 730 h as
  Fargate Spot.
- **Elastic Load Balancing**: 1 Application Load Balancer, ~0.2 LCU (scenario A).
- **Amazon VPC**: 5 interface endpoints × 2 AZs, ~6 GB processed.
- **Amazon Aurora PostgreSQL-Compatible**: Serverless v2, 1 ACU average (scenario A), storage
  1 GB, 1 M I/O; Global Database: secondary in **US West (Oregon)** with 0.5 ACU.
- **AWS Secrets Manager**: 1 secret, 1 000 API calls.
- **Amazon CloudWatch**: 1 dashboard, 3 alarms, 30 custom metrics (Container Insights), 4.5 GB
  logs ingested.
- **Amazon ECR**: 1 GB storage.
- **AWS CodePipeline** / **AWS CodeBuild**: V2 pipeline, ~20 runs × 15 action minutes; ARM small,
  ~20 builds × 1.5 min.

The calculator needs an interactive session to save and share an estimate, so no shared link was
generated here.
