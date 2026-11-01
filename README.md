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
| 1 | Build container | Docker | ✅ Done |
| 2 | Push image to registry | Amazon ECR | ⏳ Next |
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
4. **One deploy identity.** Every resource is deployed by account `977534234172`, IAM user
   `arn:aws:iam::977534234172:user/sriram` (AWS profile `default`). Scripts abort if
   `aws sts get-caller-identity` returns any other identity.
5. **Document as we go.** Every phase adds a [build log](#build-log) entry with the commands that
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
(test paths limited to the service test folders, so pytest never collects the live-AWS scripts in
`scripts/`).

**Observations:** Docker Desktop has to be started by hand before any container work.

### Phase 1 — Build the container (Docker) (2026-11-01)

**What was built**

| File | Purpose |
|---|---|
| [`product_service/main.py`](services/product-service/product_service/main.py) | FastAPI app: `GET /products`, `GET /health`. Connection pool opened at startup without waiting for the DB |
| [`product_service/repository.py`](services/product-service/product_service/repository.py) | SQL for the `products` table; `NUMERIC` → JSON number |
| [`product_service/config.py`](services/product-service/product_service/config.py) | Settings from env vars `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD/DB_SSLMODE/APP_VERSION` |
| [`product_service/seed.py`](services/product-service/product_service/seed.py) | Creates the table and 5 sample products; idempotent (`ON CONFLICT (sku) DO NOTHING`) |
| [`Dockerfile`](services/product-service/Dockerfile) | Multi-stage, pinned base `python:3.12.16-slim-trixie`, non-root user, port 3000, `HEALTHCHECK` |
| [`.dockerignore`](services/product-service/.dockerignore) | Allow-list: only `requirements.txt` and `product_service/` go into the build context |
| [`tests/test_main.py`](services/product-service/tests/test_main.py) | 7 unit tests; the repository is replaced through FastAPI dependency overrides |
| [`docker-compose.yml`](docker-compose.yml) | Local Postgres 16 → seed job → service, ordered by health/completion conditions |

**API**

| Request | Response |
|---|---|
| `GET /products` | `200 {"products": [{"id", "sku", "name", "description", "price", "stock"}], "count": n}` |
| `GET /products`, database unreachable | `503 {"message": "Database unavailable"}` (after at most 5 s pool wait) |
| `GET /health` | `200 {"status": "ok", "app_version": "…"}`; never touches the DB, so a DB outage doesn't make ECS/ALB kill healthy tasks |

**Dockerfile design**

- **Builder stage** creates `/opt/venv` and installs only `requirements.txt` (no test tools). It
  then uninstalls the venv's own `pip`, which saves ~13 MB.
- **Runtime stage** starts again from the slim base and copies just the venv and the code. There
  are no compilers, no pip cache and no build files. `psycopg[binary]` ships its own libpq, so no
  `apt-get` is needed.
- Runs as non-root user `app` (uid 10001). `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED` are set, so
  logs reach `docker logs`/CloudWatch immediately.
- Exec-form `CMD`, so uvicorn is PID 1 and gets ECS's `SIGTERM`. `--proxy-headers` makes it trust
  the ALB's `X-Forwarded-*` headers.
- `HEALTHCHECK` uses Python's `urllib`, because the slim image has no curl. ECS ignores Dockerfile
  health checks, so the task definition will declare the same check in Phase 3.

**Commands run**

```bash
.venv/Scripts/python -m pip install -r services/product-service/requirements-dev.txt
.venv/Scripts/python -m pytest -q                          # 7 passed
docker build -t product-service:local services/product-service
docker compose up --build -d
curl localhost:3000/products
docker compose run --rm seed                               # second run: still 5 products
docker compose stop db; curl localhost:3000/products       # 503; /health still 200
docker compose start db; curl localhost:3000/products      # 200 again, no restart needed
docker compose stop product-service                        # graceful SIGTERM shutdown
docker buildx build --platform linux/arm64 -t product-service:arm64 --load services/product-service
docker compose down -v
```

**Measured**

| What | Result |
|---|---|
| Unit tests | 7 passed in 1.4 s |
| Image size (compressed, `docker image inspect`) | base 43 MB → **multi-stage 54 MB** (+11 MB). A naive single-stage build with dev deps and pip cache: 76 MB (+33 MB) |
| venv size (uncompressed) | 53 MB → 40 MB after removing pip |
| Build time, amd64 native | 38 s (cold) |
| Build time, **arm64 under QEMU emulation** | **290 s** (7.6× slower) |
| arm64 image | 56.7 MB, `aarch64`, psycopg `binary` implementation loads |
| `GET /products` warm latency, local (20 calls) | min 6.7 ms, p50 8.7 ms, max 100 ms (first call) |
| Compose start → container `healthy` | ~8 s |
| DB stopped → `GET /products` | `503` in 8 ms (refused connection fails fast); recovers by itself when the DB is back |
| `docker compose stop` (SIGTERM) | 1.9 s, exit code 0 (`Shutting down` → `Finished server process`) |

**Issues hit and fixes**

| Symptom | Cause | Fix |
|---|---|---|
| `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` | Starlette 1.x moved its TestClient to `httpx2` | Dev dependency `httpx2==2.16.0` instead of `httpx` |
| `cat: 'C:/Program Files/Git/etc/os-release'` from `docker run … cat /etc/os-release` | Git Bash rewrote the container path | `MSYS_NO_PATHCONV=1 docker run …` |
| Docker Desktop sizes look wrong (`docker images`: base 384 MB, our image 248 MB) | With the containerd image store, `docker images` shows a different measure than `docker image inspect` | Compare with `docker image inspect --format '{{.Size}}'` (compressed); ECR's `imageSizeInBytes` will confirm in Phase 2 |
| Size-comparison build failed at `pip install -r requirements-dev.txt` | The allow-list `.dockerignore` excludes everything except the runtime files (working as intended) | Built the comparison image from a temp copy outside the repo |

## Repository layout

```
docker-compose.yml               local Postgres + seed + service
pytest.ini
services/product-service/
  product_service/               FastAPI app (main, repository, config, seed)
  tests/                         unit tests
  Dockerfile  .dockerignore  requirements.txt  requirements-dev.txt
```

## Getting started (local)

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r services/product-service/requirements-dev.txt
.venv/Scripts/python -m pytest -q

docker compose up --build -d         # Postgres → seed → product-service on :3000
curl http://localhost:3000/products
docker compose down -v
```

## Observations and lessons learned

- **Multi-stage pays off even on a slim base:** the app adds 11 MB instead of 33 MB. Most of the
  saving comes from not shipping pip, its cache and the test tools.
- **Don't build arm64 images on an x86 laptop routinely:** QEMU emulation made the build 7.6×
  slower (290 s vs 38 s). CodeBuild will use a native ARM build host (Phase 6).
- **Health check ≠ readiness of dependencies:** `/health` deliberately ignores the database. When
  the DB went down, the container stayed `healthy` and served fast `503`s, then recovered on its
  own when the DB came back. A DB-dependent health check would have restarted every task during a
  DB outage.
