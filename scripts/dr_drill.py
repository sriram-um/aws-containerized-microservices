"""Exercise 10: Aurora Global Database DR drill - managed switchover to us-west-2 and back.

While the drill runs, a background thread calls GET /products through the ALB 4 times a second
(the app reads via the us-east-1 cluster's reader endpoint), and the global cluster state is
polled every 2 s. Prints a timeline and the probe results per phase.

  .venv/Scripts/python scripts/dr_drill.py            # switchover there and back
  .venv/Scripts/python scripts/dr_drill.py --one-way  # only to us-west-2

A managed switchover (planned) waits until the secondary is fully synchronized: no data loss
(RPO 0). An unplanned failover would be `failover-global-cluster --allow-data-loss`.
Uses the AWS "default" profile (account 977534234172) - never the ambient AWS_PROFILE.
"""
import argparse
import sys
import threading
import time
import urllib.request
from datetime import datetime

import boto3

EXPECTED_ARN = "arn:aws:iam::977534234172:user/sriram"
STACK = "containerized-microservices"
GLOBAL = f"{STACK}-global"
CLUSTERS = {
    "us-east-1": f"arn:aws:rds:us-east-1:977534234172:cluster:{STACK}-aurora-use1",
    "us-west-2": f"arn:aws:rds:us-west-2:977534234172:cluster:{STACK}-aurora-usw2",
}

sys.stdout.reconfigure(encoding="utf-8")
probe_log: list[tuple[float, int]] = []
stop = threading.Event()


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def probe(url: str):
    while not stop.is_set():
        t = time.time()
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception:
            code = 0
        probe_log.append((t, code))
        time.sleep(0.25)


def state(rds) -> tuple[str, str]:
    g = rds.describe_global_clusters(GlobalClusterIdentifier=GLOBAL)["GlobalClusters"][0]
    writer = next((m["DBClusterArn"] for m in g["GlobalClusterMembers"] if m["IsWriter"]), "?")
    region = next((r for r, arn in CLUSTERS.items() if arn == writer), "?")
    return g["Status"], region


def switchover(rds, target_region: str) -> tuple[float, float]:
    start = time.time()
    print(f"{now()} switchover-global-cluster -> {target_region}")
    rds.switchover_global_cluster(GlobalClusterIdentifier=GLOBAL,
                                  TargetDbClusterIdentifier=CLUSTERS[target_region])
    last, writer_at = None, None
    while True:
        status, writer = state(rds)
        if (status, writer) != last:
            print(f"{now()}   +{time.time() - start:5.0f}s  status={status:<14} writer={writer}")
            last = (status, writer)
        if writer == target_region and writer_at is None:
            writer_at = time.time()
        if status == "available" and writer == target_region:
            return start, time.time()
        time.sleep(2)


def summarize(label: str, t0: float, t1: float):
    window = [(t, c) for t, c in probe_log if t0 <= t <= t1]
    bad = [(t, c) for t, c in window if c != 200]
    print(f"  {label}: {len(window)} requests, {len(bad)} not 200", end="")
    if bad:
        print(f"  first {datetime.fromtimestamp(bad[0][0]):%H:%M:%S} last "
              f"{datetime.fromtimestamp(bad[-1][0]):%H:%M:%S} codes {sorted({c for _, c in bad})}"
              f" (~{bad[-1][0] - bad[0][0]:.0f} s)")
    else:
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one-way", action="store_true")
    args = ap.parse_args()
    session = boto3.Session(profile_name="default", region_name="us-east-1")
    if (arn := session.client("sts").get_caller_identity()["Arn"]) != EXPECTED_ARN:
        sys.exit(f"wrong AWS identity {arn}")
    rds = session.client("rds")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in
               session.client("cloudformation").describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]}
    status, writer = state(rds)
    print(f"{now()} global cluster {GLOBAL}: status={status} writer={writer}")
    if status != "available" or writer != "us-east-1":
        sys.exit("expected an available global cluster with the writer in us-east-1")

    threading.Thread(target=probe, args=(outputs["ProductsUrl"],), daemon=True).start()
    time.sleep(10)
    a0, a1 = switchover(rds, "us-west-2")
    print(f"  switchover to us-west-2 took {a1 - a0:.0f} s")
    if not args.one_way:
        time.sleep(30)
        b0, b1 = switchover(rds, "us-east-1")
        print(f"  switchover back to us-east-1 took {b1 - b0:.0f} s")
    time.sleep(10)
    stop.set()
    print("\nprobe (GET /products via ALB -> app -> us-east-1 reader endpoint):")
    summarize("switchover to us-west-2", a0, a1)
    if not args.one_way:
        summarize("switchover back", b0, b1)
    summarize("whole drill", probe_log[0][0], probe_log[-1][0])


if __name__ == "__main__":
    main()
