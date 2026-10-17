"""Encode two 300-second English VISUAL DRAFTS, never synthesize human speech.

Needs an ffmpeg build with libx264/libass and Pillow for original title cards.
Inputs are real isolated UI recordings and PNG renders of the exact final deck.
Output includes burned on-screen notes, SRT notes, chapters, cue sheets, hashes
and complete decode checks. It is NOT a completed human-narrated submission.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs/video-storyboard-en.json"
FPS = 25
FONT = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def timestamp(seconds, ass=False):
    scale = 100 if ass else 1000
    ticks = round(seconds * scale)
    hours, ticks = divmod(ticks, 3600 * scale)
    minutes, ticks = divmod(ticks, 60 * scale)
    whole, fraction = divmod(ticks, scale)
    return (f"{hours}:{minutes:02}:{whole:02}.{fraction:02}" if ass else
            f"{hours:02}:{minutes:02}:{whole:02},{fraction:03}")


def validate_plan(plan):
    if plan.get("schema") != "pharmacoldops-visual-video-plan-v1":
        raise ValueError("unknown storyboard schema")
    for kind in ("promotion", "system"):
        scenes = plan[kind]
        if sum(s["seconds"] for s in scenes) != 300:
            raise ValueError("each video must have exactly 300 planned seconds")
        if len({s["id"] for s in scenes}) != len(scenes):
            raise ValueError("duplicate scene id")
        for scene in scenes:
            if scene["seconds"] < 1 or not scene["notes"] or any(len(n) > 200 for n in scene["notes"]):
                raise ValueError("invalid scene duration or on-screen notes")
            if sum(key in scene for key in ("slide", "clip", "card")) != 1:
                raise ValueError("each scene needs one visual source")
            if "clip" in scene and (Path(scene["clip"]).name != scene["clip"] or scene["clip"].startswith(".")):
                raise ValueError("unsafe clip filename")
    if [s["slide"] for s in plan["system"]] != list(range(1, 11)):
        raise ValueError("system video must preserve the 10-slide order")


def clip_bounds(scene, duration):
    start = max(0, duration - scene["tail"]) if "tail" in scene else scene.get("trim_start", 0)
    end = min(duration - scene.get("trim_end", 0), start + scene.get("take", duration))
    if start < 0 or end <= start or end > duration:
        raise ValueError("invalid source trim")
    return start, end


def inspect_video(ffmpeg, path):
    result = subprocess.run([str(ffmpeg), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not duration or "Video:" not in result.stderr:
        raise ValueError("unreadable video: " + str(path))
    return {"seconds": int(duration[1])*3600 + int(duration[2])*60 + float(duration[3]),
            "audio_present": bool(re.search(r"Stream .*Audio:", result.stderr)), "probe": result.stderr}


def note_events(scene, offset=0):
    step = scene["seconds"] / len(scene["notes"])
    return [(offset+i*step+.3, offset+(i+1)*step-.2, note) for i, note in enumerate(scene["notes"])]


def write_notes(folder, events, fonts):
    srt = "\n\n".join(f"{i}\n{timestamp(a)} --> {timestamp(b)}\n{n}" for i, (a,b,n) in enumerate(events, 1)) + "\n"
    (folder / "notes.srt").write_text(srt, encoding="utf-8")
    header = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n"
              "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
              "Style: Notes,Arial,32,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,160,160,26,1\n"
              "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    for a,b,n in events:
        wrapped = textwrap.wrap(n, width=92)
        if len(wrapped) > 2:
            raise ValueError("caption would exceed two lines")
        escaped = "\\N".join(wrapped).replace("{", "(").replace("}", ")")
        header += f"Dialogue: 0,{timestamp(a,True)},{timestamp(b,True)},Notes,,0,0,0,,{escaped}\n"
    ass = folder / "notes.ass"
    ass.write_text(header, encoding="utf-8")
    return ass


def card_image(card, path):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (1600, 900), "#063E5F")
    draw = ImageDraw.Draw(im)
    title = ImageFont.truetype(str(BOLD), 64)
    body = ImageFont.truetype(str(FONT), 34)
    y = 135
    for line in textwrap.wrap(card["title"], width=42):
        draw.text((90, y), line, font=title, fill="white"); y += 82
    y += 25
    for line in textwrap.wrap(card["subtitle"], width=66):
        draw.text((90, y), line, font=body, fill="#E7C565"); y += 48
    y = max(440, y+45)
    for line in card["lines"]:
        for wrapped in textwrap.wrap(line, width=70):
            draw.text((90, y), wrapped, font=body, fill="white"); y += 48
        y += 15
    if y > 860:
        raise ValueError("title card text exceeds the frame")
    im.save(path)


def visible_deck_unchanged(source, enhanced):
    ns = {"p":"http://schemas.openxmlformats.org/presentationml/2006/main"}
    with ZipFile(source) as a, ZipFile(enhanced) as b:
        for name in a.namelist():
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                roots = [ET.fromstring(z.read(name)) for z in (a,b)]
                for element in roots:
                    for transition in element.findall("p:transition", ns):
                        element.remove(transition)
                if ET.tostring(roots[0]) != ET.tostring(roots[1]):
                    raise ValueError("visible source slide changed")
            elif name.startswith(("ppt/media/", "ppt/notesSlides/", "ppt/slides/charts/", "ppt/embeddings/")):
                if a.read(name) != b.read(name):
                    raise ValueError("source media, notes or charts changed")


def main():
    global FONT, BOLD
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ffmpeg", type=Path, required=True)
    p.add_argument("--slides", type=Path, required=True)
    p.add_argument("--clips", type=Path, required=True)
    p.add_argument("--capture-manifest", type=Path, required=True)
    p.add_argument("--enhanced-deck", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--kind", choices=["promotion","system"], required=True)
    p.add_argument("--font", type=Path, default=FONT)
    p.add_argument("--bold-font", type=Path, default=BOLD)
    args = p.parse_args()
    FONT, BOLD = args.font.resolve(), args.bold_font.resolve()
    if not FONT.is_file() or not BOLD.is_file():
        p.error("provide readable font and bold-font files")
    if args.output.exists():
        p.error("fresh output required")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "data/processed"):
        p.error("generated videos must stay in an ignored data/processed directory")
    ffmpeg = args.ffmpeg.resolve()
    plan = json.loads(PLAN.read_text())
    validate_plan(plan)
    source = ROOT / plan["source_deck"]
    visible_deck_unchanged(source, args.enhanced_deck)
    receipt = json.loads((args.slides / "validation.json").read_text())
    if receipt.get("finalSha256") != sha(source):
        p.error("slide renders must belong to the validated final source deck")
    capture = json.loads(args.capture_manifest.read_text())
    if capture.get("human_voice_present") is not False or capture.get("independent_human_review") is not False:
        p.error("visual-draft scope must be explicit")
    expected = {"generator","parking","urgent","incident","review","delivery","qa","audit","parking-offline"}
    if {s["scene"] for s in capture["scenes"]} != expected or any(s["status"] != "captured" or s.get("page_errors") for s in capture["scenes"]):
        p.error("real UI capture verification is incomplete")
    output.mkdir(parents=True)
    fonts = output / "fonts"; fonts.mkdir()
    # Copy font bytes, not protected system-file flags or metadata.
    shutil.copyfile(FONT, fonts / "Arial.ttf"); shutil.copyfile(BOLD, fonts / "Arial-Bold.ttf")
    report = {"status":"building", "kind":args.kind, "schema":"pharmacoldops-visual-video-v1",
              "submission_ready":False, "human_voice_present":False, "audio_stream_present":False,
              "source_commit":capture["source_commit"], "source_deck_sha256":sha(source),
              "source_deck_visible_content_and_notes_preserved":True, "storyboard_sha256":sha(PLAN),
              "scope":plan["scope"], "scenes":[]}
    try:
        parts, all_notes, elapsed = [], [], 0
        chapters = ";FFMETADATA1\ntitle=PharmaColdOps - visual draft - human voice pending\n"
        for index, scene in enumerate(plan[args.kind], 1):
            work = output / f"scene-{index:02}"; work.mkdir()
            duration = scene["seconds"]
            ass = write_notes(work, note_events(scene), fonts)
            command = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "warning", "-n"]
            bounds = None
            if "slide" in scene:
                asset = args.slides / f"slide-{scene['slide']:02}.png"
                command += ["-loop","1","-framerate",str(FPS),"-i",str(asset.resolve())]
                visual = "setpts=PTS-STARTPTS"
            elif "card" in scene:
                asset = work / "card.png"; card_image(scene["card"], asset)
                command += ["-loop","1","-framerate",str(FPS),"-i",str(asset)]
                visual = "setpts=PTS-STARTPTS"
            else:
                asset = args.clips / scene["clip"]
                metadata = inspect_video(ffmpeg, asset)
                if metadata["audio_present"]:
                    raise ValueError("unexpected audio in silent capture")
                start, end = clip_bounds(scene, metadata["seconds"])
                bounds = {"start":start,"end":end,"original_duration":metadata["seconds"]}
                command += ["-i",str(asset.resolve())]
                ratio = min(1, duration/(end-start))
                # Remove only the capture tool's grey bottom padding. UI facts
                # and text are never painted over, reconstructed or replaced.
                visual = f"trim=start={start}:end={end},setpts=(PTS-STARTPTS)*{ratio:.9f},crop=1366:680:0:0,fps={FPS},tpad=stop_mode=clone:stop=-1"
            visual += (f",scale=1600:900:force_original_aspect_ratio=decrease:flags=lanczos,pad=1600:900:(ow-iw)/2:(oh-ih)/2:color=white"
                       f",fade=t=in:st=0:d=0.25,fade=t=out:st={duration-.25}:d=0.25"
                       ",pad=1920:1080:160:68:color=0xF7F9FC,drawbox=x=0:y=0:w=iw:h=60:color=0x063E5F:t=fill"
                       ",drawbox=x=0:y=980:w=iw:h=100:color=0x063E5F:t=fill"
                       f",drawtext=fontfile='{FONT}':text='PharmaColdOps  |  {args.kind.upper()}  |  {index:02}':fontcolor=white:fontsize=25:x=50:y=19"
                       f",drawtext=fontfile='{FONT}':text='VISUAL DRAFT - HUMAN VOICE PENDING':fontcolor=0xE7C565:fontsize=22:x=1320:y=20"
                       f",ass=filename='{ass}':fontsdir='{fonts}',fps={FPS},setsar=1,format=yuv420p")
            part = work / "scene.mp4"
            command += ["-vf",visual,"-frames:v",str(duration*FPS),"-an","-c:v","libx264","-preset","veryfast","-crf","21",
                        "-threads","4","-movflags","+faststart",str(part)]
            with (work / "encode.log").open("x") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            part_info = inspect_video(ffmpeg, part)
            if abs(part_info["seconds"]-duration) > .01:
                raise ValueError("scene duration drift: " + scene["id"])
            parts.append(part)
            all_notes.extend(note_events(scene, elapsed))
            chapters += f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={elapsed*1000}\nEND={(elapsed+duration)*1000}\ntitle={scene['id']}\n"
            report["scenes"].append({"id":scene["id"],"seconds":duration,"source_sha256":sha(asset),"source":str(asset),"source_bounds":bounds})
            print(json.dumps({"kind":args.kind,"scene":scene["id"],"seconds":duration,"status":"encoded"}),flush=True)
            elapsed += duration
        (output / "chapters.ffmeta").write_text(chapters)
        concat = output / "concat.txt"
        concat.write_text("\n".join("file '"+str(part)+"'" for part in parts)+"\n")
        final = output / f"PharmaColdOps-{args.kind}-visual-draft.mp4"
        subprocess.run([str(ffmpeg),"-nostdin","-hide_banner","-loglevel","warning","-n","-f","concat","-safe","0","-i",str(concat),
                        "-f","ffmetadata","-i",str(output/"chapters.ffmeta"),"-map","0:v:0","-c:v","copy","-map_metadata","1",
                        "-map_chapters","1","-an","-movflags","+faststart",str(final)],check=True)
        write_notes(output, all_notes, fonts)
        with (output / "voice-cues.csv").open("x", newline="") as stream:
            writer = csv.writer(stream);writer.writerow(["start","end","on_screen_note_not_a_speech_script"])
            writer.writerows((timestamp(a),timestamp(b),note) for a,b,note in all_notes)
        metadata = inspect_video(ffmpeg, final)
        if abs(metadata["seconds"]-300) > .08 or metadata["audio_present"] or "1920x1080" not in metadata["probe"]:
            raise ValueError("export duration/resolution/silent scope mismatch")
        with (output / "decode.log").open("x") as log:
            checked = subprocess.run([str(ffmpeg),"-nostdin","-hide_banner","-v","error","-i",str(final),"-map","0:v:0","-f","null","-"],stdout=log,stderr=subprocess.STDOUT)
        if checked.returncode or (output / "decode.log").stat().st_size:
            raise ValueError("complete video decode reported errors")
        report.update(status="encoded_and_fully_decoded",duration_seconds=metadata["seconds"],width=1920,height=1080,fps=FPS,
                      output=str(final),sha256=sha(final),complete_decode_errors=0,
                      visual_review_required=True)
    except BaseException as error:
        report.update(status="failed",error=str(error));raise
    finally:
        (output / "video-report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__ == "__main__":
    main()
