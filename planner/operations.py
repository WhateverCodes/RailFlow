"""Input-driven planning. No generated assets, timings, risk or authorization data."""
from collections import defaultdict
from itertools import combinations
from ortools.sat.python import cp_model


def subtract(ranges, occupied):
    for a, b in occupied:
        revised = []
        for lo, hi in ranges:
            if b <= lo or a >= hi:
                revised.append((lo, hi))
            else:
                if a > lo:
                    revised.append((lo, a))
                if b < hi:
                    revised.append((b, hi))
        ranges = revised
    return ranges


def can_share(a, b):
    return (a['section_id'] == b['section_id'] and a['line'] == b['line']
            and a['department'] != b['department']
            and bool(a['compatibility_group']) and a['compatibility_group'] == b['compatibility_group']
            and bool(a['compatibility_reference']) and bool(b['compatibility_reference']))


def zone(data, section):
    # Until track topology is supplied, different IDs must not evade corridor conflicts.
    return next((s['corridor'] for s in data.get('sections',[]) if s['id']==section),section)


def domains(data, group):
    duration = max(t['duration'] for t in group) + data['setup']
    section = group[0]['section_id']
    release, deadline = max(t['release'] for t in group), min(t['due'] for t in group)
    occupied = [(m['start']-data['headway'], m['end']+data['headway']) for m in data['movements'] if zone(data,m['section_id']) == zone(data,section)]
    occupied += [(b['start'], b['end']) for b in data['existing_blocks'] if zone(data,b['section_id']) == zone(data,section)]
    ranges = []
    for w in data['windows']:
        if w['section_id'] != section or (any(t['power'] for t in group) and not w['power']):
            continue
        for lo, hi in subtract([(max(w['start'], release, 0), min(w['end'], deadline, data['horizon']*1440))], occupied):
            if hi-lo >= duration:
                ranges.append((lo, hi-duration))
    return ranges, duration


def eligible(worker, task):
    return worker['department'] == task['department'] and worker['station'] in task['nearby']


