#!/bin/bash
# Bee cam -> YouTube Live. Run by systemd (pvf-restream.service); restarts on exit.
set -u
D=/opt/pvf-stream
source "$D/stream.env"; [ -f "$D/linux.env" ] && source "$D/linux.env"
: "${RTSPS_URL:?}" "${YT_STREAM_KEY:?}"
FPS="${FPS:-30}"; SCALE="${SCALE:-1920:1080}"; VB="${VIDEO_BITRATE:-6000k}"
W="${SCALE%:*}"; H="${SCALE#*:}"
YT_INGEST="${YT_INGEST:-rtmps://a.rtmps.youtube.com:443/live2}"

AMAP="1:a:0"; AF="anull"
if [ "${AUDIO:-silent}" = "camera" ]; then
  AMAP="0:a:0"
  AF="aresample=async=1000:first_pts=0,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,highpass=f=${AUDIO_HIGHPASS:-200}:poles=2,afftdn=nr=${AUDIO_DENOISE:-10}:nf=-50:tn=1,lowpass=f=7800,volume=${AUDIO_GAIN:-1.0},alimiter=limit=0.9:level=disabled"
fi

if [ "${LINUX_ENCODER:-vaapi}" = "vaapi" ]; then
  HW=(-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi)
  VOPTS=(-vf "fps=$FPS,scale_vaapi=w=$W:h=$H:format=nv12" -c:v h264_vaapi -low_power "${VAAPI_LOW_POWER:-0}" -profile:v high -rc_mode CBR
         -b:v "$VB" -maxrate "$VB" -bufsize "$((${VB%k} * 2))k" -g "$((FPS * 2))")
else
  HW=()
  VOPTS=(-vf "fps=$FPS,scale=$W:$H,format=yuv420p" -c:v libx264 -preset veryfast
         -b:v "$VB" -maxrate "$VB" -bufsize "$((${VB%k} * 2))k" -g "$((FPS * 2))" -keyint_min "$((FPS * 2))")
fi

echo "$(date '+%F %T') starting restream (encoder=${LINUX_ENCODER:-vaapi} ${W}x${H}@${FPS} ${VB} audio=${AUDIO:-silent})"
exec ffmpeg -hide_banner -loglevel error -nostdin "${HW[@]}" \
  -rtsp_transport tcp -timeout 10000000 -use_wallclock_as_timestamps 1 -fflags +genpts+discardcorrupt \
  -i "$RTSPS_URL" \
  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
  -map 0:v:0 -map "$AMAP" "${VOPTS[@]}" \
  -af "$AF" -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -f flv "$YT_INGEST/$YT_STREAM_KEY"
