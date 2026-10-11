"""Conservative night-possession CP-SAT model and independent feasibility audit."""
from collections import defaultdict
from itertools import combinations
from datetime import date
import copy
import time
from ortools.sat.python import cp_model

SETUP = 10
HEADWAY = 5


def compatible(a, b):
    if a['department']==b['department'] or a['section']!=b['section'] or a['line']!=b['line']:
        return False
    if abs(a['km_start']-b['km_start'])>4 or a['dependencies'] or b['dependencies']:
        return False
    if abs(a['due_day']-b['due_day'])>7:
        return False
    kinds = {a['task_type'], b['task_type']}
    if {'Deep screening', 'Track circuit testing'} <= kinds:
        return False
    if 'Deep screening' in kinds and any(t['power_required'] for t in [a, b]):
        return a['separation_confirmed'] and b['separation_confirmed']
    if 'Rail welding' in kinds and any(t['power_required'] for t in [a, b]):
        return a['separation_confirmed'] and b['separation_confirmed']
    return abs(a['due_day']-b['due_day'])<=7


def bundle(tasks, joint=True):
    waiting = sorted(tasks, key=lambda t: (-t['priority'], t['id'])) if joint else sorted(tasks, key=lambda t: t['id'])
    predecessors = {p for t in tasks for p in t['dependencies']}
    groups = []
    while waiting:
        group = [waiting.pop(0)]
        if joint and group[0]['id'] not in predecessors:
            for t in list(waiting):
                if len(group)==3:
                    break
                if t['id'] not in predecessors and all(compatible(t, other) for other in group):
                    group.append(t)
                    waiting.remove(t)
        groups.append(group)
    return groups


def resources(block, tasks):
    demand = defaultdict(int)
    section = int(block['section'].split('-')[-1])
    demand['section:'+block['section']] = 1
    demand['yard:'+str(section)] = 1
    demand['yard:'+str(section+1)] = 1
    for t in tasks:
        demand[t['department']] += t['crew']
        if t['machine']:
            demand[t['machine']] += 1
    return dict(demand)


def windows(data, section, duration, release, horizon, incidents):
    occupied = [(m['start']-HEADWAY, m['end']+HEADWAY) for m in data['movements'] if m['section']==section and m['start']<horizon*1440]
    occupied += [(e['start']-HEADWAY, e['end']+HEADWAY) for e in incidents if e['kind']=='freight' and e['section']==section]
    intervals = []
    for day in range(release, horizon):
        gaps = [(day*1440, day*1440+360)]
        for a, b in occupied:
            revised = []
            for lo, hi in gaps:
                if a>=hi or b<=lo:
                    revised.append((lo, hi))
                else:
                    if lo<a:
                        revised.append((lo, a))
                    if b<hi:
                        revised.append((b, hi))
            gaps = revised
        intervals.extend((lo, hi-duration) for lo, hi in gaps if hi-lo>=duration)
    return intervals


def block_for(group, start=0, ident=None):
    return dict(id=ident or 'BLOCK-'+group[0]['id'].removeprefix('SIM-TASK-'), section=group[0]['section'], line=group[0]['line'], tasks=[t['id'] for t in group], departments=sorted({t['department'] for t in group}), duration=max(t['duration'] for t in group)+SETUP, start=start, end=start+max(t['duration'] for t in group)+SETUP, power=any(t['power_required'] for t in group), decision='Proposed')


