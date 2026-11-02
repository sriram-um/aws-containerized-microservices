#!/usr/bin/env bash
# Lint and deploy template.yaml as stack "containerized-microservices".
# Usage: scripts/deploy.sh [ParamKey=Value ...]     e.g. scripts/deploy.sh EnableCompute=false
. "$(dirname "$0")/lib.sh"
check_identity
cd "$REPO_ROOT"

# cfn-lint runs on its own (not piped) so a lint failure stops the script
.venv/Scripts/cfn-lint template.yaml
echo "cfn-lint OK"

# Templates over 51,200 bytes must be staged in S3: bootstrap stack with the staging bucket
BOOTSTRAP_STACK="$STACK_NAME-deploy-bucket"
if ! aws cloudformation describe-stacks --stack-name "$BOOTSTRAP_STACK" >/dev/null 2>&1; then
  .venv/Scripts/cfn-lint infra/deploy-bucket.yaml
  aws cloudformation deploy --stack-name "$BOOTSTRAP_STACK" --template-file infra/deploy-bucket.yaml \
    --tags project=containerized-microservices --no-fail-on-empty-changeset
fi
TEMPLATE_BUCKET=$(aws cloudformation describe-stacks --stack-name "$BOOTSTRAP_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='TemplateBucketName'].OutputValue" --output text | tr -d '\r')

args=(--stack-name "$STACK_NAME" --template-file template.yaml
      --s3-bucket "$TEMPLATE_BUCKET" --s3-prefix templates
      --capabilities CAPABILITY_NAMED_IAM
      --tags project=containerized-microservices
      --no-fail-on-empty-changeset)
# (Exercises 3-8 generated the DB password into ~/.containerized-microservices.env and passed it
# as a parameter. Since exercise 9 Secrets Manager generates it; no secret passes through here.)
if [[ $# -gt 0 ]]; then
  args+=(--parameter-overrides "$@")
fi
aws cloudformation deploy "${args[@]}"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].[StackStatus, Outputs[].[OutputKey, OutputValue]]' --output text | tr -d '\r'
