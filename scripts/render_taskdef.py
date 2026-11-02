"""Turn `aws ecs describe-task-definition --query taskDefinition` output into CodeDeploy's taskdef.json.

CloudFormation owns the task definition (roles, sidecar, env, health checks). The pipeline only
changes the image: the product-service container image becomes the <IMAGE1_NAME> placeholder that
the CodeDeployToECS action fills from imageDetail.json, and APP_VERSION is set to the git SHA.

Usage (CodeBuild): python scripts/render_taskdef.py td.json <git-sha> [container] [image] > taskdef.json
  container: defaults to product-service; image: defaults to the <IMAGE1_NAME> placeholder (CodeDeploy).
  The orders pipeline (ECS rolling, exercise 12) passes the real image URI and registers the result itself.
"""
import json
import sys

CONTAINER = "product-service"
# Read-only fields returned by DescribeTaskDefinition that RegisterTaskDefinition rejects
READ_ONLY = {"taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
             "registeredAt", "registeredBy", "deregisteredAt"}


def render(task_definition: dict, version: str, container: str = CONTAINER, image: str = "<IMAGE1_NAME>") -> dict:
    td = {k: v for k, v in task_definition.items() if k not in READ_ONLY}
    containers = [c for c in td["containerDefinitions"] if c["name"] == container]
    if len(containers) != 1:
        raise ValueError(f"expected one container named {container!r}")
    app = containers[0]
    app["image"] = image
    env = [e for e in app.get("environment", []) if e["name"] != "APP_VERSION"]
    app["environment"] = env + [{"name": "APP_VERSION", "value": version}]
    return td


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(render(json.load(f), sys.argv[2], *sys.argv[3:5]), indent=2))
