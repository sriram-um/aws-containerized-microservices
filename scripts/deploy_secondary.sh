#!/usr/bin/env bash
# Lint and deploy infra/aurora-secondary.yaml in us-west-2 (exercise 10: Aurora Global Database
# secondary). Run after the primary stack has created the global cluster.
# Usage: scripts/deploy_secondary.sh
export AWS_REGION=us-west-2
. "$(dirname "$0")/lib.sh"
check_identity
cd "$REPO_ROOT"

.venv/Scripts/cfn-lint infra/aurora-secondary.yaml
echo "cfn-lint OK"

aws cloudformation deploy --stack-name "$STACK_NAME-dr" --template-file infra/aurora-secondary.yaml \
  --tags project=containerized-microservices --no-fail-on-empty-changeset

aws cloudformation describe-stacks --stack-name "$STACK_NAME-dr" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text | tr -d '\r'
