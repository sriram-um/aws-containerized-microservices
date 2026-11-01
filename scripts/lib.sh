# Shared settings for the scripts in this folder. Source it: `. "$(dirname "$0")/lib.sh"`
set -euo pipefail

# The shell has AWS_PROFILE=claude-bedrock (a different account). Every resource of this project
# is deployed by IAM user "sriram" in account 977534234172 via the "default" profile.
export AWS_PROFILE=default
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
EXPECTED_ACCOUNT=977534234172
EXPECTED_ARN="arn:aws:iam::977534234172:user/sriram"
STACK_NAME=containerized-microservices
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Abort unless the credentials belong to the expected account and user
check_identity() {
  local arn
  arn=$(aws sts get-caller-identity --query Arn --output text | tr -d '\r')
  if [[ "$arn" != "$EXPECTED_ARN" ]]; then
    echo "ERROR: AWS identity is '$arn', expected '$EXPECTED_ARN'. Aborting." >&2
    exit 1
  fi
  echo "AWS identity OK: $arn (region $AWS_REGION)"
}

stack_output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text | tr -d '\r'
}
