import pytest

from scripts.render_taskdef import render

DESCRIBED = {
    "taskDefinitionArn": "arn:aws:ecs:us-east-1:111122223333:task-definition/product-service:3",
    "family": "product-service",
    "revision": 3,
    "status": "ACTIVE",
    "compatibilities": ["EC2"],
    "requiresAttributes": [{"name": "com.amazonaws.ecs.capability.logging-driver.awslogs"}],
    "registeredAt": "2026-11-01T12:00:00Z",
    "registeredBy": "arn:aws:iam::111122223333:user/x",
    "networkMode": "awsvpc",
    "containerDefinitions": [
        {"name": "product-service", "image": "repo/product-service:old",
         "environment": [{"name": "DB_HOST", "value": "db"}, {"name": "APP_VERSION", "value": "old"}]},
        {"name": "aws-otel-collector", "image": "repo/ecr-public/aws-otel-collector:v0.51.0"},
    ],
}


def test_strips_read_only_fields_and_keeps_the_rest():
    td = render(DESCRIBED, "abc1234")
    for key in ("taskDefinitionArn", "revision", "status", "compatibilities", "requiresAttributes",
                "registeredAt", "registeredBy"):
        assert key not in td
    assert td["family"] == "product-service"
    assert td["networkMode"] == "awsvpc"


def test_sets_image_placeholder_and_version_only_on_app_container():
    td = render(DESCRIBED, "abc1234")
    app, sidecar = td["containerDefinitions"]
    assert app["image"] == "<IMAGE1_NAME>"
    assert {"name": "APP_VERSION", "value": "abc1234"} in app["environment"]
    assert [e for e in app["environment"] if e["name"] == "APP_VERSION"] == [{"name": "APP_VERSION", "value": "abc1234"}]
    assert {"name": "DB_HOST", "value": "db"} in app["environment"]
    assert sidecar["image"] == "repo/ecr-public/aws-otel-collector:v0.51.0"


def test_missing_app_container_fails():
    with pytest.raises(ValueError):
        render({"containerDefinitions": [{"name": "other", "image": "x"}]}, "abc1234")


def test_other_container_and_real_image():
    described = {**DESCRIBED, "containerDefinitions": [
        {"name": "orders-service", "image": "repo/orders-service:old", "environment": []}]}
    td = render(described, "abc1234", "orders-service", "repo/orders-service:abc1234")
    assert td["containerDefinitions"][0]["image"] == "repo/orders-service:abc1234"
    assert {"name": "APP_VERSION", "value": "abc1234"} in td["containerDefinitions"][0]["environment"]
