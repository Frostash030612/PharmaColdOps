"""Original procedural instrumental bed for the 90-second explainer. No voices.

Uses only sine/triangle oscillators, envelopes and seeded filtered noise.
No external recording, copyrighted track, TTS, voice clone or generation API.
"""
import argparse
import json
from pathlib import Path
import wave

import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('fresh output required')
    sr=44100;seconds=90;audio=np.zeros((sr*seconds,2),dtype=np.float64);rng=np.random.default_rng(41)
    def tone(at,duration,midi,volume=.035,pan=0):
        start=round(at*sr);count=min(round(duration*sr),len(audio)-start)
        if start<0 or count<=0:return
        t=np.arange(count)/sr;freq=440*2**((midi-69)/12)
        attack=np.minimum(1,t/.025);release=np.minimum(1,(duration-t)/.12)
        env=attack*np.maximum(0,release)*np.exp(-t/(duration*.6))
        # Soft additive spectrum, not a sampled or imitated instrument.
        signal=(np.sin(2*np.pi*freq*t)+.16*np.sin(2*np.pi*freq*2*t)+.05*np.sin(2*np.pi*freq*3*t))*env*volume
        audio[start:start+count,0]+=signal*np.sqrt((1-pan)/2)
        audio[start:start+count,1]+=signal*np.sqrt((1+pan)/2)
    chords=[[50,57,62,65],[46,53,58,62],[53,60,65,69],[48,55,60,64]]
    # A slow harmonic bed plus a restrained original repeating pulse.
    for bar in range(30):
        chord=chords[(bar//2)%4]
        for midi in chord:tone(bar*3,3.8,midi,.016,(-.25 if midi%2 else .25))
    for step in range(144):
        at=step*.625;chord=chords[(step//8)%4]
        tone(at,.47,chord[step%4]+12,.019,(-.4 if step%2 else .4))
        if step%4==0:tone(at,.35,26,.029,0)
    for at in [6,18,30,40,54,62,72,82]:
        n=round(.55*sr);noise=rng.normal(0,1,n);smooth=np.convolve(noise,np.ones(35)/35,mode='same')
        env=np.sin(np.linspace(0,np.pi,n))**2;signal=smooth*env*.035;start=round((at-.3)*sr)
        audio[start:start+n,0]+=signal;audio[start:start+n,1]+=signal[::-1]
        tone(at,.85,81,.015,.1)
    fade=np.minimum(1,np.arange(len(audio))/(sr*2.5))*np.minimum(1,(len(audio)-1-np.arange(len(audio)))/(sr*3))
    audio*=fade[:,None]
    peak=float(np.max(np.abs(audio)));target=10**(-15/20)
    audio*=target/max(peak,1e-12)
    pcm=np.round(np.clip(audio,-1,1)*32767).astype('<i2')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(args.output),'wb')as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())
    print(json.dumps({'duration_seconds':seconds,'sample_rate':sr,'channels':2,'peak_dbfs':-15,'spoken_voice':False,'method':'original procedural synthesis'}))


if __name__=='__main__':main()
