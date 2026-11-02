#!/usr/bin/env bash
# Exercise 13: decommission everything this project created, in both Regions.
# Order matters:
#   1. detach the us-west-2 secondary from the Aurora global cluster, delete the -dr stack
#   2. detach the primary, empty the S3 buckets, delete the main stack, then the bootstrap stack
#   3. clean up what CloudFormation doesn't own (pull-through cache repo, Container Insights log
#      group, task definition revisions registered by the pipelines, leftover log groups/secrets)
#   4. verify: no stacks, no tagged resources, no snapshots, no global cluster
# Usage: scripts/teardown.sh --yes
. "$(dirname "$0")/lib.sh"
check_identity
[[ "${1:-}" == "--yes" ]] || { echo "This deletes ALL project resources in us-east-1 and us-west-2. Re-run with --yes." >&2; exit 1; }
export MSYS_NO_PATHCONV=1
GLOBAL="$STACK_NAME-global"
SECONDARY_ARN="arn:aws:rds:us-west-2:977534234172:cluster:$STACK_NAME-aurora-usw2"
PRIMARY_ARN="arn:aws:rds:us-east-1:977534234172:cluster:$STACK_NAME-aurora-use1"
ts() { date +%H:%M:%S; }

members() {
  aws rds describe-global-clusters --region us-east-1 --global-cluster-identifier "$GLOBAL" \
    --query 'length(GlobalClusters[0].GlobalClusterMembers)' --output text 2>/dev/null | tr -d '\r'
}
detach() {  # cluster-arn region
  if aws rds describe-global-clusters --region us-east-1 --global-cluster-identifier "$GLOBAL" \
       --query 'GlobalClusters[0].GlobalClusterMembers[].DBClusterArn' --output text 2>/dev/null | grep -q "$1"; then
    echo "$(ts) remove-from-global-cluster ${1##*:}"
    aws rds remove-from-global-cluster --region "$2" --global-cluster-identifier "$GLOBAL" \
      --db-cluster-identifier "$1" --query 'GlobalCluster.Status' --output text
    until ! aws rds describe-global-clusters --region us-east-1 --global-cluster-identifier "$GLOBAL" \
        --query 'GlobalClusters[0].GlobalClusterMembers[].DBClusterArn' --output text 2>/dev/null | grep -q "$1"; do sleep 10; done
    # the detached cluster must be available again before CloudFormation can delete it
    until [[ "$(aws rds describe-db-clusters --region "$2" --db-cluster-identifier "$1" --query 'DBClusters[0].Status' --output text 2>/dev/null | tr -d '\r')" == "available" ]]; do sleep 10; done
    echo "$(ts) detached, members left: $(members)"
  fi
}
delete_stack() {  # name region
  if aws cloudformation describe-stacks --region "$2" --stack-name "$1" >/dev/null 2>&1; then
    echo "$(ts) delete-stack $1 ($2)"
    aws cloudformation delete-stack --region "$2" --stack-name "$1"
    if ! aws cloudformation wait stack-delete-complete --region "$2" --stack-name "$1"; then
      aws cloudformation describe-stack-events --region "$2" --stack-name "$1" --max-items 30 \
        --query 'StackEvents[?contains(ResourceStatus,`FAILED`)].[LogicalResourceId,ResourceStatusReason]' --output text
      exit 1
    fi
    echo "$(ts) deleted $1"
  fi
}
empty_bucket() {  # stack output-key
  local b
  b=$(aws cloudformation describe-stacks --region us-east-1 --stack-name "$1" \
        --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text 2>/dev/null | tr -d '\r')
  # The bucket may already be gone (a re-run after a partly failed delete): don't abort then
  if [[ -n "$b" && "$b" != "None" ]] && aws s3api head-bucket --bucket "$b" >/dev/null 2>&1; then
    echo "$(ts) empty s3://$b"; aws s3 rm "s3://$b" --recursive --quiet
  fi
}

# 1. Secondary Region
detach "$SECONDARY_ARN" us-west-2
delete_stack "$STACK_NAME-dr" us-west-2

