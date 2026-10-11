"""Validate and convert the supplied maintenance-request CSV without inventing schedule data."""
import csv,datetime,hashlib,json,math,pathlib,collections
root=pathlib.Path(__file__).resolve().parents[1]
source=root/'data/maintenance-requests.csv'
rows=list(csv.DictReader(source.open(encoding='utf-8-sig',newline='')))
expected=['request_id','department','task_type','corridor_name','line_type','longitude','latitude','defect_severity','backlog_age_days','required_duration_mins','timestamp']
assert rows and list(rows[0])==expected,'Unexpected CSV headers'
assert len({r['request_id'] for r in rows})==len(rows),'Duplicate request IDs'
mapping={'TMS':'TRK','SMMS':'SIG','TDMS':'TRC'}
converted=[]
for r in rows:
 assert all(isinstance(v,str) and v.strip() for v in r.values()),'Missing value'
 assert r['department'] in mapping,'Unknown source department'
 row={**r,'department_code':mapping[r['department']]}
 for k in ['defect_severity','backlog_age_days','required_duration_mins']:row[k]=int(row[k])
 for k in ['longitude','latitude']:row[k]=float(row[k]);assert math.isfinite(row[k])
 assert 1<=row['defect_severity']<=5 and row['backlog_age_days']>=0 and row['required_duration_mins']>0
 assert -180<=row['longitude']<=180 and -90<=row['latitude']<=90
 datetime.datetime.fromisoformat(row['timestamp']) # Validate only; preserve the exact source string.
 converted.append(row)
manifest={'filename':'SIH_ROUND2_DATASET_SAACHI.csv','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'row_count':len(rows),'department_counts':dict(collections.Counter(r['department_code'] for r in converted)),'department_mapping':mapping,'timestamp_timezone':'unspecified'}
(root/'data/maintenance-requests.json').write_text(json.dumps(converted,indent=2)+'\n')
(root/'data/maintenance-requests.meta.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
