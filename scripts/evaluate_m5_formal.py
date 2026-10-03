"""Fresh, checkpointed, raw VRPTW comparisons; no dispatch or inventory writes.

Static six Solomon instances plus Singapore road matrix. User-selected budgets
are per call; clocks use monotonic wall measurement. No invented runtime/gap.
"""
import argparse
from dataclasses import asdict
import csv
import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/processed/.mpl-cache'))
os.environ.setdefault('MPLBACKEND','Agg')
from optimisation.greedy import solve_greedy
from optimisation.ortools_solver import solve_ortools
from optimisation.ga_solver import solve_ga
from optimisation.solomon_loader import load_dir
from optimisation.singapore_loader import load_singapore_instance
from optimisation.routing import euclidean_leg,evaluate_route,build_result
from run_routing_baselines import REFERENCE,REFERENCE_URL,ORTOOLS_FIRST_SOLUTION


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_result(instance,result,leg_fn=euclidean_leg):
    routes=[];seen=[]
    for r in result.routes:
        seen.extend(r.customer_ids)
        routes.append(evaluate_route(instance,r.customer_ids,vehicle_id=r.vehicle_id,leg_fn=leg_fn))
    if len(seen)!=len(set(seen)):raise ValueError('customer repeated across vehicles')
    rebuilt=build_result(instance,result.algorithm,routes)
    for key in asdict(rebuilt.metrics):
        a,b=getattr(rebuilt.metrics,key),getattr(result.metrics,key)
        if isinstance(a,float):
            if not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7):raise ValueError('reported metric drift: '+key)
        elif a!=b:raise ValueError('reported metric drift: '+key)
    return rebuilt


def row_for(instance,result,seconds,budget,seed):
    m=result.metrics
    hard=sum(getattr(m,k)for k in ['time_window_violations','capacity_violations','depot_return_violations','vehicle_limit_violations','mileage_violations','pairing_violations'])
    complete=m.served_customers==instance.n_customers and not m.unserved_customer_ids and hard==0
    ref=REFERENCE.get(instance.instance.lower())
    same_fleet=bool(complete and ref and m.vehicles_used==ref[0])
    return {'instance':instance.instance,'algorithm':result.algorithm,'budget_seconds':budget,'seed':seed,
        'vehicles':m.vehicles_used,'distance':m.total_distance,'total_duration_minutes':m.total_duration,
        'target':instance.n_customers,'served':m.served_customers,'service_rate':m.served_customers/instance.n_customers,
        'on_time_rate_served':m.on_time_rate,'on_time_rate_all':m.on_time_customers/instance.n_customers,
        'hard_violations':hard,'unserved':len(m.unserved_customer_ids),'complete_feasible':complete,
        'measured_seconds':seconds,'runtime_exceeds_budget':budget is not None and seconds>budget+1,
        'gap_distance_pct':(m.total_distance-ref[1])/ref[1]*100 if same_fleet else None,
        'delta_vehicles':m.vehicles_used-ref[0]if complete and ref else None,
        'reference_scope':'SINTEF BKS, same fleet and complete feasible only' if ref else 'no comparable BKS',
        'distance_unit':'Solomon coordinate units'if ref else 'km on directed Singapore road matrix',
        'metric_reconstruction':'separate shared schedule-evaluator check, not independent optimality certificate'}


def best_rows(rows):
    grouped={}
    for row in rows:grouped.setdefault(row['instance'],[]).append(row)
    return {name:min([r for r in group if r['complete_feasible']],key=lambda r:(r['vehicles'],r['distance']))
            if any(r['complete_feasible']for r in group)else None for name,group in grouped.items()}


def save(output,report):
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if report['rows']:
        with(output/'results.csv').open('w',encoding='utf-8',newline='')as f:
            writer=csv.DictWriter(f,fieldnames=list(report['rows'][0]));writer.writeheader();writer.writerows(report['rows'])


