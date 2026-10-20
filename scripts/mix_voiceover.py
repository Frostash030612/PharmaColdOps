"""Lay a human voice-over onto a rendered keynote video, ducking the music bed.

The narrator records the whole video in one take while watching it, often with a
few seconds of sync noise first. ``--offset`` is the time in the recording that
corresponds to video 0:00; everything before it is dropped and the rest keeps the
narrator's own timing. The video stream is copied, never re-encoded.

    python scripts/mix_voiceover.py --video promo.mp4 --voice take.m4a --offset 4.6 \
        --out promo-voiced.mp4 [--plot alignment.png --scenes 7,15,27]
"""
import argparse
import subprocess
from pathlib import Path


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def media_seconds(ffmpeg, path):
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    h, m, s = info.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def speech_spans(ffmpeg, path, offset, threshold_db=-38, min_gap=0.6):
    """(start, end) of voiced stretches on the video timeline, from silencedetect."""
    log = subprocess.run([ffmpeg, "-hide_banner", "-ss", f"{offset:.3f}", "-i", str(path), "-af",
                          f"silencedetect=n={threshold_db}dB:d={min_gap}", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    starts = [float(l.split("silence_start: ")[1].split()[0]) for l in log.splitlines() if "silence_start" in l]
    ends = [float(l.split("silence_end: ")[1].split()[0]) for l in log.splitlines() if "silence_end" in l]
    total = media_seconds(ffmpeg, path) - offset
    edges = sorted([(s, "s") for s in starts] + [(e, "e") for e in ends])
    spans, cur = [], 0.0
    for t, kind in edges:
        if kind == "s":
            if t - cur > 0.05:
                spans.append((cur, t))
        else:
            cur = t
    if edges and edges[-1][1] == "e" and total - cur > 0.05:
        spans.append((cur, total))
    return spans


def plot(spans, scenes, total, path):
    from PIL import Image, ImageDraw, ImageFont
    w, h, rows = 1800, 140, 5
    per = total / rows
    img = Image.new("RGB", (w + 80, h * rows + 20), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.load_default()
    for r in range(rows):
        y0, t0 = 10 + r * h, r * per
        x = lambda t: 60 + (t - t0) / per * w
        d.rectangle((60, y0 + 40, 60 + w, y0 + 90), outline=(200, 200, 200))
        for a, b in spans:
            if b > t0 and a < t0 + per:
                d.rectangle((x(max(a, t0)), y0 + 45, x(min(b, t0 + per)), y0 + 85), fill=(40, 120, 220))
        for s in scenes:
            if t0 <= s <= t0 + per:
                d.line((x(s), y0 + 25, x(s), y0 + 100), fill=(230, 60, 40), width=2)
                d.text((x(s) + 3, y0 + 22), f"{int(s // 60)}:{s % 60:04.1f}", fill=(230, 60, 40), font=f)
        d.text((4, y0 + 58), f"{int(t0 // 60)}:{t0 % 60:02.0f}", fill="black", font=f)
    img.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--voice", type=Path, required=True)
    ap.add_argument("--offset", type=float, required=True, help="seconds in the recording that align with video 0:00")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--music-gain", type=float, default=0.45, help="music bed level before ducking")
    ap.add_argument("--pad-end", type=float, default=0.0,
                    help="add this many seconds of black at the end (re-encodes video) when speech runs long")
    ap.add_argument("--plot", type=Path, help="write a speech-vs-scene alignment PNG and stop")
    ap.add_argument("--scenes", default="", help="comma-separated scene start times for --plot")
    args = ap.parse_args()
    ffmpeg = ffmpeg_exe()
    video_len = media_seconds(ffmpeg, args.video)
    if args.plot:
        spans = speech_spans(ffmpeg, args.voice, args.offset)
        scenes = [float(s) for s in args.scenes.split(",") if s]
        plot(spans, scenes, video_len, args.plot)
        late = [(a, b) for a, b in spans if b > video_len]
        print(f"{len(spans)} speech spans; voice ends at {spans[-1][1]:.2f}s, video {video_len:.2f}s"
              + (f"; {len(late)} span(s) run past the end" if late else ""))
        return
    total = video_len + args.pad_end
    video_map, video_codec = ["-map", "0:v"], ["-c:v", "copy"]
    if args.pad_end > 0:
        video_map = ["-map", "[v]"]
        video_codec = ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p"]
    graph = (f"[1:a]atrim=start={args.offset:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
             "aformat=channel_layouts=mono,highpass=f=80,"
             "acompressor=threshold=0.1:ratio=3:attack=10:release=200:makeup=2,"
             "aformat=channel_layouts=stereo,asplit=2[vkey][vmix];"
             f"[0:a]aresample=48000,volume={args.music_gain}[bed];"
             "[bed][vkey]sidechaincompress=threshold=0.02:ratio=8:attack=40:release=600[duck];"
             f"[duck]apad=whole_dur={total:.3f}[duckpad];"
             "[duckpad][vmix]amix=inputs=2:normalize=0:duration=first,"
             "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    if args.pad_end > 0:
        graph += f";[0:v]tpad=stop_mode=add:stop_duration={args.pad_end:.3f}:color=black[v]"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(args.video), "-i", str(args.voice),
                    "-filter_complex", graph, *video_map, "-map", "[a]", *video_codec, "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.3f}", str(args.out)], check=True)
    print("mixed:", args.out)


if __name__ == "__main__":
    main()
