"""Independent audit: no imports from the scheduler and no solver variables."""
from collections import defaultdict

def validate(state,plan):
    issues=[]
    stations={s['id']:s for s in state['stations']}
    trains={t['id']:t for t in state['trains']}
    seen={}; groups=defaultdict(list)
    indexed={(r.get('train'),r.get('stop')):r for r in plan['rows']
             if all(type(r.get(k))==int for k in ('arrival','departure','platform','stop'))}
    def fail(kind,row,message,other=None):
        issues.append(dict(kind=kind,train=row.get('train'),station=row.get('station'),platform=row.get('platform'),other=other,message=message))
    blocks=[e for e in state['events'] if e['kind']=='closure']
    blocks += [j for j in state['jobs'] if j['status'] in ('Accepted','Assigned','In progress','Completed')]
    for r in plan['rows']:
        t=trains.get(r.get('train')); st=stations.get(r.get('station')); i=r.get('stop')
        if not t or not st or type(i)!=int or not 0<=i<len(t['stops']):
            fail('identity',r,'Unknown train, station or stop');continue
        expected=t['stops'][i]
        key=(t['id'],i)
        if key in seen: fail('duplicate',r,'Train stop appears twice')
        seen[key]=r
        if expected['station']!=r['station']: fail('route',r,'Station differs from input route')
        if any(type(r.get(k))!=int for k in ('arrival','departure','platform')):
            fail('format',r,'Times and platform must be integers');continue
        if not 0<=r['arrival']<r['departure']<=2880: fail('time',r,'Invalid time interval or outside two-day horizon')
        if not 1<=r['platform']<=st['platforms']: fail('platform',r,'Platform does not exist')
        if expected.get('required_platform') and expected['required_platform']!=r['platform']: fail('required',r,'Required platform violated')
        if r['departure']-r['arrival']<expected.get('min_dwell',expected['departure']-expected['arrival']): fail('dwell',r,'Minimum dwell violated')
        if r['departure']<expected.get('requested_departure',expected['departure']): fail('departure',r,'Departure before the requested or advertised time')
        if r['arrival']-expected['arrival']>state['max_delay']: fail('delay',r,'Maximum permitted delay exceeded')
        delta=0
        for e in state['events']:
            if e['kind'] in ('delay','early') and e.get('train')==t['id']:
                trigger=next((n for n,s in enumerate(t['stops']) if s['station']==e['station']),-1)
                if trigger==i: delta+=e['minutes']*(-1 if e['kind']=='early' else 1)
        earliest=max(0,expected.get('requested_arrival',expected['arrival'])+delta-expected.get('requested_event_offset',0))
        preceding=indexed.get((t['id'],i-1))
        if preceding and 'requested_arrival' not in expected and preceding['departure']<t['stops'][i-1]['departure']:
            earliest=min(earliest,preceding['departure']+expected.get('min_run',expected['arrival']-t['stops'][i-1]['departure']))
        if r['arrival']<earliest: fail('disruption',r,'Previous arrival is earlier than the newly requested arrival')
        if r['departure']<expected.get('requested_departure',0):fail('reported_departure',r,'Previous departure is earlier than the newly requested departure')
        for b in blocks:
            if b['station']==r['station'] and b['platform']==r['platform'] and r['arrival']<b['end'] and r['departure']>b['start']:
                fail('closure',r,'Train overlaps closure or accepted maintenance '+b['id'])
        groups[(r['station'],r['platform'])].append(r)
    for (station,platform),rows in groups.items():
        rows.sort(key=lambda r:r['arrival'])
        for i,a in enumerate(rows):
            for b in rows[i+1:]:
                if b['arrival']>=a['departure']+stations[station]['gap']:
                    break
                fail('overlap' if b['arrival']<a['departure'] else 'gap',b,
                     f"{a['train']} and {b['train']} violate occupancy / minimum gap on P{platform}",a['train'])
    deferred=set()
    for u in plan['unscheduled']:
        t=trains.get(u.get('train')); i=u.get('stop'); key=(u.get('train'),i)
        if not t or type(i)!=int or not 0<=i<len(t['stops']):
            fail('identity',u,'Unknown unscheduled train or stop');continue
        if key in deferred: fail('duplicate',u,'Unscheduled stop appears twice')
        if u.get('station')!=t['stops'][i]['station']: fail('route',u,'Unscheduled station differs from input route')
        deferred.add(key)
    for t in state['trains']:
        for i,s in enumerate(t['stops']):
            row=seen.get((t['id'],i))
            if row and (t['id'],i) in deferred: fail('coverage',row,'Stop is both assigned and unscheduled')
            if not row and (t['id'],i) not in deferred: fail('coverage',dict(train=t['id'],station=s['station']),'Stop silently omitted')
            if row and i and (t['id'],i) in indexed:
                prev=indexed.get((t['id'],i-1))
                if not prev or row['arrival']<prev['departure']+s.get('min_run',s['arrival']-t['stops'][i-1]['departure']):
                    fail('travel',row,'Previous stop missing or minimum journey time violated')
    return dict(passed=not issues,issues=issues,checked=len(plan['rows']),complete=not plan['unscheduled'],
        checks=['Occupancy overlaps','Minimum platform gaps','Required platforms','Closures and maintenance','Dwell and advertised departure','Inter-station travel','Disruption timing','All stops accounted for'])