def normalized_config(config, data):
    h = config.get('horizon', 7)
    if h not in [7, 30]:
        raise ValueError('Choose a 7-day or 30-day horizon.')
    try:
        start = date.fromisoformat(config['start_date']).isoformat()
    except (ValueError, KeyError, TypeError):
        raise ValueError('Choose a valid plan start date.')
    incidents = config.get('incidents', [])
    if not isinstance(incidents, list) or len(incidents)>20:
        raise ValueError('The scenario supports up to 20 disruptions.')
    for e in incidents:
        if e.get('kind') not in ['freight', 'machine', 'urgent']:
            raise ValueError('Unknown disruption.')
        if e['kind']=='urgent':
            if e.get('task_id') not in {t['id'] for t in data['tasks']}:
                raise ValueError('Choose a scenario task.')
        else:
            if not all(type(e.get(k)) is int for k in ['start', 'end']) or not 0<=e['start']<e['end']<=h*1440:
                raise ValueError('Disruption must be inside the plan horizon.')
            if e['kind']=='freight' and e.get('section') not in {s['id'] for s in data['sections']}:
                raise ValueError('Unknown section.')
            if e['kind']=='machine' and e.get('machine') not in ['tamper', 'tower', 'welder']:
                raise ValueError('Unknown machine.')
    merged = [e for e in incidents if e['kind']!='machine']
    for machine in ['tamper', 'tower', 'welder']:
        ranges = sorted((e['start'], e['end']) for e in incidents if e['kind']=='machine' and e['machine']==machine)
        combined = []
        for lo, hi in ranges:
            if combined and lo<=combined[-1][1]:
                combined[-1][1] = max(hi, combined[-1][1])
            else:
                combined.append([lo, hi])
        merged += [dict(kind='machine', machine=machine, start=lo, end=hi) for lo, hi in combined]
    return dict(horizon=h, start_date=start, incidents=merged)


def effective_tasks(data, config):
    tasks = copy.deepcopy(data['tasks'])
    urgent = {e['task_id'] for e in config['incidents'] if e['kind']=='urgent'}
    for t in tasks:
        if t['id'] in urgent:
            t.update(priority=100, release_day=0, due_day=0, emergency=True)
    return tasks


def affected(block, incidents, lookup):
    for e in incidents:
        if e['kind']=='urgent' and e['task_id'] in block['tasks']:
            return True
        if e['kind']=='freight' and block['section']==e['section'] and block['start']<e['end']+HEADWAY and block['end']>e['start']-HEADWAY:
            return True
        if e['kind']=='machine' and any(lookup[t]['machine']==e['machine'] for t in block['tasks']) and block['start']<e['end'] and block['end']>e['start']:
            return True
    return False


