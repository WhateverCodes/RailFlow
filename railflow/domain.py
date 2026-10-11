import json,re,uuid
from pathlib import Path
from copy import deepcopy
from datetime import date,timedelta,datetime
from .engine import schedule,changes,plan_maintenance,offset_at
from .validator import validate
from .strategies import compare_strategies

ROOT=Path(__file__).resolve().parents[1]
DEPARTMENTS=['Track','Signal','Traction']
def integer(value,lo,hi,label):
    if type(value)!=int or not lo<=value<=hi: raise ValueError(f'{label} must be a whole number from {lo} to {hi}.')
    return value
def label(value,name,maximum=180):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise ValueError(f'{name} is required (maximum {maximum} characters).')
    return value.strip()
def uid(prefix):return prefix+uuid.uuid4().hex[:8].upper()
def station(state,sid):
    found=next((s for s in state['stations'] if s['id']==sid),None)
    if not found:raise ValueError('Unknown station.')
    return found
def scope(user,sid):
    if user['role']=='customer' or (user['role']=='master' and user['station']!=sid):raise PermissionError('This action is outside your station permissions.')
def authority(user):
    if user['role']!='authority':raise PermissionError('City authority access required.')
def train_input(state,t):
    if not isinstance(t,dict):raise ValueError('Each train must be an object.')
    tid=label(t.get('id'),'Train ID',18).upper()
    if not re.fullmatch('[A-Z0-9-]+',tid):raise ValueError('Train IDs use letters, numbers and hyphens.')
    name=label(t.get('name'),'Train name',80)
    stops=t.get('stops')
    if not isinstance(stops,list) or not 1<=len(stops)<=100:raise ValueError('Each train needs 1–100 stops.')
    cleaned=[];seen=set()
    for s in stops:
        st=station(state,s.get('station'))
        if st['id'] in seen:raise ValueError('Repeated stations in one route are not supported.')
        seen.add(st['id']);a=integer(s.get('arrival'),0,2878,'Arrival');b=integer(s.get('departure'),a+1,2880,'Departure')
        if cleaned and a<=cleaned[-1]['departure']:raise ValueError('Onward arrival must be after the previous departure.')
        p=s.get('required_platform') or None
        if p is not None:integer(p,1,st['platforms'],'Required platform')
        extra={}
        if 'min_dwell' in s:extra['min_dwell']=integer(s['min_dwell'],1,b-a,'Minimum station stop')
        if 'min_run' in s:
            if not cleaned:raise ValueError('Minimum journey time belongs to an onward stop.')
            extra['min_run']=integer(s['min_run'],1,a-cleaned[-1]['departure'],'Minimum journey time')
        cleaned.append(dict(station=st['id'],arrival=a,departure=b,required_platform=p,**extra))
    return dict(id=tid,name=name,stops=cleaned)

def base_state():
    geo=json.loads((ROOT/'data/geography.json').read_text(encoding='utf-8'))
    sts=deepcopy(geo['stations'])
    sts.append(dict(id='DEMO',name='Rivergate · fictional test station',lat=18.6,lon=74.0,platforms=3,gap=5,corridor='Test station',mode='test'))
    workers=[]
    for st in sts:
        for dep in DEPARTMENTS:
            for i in range(1,5):
                workers.append(dict(id=f"{st['id']}-{dep[:2].upper()}{i}",name=f'{dep} crew {i}',station=st['id'],department=dep,shift_start=360,shift_end=1320))
    state=dict(schema_version=4,service_date=date.today().isoformat(),conflict_history=[],edit_outcomes=[],revision=1,stations=sts,trains=[],events=[],jobs=[],workers=workers,clock=490,max_delay=120,mode='district',geography=geo.get('provenance',{}))
    state['trains']=district_trains(sts)
    recalculate(state,None)
    state['last_changes']=[]
    return state

