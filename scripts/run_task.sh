#!/usr/bin/env bash
# Run the Product Service as standalone ECS tasks (exercise 3: CloudFormation can't "run" a task).
# Usage:
#   scripts/run_task.sh seed              # one-off task: create the table + sample rows, wait for exit code
#   scripts/run_task.sh api               # long-running API task; waits until RUNNING and HEALTHY
#   scripts/run_task.sh stop              # stop the tasks started with "api" (never the service's tasks)
#   scripts/run_task.sh write-load [secs] # exercise 10: insert rows into the primary for N seconds (default 180)
# Writes go to the Aurora writer endpoint when it exists (the service itself reads via the reader endpoint).
. "$(dirname "$0")/lib.sh"
check_identity

CLUSTER=$(stack_output ClusterName)
TASK_DEF=$(stack_output TaskDefinitionArn)
CAPACITY_PROVIDER=$(stack_output CapacityProviderName)
SUBNETS=$(stack_output PrivateSubnetIds)
SG=$(stack_output AppSecurityGroupId)
LOG_GROUP=$(stack_output LogGroupName)
NETWORK="awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"
WRITER=$(stack_output AuroraWriterEndpoint)
[[ "$WRITER" == "None" || -z "$WRITER" ]] && WRITER=$(stack_output DatabaseEndpoint)   # RDS (exercises 3-9)

run() {  # extra run-task args...
  aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" \
    --capacity-provider-strategy "capacityProvider=$CAPACITY_PROVIDER,weight=1" \
    --network-configuration "$NETWORK" "$@" \
    --query 'tasks[0].taskArn' --output text | tr -d '\r'
}

overrides() {  # command as JSON array -> containerOverrides JSON that points DB_HOST at the writer
  printf '{"containerOverrides":[{"name":"product-service","command":%s,"environment":[{"name":"DB_HOST","value":"%s"}]}]}' "$1" "$WRITER"
}

describe() {  # task-arn query
  aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$1" --query "tasks[0].$2" --output text | tr -d '\r'
}

case "${1:-}" in
  seed)
    start=$(date +%s)
    TASK=$(run --started-by seed --overrides "$(overrides '["python","-m","product_service.seed"]')")
    echo "seed task: $TASK (DB_HOST=$WRITER)"
    aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK"
    echo "stopped after $(( $(date +%s) - start ))s: exitCode=$(describe "$TASK" 'containers[?name==`product-service`].exitCode|[0]') reason=$(describe "$TASK" 'stoppedReason')"
    MSYS_NO_PATHCONV=1 aws logs get-log-events --log-group-name "$LOG_GROUP" \
      --log-stream-name "product-service/product-service/${TASK##*/}" --query 'events[].message' --output text
    ;;
  api)
    start=$(date +%s)
    TASK=$(run --started-by api)
    echo "api task: $TASK"
    aws ecs wait tasks-running --cluster "$CLUSTER" --tasks "$TASK"
    echo "RUNNING after $(( $(date +%s) - start ))s"
    for _ in $(seq 1 30); do
      health=$(describe "$TASK" healthStatus)
      [[ "$health" == HEALTHY ]] && break
      sleep 5
    done
    echo "health=$health after $(( $(date +%s) - start ))s; private IP $(describe "$TASK" 'attachments[0].details[?name==`privateIPv4Address`].value|[0]')"
    ;;
  stop)
    # --started-by api: since exercise 6 the service's tasks share the family, so never filter by family
    for t in $(aws ecs list-tasks --cluster "$CLUSTER" --started-by api --desired-status RUNNING --query 'taskArns' --output text | tr -d '\r'); do
      aws ecs stop-task --cluster "$CLUSTER" --task "$t" --reason "run_task.sh stop" --query 'task.lastStatus' --output text
    done
    ;;
  write-load)
    secs="${2:-180}"
    # One INSERT every 50 ms into replication_probe for $secs seconds (drives AuroraGlobalDBReplicationLag)
    py="import os,time,psycopg
c=psycopg.connect(host=os.environ['DB_HOST'],dbname=os.environ['DB_NAME'],user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],sslmode='require',autocommit=True)
c.execute('CREATE TABLE IF NOT EXISTS replication_probe (id bigserial primary key, written_at timestamptz default now())')
end=time.time()+$secs; n=0
while time.time()<end:
    c.execute('INSERT INTO replication_probe DEFAULT VALUES'); n+=1; time.sleep(0.05)
print('write-load rows', n)"
    cmd=$("$REPO_ROOT/.venv/Scripts/python" -c 'import json,sys; print(json.dumps(["python","-c",sys.argv[1]]))' "$py")
    TASK=$(run --started-by write-load --overrides "$(overrides "$cmd")")
    echo "write-load task: $TASK ($secs s, DB_HOST=$WRITER)"
    aws ecs wait tasks-running --cluster "$CLUSTER" --tasks "$TASK"
    echo "RUNNING at $(date +%H:%M:%S)"
    ;;
  *)
    echo "usage: $0 seed|api|stop|write-load [secs]" >&2; exit 1 ;;
esac
