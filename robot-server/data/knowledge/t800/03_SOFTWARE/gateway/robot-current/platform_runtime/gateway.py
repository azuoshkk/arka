"""One authenticated HTTP/WebSocket entry point for the existing Arcanjo UI."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import time
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType
from platform_runtime.auth import AuthStore
from platform_runtime.health import system_snapshot
from platform_runtime.logging_config import configure_logging
from platform_runtime.policy import validate_observer_message, validate_gateway_message

LOG = logging.getLogger('gateway')
PUBLIC = Path(__file__).parent / 'web'


def create_app(state_dir='.state', static_dir='out', bridge_port=8091, port=8088, secure_cookie=False, public_origin=None):
    auth = AuthStore(Path(state_dir) / 'account.json')
    cookie = f't800_session_{port}'
    static = Path(static_dir).resolve()
    attempts = {}
    sockets = {}
    login_lock = asyncio.Lock()
    bridge_url = f'http://127.0.0.1:{bridge_port}'

    def check_origin(request):
        expected = public_origin or f'{request.scheme}://{request.host}'
        return request.headers.get('Origin') == expected

    @web.middleware
    async def guard(request, handler):
        public = request.path in {'/login', '/login.js', '/login.css', '/api/login', '/livez'}
        if not public and not auth.valid(request.cookies.get(cookie)):
            if request.path.startswith('/api/') or request.path == '/health':
                raise web.HTTPUnauthorized(text='Login necessário')
            raise web.HTTPFound('/login')
        if (request.method not in {'GET', 'HEAD'} or request.path == '/api/ws') and not check_origin(request):
            raise web.HTTPForbidden(text='Origem inválida')
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        if not response.prepared:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'same-origin'
        return response

    app = web.Application(middlewares=[guard], client_max_size=16384)

    async def lifecycle(app):
        async with ClientSession(timeout=ClientTimeout(total=5)) as client:
            app['client'] = client
            app['health'] = {'status': 'degraded', 'bridge': {'status': 'offline'}}
            async def monitor():
                probe = None
                while True:
                    try:
                        if probe is None or probe.closed:
                            probe = await client.ws_connect(bridge_url + '/health-ws', compress=0)
                        await probe.send_json({'action': 'health'})
                        bridge = await asyncio.wait_for(probe.receive_json(), timeout=2)
                    except Exception:
                        if probe is not None:
                            await probe.close()
                        probe = None
                        bridge = {'status': 'offline'}
                    try:
                        system = await asyncio.to_thread(system_snapshot)
                    except Exception:
                        system = {'status': 'error'}
                    status = bridge.get('status', 'error')
                    app['health'] = dict(status=status if status == 'healthy' else 'degraded',
                                         service='arcanjo', mode='observer', bridge=bridge, system=system)
                    await asyncio.sleep(2)
            monitor_task = asyncio.create_task(monitor())
            yield
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            for connections in list(sockets.values()):
                await asyncio.gather(*(ws.close() for ws in list(connections)), return_exceptions=True)
    app.cleanup_ctx.append(lifecycle)

    async def login(request):
        now = time.monotonic()
        key = request.remote
        # One-minute global and per-IP budget; no passwords or tokens in logs.
        for expired in [k for k, values in attempts.items() if not values or values[-1] < now - 60]:
            del attempts[expired]
        recent = [t for t in attempts.get(key, []) if t > now - 60]
        if len(recent) >= 5 or sum(len(v) for v in attempts.values()) >= 40:
            raise web.HTTPTooManyRequests(text='Aguarde um minuto')
        attempts[key] = recent + [now]
        try:
            data = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        async with login_lock:
            valid = await asyncio.to_thread(auth.check_password, data.get('username'), data.get('password'))
        if not valid:
            LOG.warning('Login rejeitado')
            raise web.HTTPUnauthorized(text='Usuário ou senha inválidos')
        auth.revoke(request.cookies.get(cookie))
        token = auth.create_session()
        response = web.json_response({'username': auth.username, 'role': auth.role})
        response.set_cookie(cookie, token, httponly=True, secure=secure_cookie,
                            samesite='Strict', max_age=auth.ttl, path='/')
        LOG.info('Login realizado')
        return response

    async def logout(request):
        token = request.cookies.get(cookie)
        auth.revoke(token)
        for ws in list(sockets.get(token, set())):
            await ws.close(code=1008, message=b'Logout')
        response = web.json_response({'ok': True})
        response.del_cookie(cookie, path='/')
        return response

    async def session(request):
        controls = auth.role in {'admin', 'operator'}
        return web.json_response(dict(
            username=auth.username,
            role=auth.role,
            mode='control' if controls else 'observer',
            controls_enabled=controls
        ))

    async def health(request):
        return web.json_response(app['health'], status=200 if app['health']['status'] == 'healthy' else 503)

    async def websocket(request):
        token = request.cookies.get(cookie)
        if sum(len(value) for value in sockets.values()) >= 8:
            raise web.HTTPServiceUnavailable(text='Limite de clientes')
        try:
            upstream = await app['client'].ws_connect(bridge_url, max_msg_size=16 * 1024 * 1024, compress=0)
        except Exception:
            raise web.HTTPServiceUnavailable(text='Bridge offline')
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16384, compress=False)
        await ws.prepare(request)
        sockets.setdefault(token, set()).add(ws)

        async def inbound():
            window, count = time.monotonic(), 0
            async for msg in ws:
                if not auth.valid(token):
                    break
                if time.monotonic() - window > 1:
                    window, count = time.monotonic(), 0
                count += 1
                if count > 60:
                    await ws.close(code=1008, message=b'Rate limit')
                    break
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        validate_gateway_message(data, auth.role)
                    except (ValueError, TypeError) as exc:
                        await ws.send_json({'type': 'command_error', 'error': str(exc)})
                        continue
                    if data.get('action') == 'acquire_control':
                        data['name'] = auth.username
                    await upstream.send_json(data)
        async def outbound():
            async for msg in upstream:
                if not auth.valid(token):
                    break
                if msg.type == WSMsgType.TEXT:
                    await asyncio.wait_for(ws.send_str(msg.data), timeout=1)
                elif msg.type == WSMsgType.BINARY:
                    await asyncio.wait_for(ws.send_bytes(msg.data), timeout=1)
        async def expire():
            while auth.valid(token):
                await asyncio.sleep(2)
        tasks = [asyncio.create_task(fn()) for fn in (inbound, outbound, expire)]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await upstream.close()
            await ws.close()
            sockets[token].discard(ws)
            if not sockets[token]:
                del sockets[token]
        return ws

    async def public_file(request):
        name = {'/login': 'login.html', '/login.js': 'login.js', '/login.css': 'login.css'}[request.path]
        return web.FileResponse(PUBLIC / name)

    async def assets(request):
        target = (static / (request.match_info['path'] or 'index.html')).resolve()
        if not target.is_relative_to(static):
            raise web.HTTPForbidden()
        if target.is_dir():
            target = target / 'index.html'
        if not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def live(request):
        return web.json_response({'status': 'alive'})

    app.router.add_get('/livez', live)
    for path in ('/login', '/login.js', '/login.css'):
        app.router.add_get(path, public_file)
    app.router.add_post('/api/login', login)
    app.router.add_post('/api/logout', logout)
    app.router.add_get('/api/session', session)
    app.router.add_get('/health', health)
    app.router.add_get('/api/ws', websocket)
    app.router.add_get('/{path:.*}', assets)
    return app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8088)
    parser.add_argument('--bridge-port', type=int, default=8091)
    parser.add_argument('--state-dir', default='.state')
    parser.add_argument('--static-dir', default='out')
    parser.add_argument('--secure-cookie', action='store_true')
    parser.add_argument('--public-origin')
    args = parser.parse_args()
    configure_logging(args.state_dir, 'gateway')
    web.run_app(create_app(args.state_dir, args.static_dir, args.bridge_port, args.port,
                           args.secure_cookie, args.public_origin), host=args.host, port=args.port,
                access_log=None)
