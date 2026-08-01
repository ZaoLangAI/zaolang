#!/bin/sh
# Provisions the media bucket. Private by default: every object is served through
# the API with a short-lived signed URL, never a permanent public link.
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing "local/$MEDIA_BUCKET"
mc anonymous set none "local/$MEDIA_BUCKET"

# Uploads that are presigned but never completed become orphans; expire them so
# local storage does not grow without bound.
mc ilm rule add --expire-days 7 --prefix "staging/" "local/$MEDIA_BUCKET" 2>/dev/null || true

echo "minio-init: bucket $MEDIA_BUCKET ready"
