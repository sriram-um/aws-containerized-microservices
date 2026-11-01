# How CI/CD works in this project: from `git push` to running containers

A beginner's walkthrough of the pipeline built in Phase 6. It explains every piece, what happens
step by step after a push, how GitHub and AWS trust each other, and what went wrong on the way
(and why).

---

## 1. The big idea

**CI/CD** = *Continuous Integration / Continuous Delivery*. Instead of building and deploying by
hand (Phase 2: `docker build` + `docker push` on a laptop), a machine does it automatically every
time code changes:

- **CI (integration):** every change is *tested* and *built* the same way, on a clean machine.
- **CD (delivery/deployment):** every change that passes is *released* to the running service,
  safely, without downtime, and with an automatic way back if it's broken.

In this project, a `git push` to GitHub ends, about 14 minutes later, with the new version
serving all traffic. Nobody has to touch the AWS console.

## 2. The pieces

| Piece | What it is | Its job here |
|---|---|---|
| **GitHub repository** `sriram-um/aws-containerized-microservices` | Where the code lives | The *source of truth* for the application code |
| **AWS Connector for GitHub** (a *GitHub App*) | A small app made by AWS that you install on your GitHub account | Gives AWS permission to **read** the repository and to **receive events** ("a push happened") |
| **CodeConnections connection** `containerized-ms-github` | An AWS resource that stores the link to that GitHub App installation | Lets AWS services use the GitHub access *without storing a password or token in your code* |
| **CodePipeline** `containerized-microservices-product-service` | The conductor | Runs the 3 stages in order: Source → Build → Deploy |
| **CodeBuild** | A temporary build machine (arm64 Linux) | Runs the tests, builds the Docker image, pushes it to ECR |
| **Amazon ECR** `product-service` | The container image registry | Stores every built image, tagged with the git commit (e.g. `c3e0153`) |
| **CodeDeploy** | The release manager | Starts the new version next to the old one, shifts traffic gradually, rolls back if alarms fire |
| **ECS service + ALB** | Where the app runs, and the front door | Runs the containers; the load balancer sends user traffic to them |
| **S3 artifact bucket** | Shared storage between the stages | Hands the source code and build outputs from one stage to the next |

## 3. The flow, step by step

```
 you                    GitHub                         AWS
 ───                    ──────                         ───
 git push ───────────►  repository updated
                        │
                        │ (1) "push" event, sent by the
                        │     AWS Connector for GitHub app
                        ▼
                        ─────────────────────────────►  CodeConnections connection
                                                          │ (2) matches the event to the
                                                          │     pipeline's trigger
                                                          ▼
                                                        CodePipeline
                                                          │
                     (3) Source: download the commit ◄────┤  zip → S3 artifact bucket
                                                          │
                                                          ├─ (4) Build (CodeBuild, ~1 min)
                                                          │      pip install, pytest  ← stops here if a test fails
                                                          │      docker build, docker push → ECR :c3e0153
                                                          │      write imageDetail.json, taskdef.json, appspec.yaml
                                                          │
                                                          └─ (5) Deploy (CodeDeploy, ~12 min)
                                                                 register new task definition revision
                                                                 start GREEN tasks next to BLUE   (~2.5 min)
                                                                 send 10 % of traffic to GREEN    (5 min canary)
                                                                 send 100 % to GREEN
                                                                 keep BLUE 5 min (instant rollback)
                                                                 stop BLUE
```

### Step 1 - GitHub sends an event
When you push, GitHub notifies every *installed* GitHub App that has access to that repository.
The **AWS Connector for GitHub** is one of them, so GitHub sends it a message like "branch `main`
of `sriram-um/aws-containerized-microservices` now points to commit `c3e0153`".

### Step 2 - AWS decides whether to start the pipeline
The connection receives the event and checks the pipeline's **trigger** (in `template.yaml`):

- branch must be `main`, and
- at least one changed file must match `services/product-service/**`, `buildspec.yml`,
  `appspec.yaml` or `scripts/render_taskdef.py`.

So a README change does **not** deploy anything (measured: README-only push → no run), while a code
change does (measured: pipeline started **11 seconds** after the push). The execution shows the
trigger type `WebhookV2` / `PUSH_BRANCH`.

### Step 3 - Source
CodePipeline uses the connection to download that exact commit as a zip and stores it in the S3
artifact bucket.

### Step 4 - Build ([`buildspec.yml`](../buildspec.yml))
CodeBuild starts a fresh arm64 machine and follows the build spec:

1. installs the Python dependencies and runs **all unit tests**. If one fails, the pipeline stops
   and nothing is deployed (this happened in test 1, see the README);
