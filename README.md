# Containerized Microservices on Amazon ECS (CloudFormation)

A Python **Product Service** (`GET /products`, data in Amazon RDS for PostgreSQL), packaged as a
Docker image, stored in Amazon ECR and run on Amazon ECS. The project grows one exercise at a
time: ECS on EC2 → ECS Service + ALB + Auto Scaling → monitoring → CodePipeline/CodeDeploy
blue/green → Fargate and Fargate Spot → Secrets Manager → Aurora Global Database → cost estimate.
At the end, Project 3's orders API is ported to a second ECS service. Every exercise extends the
same `template.yaml` and is deployed as an update to a single CloudFormation stack.

| | |
|---|---|
| **IaC** | AWS CloudFormation: one template, one stack (`containerized-microservices`) |
| **Runtime** | Python 3.12, FastAPI + uvicorn, psycopg 3; container on port 3000, arm64 (Graviton) |
| **Regions** | us-east-1 (primary), us-west-2 (Aurora Global Database secondary) |
| **CI/CD** | AWS CodePipeline (GitHub via CodeConnections) → CodeBuild → CodeDeploy ECS blue/green |
| **Status** | 🚧 In progress |

## Progress

| # | Exercise | Services | Status |
|---|---|---|---|
| 0 | Project setup | git, Python venv, cfn-lint | ✅ Done |
| 1 | Build container | Docker | ⏳ Next |
| 2 | Push image to registry | Amazon ECR | ⬜ |
| 3 | Deploy container as a task | Amazon ECS (EC2), VPC, RDS | ⬜ |
| 4 | Scale with an ECS Service | ECS Service, ALB, Auto Scaling | ⬜ |
| 5 | Monitoring | CloudWatch, Container Insights, X-Ray | ⬜ |
| 6 | CI/CD pipeline | CodePipeline, CodeBuild, CodeDeploy (blue/green) | ⬜ |
| 7 | Replace EC2 with Fargate | AWS Fargate | ⬜ |
| 8 | Spot capacity | Fargate Spot capacity providers | ⬜ |
| 9 | Database credentials | AWS Secrets Manager | ⬜ |
| 10 | Disaster recovery | Aurora Global Database | ⬜ |
| 11 | Cost estimate | AWS Pricing Calculator | ⬜ |
| 12 | Real-world project | Orders service (Project 3) on ECS | ⬜ |
| 13 | Close-out | Well-Architected review, teardown/rebuild | ⬜ |

## Process

The project uses the same working agreement as the other portfolio projects:

1. **Plan first.** The exercise sheet was turned into the phase plan below. Up-front decisions
   (runtime, database, networking, CI/CD, repo) were made before any code was written.
2. **One phase at a time.** For each phase: edit code/template → `pytest` → `cfn-lint` → deploy →
   verify with the CLI/curl → console check → README update → commit + push. Then **stop** for a
   go-ahead before the next phase.
3. **Cost toggles.** Hourly-billed resources sit behind template parameters (`EnableCompute`,
   `EnableDatabase`). They are switched on for a demo and off again with explicit
   `--parameter-overrides`.
4. **Document as we go.** Every phase adds a [build log](#build-log) entry with the commands that
   were run, what was observed (real numbers), and any errors with their root cause and fix.

### Up-front decisions

| Topic | Decision | Why |
|---|---|---|
| Runtime | Python 3.12 + FastAPI (sheet says Node.js) | Same language as Projects 3/4; FastAPI is small and async, and generates OpenAPI docs |
| IaC | Plain CloudFormation | Named by the exercise sheet; no Lambda here, so SAM adds nothing |
| Database | RDS PostgreSQL 16, db.t4g.micro, single-AZ, toggle | Cheapest RDS option for a demo; migrated to Aurora for the DR exercise |
| Networking | Private subnets + VPC endpoints, no NAT gateway | No internet egress from tasks or the DB; ALB in public subnets |
| CPU architecture | arm64 (Graviton) | Lower price per vCPU; same for EC2 and Fargate |
| CI/CD | CodePipeline + CodeBuild + CodeDeploy blue/green | Named by the exercise sheet; GitHub source via CodeConnections |
| Monitoring | ECS/ALB/RDS metrics + X-Ray via ADOT sidecar | The sheet's Lambda metrics don't apply to a container workload |
| Real-world exercise | Project 3 orders API as a 2nd ECS service | Two microservices behind one ALB with path routing |
| Teardown | Everything removed at the end with the same IaC | No running cost after the project |

### Phase plan

| # | What gets built |
|---|---|
| 1 | FastAPI app (`GET /products`, `GET /health`), seed script, multi-stage Dockerfile (non-root, healthcheck), unit tests, `docker compose` with local Postgres |
| 2 | `AWS::ECR::Repository` `product-service` (scan on push, immutable tags, lifecycle policy); manual login/build/tag/push commands |
| 3 | VPC (2 AZs, no NAT), VPC endpoints, security groups, RDS PostgreSQL, ECS cluster with an EC2 capacity provider (t4g.small ASG), IAM roles, log group, task definition; standalone tasks via `aws ecs run-task` (seed + API) |
| 4 | ALB + target group, ECS Service (2 tasks across AZs), target-tracking auto scaling, capacity provider managed scaling; load test |
| 5 | Container Insights, CloudWatch dashboard (ECS reservation/task counts, ALB requests/4XX/5XX/latency, RDS), X-Ray tracing |
| 6 | CodeConnections, CodeBuild (`buildspec.yml`), CodePipeline, CodeDeploy blue/green (`appspec.yaml`, 2 target groups, test listener), rollback test |
| 7 | Migrate the service from EC2 to Fargate, remove the EC2 capacity |
| 8 | `FARGATE` + `FARGATE_SPOT` capacity provider strategy |
| 9 | Secrets Manager secret for DB credentials, injected through task definition `secrets` |
| 10 | Aurora PostgreSQL Global Database (us-east-1 primary, us-west-2 secondary), replication lag, switchover drill |
| 11 | `docs/cost-estimate.md` + AWS Pricing Calculator link |
| 12 | Orders service (FastAPI, DynamoDB, Cognito JWT) as a second ECS service behind `/orders*` |
| 13 | Well-Architected review, scripted teardown and rebuild, final teardown |

## Build log

### Phase 0 — Project setup (2026-11-01)

**Environment check** (the shell's `AWS_PROFILE` points to a different account, so every AWS
command pins `--profile default`):

```bash
aws sts get-caller-identity --profile default   # account 977534234172, user sriram
py -3.12 --version                               # Python 3.12.10
docker info --format '{{.ServerVersion}}'        # Docker Desktop not running yet
docker buildx version                            # v0.35.0 (needed for arm64 builds)
git --version                                    # 2.54.0
df -h /c                                         # 132 GB free
```

**Repository and tooling:**

```bash
git init -b main
git config user.name  "Sriram Penumatcha"
git config user.email "93265789+sriram-um@users.noreply.github.com"
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install cfn-lint pytest   # cfn-lint 1.59.0
```

Files added: `.gitignore` (venv, caches, `*.env`), `.gitattributes` (`* text=auto eol=lf`, because
the code is checked out on Windows but built on Linux in CodeBuild), `pytest.ini`
(`testpaths = services`, so pytest never collects the live-AWS scripts in `scripts/`).

**Observations:** Docker Desktop has to be started by hand before any container work.

## Observations and lessons learned

Filled in phase by phase with measured numbers and the errors hit along the way.
