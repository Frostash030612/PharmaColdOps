"""Original 150-second instrumental/sound-design bed. No voice or samples."""
import argparse
import json
from pathlib import Path
import wave
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('fresh output required')
    sr=44100;duration=150;n=sr*duration;audio=np.zeros((n,2));rng=np.random.default_rng(20261020)
    def add(at,signal,pan=0):
        start=round(at*sr);end=min(n,start+len(signal))
        if start<0 or end<=start:return
        signal=signal[:end-start];audio[start:end,0]+=signal*np.sqrt((1-pan)/2);audio[start:end,1]+=signal*np.sqrt((1+pan)/2)
    def tone(at,length,midi,volume=.025,pan=0):
        t=np.arange(round(length*sr))/sr;freq=440*2**((midi-69)/12)
        env=np.minimum(1,t/.06)*np.minimum(1,(length-t)/.3)*np.exp(-t/(length*.8))
        add(at,(np.sin(2*np.pi*freq*t)+.12*np.sin(2*np.pi*freq*2*t))*env*volume,pan)
    dark=[[38,45,50,53],[34,41,46,50],[36,43,48,51],[33,40,45,48]]
    bright=[[50,57,62,65],[46,53,58,62],[53,60,65,69],[48,55,60,64]]
    for bar in range(50):
        at=bar*3;chord=(dark if at<75 else bright)[(bar//2)%4]
        for i,midi in enumerate(chord):tone(at,4,midi,.021 if at<75 else .027,(i-1.5)*.22)
    for step in range(240):
        at=step*.625;bank=dark if at<75 else bright;chord=bank[(int(at)//6)%4]
        tone(at,.38,chord[step%4]+12,.012 if at<75 else .019,(-.4 if step%2 else .4))
    # Original impacts and sweeps on the actual shot/motion cues.
    for at in [2,6.9,15,35,43.05,75.8,95,115,147]:
        t=np.arange(round(1.7*sr))/sr;phase=2*np.pi*(33*t+65*.1*(1-np.exp(-t/.1)))
        add(at,np.sin(phase)*np.exp(-t*4)*.12)
        noise=rng.normal(size=round(.8*sr));noise=np.convolve(noise,np.ones(17)/17,mode='same')
        env=np.sin(np.linspace(0,np.pi,len(noise)))**2;add(max(0,at-.4),noise*env*.065,.12)
        if at>=75:tone(at,.9,81,.024,.2)
    # Weather/energy noises are synthetic concept sound design, not field recordings.
    storm=rng.normal(size=sr*40);storm=np.convolve(storm,np.ones(11)/11,mode='same');storm*=.015
    fade=np.minimum(1,np.arange(len(storm))/sr)*np.minimum(1,(len(storm)-np.arange(len(storm)))/(sr*2));add(35,storm*fade)
    for i in range(100):
        at=15+rng.uniform(0,20);noise=rng.normal(size=round(.045*sr));env=np.exp(-np.arange(len(noise))/(sr*.009));add(at,noise*env*.012,rng.uniform(-.5,.5))
    allfade=np.minimum(1,np.arange(n)/(sr*2))*np.minimum(1,(n-1-np.arange(n))/(sr*3));audio*=allfade[:,None]
    audio*=10**(-12/20)/max(float(np.max(np.abs(audio))),1e-12)
    pcm=np.round(np.clip(audio,-1,1)*32767).astype('<i2');args.output.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(args.output),'wb')as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())
    print(json.dumps({'seconds':duration,'sample_rate':sr,'channels':2,'peak_dbfs':-12,'voice':False,'samples_or_external_music':False}))


if __name__=='__main__':main()