# 2. Primary Region
detach "$PRIMARY_ARN" us-east-1
empty_bucket "$STACK_NAME" ArtifactBucketName
# CodeDeploy swapped the listeners' target groups (drift CloudFormation doesn't know about). Deleting
# the listeners first avoids "target group ... is currently in use by a listener" (first teardown).
ALB=$(aws elbv2 describe-load-balancers --names "$STACK_NAME-alb" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null | tr -d '\r' || true)
if [[ -n "$ALB" && "$ALB" != "None" ]]; then
  for l in $(aws elbv2 describe-listeners --load-balancer-arn "$ALB" --query 'Listeners[].ListenerArn' --output text | tr -d '\r'); do
    echo "$(ts) delete listener ${l##*/}"; aws elbv2 delete-listener --listener-arn "$l"
  done
fi
delete_stack "$STACK_NAME" us-east-1
empty_bucket "$STACK_NAME-deploy-bucket" TemplateBucketName
delete_stack "$STACK_NAME-deploy-bucket" us-east-1

# 3. Not owned by CloudFormation
aws rds describe-global-clusters --region us-east-1 --global-cluster-identifier "$GLOBAL" >/dev/null 2>&1 && \
  aws rds delete-global-cluster --region us-east-1 --global-cluster-identifier "$GLOBAL" --query 'GlobalCluster.Status' --output text
for repo in ecr-public/aws-observability/aws-otel-collector product-service orders-service; do
  aws ecr describe-repositories --repository-names "$repo" >/dev/null 2>&1 && \
    { echo "$(ts) delete ECR repository $repo"; aws ecr delete-repository --repository-name "$repo" --force --query 'repository.repositoryName' --output text; }
done
for lg in $(aws logs describe-log-groups --query 'logGroups[].logGroupName' --output text | tr -d '\r' | tr '\t' '\n' \
            | grep -E "containerized-microservices"); do
  echo "$(ts) delete log group $lg"; aws logs delete-log-group --log-group-name "$lg"
done
for family in product-service orders-service; do
  for td in $(aws ecs list-task-definitions --family-prefix "$family" --status ACTIVE --query taskDefinitionArns --output text | tr -d '\r'); do
    aws ecs deregister-task-definition --task-definition "$td" --query 'taskDefinition.revision' --output text >/dev/null
  done
  # Deregistered revisions stay readable until deleted (old ones held the Phase 3 password)
  mapfile -t tds < <(aws ecs list-task-definitions --family-prefix "$family" --status INACTIVE --query 'taskDefinitionArns[]' --output text | tr -d '\r' | tr '\t' '\n' | grep .)
  for ((i = 0; i < ${#tds[@]}; i += 10)); do
    aws ecs delete-task-definitions --task-definitions "${tds[@]:i:10}" --query 'length(taskDefinitions)' --output text >/dev/null
  done
  echo "$(ts) $family: deleted ${#tds[@]} task definition revisions"
done
for s in $(aws secretsmanager list-secrets --include-planned-deletion --query "SecretList[?starts_with(Name,'$STACK_NAME')].ARN" --output text | tr -d '\r'); do
  echo "$(ts) force-delete secret ${s##*:}"; aws secretsmanager delete-secret --secret-id "$s" --force-delete-without-recovery --query Name --output text
done

# 4. Verify
echo "--- verification"
for r in us-east-1 us-west-2; do
  echo "$r stacks: $(aws cloudformation list-stacks --region "$r" --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE DELETE_FAILED --query "StackSummaries[?starts_with(StackName,'$STACK_NAME')].StackName" --output text)"
  echo "$r tagged resources: $(aws resourcegroupstaggingapi get-resources --region "$r" --tag-filters Key=project,Values=containerized-microservices --query 'length(ResourceTagMappingList)' --output text)"
  echo "$r Aurora/RDS: $(aws rds describe-db-clusters --region "$r" --query "DBClusters[?starts_with(DBClusterIdentifier,'$STACK_NAME')].DBClusterIdentifier" --output text) $(aws rds describe-db-cluster-snapshots --region "$r" --query "DBClusterSnapshots[?starts_with(DBClusterIdentifier,'$STACK_NAME')].DBClusterSnapshotIdentifier" --output text)"
done
echo "global cluster: $(aws rds describe-global-clusters --region us-east-1 --query "GlobalClusters[?starts_with(GlobalClusterIdentifier,'$STACK_NAME')].GlobalClusterIdentifier" --output text)"
echo "task definitions left: $(aws ecs list-task-definition-families --family-prefix product-service --status ACTIVE --query 'length(families)' --output text) active product, $(aws ecs list-task-definition-families --family-prefix orders-service --status ACTIVE --query 'length(families)' --output text) active orders"
echo "$(ts) teardown complete"