def solve(data, joint=True, selected=None):
    tasks = [t for t in data['tasks'] if selected is None or t['id'] in selected]
    # Singles remain alternatives: a failed joint candidate never strands its constituent work.
    groups = [[t] for t in tasks]
    if joint:
        buckets = defaultdict(list)
        for t in tasks:
            if t['compatibility_group']:
                buckets[(t['section_id'], t['line'], t['compatibility_group'])].append(t)
        for bucket in buckets.values():
            for size in (2, 3):
                groups += [list(g) for g in combinations(bucket, size) if all(can_share(a,b) for a,b in combinations(g,2))]
                if len(groups)>2500:
                    raise ValueError('Too many joint alternatives. Split the compatibility groups or plan fewer requests.')
    model = cp_model.CpModel()
    task_choices, sections, worker_pools, machine_pools = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    candidates, objective = [], []
    for index, group in enumerate(groups):
        ranges, duration = domains(data, group)
        if not ranges:
            continue
        start = model.new_int_var_from_domain(cp_model.Domain.from_intervals(ranges), f's{index}')
        end = model.new_int_var(0, data['horizon']*1440, f'e{index}')
        present = model.new_bool_var(f'p{index}')
        interval = model.new_optional_interval_var(start, duration, end, present, f'b{index}')
        sections[zone(data,group[0]['section_id'])].append(interval)
        crew_vars = {}
        for t in group:
            task_choices[t['id']].append(present)
            choices = []
            for w in data['workers']:
                if not eligible(w, t):
                    continue
                shift_ranges = [(lo, hi-duration) for lo, hi in w['ranges'] if hi-lo >= duration]
                if not shift_ranges:
                    continue
                chosen = model.new_bool_var(f'crew{index}-{w["id"]}-{t["id"]}')
                model.add(chosen <= present)
                model.add_linear_expression_in_domain(start, cp_model.Domain.from_intervals(shift_ranges)).only_enforce_if(chosen)
                wi = model.new_optional_interval_var(start, duration, end, chosen, f'worker{index}-{w["id"]}-{t["id"]}')
                worker_pools[w['id']].append(wi)
                choices.append(chosen)
                crew_vars[(t['id'], w['id'])] = chosen
            model.add(sum(choices) == t['crew']*present)
            if t['machine']:
                machine_pools[t['machine']].append(interval)
        urgency = sum(t['priority'] for t in group)
        cost = model.new_int_var(0, data['horizon']*1440, f'cost{index}')
        model.add(cost == start).only_enforce_if(present)
        model.add(cost == 0).only_enforce_if(present.Not())
        forecast_penalty=0
        if data.get('forecasts') and group[0]['section_id'] in data['forecasts']:
            values=data['forecasts'][group[0]['section_id']]
            costs=[min(10000,round(sum(values[h:min(len(values),h+(duration+59)//60)])*100)) for h in range(data['horizon']*24)]
            hour=model.new_int_var(0,data['horizon']*24-1,f'hour{index}')
            model.add_division_equality(hour,start,60)
            traffic=model.new_int_var(0,10000,f'traffic{index}')
            model.add_element(hour,costs,traffic)
            forecast_penalty=model.new_int_var(0,10000,f'active_traffic{index}')
            model.add(forecast_penalty==traffic).only_enforce_if(present)
            model.add(forecast_penalty==0).only_enforce_if(present.Not())
        objective.append((urgency*1_000_000-duration*100-1000)*present-cost-forecast_penalty)
        candidates.append((group, start, end, present, crew_vars, duration))
    for choices in task_choices.values():
        model.add(sum(choices) <= 1)
    for pool in sections.values():
        model.add_no_overlap(pool)
    for pool in worker_pools.values():
        model.add_no_overlap(pool)
    for machine, pool in machine_pools.items():
        for i, b in enumerate(data['existing_blocks']):
            for j in range(b.get('machines', {}).get(machine, 0)):
                pool.append(model.new_fixed_size_interval_var(b['start'], b['end']-b['start'], f'booked-{machine}-{i}-{j}'))
        model.add_cumulative(pool, [1]*len(pool), data['machines'].get(machine, 0))
    model.maximize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 12
    solver.parameters.num_search_workers = 4
    status = solver.solve(model)
    blocks = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for group, start, end, present, crew_vars, duration in candidates:
            if solver.value(present):
                blocks.append(dict(id='BLOCK-'+'-'.join(t['id'] for t in group), section_id=group[0]['section_id'], line=group[0]['line'],
                    tasks=[t['id'] for t in group], departments=sorted(t['department'] for t in group), start=solver.value(start), end=solver.value(end), duration=duration,
                    crew_witness={t['id']:[wid for (tid,wid),v in crew_vars.items() if tid==t['id'] and solver.value(v)] for t in group}))
    served = {t for b in blocks for t in b['tasks']}
    return dict(blocks=sorted(blocks,key=lambda b:(b['start'],b['section_id'])), solver_status=solver.status_name(status), seconds=round(solver.wall_time,2),
        unscheduled=[dict(id=t['id'],reason='No feasible placement before the deadline with the supplied windows, train buffers, nearby shifts and shared resources.') for t in tasks if t['id'] not in served])


def validate(data, blocks):
    errors, seen, block_ids = [], set(), set()
    tasks, workers = {t['id']:t for t in data['tasks']}, {w['id']:w for w in data['workers']}
    resources = defaultdict(list)
    for b in blocks:
        if b['id'] in block_ids:
            errors.append('Repeated block ID.')
        block_ids.add(b['id'])
        if not b['tasks'] or any(t not in tasks or t in seen for t in b['tasks']) or len(set(b['tasks'])) != len(b['tasks']):
            errors.append('Unknown or repeated maintenance request.'); continue
        seen.update(b['tasks'])
        group = [tasks[t] for t in b['tasks']]
        start,end = b['start'],b['end']
        duration = max(t['duration'] for t in group)+data['setup']
        if type(start) is not int or type(end) is not int or not 0<=start<end<=data['horizon']*1440 or end-start!=duration or b['duration']!=duration:
            errors.append('Invalid block duration or horizon.'); continue
        if b['section_id']!=group[0]['section_id'] or b['line']!=group[0]['line'] or sorted(b['departments'])!=sorted(t['department'] for t in group):
            errors.append('Block metadata differs from its requests.')
        if not all(can_share(a,c) for a,c in combinations(group,2)):
            errors.append('Joint work has no recorded compatibility review.')
        if any(start<t['release'] or end>t['due'] for t in group):
            errors.append('Work falls outside a request release/deadline.')
        if not any(w['section_id']==b['section_id'] and w['start']<=start and w['end']>=end and (w['power'] or not any(t['power'] for t in group)) for w in data['windows']):
            errors.append('Block is outside its work window or power permission.')
        if any(zone(data,m['section_id'])==zone(data,b['section_id']) and start<m['end']+data['headway'] and end>m['start']-data['headway'] for m in data['movements']):
            errors.append('A train conflicts with this block or its headway.')
        if any(zone(data,o['section_id'])==zone(data,b['section_id']) and start<o['end'] and end>o['start'] for o in data['existing_blocks']):
            errors.append('Block conflicts with released work.')
        resources['section:'+zone(data,b['section_id'])].append((start,end,1))
        for t in group:
            crew=b['crew_witness'].get(t['id'],[])
            if len(crew)!=t['crew'] or len(set(crew))!=len(crew):
                errors.append('Insufficient or repeated crew in the feasibility check.')
            for wid in crew:
                w=workers.get(wid)
                if not w or not eligible(w,t) or not any(lo<=start and end<=hi for lo,hi in w['ranges']):
                    errors.append('Nearby worker is unavailable for the full block.')
                resources['worker:'+wid].append((start,end,1))
            if t['machine']:
                resources['machine:'+t['machine']].append((start,end,1))
    for b in data['existing_blocks']:
        for m,count in b.get('machines',{}).items():
            resources['machine:'+m].append((b['start'],b['end'],count))
    for key, intervals in resources.items():
        capacity = data['machines'].get(key.split(':',1)[1],0) if key.startswith('machine:') else 1
        active=0
        for _,delta in sorted([(s,n) for s,e,n in intervals]+[(e,-n) for s,e,n in intervals]):
            active+=delta
            if active>capacity:
                errors.append('Overlapping capacity exceeded: '+key);break
    return sorted(set(errors))


def generate(data):
    if len(data['tasks'])>150:
        raise ValueError('Plan at most 150 prepared maintenance requests per run.')
    result=solve(data)
    errors=validate(data,result['blocks'])
    if errors:
        raise ValueError('Generated plan failed audit: '+' '.join(errors))
    selected={t for b in result['blocks'] for t in b['tasks']}
    baseline=solve(data,joint=False,selected=selected)
    baseline_ids={t for b in baseline['blocks'] for t in b['tasks']}
    matched=[b for b in result['blocks'] if set(b['tasks'])<=baseline_ids]
    matched_ids={t for b in matched for t in b['tasks']}
    separate=sum(b['duration'] for b in baseline['blocks'] if set(b['tasks'])<=matched_ids)
    joint=sum(b['duration'] for b in matched)
    result['comparison']=dict(tasks=len(matched_ids),separate_minutes=separate,joint_minutes=joint,saved_minutes=separate-joint,
        baseline_status=baseline['solver_status'],note='Separate-block solver policy; only identical work served in both plans is compared. No measured train delay or ML accuracy is inferred.')
    result['validation']=dict(errors=[],checked_blocks=len(result['blocks']))
    return result
