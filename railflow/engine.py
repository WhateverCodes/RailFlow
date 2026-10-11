"""Deterministic earliest-feasible platform scheduler. Times are minutes from day 1."""
from copy import deepcopy

MAX_TIME = 2880

def offset_at(state, train, index):
    offset = 0
    reasons = []
    for event in state['events']:
        if event['kind'] in ('delay', 'early') and event.get('train') == train['id']:
            trigger = next((i for i,s in enumerate(train['stops']) if s['station'] == event['station']), -1)
            if trigger == index:  # Apply once; onward delay travels with the train.
                offset += event['minutes'] * (-1 if event['kind']=='early' else 1)
                reasons.append(event['reason'])
    return offset, reasons

def restrictions(state):
    blocks = [dict(e) for e in state['events'] if e['kind']=='closure']
    for job in state['jobs']:
        if job['status'] in ('Accepted','Assigned','In progress','Completed'):
            blocks.append(dict(kind='closure', station=job['station'], platform=job['platform'],
                               start=job['start'], end=job['end'], reason='Maintenance work', id=job['id']))
    return blocks

def schedule(state, *, train_order=None, reference=None):
    stations = {s['id']:s for s in state['stations']}
    reservations = {}
    blocks = restrictions(state)
    rows, unscheduled = [], []
    trains = sorted(state['trains'], key=lambda t:(max(0,t['stops'][0]['arrival']+offset_at(state,t,0)[0]), t['id']))
    if train_order is not None:
        order = {tid: i for i, tid in enumerate(train_order)}
        trains.sort(key=lambda t: order[t["id"]])
    prior = {(r["train"], r["stop"]): r for r in (reference or {}).get("rows", [])}
    for train in trains:
        previous = None
        for index, stop in enumerate(train['stops']):
            station = stations[stop['station']]
            delta, cause = offset_at(state, train, index)
            earliest = max(0, stop.get('requested_arrival',stop['arrival'])+delta-stop.get('requested_event_offset',0))
            if stop.get('timing_reason'):cause.append(stop['timing_reason'])
            if previous:
                travel = stop.get('min_run',stop['arrival']-train['stops'][index-1]['departure'])
                if 'requested_arrival' not in stop and previous['departure']<train['stops'][index-1]['departure']:
                    earliest=min(earliest,previous['departure']+travel)
                earliest = max(earliest, previous['departure']+travel)
            dwell = stop.get('min_dwell',stop['departure']-stop['arrival'])
            platforms = [stop['required_platform']] if stop.get('required_platform') else range(1,station['platforms']+1)
            choices = []
            for platform in platforms:
                if platform<1 or platform>station['platforms']:
                    continue
                arrival = earliest
                why = list(cause)
                occupied = reservations.get((station['id'],platform), [])
                closures = [b for b in blocks if b['station']==station['id'] and b['platform']==platform]
                for _ in range(len(occupied)+len(closures)+2):
                    departure = max(arrival+dwell,stop.get('requested_departure',stop['departure']))
                    bump = arrival
                    for other in occupied:
                        if arrival < other['departure']+station['gap'] and departure+station['gap'] > other['arrival']:
                            bump=max(bump,other['departure']+station['gap'])
                            why.append('Platform occupied by '+other['train'])
                    for closure in closures:
                        if arrival < closure['end'] and departure > closure['start']:
                            bump=max(bump,closure['end'])
                            why.append(closure['reason'])
                    if bump==arrival:
                        break
                    arrival=bump
                departure=max(arrival+dwell,stop.get('requested_departure',stop['departure']))
                if arrival-stop['arrival']<=state['max_delay'] and departure<=MAX_TIME:
                    choices.append((arrival,departure,platform,list(dict.fromkeys(why))))
            if not choices:
                unscheduled.extend(dict(train=train['id'],station=s['station'],stop=i,
                    reason=(('No feasible assignment on '+('required platform '+str(s['required_platform']) if s.get('required_platform') else 'platforms 1–'+str(stations[s['station']]['platforms']))+' within the maximum delay / two-day horizon') if i==index else 'Earlier stop could not be scheduled'))
                    for i,s in enumerate(train['stops'][index:],index))
                unscheduled[-len(train['stops'][index:])]['constraints'] = dict(earliest_arrival=earliest, latest_arrival=min(stop['arrival']+state['max_delay'], MAX_TIME-dwell), required_platform=stop.get('required_platform'), minimum_dwell=dwell, minimum_gap=station['gap'], blocks=[dict(id=b.get('id'),platform=b['platform'],start=b['start'],end=b['end'],reason=b.get('reason','Maintenance reservation')) for b in blocks if b['station']==station['id'] and (not stop.get('required_platform') or b['platform']==stop['required_platform'])])
                unscheduled[-len(train['stops'][index:])]['review'] = 'Review the reported timing, closure/maintenance window, required platform or configured maximum delay. No restriction was relaxed automatically.'
                break
            before = prior.get((train['id'], index))
            def choice_cost(c):
                delay = max(0, c[0]-stop['arrival'], c[1]-stop['departure'])
                moved = bool(before and c[2] != before['platform'])
                changed = bool(before and (c[0], c[1], c[2]) != (before['arrival'], before['departure'], before['platform']))
                return (delay + 5*moved + changed, c[0], c[1], c[2])
            arrival,departure,platform,why = min(choices,key=choice_cost if reference is not None else lambda c:(c[0],c[1],c[2]))
            if arrival>stop['arrival'] and not why:
                why=['Delay carried forward from previous station']
            running_recovery=max(0,max(0,previous['departure']-previous['scheduled_departure'])-max(0,arrival-stop['arrival'])) if previous else 0
            dwell_recovery=max(0,max(0,arrival-stop['arrival'])-max(0,departure-stop['departure']))
            if running_recovery:why.append(f'Recovered {running_recovery} min using journey allowance')
            if dwell_recovery:why.append(f'Recovered {dwell_recovery} min using station stop allowance')
            row=dict(recovered_running=running_recovery,recovered_dwell=dwell_recovery,min_dwell=dwell,train=train['id'],name=train['name'],station=station['id'],stop=index,
                     arrival=arrival,departure=departure,platform=platform,
                     path=f"Approach {'A' if platform%2 else 'B'} → Platform {platform} → Exit {'A' if platform%2 else 'B'}",
                     scheduled_arrival=stop['arrival'],scheduled_departure=stop['departure'],
                     delay=arrival-stop['arrival'],reason='; '.join(why) if why else 'On schedule')
            row['constraints']=dict(earliest_arrival=earliest, minimum_dwell=dwell,
                minimum_gap=station['gap'], required_platform=stop.get('required_platform'),
                feasible_platforms=len(choices),
                selection='Lowest local disruption cost' if reference is not None else 'Earliest feasible arrival, departure, then platform number')
            rows.append(row)
            reservations.setdefault((station['id'],platform),[]).append(row)
            previous=row
    return dict(rows=rows,unscheduled=unscheduled,algorithm='Earliest-feasible greedy scheduling; not a global optimum')

