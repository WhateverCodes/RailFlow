"""Deterministic synthetic railway scenario. No uploaded data is altered here."""
import math
import random
from datetime import date, timedelta
from collections import Counter
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import brier_score_loss, mean_absolute_error

SEED = 26092
VERSION = 'railblock-sim-v1'
DEPS = ['TRK', 'SIG', 'TRC']
KINDS = {
    'TRK': [('Track inspection', 60, None), ('Deep screening', 240, 'tamper'), ('Rail welding', 90, 'welder')],
    'SIG': [('Signal inspection', 45, None), ('Track circuit testing', 60, None)],
    'TRC': [('OHE inspection', 90, 'tower'), ('OHE isolation work', 120, 'tower')],
}
FEATURES = ['Age (years)', 'Previous defects', 'Overdue days', 'Traffic load', 'Condition deterioration', 'Weather stress']


def feature(r):
    return [r.uniform(1, 35), r.randint(0, 8), r.randint(0, 60), r.uniform(.2, 1), r.uniform(.05, 1), r.uniform(.1, 1)]


def build_scenario():
    r = random.Random(SEED)
    stations = [dict(id=f'SIM-ST-{i+1:02}', name=f'Demo station {i+1:02}', km=i*12) for i in range(20)]
    sections = [dict(id=f'SIM-SEC-{i+1:02}', name=f'Station {i+1:02} – {i+2:02}', from_station=stations[i]['id'], to_station=stations[i+1]['id'], km_start=i*12, km_end=(i+1)*12, power_zone=f'SIM-PZ-{i+1:02}', lines=['Up', 'Down'], parallel_line_available=True) for i in range(19)]
    # Independent synthetic historical assets; test assets never occur in training.
    x = np.array([feature(r) for _ in range(6000)])
    hazard = .0005 + x[:, 0]*.00009 + x[:, 1]*.0007 + x[:, 2]*.00005 + x[:, 3]*.001 + x[:, 4]**2*.013 + x[:, 5]*.001
    survival = np.array([-math.log(max(r.random(), 1e-8))/h for h in hazard])
    models, validation = [], []
    for days in [7, 30, 90]:
        y = (survival <= days).astype(int)
        model = RandomForestClassifier(n_estimators=80, max_depth=8, min_samples_leaf=18, random_state=SEED, n_jobs=1)
        model.fit(x[:4800], y[:4800])
        probability = model.predict_proba(x[4800:])[:, 1]
        validation.append(dict(horizon_days=days, brier=round(brier_score_loss(y[4800:], probability), 4), prevalence=round(float(y[4800:].mean()), 4)))
        models.append(model)
    held = np.maximum.accumulate(np.array([m.predict_proba(x[4800:])[:, 1] for m in models]).T, axis=1)
    for i, horizon in enumerate([7, 30, 90]):
        validation[i]['brier'] = round(brier_score_loss((survival[4800:]<=horizon).astype(int), held[:, i]), 4)
    assets = []
    for dep, count in [('TRK', 300), ('SIG', 150), ('TRC', 120)]:
        for i in range(count):
            sec = sections[i % 19]
            assets.append(dict(id=f'SIM-{dep}-A{i+1:03}', department=dep, section=sec['id'], km=round(sec['km_start']+r.uniform(.2, 11.5), 2), criticality=round(r.uniform(.4, 1), 2), features=feature(r), provenance='Synthetic'))
    predicted = np.maximum.accumulate(np.array([m.predict_proba([a['features'] for a in assets])[:, 1] for m in models]).T, axis=1)
    for a, p in zip(assets, predicted):
        a['risk'] = dict(zip(['7', '30', '90'], [round(float(n), 4) for n in p]))
    chosen = r.sample(assets, 500)
    tasks = []
    for i, a in enumerate(chosen):
        kind, duration, machine = r.choice(KINDS[a['department']])
        release = 0 if i < 100 else r.randrange(28)
        severity = r.randint(3, 5) if i < 100 else r.randint(1, 3)
        due = min(29, release+r.randint(2, 7))
        overdue = r.randrange(1, 40) if i < 100 else 0
        components = dict(asset=round(a['criticality']*15, 1), safety=round(severity/5*25, 1), urgency=round((1-(due-release)/10)*15, 1), failure=round(a['risk']['30']*25, 1), overdue=round(min(overdue/30, 1)*10, 1), operational=round(a['features'][3]*10, 1))
        tasks.append(dict(id=f'SIM-TASK-{i+1:04}', department=a['department'], asset_id=a['id'], section=a['section'], km_start=a['km'], km_end=round(a['km']+.3, 2), line='Up' if i % 3 else 'Down', task_type=kind, duration=duration, block_type='Traffic + power' if a['department']=='TRC' else 'Traffic', release_day=release, due_day=due, severity=severity, safety_criticality=severity/5, asset_criticality=a['criticality'], overdue_days=overdue, crew=r.choice([2, 3, 4]), machine=machine, power_required=a['department']=='TRC', separation_confirmed=i % 4 != 0, dependencies=[], components=components, priority=round(sum(components.values()), 1), risk=a['risk'], provenance='Synthetic', traffic_impact=round(a['features'][3], 2)))
    # Acyclic precedence: inspection first, later work in the same section.
    for i in range(35, 500, 31):
        earlier = next((t for t in tasks[:i] if t['section']==tasks[i]['section'] and t['release_day']<=tasks[i]['release_day']), None)
        if earlier:
            tasks[i]['dependencies'] = [earlier['id']]
    defects = [dict(id=f'SIM-DEF-{i+1:03}', task_id=t['id'], asset_id=t['asset_id'], severity=t['severity']) for i, t in enumerate(tasks[:100])]
    # Separate 30-day historical traffic and 30-day future scenario; 280 services/day.
    services, movements = [], []
    for day in range(-30, 30):
        for i in range(280):
            kind = 'Passenger' if i < 200 else 'Freight'
            origin = r.randrange(19)
            destination = min(19, origin+r.randint(1, 3))
            minute = r.randint(380, 1350) if kind=='Passenger' else r.randint(350, 1410)
            service_id = f'SIM-{day+1:02}-{i+1:03}'
            services.append(dict(id=service_id, day=day, kind=kind, origin=stations[origin]['id'], destination=stations[destination]['id']))
            for step, sec in enumerate(sections[origin:destination]):
                start = day*1440+minute+step*8
                movements.append(dict(service_id=service_id, section=sec['id'], start=start, end=start+7, kind=kind, line='Up' if i%2 else 'Down'))
    counts = Counter((m['start']//1440, m['section'], (m['start']%1440)//60) for m in movements if m['kind']=='Freight')
    fx, fy, days = [], [], []
    for day in range(-30, 30):
        for sec in range(19):
            for hour in range(24):
                fx.append([day % 7, hour, sec, 1+(sec%4)*.1])
                fy.append(counts[(day, sections[sec]['id'], hour)])
                days.append(day)
    fx, fy, days = np.array(fx), np.array(fy), np.array(days)
    forecast = RandomForestRegressor(n_estimators=50, max_depth=9, min_samples_leaf=12, random_state=SEED, n_jobs=1)
    forecast.fit(fx[days < -9], fy[days < -9])
    mae = mean_absolute_error(fy[(days>=-9)&(days<0)], forecast.predict(fx[(days>=-9)&(days<0)]))
    forecasts = forecast.predict(fx[days>=0]).reshape(30, 19, 24).round(3).tolist()
    return dict(version=VERSION, seed=SEED, stations=stations, sections=sections, assets=assets, tasks=tasks, defects=defects, services=[s for s in services if s['day']>=0], movements=[m for m in movements if m['start']>=0], forecasts=forecasts,
        resources=dict(TRK=12, SIG=8, TRC=6, tamper=1, welder=2, tower=2),
        models=dict(risk=dict(name='Random forest', training_rows=4800, validation_rows=1200, validation=validation, features=FEATURES, feature_importance=[round(float(v), 3) for v in models[1].feature_importances_]), traffic=dict(name='Random forest regression', train_days=21, validation_days=9, mae=round(float(mae), 3)), provenance='Trained and evaluated on generated data only. These probabilities are not validated railway failure estimates.'),
        assumptions=['Synthetic authorizations: each section has a daily 00:00–06:00 possession window; 5-minute train headway on both lines.', 'Power isolation reserves both lines in the section. Adjacent possessions share a station-yard resource.', 'Synthetic crew pools and machines are available in these night windows. Named workers remain manually assigned in department accounts.', 'Conditional coalescing requires the scenario separation flag and power isolation. No live railway clearances are connected.', 'Imported maintenance requests require asset mapping, permissions and traffic data before they can enter this simulation.'])


def describe(data):
    return {k: data[k] for k in ['version', 'seed', 'stations', 'sections', 'assets', 'tasks', 'defects', 'resources', 'models', 'assumptions']} | {'counts': dict(stations=20, sections=19, assets=570, tasks=500, defects=100, passenger_services=6000, freight_paths=2400, traffic_days=30), 'traffic': data['movements'], 'forecasts': data['forecasts']}
