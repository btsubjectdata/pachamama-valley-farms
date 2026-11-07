#!/bin/bash
# Camera -> YouTube Live AND the website HLS feed, from ONE decode.  Usage: restream.sh [camera]   (default: bees)
# bees reads /opt/pvf-stream/stream.env; any other camera reads /opt/pvf-stream/cams/<camera>.env
# (which can override audio/size settings; stream.env supplies the defaults). Run by systemd; restarts on exit.
#
# Why one process: the Intel GPU decodes the 4K camera stream once and encodes three outputs from it
# (YouTube + 1080p + 720p). The old layout ran a second ffmpeg (hls.sh) that decoded the same 4K stream again,
# and with two cameras that was four 4K decodes for two 4K encodes - the GPU fell behind and UniFi dropped
# the RTSP session. hls.sh is retired; its playlists (<cam>.m3u8, <cam>_1080.m3u8, <cam>_720.m3u8) come from here.
#
# Settings (stream.env / cams/<cam>.env):
#   FPS=30  SCALE=3840:2160  VIDEO_BITRATE=16000k   YouTube output (SCALE/VIDEO_BITRATE per camera)
#   HLS_RENDITIONS="1080,720" | "720" | "off"        website feed sizes (720 only = less GPU; off = YouTube only)
#   YT_STREAM_KEY=PENDING (or empty)                 skip YouTube, keep the website feed (new camera before watchdog)
set -u
D=/opt/pvf-stream; OUT="$D/hls"; CAM="${1:-bees}"
source "$D/stream.env"; [ -f "$D/linux.env" ] && source "$D/linux.env"
[ "$CAM" = bees ] || source "$D/cams/$CAM.env"
: "${RTSPS_URL:?}"
FPS="${FPS:-30}"; SCALE="${SCALE:-1920:1080}"; VB="${VIDEO_BITRATE:-6000k}"
W="${SCALE%:*}"; H="${SCALE#*:}"
YT_INGEST="${YT_INGEST:-rtmps://a.rtmps.youtube.com:443/live2}"
HLS="${HLS_RENDITIONS:-1080,720}"; LP="${VAAPI_LOW_POWER:-0}"
YT=1; case "${YT_STREAM_KEY:-}" in ""|PENDING) YT=0;; esac
mkdir -p "$OUT"; rm -f "$OUT/${CAM}"*.ts "$OUT/${CAM}"*.m3u8

# ---- audio: camera mic (filtered) or silence ----
ASRC="1:a"; AF="anull"
if [ "${AUDIO:-silent}" = "camera" ]; then
  ASRC="0:a:0"
  AF="aresample=async=1000:first_pts=0,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,afftdn=nr=${AUDIO_DENOISE:-10}:nf=-50:tn=1,lowpass=f=7800,volume=${AUDIO_GAIN:-1.0},alimiter=limit=0.9:level=disabled"
  # AUDIO_FILTER="off" in stream.env = out-of-the-box camera sound (no wind filter, denoise, EQ or gain); only timing resample.
  [ "${AUDIO_FILTER:-on}" = "off" ] && AF="aresample=async=1000:first_pts=0"
fi

# ---- which outputs ----
VOUT=(); NV=0
[ "$YT" = 1 ] && { VOUT+=("yt:$W:$H"); NV=$((NV+1)); }
case "$HLS" in
  off) ;;
  720) VOUT+=("720:1280:720"); NV=$((NV+1));;
  *)   VOUT+=("1080:1920:1080" "720:1280:720"); NV=$((NV+2));;
esac
[ "$NV" = 0 ] && { echo "$(date '+%F %T') $CAM: nothing to do (no YouTube key and HLS off); sleeping"; sleep 300; exit 0; }

# ---- filter graph: decode once, fps once, split, scale per output ----
if [ "${LINUX_ENCODER:-vaapi}" = "vaapi" ]; then
  HW=(-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi)
  SC() { echo "scale_vaapi=w=$1:h=$2:format=nv12"; }
  VCODEC=(-c:v h264_vaapi -low_power "$LP" -profile:v high); YTRC=(-rc_mode CBR); HLSRC=(-rc_mode VBR)
else
  HW=()
  SC() { echo "scale=$1:$2,format=yuv420p"; }
  VCODEC=(-c:v libx264 -preset veryfast -profile:v high); YTRC=(-keyint_min "$((FPS * 2))"); HLSRC=()
fi
FC="[0:v]fps=$FPS,split=$NV"; i=0
for o in "${VOUT[@]}"; do FC="$FC[s$i]"; i=$((i+1)); done
FC="$FC;"; i=0
for o in "${VOUT[@]}"; do IFS=: read -r n w h <<<"$o"; FC="$FC[s$i]$(SC "$w" "$h")[v$n];"; i=$((i+1)); done
FC="$FC[$ASRC]${AF},asplit=$NV"
for o in "${VOUT[@]}"; do FC="$FC[a${o%%:*}]"; done

AENC=(-c:a aac -b:a 128k -ar 44100 -ac 2)
OUTS=()
if [ "$YT" = 1 ]; then
  OUTS+=(-map "[vyt]" -map "[ayt]" "${VCODEC[@]}" "${YTRC[@]}" -b:v "$VB" -maxrate "$VB" -bufsize "$((${VB%k} * 2))k" -g "$((FPS * 2))"
         "${AENC[@]}" -f flv "$YT_INGEST/$YT_STREAM_KEY")
fi
if [ "$HLS" != off ]; then
  if [ "$HLS" = 720 ]; then
    OUTS+=(-map "[v720]" -map "[a720]" "${VCODEC[@]}" "${HLSRC[@]}" -g "$((FPS * 2))"
           -b:v:0 2500k -maxrate:v:0 2800k -bufsize:v:0 5000k "${AENC[@]}"
           -f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+independent_segments+omit_endlist+temp_file
           -master_pl_name "$CAM.m3u8" -var_stream_map "v:0,a:0,name:720"
           -hls_segment_filename "$OUT/${CAM}_%v_%06d.ts" "$OUT/${CAM}_%v.m3u8")
  else
    OUTS+=(-map "[v1080]" -map "[a1080]" -map "[v720]" -map "[a720]" "${VCODEC[@]}" "${HLSRC[@]}" -g "$((FPS * 2))"
           -b:v:0 6000k -maxrate:v:0 6500k -bufsize:v:0 12000k
           -b:v:1 2500k -maxrate:v:1 2800k -bufsize:v:1 5000k "${AENC[@]}"
           -f hls -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+independent_segments+omit_endlist+temp_file
           -master_pl_name "$CAM.m3u8" -var_stream_map "v:0,a:0,name:1080 v:1,a:1,name:720"
           -hls_segment_filename "$OUT/${CAM}_%v_%06d.ts" "$OUT/${CAM}_%v.m3u8")
  fi
fi

echo "$(date '+%F %T') starting $CAM: encoder=${LINUX_ENCODER:-vaapi} lp=$LP youtube=$([ $YT = 1 ] && echo ${W}x${H}@${FPS}/$VB || echo off) hls=$HLS audio=${AUDIO:-silent} filter=${AUDIO_FILTER:-on}"
exec ffmpeg -hide_banner -loglevel error -nostdin "${HW[@]}" \
  -rtsp_transport tcp -timeout 10000000 -use_wallclock_as_timestamps 1 -fflags +genpts+discardcorrupt \
  -i "$RTSPS_URL" \
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
  -shortest -filter_complex "$FC" "${OUTS[@]}"
