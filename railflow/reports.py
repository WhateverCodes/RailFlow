"""Permission-scoped operational datasets and UTF-8 CSV / paginated PDF exports."""
import csv
import io
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

IST = timezone(timedelta(hours=5, minutes=30))
PDF_LOCK = threading.Lock()


def clock(value, service_date):
    if value is None:
        return ''
    day = date.fromisoformat(service_date) + timedelta(days=value // 1440)
    return f'{day.isoformat()} {value//60%24:02}:{value%60:02}'


def departure_status(row):
    difference = row['departure'] - row['scheduled_departure']
    return 'Early departure' if difference < 0 else 'Delayed departure' if difference > 0 else 'On-time departure'


def visible_rows(state, user):
    return [r for r in state['plan']['rows'] if user['role'] != 'master' or r['station'] == user['station']]


def dataset(state, user, kind, history=(), station=None, search=''):
    """Use only current records. No inferred priority, ownership or incident dates."""
    if kind not in ('timetable', 'backlog', 'disruptions', 'history'):
        raise ValueError('Unknown report dataset.')
    if user['role'] == 'customer' and kind != 'timetable':
        raise PermissionError('Operational reports are restricted to operating roles.')
    stations = {s['id']: s for s in state['stations']}
    if station and station not in stations:
        raise ValueError('Unknown report station.')
    if user['role'] == 'master' and station and station != user['station']:
        raise PermissionError('Report is outside your station permissions.')
    rows = visible_rows(state, user)
    if station:
        rows = [r for r in rows if r['station'] == station]
    if search:
        rows = [r for r in rows if search.casefold() in (r['train']+' '+r['name']).casefold()]
    rows.sort(key=lambda r: (r['arrival'], r['train']))
    result = []
    if kind == 'timetable':
        for r in rows:
            base = r.get('service_date', state['service_date'])
            result.append(dict(train=r['train'], name=r['name'], stop=r['stop']+1,
                station=r['station'], station_name=stations[r['station']]['name'], service_date=base,
                planned_arrival=clock(r['scheduled_arrival'],base), arrival=clock(r['arrival'],base),
                planned_departure=clock(r['scheduled_departure'],base), departure=clock(r['departure'],base),
                platform=r['platform'], previous_platform=r.get('previous_platform') or '',
                arrival_delay=r['arrival']-r['scheduled_arrival'], departure_delay=r['departure']-r['scheduled_departure'],
                status=departure_status(r), reason=r['reason']))
        headers = ['train','name','stop','station','station_name','service_date','planned_arrival','arrival','planned_departure','departure','platform','previous_platform','arrival_delay','departure_delay','status','reason']
    elif kind == 'backlog':
        for r in rows:
            delayed = max(r['delay'],r['departure']-r['scheduled_departure'])>0
            if not delayed and not r.get('risk'):
                continue
            base = r.get('service_date',state['service_date'])
            result.append(dict(train=r['train'], stop=r['stop']+1, station=r['station'],
                station_name=stations[r['station']]['name'], status='Delayed' if delayed else 'Turnaround risk',
                service_date=base, revision=state['revision'], platform=r['platform'],
                arrival=clock(r['arrival'],base),departure=clock(r['departure'],base),
                arrival_delay=r['delay'],departure_delay=r['departure']-r['scheduled_departure'],
                description=r['reason'] if delayed else r.get('risk_reason','Tight platform turnaround'),resolution=''))
        for r in state['plan']['unscheduled']:
            if (user['role']=='master' and r['station']!=user['station']) or (station and r['station']!=station):continue
            result.append(dict(train=r['train'],stop=r['stop']+1,station=r['station'],station_name=stations[r['station']]['name'],
                status='Unscheduled',service_date=state['service_date'],revision=state['revision'],description=r['reason'],resolution=r.get('review','')))
        for r in reversed(state.get('conflict_history',[])):
            if (user['role']=='master' and r['station']!=user['station']) or (station and r['station']!=station):continue
            result.append(dict(train=r['train'],station=r['station'],station_name=stations[r['station']]['name'],
                status='Resolved conflict',revision=r['revision'],service_date=r['service_date'],platform=r['platform'],
                description=r['message'],resolution=r['resolution']+'; '+'; '.join(f"{a['train']} P{a['platform']} {clock(a['arrival'],r['service_date'])} - {clock(a['departure'],r['service_date'])}" for a in r.get('after',[]))))
        headers=['train','stop','station','station_name','status','service_date','revision','platform','arrival','departure','arrival_delay','departure_delay','description','resolution']
    elif kind == 'disruptions':
        for e in state['events']:
            if (user['role']=='master' and e['station']!=user['station']) or (station and e['station']!=station):continue
            # No per-incident impact is stored; do not attribute overall metrics to it.
            updates = [c for c in state.get('last_changes',[]) if c['station']==e['station'] and (e['kind']=='closure' or c['train']==e.get('train'))]
            result.append(dict(incident=e['id'],kind=e['kind'],station=e['station'],station_name=stations[e['station']]['name'],
                train=e.get('train',''),platform=e.get('platform',''),minutes=e.get('minutes',''),
                start=clock(e.get('start'),state['service_date']),end=clock(e.get('end'),state['service_date']),
                created_at=e.get('created_at','Unavailable'),status='Active',reason=e['reason'],
                latest_recorded_changes='\n'.join(change_description(c,state['service_date']) for c in updates),
                validation='Passed' if state['plan']['validation']['passed'] else 'Failed',
                completeness='Complete' if state['plan']['validation']['complete'] else 'Incomplete'))
        headers=['incident','kind','station','station_name','train','platform','minutes','start','end','created_at','status','reason','latest_recorded_changes','validation','completeness']
    else:
        for h in history:
            for c in h['changes'] or [None]:
                result.append(dict(revision=h['revision'],timestamp=h['timestamp'],actor=h['actor'],note=h['note'],
                    service_date=h['service_date'],train=c['train'] if c else '',station=c['station'] if c else '',
                    station_name=stations.get(c['station'],{}).get('name',c['station']) if c else '',
                    change=change_description(c,h['service_date']) if c else 'No recorded timetable changes',
                    validation='Passed' if h['validation']['passed'] else 'Failed',
                    completeness='Complete' if h['validation']['complete'] else 'Incomplete',publication='Saved revision'))
        headers=['revision','timestamp','actor','note','service_date','train','station','station_name','change','validation','completeness','publication']
    return headers,result


def change_description(c, base):
    a,b=c.get('before'),c.get('after')
    def values(r):
        return f"arrival {clock(r['arrival'],r.get('service_date',base))}; departure {clock(r['departure'],r.get('service_date',base))}; P{r['platform']}" if r else 'Unscheduled / no prior assignment'
    detail=f"{c['train']}: Before: {values(a)}. After: {values(b)}."
    if a and b:
        detail+=f" Arrival change {b['arrival']-a['arrival']:+} min; departure change {b['departure']-a['departure']:+} min."
        if a['platform']!=b['platform']:detail+=f" Platform reassigned P{a['platform']} to P{b['platform']}."
    return detail+' Reason: '+c['reason']


def csv_bytes(headers, records):
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(headers)
    def safe(value):
        if value is None:return ''
        # Only text is untrusted. Numeric signed delays remain usable as numbers.
        if isinstance(value,str) and (re.match(r'^\s*[=+@-]',value) or value.startswith(('\t','\r','\n'))):return "'"+value
        return value
    writer.writerows([[safe(r.get(k,'')) for k in headers] for r in records])
    return ('\ufeff'+stream.getvalue()).encode('utf-8')


def pdf_bytes(title, headers, records, state, user):
    # Optional dependency: the simulator starts even if PDF tooling is unavailable.
    try:
        import uharfbuzz
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
    except ImportError as error:
        raise ValueError('PDF export needs the report dependencies. Run python -m pip install -r requirements-reports.txt.') from error
    font_path=Path(os.environ.get('RAILFLOW_PDF_FONT',str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/Nirmala.ttc')))
    if not font_path.is_file():
        raise ValueError('Set RAILFLOW_PDF_FONT to a Unicode TrueType font supporting your report languages.')
    with PDF_LOCK:
        if 'RailFlowReport' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('RailFlowReport',str(font_path),subfontIndex=0,shapable=True))
        body=ParagraphStyle('report-body',fontName='RailFlowReport',fontSize=10,leading=15,shaping=1,wordWrap='LTR',splitLongWords=1)
        head=ParagraphStyle('report-head',parent=body,fontSize=17,leading=22,spaceAfter=12)
        small=ParagraphStyle('report-small',parent=body,fontSize=9,leading=13)
        def p(text,style=body):return Paragraph(escape(str(text if text is not None else '')).replace('\n','<br/>'),style)
        generated=datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')
        buffer=io.BytesIO();doc=SimpleDocTemplate(buffer,pagesize=(595.28,841.89),leftMargin=38,rightMargin=38,topMargin=49,bottomMargin=45,title=title,author='RailFlow')
        story=[p(title,head),p(f'Generated: {generated} | Role: {user["role"]} | Official revision: {state["revision"]}',small),Spacer(1,10)]
        if user['role']=='master':story += [p('Station scope: '+user['station'],small),Spacer(1,7)]
        if kind_note := {'RailFlow - Disruption report':'Active incident records. Latest recorded changes are contextual and are not a per-incident causal impact calculation.',
                         'RailFlow - Backlog report':'Current delays/turnaround risks, unscheduled calls and the stored resolved-conflict log. Priority, creation date and assigned ownership are not stored.',
                         'RailFlow - Revision history':'Saved revisions and recorded changes. Separate approval timestamps are not stored.'}.get(title):
            story += [p(kind_note,small),Spacer(1,10)]
        scoped=visible_rows(state,user)
        total=sum(max(0,r['arrival']-r['scheduled_arrival'],r['departure']-r['scheduled_departure']) for r in scoped)
        incomplete=[r for r in state['plan']['unscheduled'] if user['role']!='master' or r['station']==user['station']]
        story += [p(f'Current plan in your scope: {len(scoped)} assigned calls; {total} delay minutes; {len(incomplete)} unscheduled calls. These are overall plan values, not per-incident impact.',small),Spacer(1,10)]
        if not records:story.append(p('No records match this report.'))
        else:
            # Key/value rows paginate even a long revision or incident across pages.
            data=[[p('Record / field'),p('Actual stored value')]]
            for i,r in enumerate(records,1):
                data.append([p(f'Record {i}'),p(' | '.join(str(r.get(k,'')) for k in ('revision','incident','train','station_name') if r.get(k)!='' and r.get(k) is not None))])
                for k in headers:
                    val=r.get(k,'')
                    if val=='':continue
                    # Bound individual text rows so even huge multiline records paginate.
                    text=str(val)
                    for part in range(0,len(text),900):data.append([p(k.replace('_',' ').title() if part==0 else k.replace('_',' ').title()+' (continued)'),p(text[part:part+900])])
            t=LongTable(data,colWidths=[126,393],repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCEEFF')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#C7D8E9'))]))
            story.append(t)
        def footer(c,d):
            c.setFont('RailFlowReport',9);c.setFillColor(colors.HexColor('#345877'))
            c.drawString(38,23,'RailFlow | Fictional railway operations');c.drawRightString(557,23,f'Page {d.page}')
        doc.build(story,onFirstPage=footer,onLaterPages=footer)
        return buffer.getvalue()
