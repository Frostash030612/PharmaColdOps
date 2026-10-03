"""Real M3 engine vs frozen aggregated human gold, without private answers.

This is NOT evaluate_engine.py --selftest and does not pretend to recompute
private B/C agreement or prove clinical stability validity.
"""
import argparse
from collections import Counter
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/processed/.mpl-cache'))
os.environ.setdefault('MPLBACKEND','Agg')
from sklearn.metrics import accuracy_score, classification_report, cohen_kappa_score, confusion_matrix
from rule_engine.engine import RuleEngine
from rule_engine.models import ExcursionEvent

LABELS=['release','retest','quarantine','scrap']
INPUT=ROOT/'data/scenarios/annotation/input_v1.csv'
GOLD=ROOT/'data/scenarios/gold_labels.csv'
CONFIG=ROOT/'src/rule_engine/rules_config.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_unique(path,required):
    with Path(path).open(encoding='utf-8-sig',newline='')as f:
        reader=csv.DictReader(f)
        if not set(required)<=set(reader.fieldnames or []):raise ValueError('missing evaluation columns')
        rows={}
        for row in reader:
            key=row['scenario_id']
            if not key or key in rows:raise ValueError('duplicate or missing scenario identity')
            rows[key]=row
    if not rows:raise ValueError('empty evaluation input')
    return rows


def evaluate(inputs=INPUT,gold=GOLD):
    examples=read_unique(inputs,['scenario_id','product_id','excursion_temp_c','duration_min','mkt_c','packaging','stage'])
    labels=read_unique(gold,['scenario_id','gold_label'])
    if set(examples)!=set(labels):raise ValueError('input and gold identities differ')
    if any(r['gold_label']not in LABELS for r in labels.values()):raise ValueError('unknown human label')
    engine=RuleEngine();predictions=[]
    for sid,row in sorted(examples.items()):
        event=ExcursionEvent(scenario_id=sid,product_id=row['product_id'],excursion_temp_c=float(row['excursion_temp_c']),
            duration_min=int(row['duration_min']),mkt_c=float(row['mkt_c']),packaging=row['packaging'],stage=row['stage'])
        d=engine.evaluate(event)
        predictions.append({'scenario_id':sid,**{k:row[k]for k in ['product_id','excursion_temp_c','duration_min','mkt_c','packaging','stage']},
            'automatic_disposition':d.disposition.value,'gold_label':labels[sid]['gold_label'],'rule_no':d.rule_no,
            'reshipment_required':d.reshipment_required,'reason':d.reason,'agree':d.disposition.value==labels[sid]['gold_label']})
    truth=[p['gold_label']for p in predictions];actual=[p['automatic_disposition']for p in predictions]
    scored=classification_report(truth,actual,labels=LABELS,output_dict=True,zero_division=0)
    report={'schema':'m3-real-engine-evaluation-v1','generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'evaluation_scope':'automatic rule implementation vs frozen historical human reference; not clinical correctness or reviewed effective outcomes',
        'rows':len(predictions),'agree':sum(p['agree']for p in predictions),'accuracy':float(accuracy_score(truth,actual)),
        'engine_vs_gold_kappa':float(cohen_kappa_score(truth,actual,labels=LABELS)),
        'label_order':LABELS,'confusion':confusion_matrix(truth,actual,labels=LABELS).tolist(),'class_report':scored,
        'rule_coverage':dict(Counter(str(p['rule_no'])for p in predictions)),
        'product_support':dict(Counter(p['product_id']for p in predictions)),
        'stage_support':dict(Counter(p['stage']for p in predictions)),
        'predicted_counts':dict(Counter(actual)),'gold_counts':dict(Counter(truth)),
        'deviations':[p for p in predictions if not p['agree']],
        'source_hashes':{str(Path(p).relative_to(ROOT)) if Path(p).is_relative_to(ROOT)else str(p):sha(p)for p in [inputs,gold,CONFIG,ROOT/'src/rule_engine/engine.py',Path(__file__)]},
        'historical_human_human_kappa':{'value':.6434,'scope':'archival B/C statistic, not recomputed; requires private original answers'},
        'no_private_answers_read_or_distributed':True,'no_gold_or_rule_changes':True}
    return report,predictions


def write_report(output,report,rows):
    output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    with(output/'predictions.csv').open('w',encoding='utf-8',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    text=['# M3 real-engine formal evaluation','',f'Accuracy: {report["agree"]}/{report["rows"]} = {report["accuracy"]:.4%}',
        f'Engine vs gold kappa: {report["engine_vs_gold_kappa"]:.6f}',f'Macro-F1 (all four labels): {report["class_report"]["macro avg"]["f1-score"]:.6f}',
        '', '| label | support | precision | recall | F1 |','|---|---:|---:|---:|---:|']
    for label in LABELS:
        m=report['class_report'][label];text.append(f'| {label} | {m["support"]} | {m["precision"]:.4f} | {m["recall"]:.4f} | {m["f1-score"]:.4f} |')
    text+=['','Historical B/C kappa 0.6434 is NOT engine/gold kappa. No private annotator answers were read.',
        'Known deviations remain frozen. Current rubric does not emit quarantine; its zero recall on three historical labels is disclosed.',
        'Rule coverage is scenario-bank coverage, not exhaustive boundary or clinical validation. Human execution overrides are excluded.']
    (output/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(6,5));matrix=report['confusion'];ax.imshow(matrix,cmap='Blues')
    ax.set_xticks(range(4),LABELS,rotation=30,ha='right');ax.set_yticks(range(4),LABELS)
    for i in range(4):
        for j in range(4):ax.text(j,i,str(matrix[i][j]),ha='center',va='center')
    ax.set(xlabel='Real automatic engine',ylabel='Frozen human reference',title='M3 confusion: counts, all four labels')
    fig.tight_layout();fig.savefig(output/'confusion.png',dpi=150);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():p.error('fresh output required')
    report,rows=evaluate();write_report(args.output,report,rows)
    print(json.dumps({k:report[k]for k in ['rows','agree','accuracy','engine_vs_gold_kappa','rule_coverage']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