def district_trains(stations):
    catalogue=json.loads((ROOT/'data/geography.json').read_text(encoding='utf-8'))
    lookup={s['id']:s for s in stations}
    routes={name:[lookup[sid] for sid in ids] for name,ids in catalogue['routes'].items()}
    trains=[]
    for n,(corridor,route) in enumerate(routes.items()):
        for direction in range(2):
            ordered=route if direction==0 else list(reversed(route))
            for run in range(3):
                # Repeatable fictional morning, midday and evening services.
                start=(365,705,1040)[run]+n*13+direction*19+(run*n*7)%23;stops=[]
                for i,s in enumerate(ordered):
                    minimum_run=7+(i*3+n+direction)%9
                    padding=3+(i*5+run+n)%10
                    arrival=start if not stops else stops[-1]['departure']+minimum_run+padding
                    minimum_dwell=2+(i+n)%3
                    dwell=minimum_dwell+(i*2+run+direction)%6
                    stop=dict(station=s['id'],arrival=arrival,departure=arrival+dwell,min_dwell=minimum_dwell,required_platform=None)
                    if i:stop['min_run']=minimum_run
                    stops.append(stop)
                trains.append(dict(id=f'RF{n+1}{direction}{run+1}',name=corridor+(' → outbound' if direction==0 else ' → return'),stops=stops))
    recovery_stations=[s['id'] for s in list(routes.values())[0]][:4]
    if len(recovery_stations)==4:
        trains.append(dict(id='REC01',name=next(iter(routes))+' → recovery demonstration',stops=[
            dict(station=recovery_stations[0],arrival=560,departure=565,min_dwell=5,required_platform=None),
            dict(station=recovery_stations[1],arrival=620,departure=630,min_run=15,min_dwell=5,required_platform=None),
            dict(station=recovery_stations[2],arrival=652,departure=658,min_run=12,min_dwell=3,required_platform=None),
            dict(station=recovery_stations[3],arrival=675,departure=679,min_run=12,min_dwell=2,required_platform=None)]))
    return trains

