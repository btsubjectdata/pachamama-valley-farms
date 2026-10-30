#!/bin/bash
# Bee cam (4K High stream) -> adaptive HLS for the website: 1080p30 + 720p30, with the filtered camera mic.
# Run by pvf-hls.service. Encodes on the Intel GPU (VA-API); software fallback if LINUX_ENCODER=software.
set -u
D=/opt/pvf-stream; OUT="$D/hls"
source "$D/stream.env"; [ -f "$D/linux.env" ] && source "$D/linux.env"
CAM="${HLS_HIGH_URL:-$RTSPS_URL}"
mkdir -p "$OUT"; rm -f "$OUT"/*.ts "$OUT"/*.m3u8

AF="aresample=async=1000:first_pts=0,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,afftdn=nr=${AUDIO_DENOISE:-10}:nf=-50:tn=1,lowpass=f=7800,volume=${AUDIO_GAIN:-1.0},alimiter=limit=0.9:level=disabled"
LP="${VAAPI_LOW_POWER:-0}"

if [ "${LINUX_ENCODER:-vaapi}" = "vaapi" ]; then
  HW=(-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi)
  FC="[0:v]fps=30,split=2[a][b];[a]scale_vaapi=w=1920:h=1080:format=nv12[v1080];[b]scale_vaapi=w=1280:h=720:format=nv12[v720];[0:a]${AF},asplit=2[a1][a2]"
  ENC=(-c:v h264_vaapi -low_power "$LP" -profile:v high -rc_mode VBR)
else
  HW=()
  FC="[0:v]fps=30,split=2[a][b];[a]scale=1920:1080,format=yuv420p[v1080];[b]scale=1280:720,format=yuv420p[v720];[0:a]${AF},asplit=2[a1][a2]"
  ENC=(-c:v libx264 -preset veryfast -profile:v high)
fi

echo "$(date '+%F %T') starting hls (1080p30 + 720p30, audio)"
exec ffmpeg -hide_banner -loglevel error -nostdin "${HW[@]}" \
  -rtsp_transport tcp -timeout 10000000 -use_wallclock_as_timestamps 1 -fflags +genpts+discardcorrupt \
  -i "$CAM" -filter_complex "$FC" \
  -map "[v1080]" -map "[a1]" -map "[v720]" -map "[a2]" \
  "${ENC[@]}" -g 60 \
  -b:v:0 6000k -maxrate:v:0 6500k -bufsize:v:0 12000k \
  -b:v:1 2500k -maxrate:v:1 2800k -bufsize:v:1 5000k \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -f hls -hls_time 2 -hls_list_size 6 \
  -hls_flags delete_segments+independent_segments+omit_endlist+temp_file \
  -master_pl_name bees.m3u8 -var_stream_map "v:0,a:0,name:1080 v:1,a:1,name:720" \
  -hls_segment_filename "$OUT/bees_%v_%06d.ts" "$OUT/bees_%v.m3u8"