def plots(output,rows):
    import matplotlib.pyplot as plt
    for name in sorted({r['instance']for r in rows}):
        subset=[r for r in rows if r['instance']==name]
        fig,axes=plt.subplots(1,3,figsize=(13,4))
        for algo in sorted({r['algorithm']for r in subset}):
            series=[r for r in subset if r['algorithm']==algo]
            xs=[r['budget_seconds'] or 0 for r in series]
            axes[0].plot(xs,[r['distance']if r['complete_feasible']else math.nan for r in series],'o-',label=algo)
            axes[1].plot(xs,[r['vehicles']if r['complete_feasible']else math.nan for r in series],'o-')
            axes[2].plot(xs,[r['service_rate']for r in series],'o-')
        axes[0].set(ylabel='Distance (instance-specific units)',title='Complete feasible distance only')
        axes[1].set(ylabel='Vehicles',title='Do not rank distance across fleets')
        axes[2].set(ylabel='Served / all customers',ylim=(0,1.05),title='Coverage (infeasible runs included)')
        for ax in axes:ax.set_xlabel('Budget seconds (0 = untimed greedy)')
        axes[0].legend(fontsize=7);fig.suptitle(name+' static benchmark, not measured operating savings');fig.tight_layout()
        fig.savefig(output/(name.lower()+'-comparison.png'),dpi=150);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--budgets',nargs='+',type=int,default=[10,30,60])
    p.add_argument('--seed',type=int,default=42);p.add_argument('--instances',nargs='*');p.add_argument('--no-singapore',action='store_true')
    args=p.parse_args()
    if args.output.exists():p.error('fresh output required')
    if len(set(args.budgets))!=len(args.budgets)or any(b<1 for b in args.budgets):p.error('positive unique budgets required')
    source=load_dir();labels=args.instances or sorted(source)
    normalized={k.lower():k for k in source}
    if any(n.lower()not in normalized for n in labels):p.error('unknown instance')
    cases=[(source[normalized[n.lower()]],euclidean_leg)for n in labels]
    if not args.no_singapore:cases.append(load_singapore_instance())
    args.output.mkdir(parents=True)
    files=[ROOT/'data/optimisation/solomon'/f'{n.lower()}.json'for n in labels]
    if not args.no_singapore:files.append(ROOT/'data/optimisation/singapore/network.json')
    report={'schema':'m5-formal-evaluation-v1','status':'running','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'config':{'budgets':args.budgets,'seed':args.seed,'ortools_first_solution':ORTOOLS_FIRST_SOLUTION,'distance_scale':1000,'time_scale':1000,
        'ga_population':60,'ga_seeded_by_greedy':True,'ga_search_fitness':'1e6*unserved+1000*vehicles+distance, not a proof of lexicographic dominance',
        'report_ranking':'complete feasible only, then fewest vehicles, then distance','ortools_seed_unavailable':True,
        'scope':'static solver benchmarks, not replayed medical delivery, pickup-delivery capability or clinical/operating savings'},
        'versions':{k:importlib.metadata.version(k)for k in ['ortools','numpy','matplotlib']},
        'environment':{'python':platform.python_version(),'platform':platform.platform(),'machine':platform.machine(),
            'logical_cpus':os.cpu_count(),'loky_max_cpu_count':os.environ.get('LOKY_MAX_CPU_COUNT')},
        'hashes':{str(f.relative_to(ROOT)):sha(f)for f in files+[Path(__file__),ROOT/'src/optimisation/greedy.py',ROOT/'src/optimisation/ga_solver.py',ROOT/'src/optimisation/ortools_solver.py',ROOT/'src/optimisation/routing.py']},
        'reference':{'url':REFERENCE_URL,'checked_date':'2026-10-03','values':REFERENCE,'best_known_not_optimality_certificate':True},'rows':[]}
    save(args.output,report)
    for instance,leg in cases:
        jobs=[('greedy',None)]+[(algorithm,budget)for budget in args.budgets for algorithm in ['ortools','ga']]
        for algorithm,budget in jobs:
            start=time.monotonic()
            if algorithm=='greedy':result=solve_greedy(instance,leg_fn=leg)
            elif algorithm=='ortools':result=solve_ortools(instance,time_limit_seconds=budget,leg_fn=leg,first_solution=ORTOOLS_FIRST_SOLUTION,minimize_vehicles=True)
            else:result=solve_ga(instance,leg_fn=leg,time_limit_seconds=budget,population_size=60,seed=args.seed)
            seconds=time.monotonic()-start
            validate_result(instance,result,leg)
            row=row_for(instance,result,seconds,budget,args.seed if algorithm=='ga'else None)
            report['rows'].append(row);save(args.output,report)
            (args.output/f'{instance.instance.lower()}-{algorithm}-{budget or "baseline"}.json').write_text(json.dumps(asdict(result),indent=2),encoding='utf-8')
            print(instance.instance,algorithm,budget,row['vehicles'],row['distance'],row['unserved'],f'{seconds:.2f}s',flush=True)
    report.update(status='complete',best=best_rows(report['rows']))
    save(args.output,report);plots(args.output,report['rows'])
    lines=['# M5 static benchmark formal results','','Raw runtime retained. No gap for incomplete/infeasible/different-fleet cases.',
        'GA scalar penalties are not a lexicographic optimality proof. Report ranking follows complete feasibility / fleet / distance.',
        '', '| instance | algorithm | budget | vehicles | distance | served/all | hard violations | seconds | comparable gap |', '|---|---|---:|---:|---:|---|---:|---:|---:|']
    for r in report['rows']:
        gap='—'if r['gap_distance_pct']is None else f'{r["gap_distance_pct"]:.2f}%'
        lines.append(f'| {r["instance"]} | {r["algorithm"]} | {r["budget_seconds"] or "—"} | {r["vehicles"]} | {r["distance"]:.2f} | {r["served"]}/{r["target"]} | {r["hard_violations"]} | {r["measured_seconds"]:.3f} | {gap} |')
    (args.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())
