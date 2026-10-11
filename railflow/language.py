"""Small local supervised intent model; deterministic slots are reviewed before use.

Multinomial Naive Bayes is fitted from labelled examples at startup. No API or GPU.
The score is model confidence, not a calibrated real-world probability.
"""
import math,re
from collections import Counter

EXAMPLES={
 'delay':['train is late by minutes','delay train at station','service running behind schedule','postpone train arrival','hold train for minutes','train delayed due to signal failure','train arrives later than expected','push arrival back by minutes'],
 'closure':['close platform from until','platform unavailable between and','shut platform for repairs','block platform for inspection','platform closed due to incident','suspend use of platform','maintenance closure of platform'],
 'early':['train arrives early by minutes','service ahead of schedule','train arriving sooner','advance train arrival by minutes','train reaches station early','arrival is earlier than planned']}
def tokens(text): return re.findall(r'[a-z]+',text.lower())
COUNTS={k:Counter(w for s in v for w in tokens(s)) for k,v in EXAMPLES.items()}
VOCAB=set(w for c in COUNTS.values() for w in c)

def interpret(text,state):
    words=tokens(text)
    if not text.strip() or len(text)>500: raise ValueError('Enter a disruption description of 1–500 characters.')
    scores={k:sum(math.log((counts[w]+1)/(sum(counts.values())+len(VOCAB))) for w in words if w in VOCAB) for k,counts in COUNTS.items()}
    maximum=max(scores.values());probs={k:math.exp(v-maximum) for k,v in scores.items()}
    total=sum(probs.values());probs={k:v/total for k,v in probs.items()}
    kind=max(probs,key=probs.get)
    explicit = set()
    for label, pattern in [('closure', r'\b(close|closed|closure|shut|block|unavailable)\b'),
                           ('delay', r'\b(delay|delayed|late|hold|postpone)\b'),
                           ('early', r'\b(early|earlier|advance|ahead)\b')]:
        if re.search(pattern, text, re.I): explicit.add(label)
    ambiguous = []
    if re.search(r"\b(not|never|maybe|possibly|either|cancel|reopen)\b", text, re.I):
        ambiguous.append("Confirm a definite new disruption; negated, tentative or cancellation requests need manual review")
    if len(explicit) == 1: kind = next(iter(explicit))
    elif len(explicit) > 1: ambiguous.append('Describe only one disruption type per request')
    if not explicit and (not any(w in VOCAB for w in words) or probs[kind] < .65):
        ambiguous.append('Specify whether this is a delay, early arrival or platform closure')
    def mention(value):
        return bool(re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)', text, re.I))
    stations = [s for s in state['stations'] if mention(s['id']) or mention(s['name']) or
                mention(s['name'].split(' · ')[0])]
    # Suppress shorter station names contained in a longer matched name.
    stations = [s for s in stations if not any(s['name'] != other['name'] and
                s['name'].lower() in other['name'].lower() and mention(other['name'])
                for other in stations)]
    trains = [t for t in state['trains'] if mention(t['id'])]
    draft = {'kind':kind, 'reason':'Platform closure' if kind=='closure' else
             'Reported early arrival' if kind=='early' else 'Operational delay'}
    if len(stations)==1: draft['station']=stations[0]['id']
    elif len(stations)>1: ambiguous.append('Specify one station')
    if len(trains)==1 and kind!='closure': draft['train']=trains[0]['id']
    elif len(trains)>1: ambiguous.append('Specify one train')
    platforms = re.findall(r'(?:platform\s*|\bP)(\d+)', text, re.I)
    if len(platforms)==1 and kind=='closure': draft['platform']=int(platforms[0])
    elif len(platforms)>1: ambiguous.append('Specify one platform')
    durations = re.findall(r'(\d+)\s*(hours?|hrs?|minutes?|mins?)\b', text, re.I)
    if kind!='closure':
        if len(durations)==1:
            amount, unit=durations[0]; draft['minutes']=int(amount)*(60 if unit.lower().startswith(('h')) else 1)
        elif len(durations)>1: ambiguous.append('Specify one delay duration in minutes or hours')
    times = []
    invalid_time = False
    for m in re.finditer(r'(?<![\w:])(\d{1,2})(?::([0-5]\d))?\s*(AM|PM)\b|(?<![\w:])(\d{1,2}):([0-5]\d)(?![\w:])', text, re.I):
        if m[1]:
            hour=int(m[1]); minute=int(m[2] or 0)
            if not 1<=hour<=12: invalid_time=True; continue
            times.append((hour%12+(12 if m[3].lower()=='pm' else 0))*60+minute)
        else:
            hour=int(m[4])
            if hour>47: invalid_time=True; continue
            times.append(hour*60+int(m[5]))
    if kind=='closure':
        if len(times)==2 and not invalid_time:
            draft['start'],draft['end']=times
            if times[1]<=times[0]: ambiguous.append('End must follow start; use 24:00 or later for next-day times')
        elif times or invalid_time: ambiguous.append('Specify two valid closure times, using HH:MM or AM/PM')
    needed=['station','platform','start','end'] if kind=='closure' else ['station','train','minutes']
    missing=[x for x in needed if x not in draft]
    if draft.get('minutes',1) not in range(1,241): ambiguous.append('Duration must be 1-240 minutes')
    if 'station' in draft:
        st=stations[0]
        if 'platform' in draft and not 1<=draft['platform']<=st['platforms']:
            ambiguous.append('Platform does not exist at this station')
        if 'train' in draft and not any(s['station']==st['id'] for s in trains[0]['stops']):
            ambiguous.append('Train does not call at this station')
    missing += ambiguous  # Backward-compatible review list for existing callers.
    return dict(draft=draft,confidence=round(probs[kind],3),missing=missing,
                clarification_required=bool(missing),ambiguities=ambiguous,
                review_required=True,model='Local Naive Bayes intent classifier + checked slot extraction',
                warning='Uncalibrated model score. Confirm every field before previewing. Missing or ambiguous requests do not modify state.')
