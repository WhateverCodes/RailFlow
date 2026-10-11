import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, openSync, closeSync } from 'node:fs';

if (!existsSync('.venv/Scripts/python.exe')) {
  console.error('Install the local planner first: python3 -m venv .venv && .venv/bin/pip install -r planner/requirements.txt');
  process.exit(1);
}
const env = { ...process.env, RAILBLOCK_ENGINE_TOKEN: randomBytes(32).toString('hex') };
const children = [];
let closing = false;
function stop(code=0) {
  if (closing) return;
  closing=true;
  for (const child of children) child.kill('SIGTERM');
  setTimeout(()=>process.exit(code), 800).unref();
}
for (const signal of ['SIGINT','SIGTERM']) process.on(signal, ()=>stop());
mkdirSync('.wrangler/logs',{recursive:true});
function launch(command, args, logName) {
  // Keep service output independent of a chat turn's terminal pipe lifetime.
  const log=openSync(`.wrangler/logs/${logName}.log`,'a');
  const child=spawn(command,args,{env,stdio:['ignore',log,log]});
  closeSync(log);
  children.push(child);
  child.on('error',e=>{console.error(e.message);stop(1)});
  child.on('exit',code=>{if(!closing)stop(code||1)});
}
launch('.venv/Scripts/python.exe',['-u','planner/server.py'],'planner');
launch('node',['node_modules/vinext/dist/cli.js','dev','--host','127.0.0.1','--port','3000'],'app');
console.log('Starting RailBlock AI at http://localhost:3000. Local service logs are in .wrangler/logs/.');
