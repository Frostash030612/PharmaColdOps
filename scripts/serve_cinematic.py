"""Stage only public animation dependencies and scoped project geography.

Loopback-only rendering server. Authenticated uploads can write only 15 fixed,
fresh part-NN.mp4 slots in this new directory. No app database or API is used.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil

ROOT=Path(__file__).resolve().parents[1]


def upload_target(output,value):
    part=int(value)
    if part not in range(15):raise ValueError('part outside fixed render slots')
    return output/f'part-{part:02}.mp4'


def stage(output,tools,coastline):
    if output.exists()or not output.resolve().is_relative_to(ROOT/'data/processed'):
        raise ValueError('fresh output under data/processed required')
    output.mkdir(parents=True)
    for name in ['index.html','film.mjs','story.mjs']:
        shutil.copyfile(ROOT/'media/cinematic'/name,output/name)
    vendor=output/'vendor';vendor.mkdir()
    for name in ['three.module.js','three.core.js']:
        shutil.copyfile(tools/'node_modules/three/build'/name,vendor/name)
    shutil.copytree(tools/'node_modules/three/examples/jsm',vendor/'addons')
    shutil.copyfile(tools/'node_modules/mp4-muxer/build/mp4-muxer.mjs',vendor/'mp4-muxer.mjs')
    shutil.copyfile(tools/'node_modules/three/LICENSE',vendor/'THREE-LICENSE.txt')
    shutil.copyfile(tools/'node_modules/mp4-muxer/LICENSE',vendor/'MP4-MUXER-LICENSE.txt')
    source=json.loads((ROOT/'frontend-vue/src/data/singaporeRoutes.json').read_text())
    network=json.loads((ROOT/'data/optimisation/singapore/network.json').read_text())
    roads=[]
    for key,coords in network['leg_geometry'].items():
        a,b=map(int,key.split(':'))
        if a==0 or (a<b and a%4==0):
            step=max(1,len(coords)//75);roads.append(coords[::step]+[coords[-1]])
    routes=[f['geometry']['coordinates'] for f in source['plans']['ortools']['geojson']['features'] if f['geometry']['type']=='LineString']
    data={'nodes':[{k:n[k]for k in ['facility_id','name','role','lat','lon']}for n in source['nodes']],
          'roads':roads,'routes':[r[::max(1,len(r)//180)]+[r[-1]]for r in routes],
          'scope':'Real project facility coordinates and cached road paths; procedural buildings and operations are illustrative.',
          'attribution':'OpenStreetMap contributors','license_url':'https://www.openstreetmap.org/copyright'}
    countries=json.loads(coastline.read_text())
    singapore=next(f for f in countries['features']if f['properties'].get('ADM0_A3')=='SGP')
    data['land']=singapore['geometry']
    data['land_source']='Natural Earth 1:10m admin-0 countries, public domain'
    data['land_source_url']='https://github.com/nvkelso/natural-earth-vector'
    (output/'geography.mjs').write_text('export const GEO='+json.dumps(data,separators=(',',':'))+';\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--tools',type=Path,required=True)
    p.add_argument('--port',type=int,default=8770);p.add_argument('--coastline',type=Path,default=ROOT/'media/cinematic/assets/singapore-outline.geojson');args=p.parse_args()
    output=args.output.resolve();stage(output,args.tools.resolve(),args.coastline.resolve());token=secrets.token_hex(24)
    (output/'render-session.json').write_text(json.dumps({'token':token,'upload':'/upload','scope':'this recording stage only'}))
    class Handler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Cache-Control','no-store');super().end_headers()
        def do_POST(self):
            if self.path!='/upload'or self.headers.get('X-Render-Session')!=token:
                self.send_error(403);return
            count=int(self.headers.get('Content-Length','0'))
            try:
                part=int(self.headers.get('X-Render-Part','-1'))
                target=upload_target(output,part)
            except (ValueError,TypeError):self.send_error(400);return
            if not 1024<count<400_000_000 or target.exists():self.send_error(409);return
            payload=self.rfile.read(count)
            if len(payload)!=count or payload[4:8]!=b'ftyp':
                (output/f'upload-error-{part:02}.json').write_text(json.dumps({'expected_bytes':count,'received_bytes':len(payload),'prefix_hex':payload[:24].hex()}))
                self.send_error(400);return
            with target.open('xb')as stream:stream.write(payload)
            self.send_response(201);self.end_headers();self.wfile.write(b'{"saved":true}')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(output)))
    print(json.dumps({'url':f'http://127.0.0.1:{args.port}','stage':str(output),'upload_scope':'15 fresh stage/part-NN.mp4 slots only'}),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
