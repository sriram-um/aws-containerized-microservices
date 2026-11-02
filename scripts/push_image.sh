#!/usr/bin/env bash
# Manually build a service image for arm64, tag it with the git SHA and push it to ECR.
# (Exercise 2; exercise 12 added the orders service. Since exercise 6 the pipelines do this on
# every push to main - this script is for bootstrapping a new repository or a rebuild.)
# Usage: scripts/push_image.sh [product-service|orders-service]     (default: product-service)
. "$(dirname "$0")/lib.sh"
check_identity
cd "$REPO_ROOT"

SERVICE="${1:-product-service}"
case "$SERVICE" in
  product-service) OUTPUT=ProductServiceRepositoryUri ;;
  orders-service)  OUTPUT=OrdersServiceRepositoryUri ;;
  *) echo "usage: $0 [product-service|orders-service]" >&2; exit 1 ;;
esac

if [[ -n "$(git status --porcelain -- "services/$SERVICE")" ]]; then
  echo "ERROR: uncommitted changes in services/$SERVICE; commit first so the tag matches the code." >&2
  exit 1
fi
TAG=$(git rev-parse --short=7 HEAD)
REPO_URI=$(stack_output "$OUTPUT")
REGISTRY="${REPO_URI%%/*}"
echo "Image: $REPO_URI:$TAG"

# Tags are immutable: pushing an existing tag again would fail
if aws ecr describe-images --repository-name "$SERVICE" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG already in ECR - nothing to do."
  exit 0
fi

# 1. Authenticate Docker with ECR (token valid for 12 hours)
aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"

# 2. Build for the Graviton (arm64) target. --provenance/--sbom=false: push a single image
#    manifest instead of an index with attestation manifests (which ECR lists as untagged artifacts).
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  -t "$SERVICE:$TAG" --load "services/$SERVICE"

# 3. Tag with the ECR repository URI
docker tag "$SERVICE:$TAG" "$REPO_URI:$TAG"

# 4. Push
docker push "$REPO_URI:$TAG"

aws ecr describe-images --repository-name "$SERVICE" --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].[imageTags[0], imageSizeInBytes, imagePushedAt, imageManifestMediaType]' --output text
