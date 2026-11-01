#!/usr/bin/env bash
# Run the Product Service as standalone ECS tasks (exercise 3: CloudFormation can't "run" a task).
# Usage:
#   scripts/run_task.sh seed    # one-off task: create the table + sample rows, wait for exit code
#   scripts/run_task.sh api     # long-running API task; waits until RUNNING and HEALTHY
#   scripts/run_task.sh stop    # stop all running product-service tasks
. "$(dirname "$0")/lib.sh"
check_identity

CLUSTER=$(stack_output ClusterName)
TASK_DEF=$(stack_output TaskDefinitionArn)
CAPACITY_PROVIDER=$(stack_output CapacityProviderName)
SUBNETS=$(stack_output PrivateSubnetIds)
SG=$(stack_output AppSecurityGroupId)
LOG_GROUP=$(stack_output LogGroupName)
NETWORK="awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=DISABLED}"

run() {  # extra run-task args...
  aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" \
    --capacity-provider-strategy "capacityProvider=$CAPACITY_PROVIDER,weight=1" \
    --network-configuration "$NETWORK" "$@" \
    --query 'tasks[0].taskArn' --output text | tr -d '\r'
}

describe() {  # task-arn query
  aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$1" --query "tasks[0].$2" --output text | tr -d '\r'
}

case "${1:-}" in
  seed)
    start=$(date +%s)
    TASK=$(run --started-by seed \
      --overrides '{"containerOverrides":[{"name":"product-service","command":["python","-m","product_service.seed"]}]}')
    echo "seed task: $TASK"
    aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK"
    echo "stopped after $(( $(date +%s) - start ))s: exitCode=$(describe "$TASK" 'containers[0].exitCode') reason=$(describe "$TASK" 'stoppedReason')"
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
    for t in $(aws ecs list-tasks --cluster "$CLUSTER" --family product-service --desired-status RUNNING --query 'taskArns' --output text | tr -d '\r'); do
      aws ecs stop-task --cluster "$CLUSTER" --task "$t" --reason "run_task.sh stop" --query 'task.lastStatus' --output text
    done
    ;;
  *)
    echo "usage: $0 seed|api|stop" >&2; exit 1 ;;
esac
