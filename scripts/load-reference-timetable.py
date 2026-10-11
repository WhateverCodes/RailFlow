"""Append the researched, explicitly incomplete timetable reference to the local register."""
import datetime
import http.cookiejar
import json
import os
import urllib.request

base='http://localhost:3000'
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path,body=None):
    request=urllib.request.Request(base+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','Origin':base})
    with opener.open(request,timeout=120) as response:return json.load(response)
call('/api/app',{'action':'login','id':'CONTROL-01','password':os.environ.get('RAILBLOCK_CONTROLLER_PASSWORD','RailOps@123')})
state=call('/api/operations')
date=(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30)))+datetime.timedelta(days=1)).date().isoformat()
result=call('/api/operations',{'action':'reference','revision':state['revision'],'start_date':date,'horizon':7})
updated=call('/api/operations')
print(result['message'])
print('Saved sections:',len(updated['input']['sections']))
print('Saved movements:',len(updated['input']['movements']))
print('Work windows were not created or automatically verified.')
call('/api/app',{'action':'logout'})