def solve(data, config, joint=True, frozen=None, preferences=None, task_subset=None):
    horizon = config['horizon']
    tasks = effective_tasks(data, config)
    lookup = {t['id']: t for t in tasks}
    eligible = [t for t in tasks if t['release_day']<horizon and (task_subset is None or t['id'] in task_subset)]
    frozen = frozen or []
    fixed_ids = {t for b in frozen for t in b['tasks']}
    groups = [[lookup[t] for t in b['tasks']] for b in frozen]+bundle([t for t in eligible if t['id'] not in fixed_ids], joint)
    model = cp_model.CpModel()
    pools, variables, by_task, reward, unscheduled = defaultdict(list), [], {}, [], []
    caps = data['resources']
    for i, group in enumerate(groups):
        b = block_for(group)
        domain = windows(data, b['section'], b['duration'], max(t['release_day'] for t in group), horizon, config['incidents'])
        if not domain:
            if i<len(frozen):
                raise ValueError('A retained block no longer fits its authorization. Generate a fresh plan.')
            unscheduled += [dict(id=t['id'], reason='No authorized gap fits the full work duration and headway.') for t in group]
            continue
        start = model.new_int_var_from_domain(cp_model.Domain.from_intervals(domain), f's{i}')
        end = model.new_int_var(0, horizon*1440, f'e{i}')
        present = model.new_bool_var(f'p{i}')
        interval = model.new_optional_interval_var(start, b['duration'], end, present, f'i{i}')
        if i<len(frozen):
            model.add(present==1)
            model.add(start==frozen[i]['start'])
        for resource, demand in resources(b, group).items():
            pools[resource].append((interval, demand))
        for t in group:
            by_task[t['id']] = (start, end, present)
        day = model.new_int_var(0, horizon-1, f'day{i}')
        model.add_division_equality(day, start, 1440)
        scheduled_day = model.new_int_var(0, horizon, f'sd{i}')
        model.add(scheduled_day==day).only_enforce_if(present)
        model.add(scheduled_day==0).only_enforce_if(present.Not())
        # Priority coverage dominates all soft costs. Forecast and feedback are bounded.
        urgency = sum(int(t['priority']) for t in group)
        section_index = int(b['section'].split('-')[-1])-1
        hour = model.new_int_var(0, horizon*24-1, f'hour{i}')
        model.add_division_equality(hour, start, 60)
        traffic_costs = [int(sum(data['forecasts'][slot//24][section_index][slot%24:min(24, slot%24+(b['duration']+59)//60)])*100) for slot in range(horizon*24)]
        traffic = model.new_int_var(0, max(traffic_costs+[0]), f'traffic{i}')
        model.add_element(hour, traffic_costs, traffic)
        traffic_active = model.new_int_var(0, max(traffic_costs+[0]), f'traffic_active{i}')
        model.add(traffic_active==traffic).only_enforce_if(present)
        model.add(traffic_active==0).only_enforce_if(present.Not())
        preference = (preferences or {}).get(b['section'], 0)
        reward.append((urgency*1000-b['duration']*2-100+int(preference*100))*present-urgency*scheduled_day*12-traffic_active)
        variables.append((b, group, start, end, present, i<len(frozen)))
    for resource, entries in pools.items():
        cap = caps.get(resource, 1)
        for n, event in enumerate(config['incidents']):
            if event['kind']=='machine' and event['machine']==resource:
                entries.append((model.new_fixed_size_interval_var(event['start'], event['end']-event['start'], f'outage-{resource}-{n}'), cap))
        model.add_cumulative([x[0] for x in entries], [x[1] for x in entries], cap)
    for task in eligible:
        if task['id'] not in by_task:
            continue
        start, _, present = by_task[task['id']]
        for predecessor in task['dependencies']:
            if predecessor not in by_task:
                model.add(present==0)
            else:
                _, previous_end, previous_present = by_task[predecessor]
                model.add(present<=previous_present)
                model.add(start>=previous_end).only_enforce_if(present)
    model.maximize(sum(reward))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8 if horizon==7 else 14
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 26092
    status = solver.solve(model)
    blocks = []
    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        if frozen:
            raise ValueError('Retained blocks conflict with the revised constraints. Generate a fresh plan for a full reschedule.')
        return dict(blocks=[], unscheduled=[dict(id=t['id'], reason='Solver returned '+solver.status_name(status)) for t in eligible], solver_status=solver.status_name(status), seconds=round(solver.wall_time, 2))
    for b, group, start, end, present, fixed in variables:
        if solver.value(present):
            b.update(start=solver.value(start), end=solver.value(end), frozen=fixed)
            day = b['start']//1440
            expected = sum(data['forecasts'][day][int(b['section'].split('-')[-1])-1][b['start']%1440//60:min(24, (b['end']%1440+59)//60)])
            b['expected_freight'] = round(expected, 2)
            b['opportunity'] = round(max(0, min(100, 100-expected*12-b['duration']/30)), 1)
            b['reasons'] = [f"Priority {max(t['priority'] for t in group)}/100; {sum(t['overdue_days']>0 for t in group)} overdue activities.", f"{len(b['departments'])} department(s), {len(group)} tasks share one {b['duration']}-minute possession including {SETUP} minutes clearance.", 'Full work fits the synthetic authorization, with passenger and freight headway protected.', 'Power isolation and work separation reserved.' if b['power'] else 'Traffic possession; no power isolation required.', f"Forecast {expected:.2f} freight paths in this interval; listed paths remain protected."]
            blocks.append(b)
        else:
            unscheduled += [dict(id=t['id'], reason='Deferred by shared crew, machine, yard capacity or dependency constraints within this horizon.') for t in group]
    return dict(blocks=sorted(blocks, key=lambda b: (b['start'], b['section'])), unscheduled=unscheduled, solver_status=solver.status_name(status), seconds=round(solver.wall_time, 2), objective=round(solver.objective_value), bound=round(solver.best_objective_bound))


def validate(data, plan):
    """Audit outputs without relying on solver variables or its constraint code."""
    errors, seen, pool_events, assigned = [], set(), defaultdict(list), {}
    config = normalized_config(plan['config'], data)
    lookup = {t['id']: t for t in effective_tasks(data, config)}
    block_ids = set()
    for b in plan['blocks']:
        if b.get('id') in block_ids:
            errors.append('Duplicate block ID.')
        block_ids.add(b.get('id'))
        if not b.get('tasks') or any(t not in lookup for t in b['tasks']):
            errors.append('Unknown or empty task bundle.')
            continue
        group = [lookup[t] for t in b['tasks']]
        if any(type(b.get(k)) is not int for k in ['start', 'end']):
            errors.append('Block times must be whole minutes.')
            continue
        if not 0<=b['start']<b['end']<=config['horizon']*1440:
            errors.append(b['id']+': outside horizon.')
        if b['start']//1440 != (b['end']-1)//1440 or b['end']%1440>360 or b['start']%1440>=360:
            errors.append(b['id']+': outside authorized possession.')
        if b.get('duration')!=b['end']-b['start'] or sorted(b.get('departments', []))!=sorted({t['department'] for t in group}):
            errors.append(b['id']+': inconsistent block metadata.')
        if b['end']-b['start']!=max(t['duration'] for t in group)+SETUP:
            errors.append(b['id']+': incorrect work duration or clearance.')
        for t in group:
            if t['id'] in seen:
                errors.append(t['id']+': duplicated task.')
            seen.add(t['id'])
            assigned[t['id']] = b
            sec = next(s for s in data['sections'] if s['id']==t['section'])
            if t['section']!=b['section'] or t['line']!=b['line'] or not sec['km_start']<=t['km_start']<t['km_end']<=sec['km_end'] or b['start']<t['release_day']*1440:
                errors.append(t['id']+': location or release violation.')
            if t['power_required'] and not b.get('power'):
                errors.append(t['id']+': missing power isolation.')
        if any(not compatible(a, c) for a, c in combinations(group, 2)):
            errors.append(b['id']+': incompatible activities.')
        for m in data['movements']:
            if m['section']==b['section'] and b['start']<m['end']+HEADWAY and b['end']>m['start']-HEADWAY:
                errors.append(b['id']+': train headway violation.')
                break
        for e in config['incidents']:
            if e['kind']=='freight' and e['section']==b['section'] and b['start']<e['end']+HEADWAY and b['end']>e['start']-HEADWAY:
                errors.append(b['id']+': disrupted traffic window.')
        for resource, demand in resources(b, group).items():
            pool_events[resource] += [(b['start'], demand), (b['end'], -demand)]
    for e in config['incidents']:
        if e['kind']=='machine':
            cap = data['resources'][e['machine']]
            pool_events[e['machine']] += [(e['start'], cap), (e['end'], -cap)]
    for resource, events in pool_events.items():
        used = 0
        for _, delta in sorted(events):
            used += delta
            if used>data['resources'].get(resource, 1):
                errors.append(resource+': capacity exceeded.')
                break
    for tid, b in assigned.items():
        for parent in lookup[tid]['dependencies']:
            if parent not in assigned or assigned[parent]['end']>b['start']:
                errors.append(tid+': predecessor incomplete.')
    return sorted(set(errors))


def metrics(data, blocks, horizon, config=None):
    lookup = {t['id']: t for t in (effective_tasks(data, config) if config else data['tasks'])}
    tids = {t for b in blocks for t in b['tasks']}
    downtime = sum(b['end']-b['start'] for b in blocks)
    work = sum(max(lookup[t]['duration'] for t in b['tasks']) for b in blocks)
    return dict(tasks=len(tids), blocks=len(blocks), joint_blocks=sum(len({lookup[t]['department'] for t in b['tasks']})>1 for b in blocks), possession_minutes=downtime, availability=round(100*(1-downtime/(19*horizon*1440)), 2), utilization=round(100*work/downtime, 1) if downtime else 0, planned_before_due=sum(b['end']<=(lookup[t]['due_day']+1)*1440 for b in blocks for t in b['tasks']), protected_train_conflicts=0, average_block_minutes=round(downtime/len(blocks), 1) if blocks else 0)


def generate(data, raw_config, previous=None, preferences=None):
    config = normalized_config(raw_config, data)
    lookup = {t['id']: t for t in data['tasks']}
    frozen = []
    if previous:
        if previous['config']['horizon']!=config['horizon'] or previous['config']['start_date']!=config['start_date']:
            raise ValueError('Re-optimization keeps the existing dates and horizon.')
        affected_ids = {t for b in previous['blocks'] if affected(b, config['incidents'], lookup) for t in b['tasks']}
        while True:
            expanded = affected_ids | {t['id'] for t in data['tasks'] if set(t['dependencies']) & affected_ids}
            if expanded==affected_ids:
                break
            affected_ids=expanded
        frozen = [b for b in previous['blocks'] if not set(b['tasks']) & affected_ids]
    optimized = solve(data, config, frozen=frozen, preferences=preferences)
    baseline = solve(data, config, joint=False)
    plan = dict(config=config, **optimized, scenario=data['version'])
    errors = validate(data, plan)
    baseline_errors = validate(data, dict(config=config, blocks=baseline['blocks']))
    if errors or baseline_errors:
        raise ValueError('Feasibility audit failed: '+'; '.join((errors+baseline_errors)[:4]))
    opt_ids = {t for b in optimized['blocks'] for t in b['tasks']}
    base_ids = {t for b in baseline['blocks'] for t in b['tasks']}
    # A matched-work comparison includes only entire bundles served in both plans.
    comparable = [b for b in optimized['blocks'] if set(b['tasks'])<=base_ids]
    common = {t for b in comparable for t in b['tasks']}
    base_common = [b for b in baseline['blocks'] if set(b['tasks'])<=common]
    base_minutes = sum(b['duration'] for b in base_common)
    optimized_minutes = sum(b['duration'] for b in comparable)
    plan['metrics'] = metrics(data, optimized['blocks'], config['horizon'], config)
    plan['baseline'] = dict(**metrics(data, baseline['blocks'], config['horizon'], config), solver_status=baseline['solver_status'], blocks_detail=baseline['blocks'])
    plan['comparison'] = dict(tasks=len(common), baseline_minutes=base_minutes, optimized_minutes=optimized_minutes, minutes_saved=base_minutes-optimized_minutes, reduction=round(100*(base_minutes-optimized_minutes)/base_minutes, 1) if base_minutes else 0, note='Same retained tasks in both feasible schedules. Baseline uses separate department blocks with the same solver, limits and horizon; it is not a measured human plan.')
    plan['validation'] = dict(passed=True, violations=0, checked_blocks=len(plan['blocks']), checks=['Authorization and duration', 'Pairwise compatibility', 'Power isolation', 'Passenger and freight headway', 'Crew and machine capacity', 'Adjacent yard exclusion', 'Release times and precedence'])
    plan['preference_adjustments'] = preferences or {}
    plan['changes'] = []
    if previous:
        old = {t: b for b in previous['blocks'] for t in b['tasks']}
        new = {t: b for b in plan['blocks'] for t in b['tasks']}
        for tid in sorted(set(old)|set(new)):
            a, b = old.get(tid), new.get(tid)
            change = 'Retained' if a and b and a['start']==b['start'] and a['end']==b['end'] else 'Moved' if a and b else 'Newly scheduled' if b else 'Deferred'
            plan['changes'].append(dict(task_id=tid, change=change, old_start=a['start'] if a else None, new_start=b['start'] if b else None))
    return plan
