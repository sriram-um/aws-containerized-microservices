"""Checks that every metric on the deployed dashboard returns data and renders widgets as PNGs.

A typo in a dimension doesn't fail the deployment - the graph is just empty. This script reads
the dashboard back, expands CloudWatch's "." / "..." shorthand, and sums each metric over the
last N minutes. With --images it renders each metric widget with GetMetricWidgetImage into
docs/images/ for the README. (Adapted from Project 4.)

Usage: .venv/Scripts/python scripts/check_dashboard.py [minutes] [--images[=<subfolder of docs/images>]]
Uses the AWS "default" profile (account 977534234172) - never the ambient AWS_PROFILE.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

STACK = "containerized-microservices"
EXPECTED_ARN = "arn:aws:iam::977534234172:user/sriram"
IMAGES = Path(__file__).resolve().parents[1] / "docs" / "images"


def expand(metrics):
    """Resolves the '.' (same as previous) and '...' (all remaining dims as previous) shorthand."""
    previous, out = None, []
    labels = {r[0]["expression"].split("(")[1].split(",")[0]: r[0]["label"]
              for r in metrics if len(r) == 1 and "expression" in r[0]}
    for row in metrics:
        if len(row) == 1 and "expression" in row[0]:
            continue  # FILL(mX, 0) wrapper - the underlying metric row is checked instead
        opts = row[-1] if isinstance(row[-1], dict) else {}
        if opts.get("id") in labels:
            opts = {**opts, "label": labels[opts["id"]]}
        parts = row[:-1] if opts else row
        if parts and parts[0] == "...":
            parts = previous[: len(previous) - (len(parts) - 1)] + parts[1:]
        else:
            parts = [previous[i] if p == "." and previous else p for i, p in enumerate(parts)]
        previous = parts
        out.append((parts, opts))
    return out


def main(minutes=30, images=False, subdir=""):
    session = boto3.Session(profile_name="default", region_name="us-east-1")
    if (arn := session.client("sts").get_caller_identity()["Arn"]) != EXPECTED_ARN:
        sys.exit(f"wrong AWS identity {arn}")
    cw = session.client("cloudwatch")
    body = json.loads(cw.get_dashboard(DashboardName=f"{STACK}-dashboard")["DashboardBody"])
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    empty = 0
    for widget in body["widgets"]:
        props = widget["properties"]
        if widget["type"] != "metric":
            continue
        print(f"\n{props['title']}")
        for parts, opts in expand(props["metrics"]):
            namespace, metric, *dims = parts
            stat = opts.get("stat", props.get("stat", "Sum"))
            stat = "Sum" if stat.startswith("p") else stat  # just checking presence of data
            resp = cw.get_metric_statistics(
                Namespace=namespace, MetricName=metric, StartTime=start, EndTime=end,
                Period=minutes * 60, Statistics=[stat],
                Dimensions=[{"Name": dims[i], "Value": dims[i + 1]} for i in range(0, len(dims), 2)])
            points = resp["Datapoints"]
            value = points[0][stat] if points else None
            empty += value is None
            print(f"  {'NO DATA' if value is None else f'{value:>10.1f}'}  {stat:<8} {opts.get('label', metric)}")
        if images:
            out = IMAGES / subdir
            out.mkdir(parents=True, exist_ok=True)
            widget_def = {**props, "start": f"-PT{minutes}M", "width": 600, "height": 300}
            png = cw.get_metric_widget_image(MetricWidget=json.dumps(widget_def))["MetricWidgetImage"]
            name = re.sub(r"[^a-z0-9]+", "-", props["title"].lower()).strip("-")[:60]
            (out / f"dashboard-{name}.png").write_bytes(png)
    print(f"\n{empty} metric(s) without data in the last {minutes} min")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    img = next((a for a in sys.argv if a.startswith("--images")), None)
    main(int(args[0]) if args else 30, img is not None, img.split("=", 1)[1] if img and "=" in img else "")
