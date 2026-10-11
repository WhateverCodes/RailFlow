import csv,json,hashlib,secrets,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
rows=list(csv.DictReader((root/'data/workers.csv').open(encoding='utf-8-sig')))
assert len({r['worker_id'] for r in rows})==len(rows)
(root/'data/workers.json').write_text(json.dumps(rows,indent=2)+'\n')
accounts=[]
for r in rows:
 accounts.append({'id':r['worker_id'],'name':r['name'],'role':'worker','department':r['department_code']})
for code,name in [('TRK','Track'),('SIG','Signal'),('TRC','Traction')]:
 accounts.append({'id':'HEAD-'+code,'name':name+' Department Head','role':'head','department':code})
for a in accounts:
 a['salt']=secrets.token_hex(16)
 a['password_hash']=hashlib.pbkdf2_hmac('sha256',b'RailOps@123',a['salt'].encode(),100000).hex()
(root/'data/accounts.json').write_text(json.dumps(accounts,indent=2)+'\n')
print(f'Imported {len(rows)} workers; prepared {len(accounts)} prototype accounts.')
