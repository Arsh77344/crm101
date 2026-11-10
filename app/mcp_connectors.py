from __future__ import annotations

"""Managed MCP connector registry for V42 using the official MCP Python SDK.

A registry row is only setup metadata. It becomes Connected only after the SDK
negotiates the server protocol and list_tools() returns at least one real tool.
The SDK's automatic negotiation supports both the current 2026-era discovery flow
and compatible legacy initialize-handshake servers.
"""

import json
from typing import Any
import marketing as m

SCHEMA='''
CREATE TABLE IF NOT EXISTS v42_mcp_connectors(
 id TEXT PRIMARY KEY,
 provider_key TEXT NOT NULL,
 label TEXT NOT NULL,
 endpoint TEXT NOT NULL,
 auth_type TEXT NOT NULL DEFAULT 'managed',
 status TEXT NOT NULL DEFAULT 'Setup Required',
 protocol_version TEXT DEFAULT '',
 server_name TEXT DEFAULT '',
 capabilities_json TEXT NOT NULL DEFAULT '[]',
 read_permissions_json TEXT NOT NULL DEFAULT '[]',
 write_permissions_json TEXT NOT NULL DEFAULT '[]',
 last_success_at TEXT,
 last_error TEXT DEFAULT '',
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS v42_mcp_provider_endpoint ON v42_mcp_connectors(provider_key,endpoint);
'''


def initialise():
    with m.connect() as con:
        con.executescript(SCHEMA)
        try:
            cols={r['name'] for r in con.execute('PRAGMA table_info(v42_mcp_connectors)')}
        except Exception:cols=set()
        for name,decl in [('protocol_version',"TEXT DEFAULT ''"),('server_name',"TEXT DEFAULT ''")]:
            if cols and name not in cols:
                try:con.execute(f'ALTER TABLE v42_mcp_connectors ADD COLUMN {name} {decl}')
                except Exception:pass


def uid():
    import secrets
    return 'MCP-'+secrets.token_hex(6).upper()


def register(provider_key: str,label: str,endpoint: str,auth_type: str='managed',read_permissions=None,write_permissions=None) -> str:
    initialise();endpoint=(endpoint or '').strip()
    if not endpoint.startswith(('https://','http://127.0.0.1','http://localhost')):
        raise ValueError('Use an HTTPS MCP endpoint, or localhost for development.')
    mid=uid()
    with m.connect() as con:
        con.execute('''INSERT INTO v42_mcp_connectors(id,provider_key,label,endpoint,auth_type,read_permissions_json,write_permissions_json)
                       VALUES(?,?,?,?,?,?,?)''',(mid,provider_key.strip(),label.strip() or provider_key,endpoint,auth_type,json.dumps(read_permissions or []),json.dumps(write_permissions or [])))
    return mid


def connector(mid: str) -> dict:
    row=m.one('SELECT * FROM v42_mcp_connectors WHERE id=?',(mid,))
    if not row:raise ValueError('MCP connector not found.')
    row['capabilities']=json.loads(row.get('capabilities_json') or '[]')
    row['read_permissions']=json.loads(row.get('read_permissions_json') or '[]')
    row['write_permissions']=json.loads(row.get('write_permissions_json') or '[]')
    return row


def list_connectors() -> list[dict]:
    initialise();return [connector(r['id']) for r in m.rows('SELECT id FROM v42_mcp_connectors ORDER BY label')]


def _probe(endpoint: str) -> dict[str,Any]:
    try:
        import anyio
        from mcp import Client
    except ImportError:
        raise ValueError('The official MCP Python SDK is not installed in this runtime. Run PREPARE_FULL_RUNTIME.command while online, then retry.') from None
    async def run():
        async with Client(endpoint) as client:
            result=await client.list_tools()
            tools=sorted({str(getattr(t,'name','') or '') for t in (result.tools or []) if getattr(t,'name',None)})
            info=getattr(client,'server_info',None)
            name=str(getattr(info,'name','') or '') if info else ''
            return {'tools':tools,'protocol_version':str(getattr(client,'protocol_version','') or ''),'server_name':name}
    return anyio.run(run)


