"""Bounded deterministic search, with independent validation of every candidate.

Cost = total call delay minutes + 5 * platform changes + changed calls
       + 10000 * unscheduled calls. Hard violations are never scored as feasible.
Delay is max(0, arrival lateness, departure lateness) per call, against advertised
times. Platform/changed-call costs compare with the previous operational plan.
The search tests at most eight priority orders; it is not globally optimal.
"""
from copy import deepcopy
from time import perf_counter
from .engine import schedule
from .validator import validate


def metrics(plan, reference=None):
    prior = {(r['train'], r['stop']): r for r in (reference or {}).get('rows', [])}
    delays = [max(0, r['arrival']-r['scheduled_arrival'],
                  r['departure']-r['scheduled_departure']) for r in plan['rows']]
    moved = changed = additional = 0
    for r in plan['rows']:
        before = prior.get((r['train'], r['stop']))
        if before:
            moved += r['platform'] != before['platform']
            changed += any(r[k] != before[k] for k in ('arrival', 'departure', 'platform'))
            prior_delay = max(0, before['arrival']-before['scheduled_arrival'],
                              before['departure']-before['scheduled_departure'])
            current_delay = max(0, r['arrival']-r['scheduled_arrival'],
                                r['departure']-r['scheduled_departure'])
            additional += max(0, current_delay-prior_delay)
    unscheduled = len(plan['unscheduled'])
    return dict(total_delay=sum(delays), additional_delay=additional, maximum_delay=max(delays, default=0),
                platform_changes=moved, changed_calls=changed, unscheduled=unscheduled,
                score=sum(delays)+5*moved+changed+10000*unscheduled)


def compare_strategies(state, reference=None):
    """Return safest best plan and measured summaries; never mutate either input."""
    start = perf_counter()
    baseline = schedule(deepcopy(state))
    baseline_check = validate(state, baseline)
    baseline_metrics = metrics(baseline, reference)
    baseline_ms = (perf_counter()-start)*1000
    start = perf_counter()
    trains = state['trains']
    # Preserve the baseline as a fallback. Fixed bounds keep large demos responsive.
    normal = sorted(trains, key=lambda t: (t['stops'][0]['arrival'], t['id']))
    constrained = sorted(normal, key=lambda t: (-sum(bool(s.get('required_platform')) for s in t['stops']), t['stops'][0]['arrival'], t['id']))
    orders = [[t['id'] for t in normal], [t['id'] for t in constrained]]
    for i in range(min(6, max(0, len(normal)-1))):
        order = list(orders[0]); order[i], order[i+1] = order[i+1], order[i]
        orders.append(order)
    best, best_metrics, best_check = baseline, baseline_metrics, baseline_check
    attempted = rejected = 0
    recovery_orders = []
    if baseline["unscheduled"]:
        affected = list(dict.fromkeys(u["train"] for u in baseline["unscheduled"]))
        for tid in affected[:12]:
            recovery_orders.append([tid] + [t["id"] for t in normal if t["id"] != tid])
        recovery_orders.append(list(reversed(orders[0])))
        recovery_orders.append([t["id"] for t in sorted(normal, key=lambda t: (min(s["arrival"]+state["max_delay"] for s in t["stops"]), t["id"]))])
    orders += [o for o in recovery_orders if o not in orders]
    for order in orders:
        attempted += 1
        candidate = schedule(deepcopy(state), train_order=order, reference=reference or baseline)
        check = validate(state, candidate)
        if not check['passed']:
            rejected += 1
            continue
        measured = metrics(candidate, reference)
        # A complete schedule always outranks an incomplete one.
        if (not best_check['passed'] or
            (measured['unscheduled'], measured['score']) < (best_metrics['unscheduled'], best_metrics['score'])):
            best, best_metrics, best_check = candidate, measured, check
    search_ms = (perf_counter()-start)*1000
    improved = best is not baseline
    if improved:
        best['algorithm'] = 'Minimum-disruption bounded greedy-order search; not a global optimum'
    summary = dict(selected='minimum_disruption' if improved else 'baseline',
                   objective='delay minutes + 5 × platform changes + changed calls + 10000 × unscheduled calls; fewer unscheduled calls take precedence',
                   baseline=dict(**baseline_metrics, execution_ms=round(baseline_ms, 3), validation=baseline_check['passed'], complete=baseline_check['complete']),
                   minimum_disruption=dict(**best_metrics, execution_ms=round(search_ms, 3), validation=best_check['passed'], complete=best_check['complete']),
                   candidates=attempted, rejected_candidates=rejected, recovery_attempted=bool(recovery_orders),
                   explanation=('Fewer unscheduled calls; all independent checks passed.' if best_metrics['unscheduled'] < baseline_metrics['unscheduled'] else 'Lower measured disruption cost; all independent checks passed.') if improved else 'No better validated candidate found; baseline retained.',
                   delay_definition='Sum of max(0, arrival lateness, departure lateness) per call against advertised times; not passenger delay or delay per whole train.')
    return best, summary
