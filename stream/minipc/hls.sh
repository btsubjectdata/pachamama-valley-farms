#!/bin/bash
# Bee cam (medium 720p stream) -> HLS files for the website's backup player. Run by pvf-hls.service.
set -u
D=/opt/pvf-stream; OUT="$D/hls"
[ -f "$D/linux.env" ] && source "$D/linux.env"
CAM="${HLS_CAMERA_URL:-rtsp://192.168.0.1:7447/EUlrQv8OgAzHpK1h}"
mkdir -p "$OUT"; rm -f "$OUT"/*.ts "$OUT"/*.m3u8
if [ "${LINUX_ENCODER:-vaapi}" = "vaapi" ]; then
  HW=(-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi)
  VOPTS=(-vf "fps=15,scale_vaapi=format=nv12" -c:v h264_vaapi -low_power "${VAAPI_LOW_POWER:-0}" -profile:v main -rc_mode VBR -b:v 2000k -maxrate 2500k -bufsize 4000k -g 30)
else
  HW=()
  VOPTS=(-vf "fps=15,format=yuv420p" -c:v libx264 -preset veryfast -profile:v main -b:v 2000k -maxrate 2500k -bufsize 4000k -g 30 -keyint_min 30)
fi
echo "$(date '+%F %T') starting hls"
exec ffmpeg -hide_banner -loglevel error -nostdin "${HW[@]}" \
  -rtsp_transport tcp -timeout 10000000 -fflags +genpts+discardcorrupt \
  -i "$CAM" -an "${VOPTS[@]}" \
  -f hls -hls_time 2 -hls_list_size 6 \
  -hls_flags delete_segments+independent_segments+omit_endlist+temp_file \
  -hls_segment_filename "$OUT/bees_%06d.ts" "$OUT/bees.m3u8"
