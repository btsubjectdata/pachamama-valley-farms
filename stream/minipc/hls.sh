#!/bin/bash
# RETIRED (Nov 7, 2026). The website HLS feed is now produced by restream.sh in the same ffmpeg process as the
# YouTube stream, so the GPU decodes each camera once. Keeping this file so old pvf-hls units exit cleanly;
# update.sh disables them. Set HLS_RENDITIONS in stream.env / cams/<cam>.env to change the website feed.
echo "$(date '+%F %T') hls.sh is retired; restream.sh now writes the HLS feed. Disabling this unit."
exit 0
