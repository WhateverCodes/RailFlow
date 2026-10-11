"""Chronological freight-count training from observed hourly coverage, never timetables."""
import csv
import hashlib
import io
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT=Path(__file__).resolve().parents[1]/'data'/'ml'
IST=timezone(timedelta(hours=5,minutes=30))
HEADERS=['section_id','hour_start','freight_count','coverage_complete','source_reference']


def read_history(text, allowed_sections, now=None):
    if len(text.encode())>2_000_000:
        raise ValueError('History CSV exceeds 2 MB.')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if reader.fieldnames != HEADERS:
        raise ValueError('Use the freight history CSV template in its original column order.')
    rows=[];seen=set();now=now or datetime.now(IST)
    for n,row in enumerate(reader,2):
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f'Row {n}: incorrect column count.')
        section=row['section_id'].strip()
        if section not in allowed_sections:
            raise ValueError(f'Row {n}: section is not in the saved planning register.')
        try:
            stamp=datetime.fromisoformat(row['hour_start'].replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
            stamp=stamp.astimezone(IST)
        except ValueError:
            raise ValueError(f'Row {n}: use an ISO timestamp with a timezone.')
        if stamp.minute or stamp.second or stamp.microsecond or stamp+timedelta(hours=1)>now:
            raise ValueError(f'Row {n}: use a fully observed past IST hour.')
        if row['coverage_complete'].strip()!='true':
            raise ValueError(f'Row {n}: incomplete coverage cannot be treated as zero trains.')
        value=row['freight_count'].strip()
        if not value.isascii() or not value.isdigit() or not 0<=int(value)<=120:
            raise ValueError(f'Row {n}: freight_count must be a whole number from 0 to 120.')
        source=row['source_reference'].strip()
        if not source or len(source)>500:
            raise ValueError(f'Row {n}: add the observation source reference.')
        if (section,stamp) in seen:raise ValueError(f'Row {n}: duplicate section and hour.')
        seen.add((section,stamp));rows.append(dict(section=section,time=stamp,count=int(value),source=source))
    if not rows:raise ValueError('No observations were supplied.')
    first=min(r['time'] for r in rows);last=max(r['time'] for r in rows)
    if first.hour!=0 or last.hour!=23:
        raise ValueError('Supply complete IST days, from 00:00 through 23:00.')
    total_hours=int((last-first).total_seconds()/3600)+1
    if total_hours<42*24:raise ValueError('At least 42 consecutive complete days per section are required (28 training + 14 holdout).')
    sections=sorted({r['section'] for r in rows})
    if len(rows)!=total_hours*len(sections):
        raise ValueError('All sections must cover the same consecutive hours. Missing observations cannot be filled with invented zeros.')
    if sum(r['count'] for r in rows)<100:
        raise ValueError('At least 100 observed freight movements are required for this training gate.')
    return sorted(rows,key=lambda r:(r['time'],r['section'])),sections


def features(rows):
    return np.array([[r['section'],r['time'].weekday(),r['time'].hour,
        math.sin(2*math.pi*r['time'].hour/24),math.cos(2*math.pi*r['time'].hour/24)] for r in rows],dtype=object)


def pipeline():
    return Pipeline([('features',ColumnTransformer([('section',OneHotEncoder(handle_unknown='error',sparse_output=False),[0]),('calendar','passthrough',[1,2,3,4])])),
        ('model',RandomForestRegressor(n_estimators=100,max_depth=10,min_samples_leaf=8,random_state=26092,n_jobs=2))])


def train(text, source, allowed_sections, root=ROOT):
    if not isinstance(source,str) or not source.strip() or len(source)>1000:
        raise ValueError('Describe the observation source, dates and collection method.')
    rows,sections=read_history(text,allowed_sections)
    last=rows[-1]['time'];cutoff=(last+timedelta(hours=1))-timedelta(days=14)
    training=[r for r in rows if r['time']<cutoff];holdout=[r for r in rows if r['time']>=cutoff]
    grouped={};fallback={}
    for r in training:
        grouped.setdefault((r['section'],r['time'].weekday(),r['time'].hour),[]).append(r['count'])
        fallback.setdefault(r['section'],[]).append(r['count'])
    baseline=np.array([np.mean(grouped.get((r['section'],r['time'].weekday(),r['time'].hour),fallback[r['section']])) for r in holdout])
    model=pipeline();model.fit(features(training),[r['count'] for r in training])
    pred=model.predict(features(holdout));target=np.array([r['count'] for r in holdout])
    mae=float(mean_absolute_error(target,pred));baseline_mae=float(mean_absolute_error(target,baseline))
    # Promotion is evidence-based; an inferior RF never replaces a stronger simple baseline.
    promoted=baseline_mae>0 and mae<=baseline_mae*.95
    per_section={s:{'mae':float(mean_absolute_error(target[[r['section']==s for r in holdout]],pred[[r['section']==s for r in holdout]])),
        'baseline_mae':float(mean_absolute_error(target[[r['section']==s for r in holdout]],baseline[[r['section']==s for r in holdout]]))} for s in sections}
    promoted=promoted and all(v['mae']<=v['baseline_mae'] for v in per_section.values())
    sha=hashlib.sha256(text.encode()).hexdigest();run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+sha[:8]
    metadata=dict(id=run_id,model='RandomForestRegressor',target='Observed freight entries per section per IST hour',source=source.strip(),sha256=sha,
        created_at=datetime.now(timezone.utc).isoformat(),sections=sections,rows=len(rows),observed_movements=sum(r['count'] for r in rows),
        training_start=training[0]['time'].isoformat(),training_end=training[-1]['time'].isoformat(),holdout_start=cutoff.isoformat(),holdout_end=last.isoformat(),
        mae=round(mae,6),rmse=round(float(math.sqrt(mean_squared_error(target,pred))),6),baseline_mae=round(baseline_mae,6),per_section=per_section,
        eligible_for_activation=bool(promoted),status='Candidate passed holdout gate; refitted on all supplied history' if promoted else 'Candidate retained for review; baseline gate not passed',
        rule='At least 5% lower chronological holdout MAE than section/weekday/hour mean, with no section regression. This is a project gate, not operational certification.')
    if promoted:model.fit(features(rows),[r['count'] for r in rows])
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temp:
        path=Path(temp);joblib.dump(model,path/'model.joblib')
        metadata['model_sha256']=hashlib.sha256((path/'model.joblib').read_bytes()).hexdigest()
        (path/'metadata.json').write_text(json.dumps(metadata,indent=2))
        (path/'history.csv').write_text(text)
        destination=root/run_id;os.replace(path,destination)
    # A separate controller action activates a reviewed eligible candidate.
    return metadata


def status(root=ROOT):
    runs=[]
    if root.exists():
        for path in root.glob('*/metadata.json'):
            runs.append(json.loads(path.read_text()))
    active=json.loads((root/'active.json').read_text())['id'] if (root/'active.json').exists() else None
    recent=sorted(runs,key=lambda r:r['created_at'],reverse=True)[:30]
    if active and not any(r['id']==active for r in recent):
        activated=next((r for r in runs if r['id']==active),None)
        if activated:recent=[activated]+recent[:29]
    return dict(active=active,runs=recent,
        status='Active observed-history model' if active else 'No observed-history model activated',
        required_columns=HEADERS,minimum_days=42,
        requirements=['Complete observed hourly freight counts including confirmed zero-count hours.','The same continuous period for each included section.','No future rows, duplicate hours or passenger timetable substitution.','Last 14 days held out chronologically; model must outperform the historical mean baseline before activation.'])


def activate(run_id, root=ROOT):
    runs=status(root)['runs'];row=next((r for r in runs if r['id']==run_id),None)
    if not row or not row['eligible_for_activation']:raise ValueError('Choose a candidate that passed the holdout gate.')
    with tempfile.NamedTemporaryFile('w',dir=root,delete=False) as file:
        json.dump({'id':run_id},file);name=file.name
    os.replace(name,root/'active.json')
    return status(root)


def forecasts(data, root=ROOT):
    info=status(root)
    if not info['active']:return None,{'status':info['status']}
    row=next((r for r in info['runs'] if r['id']==info['active']),None)
    if not row:return None,{'status':'Active model metadata unavailable'}
    start=datetime.fromisoformat(data['start_date']).replace(tzinfo=IST)
    end=start+timedelta(days=data['horizon'])
    trained_through=datetime.fromisoformat(row['holdout_end'])+timedelta(hours=1)
    if start<trained_through or end>trained_through+timedelta(days=30):
        return None,{'status':'Model history is outside the supported next-30-day forecast period'}
    sections={t['section_id'] for t in data['tasks']}
    if not sections<=set(row['sections']):return None,{'status':'The active model does not cover all selected work sections'}
    path=root/row['id']/'model.joblib'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row['model_sha256']:raise ValueError('Saved model integrity check failed.')
    model=joblib.load(path)
    values={}
    for section in sections:
        records=[dict(section=section,time=start+timedelta(hours=h)) for h in range(data['horizon']*24)]
        values[section]=[round(float(v),4) for v in model.predict(features(records))]
    return values,{'status':'Observed-history forecast used as a bounded preference','model_id':row['id'],'source':row['source'],'holdout_mae':row['mae']}
