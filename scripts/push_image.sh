#!/usr/bin/env bash
# Manually build the Product Service image for arm64, tag it with the git SHA and push it to ECR.
# (Exercise 2. From exercise 6 on, CodeBuild does this on every push to main.)
# Usage: scripts/push_image.sh
. "$(dirname "$0")/lib.sh"
check_identity
cd "$REPO_ROOT"

if [[ -n "$(git status --porcelain -- services/product-service)" ]]; then
  echo "ERROR: uncommitted changes in services/product-service; commit first so the tag matches the code." >&2
  exit 1
fi
TAG=$(git rev-parse --short=7 HEAD)
REPO_URI=$(stack_output ProductServiceRepositoryUri)
REGISTRY="${REPO_URI%%/*}"
echo "Image: $REPO_URI:$TAG"

# Tags are immutable: pushing an existing tag again would fail
if aws ecr describe-images --repository-name product-service --image-ids imageTag="$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG already in ECR - nothing to do."
  exit 0
fi

# 1. Authenticate Docker with ECR (token valid for 12 hours)
aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"

# 2. Build for the Graviton (arm64) target. --provenance/--sbom=false: push a single image
#    manifest instead of an index with attestation manifests (which ECR lists as untagged artifacts).
docker buildx build --platform linux/arm64 --provenance=false --sbom=false \
  -t "product-service:$TAG" --load services/product-service

# 3. Tag with the ECR repository URI
docker tag "product-service:$TAG" "$REPO_URI:$TAG"

# 4. Push
docker push "$REPO_URI:$TAG"

aws ecr describe-images --repository-name product-service --image-ids imageTag="$TAG" \
  --query 'imageDetails[0].[imageTags[0], imageSizeInBytes, imagePushedAt, imageManifestMediaType]' --output text