def recalculate(state,old):
    state.setdefault('service_date',date.today().isoformat())
    plan, comparison=compare_strategies(state,old)
    state["strategy_comparison"]=comparison
    result=validate(state,plan)
    if not result['passed']:raise ValueError('Independent validation rejected the revision: '+result['issues'][0]['message'])
    plan['validation']=result
    prior={(r['train'],r['stop']):r for r in (old or {}).get('rows',[])}
    for row in plan['rows']:
        before=prior.get((row['train'],row['stop']))
        row['previous_platform']=before['platform'] if before and before['platform']!=row['platform'] else None
        if before and before['platform']!=row['platform']:
            closed=any(e['kind']=='closure' and e['station']==row['station'] and e['platform']==before['platform'] and row['arrival']<e['end'] and row['departure']>e['start'] for e in state['events'])
            maintenance=any(j['station']==row['station'] and j['platform']==before['platform'] and j['status'] in ('Accepted','Assigned','In progress','Completed') and row['arrival']<j['end'] and row['departure']>j['start'] for j in state['jobs'])
            reason='Platform changed because previous platform is closed' if closed else 'Platform changed for maintenance work' if maintenance else 'A different platform was selected by the deterministic strategy; independent occupancy and gap checks passed'
            row['reason']=reason if row['reason']=='On schedule' else row['reason']+'; '+reason
        neighbours=[r for r in plan['rows'] if r['station']==row['station'] and r['platform']==row['platform'] and r['departure']<=row['arrival'] and r is not row]
        gap=next(s['gap'] for s in state['stations'] if s['id']==row['station'])
        margin=min((row['arrival']-r['departure']-gap for r in neighbours),default=999)
        row['departure_delay']=row['departure']-row['scheduled_departure']
        row['risk']=max(row['delay'],row['departure_delay'])<=0 and margin<=3
        row['risk_reason']='Tight platform turnaround' if row['risk'] else ''
        row['service_date']=state['service_date']
        row['arrival_date']=(date.fromisoformat(state['service_date'])+timedelta(days=row['arrival']//1440)).isoformat()
        row['departure_date']=(date.fromisoformat(state['service_date'])+timedelta(days=row['departure']//1440)).isoformat()
    for t in state['trains']:t['service_date']=state['service_date']
    state['last_changes']=changes(old,plan)
    state['plan']=plan
    state['metrics']=dict(trains=len(state['trains']),stops=len(plan['rows']),delayed=sum(max(r['delay'],r['departure_delay'])>0 for r in plan['rows']),
        delay_minutes=sum(max(0,r['delay'],r['departure_delay']) for r in plan['rows']),unscheduled=len(plan['unscheduled']))

def mutate(state,user,body):
    if user['role']=='customer':raise PermissionError('Customer accounts are view-only.')
    action=body.get('action');old=deepcopy(state['plan']);note='';projected=deepcopy(old);requests=[]
    state['edit_outcomes']=[]
    if action=='clock':
        authority(user);state['clock']=integer(body.get('clock'),0,2879,'Simulation clock');note='Simulation clock changed'
    elif action=='settings':
        sid=body.get('station');scope(user,sid);st=station(state,sid)
        count=integer(body.get('platforms'),1,12,'Platform count');gap=integer(body.get('gap'),0,60,'Minimum gap')
        if any(e['station']==sid and e.get('platform',0)>count for e in state['events']):raise ValueError('Remove closures on platforms being removed first.')
        if any(j['station']==sid and j['platform']>count and j['status'] not in ('Refused','Cancelled') for j in state['jobs']):raise ValueError('Existing maintenance uses a platform being removed.')
        if any(s['station']==sid and (s.get('required_platform') or 0)>count for t in state['trains'] for s in t['stops']):raise ValueError('A train requires a platform being removed.')
        st.update(platforms=count,gap=gap);note=f"Updated {sid}: {count} platforms, {gap}-minute gap"
    elif action=='simulate':
        edits=body.get('edits')
        if not isinstance(edits,list) or not 1<=len(edits)<=1000:raise ValueError('Change at least one timing or platform requirement before creating a schedule.')
        seen=set()
        for edit in edits:
            tid=edit.get('train');idx=edit.get('stop');key=(tid,idx)
            if key in seen:raise ValueError('Duplicate stop edit.')
            seen.add(key);t=next((t for t in state['trains'] if t['id']==tid),None)
            if not t or type(idx)!=int or not 0<=idx<len(t['stops']):raise ValueError('Unknown train stop.')
            stop=t['stops'][idx];scope(user,stop['station']);st=station(state,stop['station'])
            a=integer(edit.get('arrival'),0,2878,'Reported arrival');b=integer(edit.get('departure'),a+1,2880,'Reported departure')
            # Explicit timetable edits can advance departure, unlike a simple early-arrival report.
            p=edit.get('required_platform') or None
            if p is not None:integer(p,1,st['platforms'],'Required platform')
            stop.update(requested_arrival=a,requested_departure=b,requested_event_offset=offset_at(state,t,idx)[0],required_platform=p,timing_reason=label(edit.get('reason'),'Timing-change reason'))
            requests.append(dict(train=tid,stop=idx,station=stop['station'],arrival=a,departure=b))
            row=next((r for r in projected['rows'] if r['train']==tid and r['stop']==idx),None)
            if row:row.update(arrival=a,departure=b,platform=p or row['platform'])
        note=f'Replanned {len(edits)} edited train calls from Simulation'
    elif action=='service_date':
        authority(user)
        state['service_date']=date.fromisoformat(body.get('service_date','')).isoformat()
        note='Operating date changed to '+state['service_date']
    elif action=='train':
        authority(user);t=train_input(state,body.get('train'));existing=next((i for i,v in enumerate(state['trains']) if v['id']==t['id']),None)
        if existing is not None:
            if any(e.get('train')==t['id'] for e in state['events']):raise ValueError('Remove this train’s disruptions before replacing its route.')
            state['trains'][existing]=t
        else:
            if len(state['trains'])>=100:raise ValueError('Maximum 100 trains.')
            state['trains'].append(t)
        note='Saved timetable for '+t['id']
    elif action=='import':
        authority(user);data=body.get('trains')
        if not isinstance(data,list) or not 1<=len(data)<=100:raise ValueError('Upload an array of 1–100 trains.')
        ts=[train_input(state,t) for t in data]
        if len({t['id'] for t in ts})!=len(ts):raise ValueError('Duplicate train IDs.')
        if state['events']:raise ValueError('Remove existing disruptions before replacing the timetable.')
        state['trains']=ts;note='Imported replacement timetable'
    elif action=='event':
        event=body.get('event',{});sid=event.get('station');scope(user,sid);st=station(state,sid)
        reason=label(event.get('reason'),'Reason');kind=event.get('kind')
        e=dict(id=uid('EV-'),kind=kind,station=sid,reason=reason)
        if len(state['events'])>=200:raise ValueError('Maximum 200 active disruptions.')
        if kind=='closure':
            e.update(platform=integer(event.get('platform'),1,st['platforms'],'Platform'),start=integer(event.get('start'),0,2879,'Closure start'))
            e['end']=integer(event.get('end'),e['start']+1,2880,'Closure end')
        elif kind in ('delay','early'):
            t=next((t for t in state['trains'] if t['id']==event.get('train')),None)
            if not t or not any(s['station']==sid for s in t['stops']):raise ValueError('Choose a train that calls at this station.')
            e.update(train=t['id'],minutes=integer(event.get('minutes'),1,240,'Minutes'))
        else:raise ValueError('Unknown disruption type.')
        state['events'].append(e);note=f"{kind.title()} at {sid}: {reason}"
    elif action=='remove_event':
        e=next((e for e in state['events'] if e['id']==body.get('id')),None)
        if not e:raise ValueError('Disruption not found.')
        scope(user,e['station']);state['events'].remove(e);note='Cleared disruption '+e['id']
    elif action=='job':
        authority(user);sid=body.get('station');st=station(state,sid)
        platform=integer(body.get('platform'),1,st['platforms'],'Platform')
        start=integer(body.get('start'),0,2879,'Start');end=integer(body.get('end'),start+1,2880,'End')
        dep=body.get('department')
        if dep not in DEPARTMENTS:raise ValueError('Unknown department.')
        state['jobs'].append(dict(id=uid('JOB-'),station=sid,platform=platform,start=start,end=end,title=label(body.get('title'),'Work title'),
            department=dep,crew_required=integer(body.get('crew_required'),1,4,'Crew size'),crew=[],status='Pending',reason='',reports=[]))
        note='Proposed maintenance at '+sid
    elif action=='job_status':
        j=next((j for j in state['jobs'] if j['id']==body.get('id')),None)
        if not j:raise ValueError('Job not found.')
        scope(user,j['station']);target=body.get('status');reason=label(body.get('reason'),'Decision reason')
        if user['role']!='master':raise PermissionError('The assigned station master must review and manage this job.')
        transitions={'Pending':['Accepted','Assigned','Refused'],'Accepted':['Refused','Assigned'],'Assigned':['Refused','In progress'],'In progress':['Completed']}
        if target not in transitions.get(j['status'],[]):raise ValueError('Invalid job status transition.')
        if target in ('Accepted','Assigned'):
            if any(k['id']!=j['id'] and k['station']==j['station'] and k['platform']==j['platform'] and k['status'] in ('Accepted','Assigned','In progress','Completed') and j['start']<k['end'] and j['end']>k['start'] for k in state['jobs']):raise ValueError('Another accepted job occupies this platform.')
        if target=='Refused':
            j['crew']=[]
            proposed=body.get('proposed_start','')
            proposed_end=body.get('proposed_end','')
            if bool(proposed)!=bool(proposed_end):raise ValueError('Provide both alternative start and end, or leave both blank.')
            if proposed:
                a=datetime.fromisoformat(proposed);b=datetime.fromisoformat(proposed_end)
                if b<=a:raise ValueError('Alternative end must be after start.')
                j['alternative']=dict(start=a.isoformat(timespec='minutes'),end=b.isoformat(timespec='minutes'))
        if target=='Assigned':
            selected=body.get('crew',[])
            if len(set(selected))!=len(selected) or len(selected)!=j['crew_required']:raise ValueError('Select exactly the required number of distinct workers.')
            for wid in selected:
                w=next((w for w in state['workers'] if w['id']==wid),None)
                if not w or w['station']!=j['station'] or w['department']!=j['department']:raise ValueError('Crew must belong to this station and department.')
                if not w['shift_start']<=j['start']<j['end']<=w['shift_end']:raise ValueError('Work must fit the entire crew shift (06:00–22:00).')
                if any(wid in k['crew'] and k['status'] in ('Assigned','In progress','Completed') and j['start']<k['end'] and j['end']>k['start'] for k in state['jobs']):raise ValueError('A selected worker already has overlapping work.')
            j['crew']=selected
        # This is an offline planning exercise: progress is reported by the master,
        # not gated by a global simulation clock. Reserved intervals stay enforced.
        j['status']=target;j['reason']=reason;j['reports'].append(dict(status=target,reason=reason,by=user['name']))
        note=j['id']+' '+target+': '+reason
    elif action=='scenario':
        authority(user)
        if any(j['status']=='In progress' for j in state['jobs']):raise ValueError('Finish active work before switching scenarios.')
        mode=body.get('mode')
        if mode not in ('district','test'):raise ValueError('Unknown scenario.')
        state.update(mode=mode,events=[],jobs=[],clock=490)
        if mode=='district':state['trains']=district_trains(state['stations'])
        else:
            state['trains']=[dict(id=f'T{i+1:02}',name=f'Rivergate service {i+1}',stops=[dict(station='DEMO',arrival=480+i*4,departure=489+i*4,required_platform=1 if i in (0,3) else None)]) for i in range(8)]
        note='Loaded '+mode+' scenario; previous revision retained in history'
    elif action=='replan':
        note='Recomputed platform assignments'
    else:raise ValueError('Unknown action.')
    state['before_validation']=validate(state,projected)
    recalculate(state,old)
    for request in requests:
        actual=next((r for r in state['plan']['rows'] if r['train']==request['train'] and r['stop']==request['stop']),None)
        exact=actual is not None and all(actual[k]==request[k] for k in ('arrival','departure'))
        state['edit_outcomes'].append(dict(**request,actual=actual,exact=exact,explanation='Requested times accommodated' if exact else (actual['reason']+'; adjusted to respect minimum dwell, travel time, occupancy or closure constraints' if actual else 'No feasible assignment within the planning limits')))
    for conflict in state['before_validation']['issues']:
        if conflict['kind'] not in ('overlap','gap','closure'):continue
        ids={conflict['train'],conflict.get('other')}
        affected=[r for r in state['plan']['rows'] if r['train'] in ids and r['station']==conflict['station']]
        state.setdefault('conflict_history',[]).append(dict(**conflict,revision=state['revision']+1,service_date=state['service_date'],resolution='Replanned without overlap or gap violations' if len(affected)==len(ids-{None}) else 'Capacity conflict removed; one or more calls are explicitly unscheduled',after=affected))
    state['revision']+=1
    return note

def public_state(state,user):
    data=deepcopy(state);role=user['role']
    if role=='master':
        sid=user['station'];data['jobs']=[j for j in data['jobs'] if j['station']==sid];data['workers']=[w for w in data['workers'] if w['station']==sid]
        data['events']=[e for e in data['events'] if e['station']==sid]
        affected={c['train'] for c in data['last_changes'] if c['station']==sid}
        data['last_changes']=[c for c in data['last_changes'] if c['station']==sid or c['train'] in affected]
        data['conflict_history']=[c for c in data.get('conflict_history',[]) if c['station']==sid]
    if role=='customer':
        data['jobs']=[];data['workers']=[];data['events']=[];data['last_changes']=[]
        data['conflict_history']=[];data['edit_outcomes']=[]
        data.pop('before_validation',None)
        data.pop('strategy_comparison',None)
        for t in data['trains']:
            for s in t['stops']:s.pop('timing_reason',None)
        for r in data['plan']['rows']:
            r.pop('constraints',None)
            reason=r['reason'].lower()
            late=max(r['delay'],r.get('departure_delay',0))>0
            r['reason']=('Maintenance work' if 'maintenance' in reason else 'Platform congestion' if 'platform' in reason else 'Service disruption') if late else 'Early arrival' if r['delay']<0 else 'On time'
    return data
