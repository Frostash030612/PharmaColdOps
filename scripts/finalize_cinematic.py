"""Verify 15 real 3D video segments, join them, add original sound and package.

The six story intervals remain exactly 0/15/35/75/95/115/150 seconds.
Only fresh data/processed outputs are allowed. No application service is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave
from zipfile import ZipFile,ZIP_DEFLATED

from build_demo_videos import inspect_video

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb')as stream:
        while block:=stream.read(1024*1024):digest.update(block)
    return digest.hexdigest()


def stamp(value):
    ms=round(value*1000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
    return f'00:{minutes:02}:{seconds:02},{ms:03}'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['stage','score','ffmpeg','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--node',default='node');args=p.parse_args()
    output=args.output.resolve()
    if output.exists()or not output.is_relative_to(ROOT/'data/processed'):p.error('fresh output under data/processed required')
    stage=args.stage.resolve();ffmpeg=str(args.ffmpeg.resolve())
    for name in ['film.mjs','story.mjs','index.html']:
        if sha(stage/name)!=sha(ROOT/'media/cinematic'/name):p.error('staged source differs from repository: '+name)
    story=json.loads(subprocess.check_output([args.node,'--input-type=module','-e','import {FILM} from "./media/cinematic/story.mjs";console.log(JSON.stringify(FILM));'],cwd=ROOT,text=True))
    if [(s['start'],s['end'])for s in story['scenes']]!=[(0,15),(15,35),(35,75),(75,95),(95,115),(115,150)]:p.error('storyboard timings changed')
    parts=[stage/f'part-{i:02}.mp4'for i in range(15)]
    source=[]
    for part in parts:
        check=inspect_video(args.ffmpeg,part)
        if abs(check['seconds']-10)>.02 or check['audio_present']or '1920x1080'not in check['probe']or '30 fps'not in check['probe']:
            p.error('invalid segment: '+part.name)
        source.append({'file':part.name,'sha256':sha(part),'seconds':check['seconds']})
    with wave.open(str(args.score),'rb')as sound:
        if abs(sound.getnframes()/sound.getframerate()-150)>.01 or sound.getnchannels()!=2:p.error('150-second stereo score required')
    output.mkdir(parents=True);delivery=output/'delivery';delivery.mkdir()
    concat=output/'concat.txt';concat.write_text('\n'.join("file '"+str(p)+"'"for p in parts)+'\n')
    chapters=';FFMETADATA1\ntitle=PharmaColdOps - Cinematic concept film\n'
    srt='';index=1
    for scene in story['scenes']:
        chapters+=f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={scene['start']*1000}\nEND={scene['end']*1000}\ntitle={scene['part']} - {scene['id']}\n"
        step=(scene['end']-scene['start'])/len(scene['notes'])
        for i,note in enumerate(scene['notes']):
            srt+=f"{index}\n{stamp(scene['start']+i*step)} --> {stamp(scene['start']+(i+1)*step-.04)}\n{note}\n\n";index+=1
    chapter_file=output/'chapters.ffmeta';chapter_file.write_text(chapters)
    silent=output/'joined-silent.mp4'
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','warning','-n','-f','concat','-safe','0','-i',str(concat),'-c:v','copy','-an','-movflags','+faststart',str(silent)],check=True)
    final=delivery/'PharmaColdOps-Cinematic-Concept-Film-English.mp4'
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','warning','-n','-i',str(silent),'-i',str(args.score),'-f','ffmetadata','-i',str(chapter_file),
        '-map','0:v:0','-map','1:a:0','-map_metadata','2','-map_chapters','2','-c:v','copy','-c:a','aac','-b:a','192k','-t','150','-movflags','+faststart',str(final)],check=True)
    info=inspect_video(args.ffmpeg,final)
    if abs(info['seconds']-150)>.04 or not info['audio_present']or '30 fps'not in info['probe']:raise ValueError('final media timing/tracks mismatch')
    decode=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','error','-i',str(final),'-map','0:v:0','-map','0:a:0','-progress','pipe:1','-f','null','-'],capture_output=True,text=True)
    frames=int(re.findall(r'^frame=(\d+)',decode.stdout,re.M)[-1])
    if decode.returncode or decode.stderr.strip()or frames!=4500:raise ValueError('decode errors or wrong complete frame count: '+decode.stderr)
    volume=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-i',str(final),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
    peak=float(re.search(r'max_volume: ([\-\d.]+) dB',volume.stderr)[1])
    if not -25<peak<-6:raise ValueError('unexpected sound-design peak')
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','error','-n','-ss','85','-i',str(final),'-frames:v','1',str(delivery/'Poster.png')],check=True)
    (delivery/'English-On-Screen-Notes.srt').write_text(srt,encoding='utf-8')
    (delivery/'Storyboard.en.json').write_text(json.dumps(story,indent=2),encoding='utf-8')
    readme='''# PharmaColdOps - Cinematic concept film

150 seconds, 1920x1080, 30fps. All visible wording and on-screen notes are English.
Original procedural instrumental music, rain/energy textures and transition
sound design are included. There is no speech, TTS, voice clone or sampled song.
Kling and other video-generation models were not used.

Six intervals follow the supplied storyboard exactly:
00:00-00:15 valve warning and warehouse pullback
00:15-00:35 server/data flyby and sparks
00:35-01:15 rainy digital city and vehicle plunge/tracking
01:15-01:35 metallic core and cyan ignition
01:35-01:55 expanding node network
01:55-02:30 Singapore map, route reveals and 180-degree camera orbit

All geometry, lighting, cameras, reflection, bloom and directional/radial blur
are procedural Three.js/WebGL rendering, not real camera footage. The 8K RED
phrase was a visual reference, NOT an actual capture or delivery specification.
No Apple/RED affiliation, product, logo or endorsement is represented.

This is a stylised concept film, not actual infrastructure failure, live weather,
a real fleet, a live solver replay, a surveyed 3D digital twin, clinical validation
or medicine authorisation. Project facility coordinates and cached roads were
used; buildings, vehicle, valve, infrastructure and operations are illustrative.
The country outline is generalized Natural Earth admin-0 geography, not a current
surveyed shoreline. Models remain advisory and humans retain responsibility.

Map attribution: OpenStreetMap contributors, https://www.openstreetmap.org/copyright
Country outline: Natural Earth (public domain), https://github.com/nvkelso/natural-earth-vector
Renderer: Three.js r180 (MIT). MP4 creation tool: mp4-muxer 5.2.2 (MIT).

The SRT is on-screen explanation, not an authentic spoken transcript. This new
2:30 film does not replace the course's two 5-minute human-presented submissions.
Rapid camera moves and localized light pulses are present. No high-frequency
full-screen flashing sequence was added.

The final file fully decoded 4,500 frames and its audio without errors.
Frame/colour appearance can vary by GPU and display; no byte-identical
cross-device reproduction or live-business performance is claimed.
Share this clean delivery folder or ZIP, not the raw rendering stage or tokens.
Earlier videos were retained as separate versions.
'''
    (delivery/'README.md').write_text(readme,encoding='utf-8')
    report={'schema':'pharmacoldops-cinematic-delivery-v1','seconds':150,'width':1920,'height':1080,'fps':30,'frames':frames,
        'language':'en','audio':'original procedural instrumental and sound design, no spoken narration','peak_dbfs':peak,
        'complete_decode_errors':0,'kling_used':False,'video_generation_model_used':False,'real_camera_footage':False,
        'submission_ready':False,'source_application_commit':story['sourceApplicationCommit'],'segments':source,
        'source_sha256':{name:sha(ROOT/'media/cinematic'/name)for name in ['film.mjs','story.mjs','index.html']},
        'geography_sha256':sha(stage/'geography.mjs'),'country_outline_sha256':sha(ROOT/'media/cinematic/assets/singapore-outline.geojson'),
        'sha256':{f.name:sha(f)for f in sorted(delivery.iterdir())}}
    (delivery/'manifest.json').write_text(json.dumps(report,indent=2))
    archive=output/'PharmaColdOps-English-Cinematic-Film.zip'
    with ZipFile(archive,'x',ZIP_DEFLATED,compresslevel=1)as bundle:
        for file in sorted(delivery.iterdir()):bundle.write(file,'PharmaColdOps-English-Cinematic-Film/'+file.name)
    with ZipFile(archive)as bundle:
        if bundle.testzip()is not None:raise ValueError('archive failed integrity check')
    print(json.dumps({'status':'complete_decode_checked_and_packaged','video':str(final),'zip':str(archive),'seconds':150,'frames':frames,'peak_dbfs':peak}))


if __name__=='__main__':main()