2. logs in to ECR, builds the Docker image and pushes it as `product-service:<commit>`;
3. writes three small files for the next stage:
   - `imageDetail.json`: which image to deploy;
   - `taskdef.json`: the ECS task definition, copied from the one CloudFormation manages, with the
     image replaced by a placeholder ([`scripts/render_taskdef.py`](../scripts/render_taskdef.py));
   - `appspec.yaml` ([file](../appspec.yaml)): tells CodeDeploy which container and port receive traffic.

### Step 5 - Deploy (blue/green with a canary)
CodeDeploy never touches the running version until the new one is proven healthy:

- **Blue** = the version serving users now. **Green** = the new version.
- Green tasks start in their own target group. The load balancer has two listeners: port 80
  (users) and port 8080 (test).
- When green is healthy, **10 %** of user traffic goes to it for 5 minutes (the *canary*).
- If an alarm fires (unhealthy targets, or the app returns 5xx errors), CodeDeploy **rolls back**
  in seconds: 100 % back to blue. Measured: a broken release reached only 10.1 % of requests.
- Otherwise 100 % goes to green; blue is kept for 5 more minutes, then stopped.

## 4. How GitHub and AWS trust each other (the part that went wrong)

There are **two different permissions** in a GitHub App connection, and both are needed:

| Permission | Granted by | Used for |
|---|---|---|
| **User authorization** ("AWS Connector for GitHub can access your account sriram-um to: verify your identity, act on your behalf") | You, when you click *Authorize* | Proving who you are; reading repositories you can see |
| **App installation** on an account (personal or organization), with a list of repositories | You, when you click *Install* and pick repositories | **Sending push events** for those repositories, and access as a "bot" |

**What happened in this project:**

1. The first connection was authorized, but during the handshake an *existing* installation was
   picked: the app was installed on two **other** accounts (`awsfundamentals-hq`, `Shravanthi-J`),
   not on `sriram-um`.
2. Downloading code still worked, because the repository is **public**, so the user
   authorization could read it. That made the problem confusing: the pipeline *looked* connected.
3. But GitHub only sends push events through an installation **on the account that owns the
   repository**. There was none, so no event ever reached AWS and the pipeline never started on
   its own (4 pushes, nothing).
4. **Fix:** install the app on `sriram-um` (only this repository), create a **new** connection
   (a connection can't switch to another installation), and pick the `sriram-um` installation
   during *Update pending connection*. The next push started the pipeline after 11 seconds.

**Rule of thumb:** when the handshake asks for an *App installation*, choose the one that belongs
to the account (or organization) that **owns the repository**, or choose *Install a new app*.

### Why a connection instead of a token?
Older setups stored a GitHub personal access token in AWS. With CodeConnections there is no
secret in the template, in the code or in CodeBuild: AWS holds the GitHub App credentials, the
pipeline role is only allowed to *use this one connection*, and you can revoke access in GitHub
at any time (Settings → Applications).

## 5. Who is allowed to do what (IAM)

Each AWS service gets its own role with only the permissions its step needs:

| Role | Can do |
|---|---|
| Pipeline role | use the GitHub connection, start this CodeBuild project, create deployments in this CodeDeploy group, read/write the artifact bucket, register task definitions, pass the two task roles to ECS |
| CodeBuild role | write its logs, read/write the artifact bucket, push images to the `product-service` repository, read task definitions |
| CodeDeploy role | AWS-managed policy for ECS blue/green: create task sets, switch load balancer listeners, read alarms |

## 6. Everyday operations

| I want to… | Do this |
|---|---|
| Deploy a change | Commit and push to `main` (a file under `services/product-service/` or the build files) |
| Re-run the pipeline without a code change | Console → CodePipeline → *Release change*, or `aws codepipeline start-pipeline-execution --name containerized-microservices-product-service --profile default` |
| See why a build failed | Pipeline → Build stage → *View details* → CodeBuild logs (test output is there) |
| Watch a deployment | Console → CodeDeploy → Deployments: shows each step, the traffic split and the timing |
| Stop a bad deployment now | CodeDeploy → *Stop and roll back*, or `aws deploy stop-deployment --deployment-id <id> --auto-rollback-enabled` |
| Change infrastructure (memory, env vars, roles) | Edit `template.yaml` and run `scripts/deploy.sh`; the next pipeline run picks up the new task definition |
| Find which version is live | `curl http://<alb>/health` → `app_version` = the git commit |

## 7. What the pipeline does **not** do
- It doesn't deploy **infrastructure** (`template.yaml`). That stays a deliberate, local
  `scripts/deploy.sh` run, so a code push can never accidentally change networking, IAM or the database.
- It doesn't run on pull requests. Only pushes to `main` deploy.
