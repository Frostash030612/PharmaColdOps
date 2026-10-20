"""Mux an original instrumental bed, check full decode, and package an explainer.

No speech synthesis, generated footage, application calls or course-submission
claim. The standalone preview inlines only this project's own animation code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import wave
from zipfile import ZipFile, ZIP_DEFLATED

from build_demo_videos import inspect_video

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb')as stream:
        while block:=stream.read(1024*1024):digest.update(block)
    return digest.hexdigest()


def inline_preview():
    folder=ROOT/'media/explainer'
    story=(folder/'story.mjs').read_text(encoding='utf-8')
    scene=(folder/'scene.mjs').read_text(encoding='utf-8')
    html=(folder/'index.html').read_text(encoding='utf-8')
    own_code=re.sub(r'^import[^\n]*\n','',story+'\n'+scene,flags=re.M)
    own_code=re.sub(r'^export ','',own_code,flags=re.M)
    html=re.sub(r'^import[^\n]*\n','',html,flags=re.M)
    return html.replace('<script type="module">','<script type="module">\n'+own_code+'\n',1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--render',type=Path,required=True)
    p.add_argument('--score',type=Path,required=True)
    p.add_argument('--ffmpeg',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    output=args.output.resolve()
    if output.exists()or not output.is_relative_to(ROOT/'data/processed'):
        p.error('fresh output under data/processed required')
    render=json.loads((args.render/'render-report.json').read_text())
    if render['status']!='video_encoded'or render['findings']or render['durationSeconds']!=90 or render['frameCount']!=90*render['fps']:
        p.error('completed, geometry-checked render required')
    silent=args.render/render['video']
    if sha(silent)!=render['videoSha256']:p.error('encoded source changed')
    for name in ['story.mjs','scene.mjs']:
        key='media/explainer/'+name+'Sha256'
        if sha(ROOT/'media/explainer'/name)!=render[key]:p.error('animation source changed after render')
    with wave.open(str(args.score),'rb')as wavefile:
        if wavefile.getnchannels()!=2 or abs(wavefile.getnframes()/wavefile.getframerate()-90)>.01:
            p.error('90-second stereo original score required')
    output.mkdir(parents=True)
    final=output/'PharmaColdOps-Beyond-the-Temperature-Alarm-English.mp4'
    ffmpeg=str(args.ffmpeg.resolve())
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','warning','-n','-i',str(silent),'-i',str(args.score),
        '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','160k','-t','90','-movflags','+faststart',
        '-metadata','title=PharmaColdOps - Beyond the temperature alarm',
        '-metadata','comment=English code-drawn prototype explainer. Original procedural music. No spoken narration.',str(final)],check=True)
    checked=inspect_video(args.ffmpeg,final)
    if abs(checked['seconds']-90)>.04 or not checked['audio_present']or '1920x1080'not in checked['probe']or f"{render['fps']} fps"not in checked['probe']:
        raise ValueError('final duration, tracks or geometry mismatch')
    decode=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','error','-i',str(final),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True,text=True)
    if decode.returncode or decode.stderr.strip():raise ValueError('complete audio/video decode failed: '+decode.stderr)
    volume=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-i',str(final),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
    peak=float(re.search(r'max_volume: ([\-\d.]+) dB',volume.stderr)[1])
    if not -30<peak<-6:raise ValueError('unexpected audio peak')
    subprocess.run([ffmpeg,'-nostdin','-hide_banner','-v','error','-n','-ss','5','-i',str(final),'-frames:v','1',str(output/'Poster.png')],check=True)
    shutil.copyfile(args.render/'English-On-Screen-Notes.srt',output/'English-On-Screen-Notes.srt')
    (output/'Interactive-Preview.html').write_text(inline_preview(),encoding='utf-8')
    readme='''# Beyond the temperature alarm - PharmaColdOps

90 seconds / 1920x1080 / 60fps / English screen text and on-screen notes.
The MP4 contains an original, quiet, procedurally synthesized instrumental
bed and transition tones. It has NO spoken narration, TTS or cloned voice.
No Kling or other video generation model was used.

This is a code-drawn educational illustration, not a live system recording,
an actual human review, a solver replay, GPS data or medicine authorisation.
The English SRT is on-screen explanation, not an authentic speech transcript.
The prototype's engineering thresholds are not clinical stability evidence.

The observation uses constant simulated intervals: 5 C for 15 min, 20 C for
90 min, then 5 C for 15 min. The hot-window MKT is 20.0 C. The illustrated
prototype Rule 3 matches the repository implementation. A separate diagram
shows original advice, a review record and effective outcome, not a signed
review by any named person. Routing sketches are explicitly schematic.

165.26 -> 137.85 km compares three vehicles against three on one frozen
Singapore static instance. 16.59% is not measured operating savings.
The graph answers concern original case evidence; human outcomes stay in
separate review history. Clinical validity and independent QA quality are
not established by this video. Source application snapshot: ff4dcb8.

Open Interactive-Preview.html locally to inspect any moment. It contains only
our own drawing code, requires no server or network and does not call the app.
The SRT and poster accompany the video. Keep the previous two five-minute
English visual drafts; this 90-second explainer is a separate new work.

This is not a completed course submission or human-narrated presentation.
Genuine human speech and a full team review remain necessary where required.
'''
    readme=readme.replace('60fps',str(render['fps'])+'fps')
    (output/'README.md').write_text(readme,encoding='utf-8')
    manifest={'schema':'pharmacoldops-english-code-explainer-delivery-v1','language':'en','duration_seconds':checked['seconds'],
        'width':1920,'height':1080,'fps':render['fps'],'video_frames':render['frameCount'],'spoken_narration':False,
        'audio':'original procedural instrumental score, no voice','peak_dbfs':peak,
        'kling_used':False,'video_generation_model_used':False,'complete_decode_errors':0,
        'geometry_findings':0,'workflow_is_illustrative':True,'source_application_commit':render['sourceApplicationCommit'],
        'submission_ready':False,'human_review_or_clinical_validation_claimed':False,
        'sha256':{f.name:sha(f)for f in sorted(output.iterdir())if f.is_file()}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=output.parent/(output.name+'.zip')
    with ZipFile(archive,'x',ZIP_DEFLATED,compresslevel=1)as bundle:
        for file in sorted(output.iterdir()):bundle.write(file,'PharmaColdOps-English-Explainer/'+file.name)
    with ZipFile(archive)as bundle:
        if bundle.testzip()is not None:raise ValueError('archive verification failed')
    print(json.dumps({'status':'encoded_fully_decoded_and_packaged','video':str(final),'zip':str(archive),
        'seconds':checked['seconds'],'fps':render['fps'],'peak_dbfs':peak,'files':len(list(output.iterdir()))}))


if __name__=='__main__':main()