def test(mid: str) -> dict[str,Any]:
    c=connector(mid)
    try:
        out=_probe(c['endpoint']);capabilities=sorted(out.get('tools') or [])
        if not capabilities:raise ValueError('The MCP server connected successfully but did not expose any tools.')
        with m.connect() as con:
            con.execute("UPDATE v42_mcp_connectors SET status='Connected',capabilities_json=?,protocol_version=?,server_name=?,last_success_at=CURRENT_TIMESTAMP,last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (json.dumps(capabilities),str(out.get('protocol_version') or ''),str(out.get('server_name') or ''),mid))
        return {'ok':True,'capabilities':capabilities,'protocol_version':out.get('protocol_version',''),'server_name':out.get('server_name','')}
    except Exception as exc:
        with m.connect() as con:
            con.execute("UPDATE v42_mcp_connectors SET status='Needs Attention',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],mid))
        return {'ok':False,'capabilities':[],'error':str(exc)}


def disconnect(mid: str):
    connector(mid)
    with m.connect() as con:
        con.execute("UPDATE v42_mcp_connectors SET status='Setup Required',capabilities_json='[]',protocol_version='',server_name='',last_error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(mid,))


def _permission_for(c: dict, tool_name: str) -> str:
    """Return read/write/blocked for a discovered MCP tool using explicit owner grants.

    Empty permission lists are fail-closed for execution. Discovery alone never
    grants authority to read or write business data.
    """
    name=str(tool_name or '').strip()
    if name in set(c.get('write_permissions') or []): return 'write'
    if name in set(c.get('read_permissions') or []): return 'read'
    return 'blocked'


def call_tool(mid: str, tool_name: str, arguments: dict|None=None, *, require: str='read') -> dict[str,Any]:
    """Execute one permitted MCP tool after live capability and permission checks."""
    c=connector(mid); tool_name=str(tool_name or '').strip(); arguments=arguments or {}
    if c.get('status')!='Connected':
        raise ValueError('This MCP connector is not connected. Test or reconnect it first.')
    if tool_name not in set(c.get('capabilities') or []):
        raise ValueError('The connected MCP server does not advertise this capability.')
    permission=_permission_for(c,tool_name)
    if permission=='blocked' or (require=='write' and permission!='write'):
        raise ValueError('This MCP action is not permitted by the connector permission policy.')
    try:
        import anyio
        from mcp import Client
    except ImportError:
        raise ValueError('The official MCP Python SDK is not installed in this runtime.') from None

    async def run():
        async with Client(c['endpoint']) as client:
            result=await client.call_tool(tool_name,arguments)
            # Keep transport details serialisable without making business modules
            # depend on SDK content classes.
            content=[]
            for item in (getattr(result,'content',None) or []):
                if hasattr(item,'model_dump'):
                    content.append(item.model_dump(mode='json'))
                elif hasattr(item,'dict'):
                    content.append(item.dict())
                else:
                    content.append({'text':str(getattr(item,'text',item))})
            return {
                'content':content,
                'is_error':bool(getattr(result,'isError',False) or getattr(result,'is_error',False)),
                'structured':getattr(result,'structuredContent',None) or getattr(result,'structured_content',None),
            }
    try:
        out=anyio.run(run)
        if out.get('is_error'):
            raise ValueError('The MCP server returned an error for '+tool_name+'.')
        with m.connect() as con:
            con.execute("UPDATE v42_mcp_connectors SET last_success_at=CURRENT_TIMESTAMP,last_error='',status='Connected',updated_at=CURRENT_TIMESTAMP WHERE id=?",(mid,))
        return {'ok':True,'tool':tool_name,'permission':permission,**out}
    except Exception as exc:
        with m.connect() as con:
            con.execute("UPDATE v42_mcp_connectors SET status='Needs Attention',last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(exc)[:1200],mid))
        raise ValueError('MCP action failed: '+str(exc)) from None


def health(mid: str) -> dict[str,Any]:
    """Perform live discovery health check without executing a business action."""
    c=connector(mid)
    out=test(mid)
    fresh=connector(mid)
    return {'ok':bool(out.get('ok')),'status':fresh.get('status'),'capabilities':fresh.get('capabilities',[]),
            'last_success_at':fresh.get('last_success_at'),'last_error':fresh.get('last_error','')}