def changes(old,new):
    before={(r['train'],r['stop']):r for r in (old or {}).get('rows',[])}
    after={(r['train'],r['stop']):r for r in new['rows']}
    out=[]
    for key,row in after.items():
        prior=before.get(key)
        if not prior or any(prior[k]!=row[k] for k in ('arrival','departure','platform')):
            out.append(dict(train=row['train'],station=row['station'],before=prior,after=row,reason=row['reason']))
    for key,row in before.items():
        if key not in after:
            out.append(dict(train=row['train'],station=row['station'],before=row,after=None,reason='No feasible revised assignment'))
    return out

def plan_maintenance(state,station,platform,earliest,latest,duration):
    """Find earliest train-free window. Existing accepted jobs remain reservations."""
    st=next(s for s in state['stations'] if s['id']==station)
    taken=[(r['arrival']-st['gap'],r['departure']+st['gap']) for r in state['plan']['rows']
           if r['station']==station and r['platform']==platform]
    taken += [(b['start'],b['end']) for b in restrictions(state) if b['station']==station and b['platform']==platform]
    start=earliest
    for a,b in sorted(taken):
        if start+duration<=a:
            break
        if start<b and start+duration>a:
            start=b
    if start+duration>latest:
        return None
    return dict(start=start,end=start+duration,reason='Earliest available window outside train occupancies, safety gaps and accepted blocks')
