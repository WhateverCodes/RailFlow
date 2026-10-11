"""Loopback-only compute service. Application authorization stays in the app API."""
import json
import os
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from scenario import build_scenario, describe
from engine import generate, validate, metrics
import operations
import freight_model

DATA = build_scenario()
LOCK = threading.Lock()
TOKEN = os.environ.get('RAILBLOCK_ENGINE_TOKEN')
if not TOKEN:
    raise RuntimeError('Start with npm run dev so the app and planner share a local service token.')


class Handler(BaseHTTPRequestHandler):
    def respond(self, value, status=200):
        payload = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path=='/health':
            return self.respond({'ready': True})
        if not secrets.compare_digest(self.headers.get('X-Engine-Token', ''), TOKEN):
            return self.respond({'error': 'App authentication required.'}, 403)
        if self.path=='/dataset':
            return self.respond(describe(DATA))
        return self.respond({'error': 'Not found'}, 404)

    def do_POST(self):
        if not secrets.compare_digest(self.headers.get('X-Engine-Token', ''), TOKEN):
            return self.respond({'error': 'App authentication required.'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0<length<3_000_000:
                return self.respond({'error': 'Invalid request size.'}, 413)
            body = json.loads(self.rfile.read(length))
            if self.path=='/ml/status':
                return self.respond(freight_model.status())
            if self.path in ['/ml/train','/ml/activate']:
                if not LOCK.acquire(blocking=False):
                    return self.respond({'error':'A model or planning run is already in progress.'},409)
                try:
                    if self.path=='/ml/train':
                        return self.respond(freight_model.train(body['csv'],body['source'],body['sections']))
                    return self.respond(freight_model.activate(body['id']))
                finally:
                    LOCK.release()
            if self.path=='/operations/generate':
                if not LOCK.acquire(blocking=False):
                    return self.respond({'error':'A planning run is already in progress.'},409)
                try:
                    data=body['input'];forecast,model_info=freight_model.forecasts(data)
                    data['forecasts']=forecast
                    result=operations.generate(data)
                    result.update(ml=model_info,forecast_snapshot=forecast)
                    return self.respond(result)
                finally:
                    LOCK.release()
            if self.path=='/operations/validate':
                return self.respond({'errors':operations.validate(body['input'],body['blocks'])})
            if self.path=='/generate':
                if not LOCK.acquire(blocking=False):
                    return self.respond({'error': 'A planning run is already in progress. Please retry after it finishes.'}, 409)
                try:
                    return self.respond(generate(DATA, body['config'], body.get('previous'), body.get('preferences')))
                finally:
                    LOCK.release()
            if self.path=='/validate':
                errors = validate(DATA, body['plan'])
                return self.respond(dict(errors=errors, metrics=metrics(DATA, body['plan']['blocks'], body['plan']['config']['horizon'], body['plan']['config'])))
            return self.respond({'error': 'Not found'}, 404)
        except (ValueError, KeyError, TypeError) as e:
            return self.respond({'error': str(e)}, 400)
        except Exception:
            traceback.print_exc()
            return self.respond({'error': 'The local planner failed. See its terminal log.'}, 500)


if __name__=='__main__':
    print('RailBlock planning engine ready on localhost:8008', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8008), Handler).serve_forever()
