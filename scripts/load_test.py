"""Load test GET /products through the ALB and record how the ECS service and the ASG scale.

Every --interval seconds it prints one line: request rate, latency, errors, ECS task counts
(desired/running/pending) and ASG instances (desired/in service). Results also go to a CSV.

  .venv/Scripts/python scripts/load_test.py --concurrency 64 --duration 600 --watch-after 1200

Uses the AWS "default" profile (account 977534234172) - never the ambient AWS_PROFILE.
"""
import argparse
import csv
import http.client
import statistics
import sys
import threading
import time
from urllib.parse import urlparse

import boto3

STACK = "containerized-microservices"
EXPECTED_ARN = "arn:aws:iam::977534234172:user/sriram"

sys.stdout.reconfigure(encoding="utf-8")


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies: list[float] = []
        self.codes: dict[int, int] = {}
        self.errors = 0

    def add(self, latency_ms: float | None, code: int | None):
        with self.lock:
            if code is None:
                self.errors += 1
            else:
                self.latencies.append(latency_ms)
                self.codes[code] = self.codes.get(code, 0) + 1

    def drain(self):
        with self.lock:
            out = (self.latencies, self.codes, self.errors)
            self.latencies, self.codes, self.errors = [], {}, 0
        return out


def worker(host: str, path: str, stop: threading.Event, stats: Stats):
    conn = http.client.HTTPConnection(host, 80, timeout=10)
    while not stop.is_set():
        start = time.perf_counter()
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            stats.add((time.perf_counter() - start) * 1000, resp.status)
        except (OSError, http.client.HTTPException):
            stats.add(None, None)
            conn.close()
            conn = http.client.HTTPConnection(host, 80, timeout=10)


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    return statistics.quantiles(values, n=100)[p - 1] if len(values) > 1 else values[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--duration", type=int, default=600, help="seconds of load")
    ap.add_argument("--watch-after", type=int, default=0, help="keep watching (no load) for scale-in, seconds")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--csv", default="load_test_results.csv")
    args = ap.parse_args()

    session = boto3.Session(profile_name="default", region_name="us-east-1")
    arn = session.client("sts").get_caller_identity()["Arn"]
    if arn != EXPECTED_ARN:
        sys.exit(f"wrong AWS identity {arn}")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in
               session.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
    url = urlparse(outputs["ProductsUrl"])
    cluster, service = outputs["ClusterName"], outputs["ServiceName"]
    asg_name = outputs.get("AutoScalingGroupName")  # EC2 only (exercises 3-6); Fargate has no hosts
    ecs, asg = session.client("ecs"), session.client("autoscaling")

    stats, stop = Stats(), threading.Event()
    threads = [threading.Thread(target=worker, args=(url.netloc, url.path, stop, stats), daemon=True)
               for _ in range(args.concurrency)]
    t0 = time.time()
    for t in threads:
        t.start()
    print(f"load: {args.concurrency} connections -> {outputs['ProductsUrl']} for {args.duration}s")

    header = ["t_s", "phase", "rps", "p50_ms", "p95_ms", "http_2xx", "http_other", "conn_errors",
              "tasks_desired", "tasks_running", "tasks_pending", "asg_desired", "asg_in_service"]
    print("  ".join(header))
    with open(args.csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        end = t0 + args.duration + args.watch_after
        while time.time() < end:
            time.sleep(args.interval)
            elapsed = time.time() - t0
            if elapsed >= args.duration and not stop.is_set():
                stop.set()
            lat, codes, errors = stats.drain()
            ok = sum(v for k, v in codes.items() if 200 <= k < 300)
            svc = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
            asg_desired = in_service = "-"
            if asg_name:
                group = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])["AutoScalingGroups"][0]
                asg_desired = group["DesiredCapacity"]
                in_service = sum(1 for i in group["Instances"] if i["LifecycleState"] == "InService")
            row = [round(elapsed), "load" if elapsed <= args.duration + args.interval else "idle",
                   round((len(lat) + errors) / args.interval), round(pct(lat, 50), 1), round(pct(lat, 95), 1),
                   ok, sum(codes.values()) - ok, errors,
                   svc["desiredCount"], svc["runningCount"], svc["pendingCount"],
                   asg_desired, in_service]
            writer.writerow(row)
            f.flush()
            print("  ".join(str(v) for v in row), flush=True)
    stop.set()


if __name__ == "__main__":
    main()
