from __future__ import annotations

"""One business-connection abstraction across OAuth, MCP and direct API adapters."""
import json
from typing import Any
import marketing as m
import integration_layer as legacy
import integration_v14 as oauth
import mcp_connectors as mcp
import runtime_config as rc


def initialise():
    mcp.initialise()


def business_connections() -> list[dict[str,Any]]:
    rows=[]
    for c in legacy.connections():
        meta=oauth.business_catalog().get(c['connector_key']) or legacy.CONNECTOR_CATALOG.get(c['connector_key'],{})
        mode='OAuth / Login' if meta.get('login_first') else 'Direct API / Advanced Setup'
        rows.append({'id':c['id'],'provider':c.get('provider') or meta.get('provider',''),'label':c.get('label') or meta.get('label',''),
                     'mode':mode,'status':c.get('status'),'capabilities':c.get('capabilities') or meta.get('capabilities',[]),
                     'last_success_at':c.get('last_success_at'),'last_error':c.get('last_error','')})
    for c in mcp.list_connectors():
        rows.append({'id':c['id'],'provider':c['provider_key'],'label':c['label'],'mode':'MCP Connector','status':c['status'],
                     'capabilities':c['capabilities'],'last_success_at':c.get('last_success_at'),'last_error':c.get('last_error','')})
    return rows


def capability(provider: str, capability_name: str) -> list[dict]:
    p=(provider or '').lower();out=[]
    for c in business_connections():
        if p and p not in str(c.get('provider','')).lower() and p not in str(c.get('label','')).lower():continue
        if c.get('status') not in {'Connected'}:continue
        if capability_name in (c.get('capabilities') or []):out.append(c)
    return out


def status_label(raw: str) -> str:
    raw=str(raw or '')
    if raw=='Connected':return 'Connected'
    if raw in {'Reconnect required','Connection error','Permission required','Needs Attention'}:return 'Needs Attention'
    if raw in {'Connection requires setup','Setup Required'}:return 'Setup Required'
    if raw in {'Unsupported / planned'}:return 'Coming Soon'
    return 'Connect'


def execute(connection_id: str, capability_name: str, payload: dict|None=None, *, write: bool=False) -> dict[str,Any]:
    """Transport-neutral execution entry point.

    V44 initially supports execution through validated MCP connectors here. OAuth/API
    providers continue to use their mature provider adapters, but business modules can
    query this service for a validated connection and no longer need to infer readiness
    from stored credentials alone.
    """
    initialise(); payload=payload or {}
    if write: rc.require_external_write_allowed(capability_name)
    for c in mcp.list_connectors():
        if c['id']==connection_id:
            return mcp.call_tool(connection_id,capability_name,payload,require='write' if write else 'read')
    row=next((x for x in business_connections() if x['id']==connection_id),None)
    if not row: raise ValueError('Business connection not found.')
    if row.get('status')!='Connected' and capability_name!='test':
        raise ValueError('This business connection must validate successfully before it can perform that action.')
    # Shared OAuth/API execution path. This intentionally dispatches only named,
    # audited capabilities; it is not a generic arbitrary-provider request tunnel.
    c=legacy.connection(connection_id)
    if capability_name=='test':return oauth.test_connection(connection_id)
    if capability_name in {'sync','sync_products','sync_customers','sync_orders','sync_inventory'}:
        return oauth.sync_connection(connection_id)
    if capability_name=='push_product_draft':
        product_id=str(payload.get('product_id') or '').strip()
        if not product_id:raise ValueError('Choose a product before creating a store draft.')
        if c.get('connector_key')=='wix':
            import wix_v50 as wix
            app=oauth.provider_app('wix')
            return wix.create_product_draft(connection_id,app,oauth.provider_secret('wix','client_secret'),product_id)
        if c.get('connector_key')=='shopify':
            return legacy.publish_product_to_shopify(connection_id,product_id)
    raise ValueError('That capability is not mapped through the shared connector service for this provider.')


class ConnectorFacade:
    def __init__(self,capability_prefix: str=''):
        self.capability_prefix=capability_prefix
    def available(self,provider: str, capability_name: str) -> list[dict]:
        return capability(provider,capability_name)
    def execute(self,connection_id: str, capability_name: str, payload: dict|None=None, *, write: bool=False):
        return execute(connection_id,capability_name,payload,write=write)

CommerceConnector=ConnectorFacade('commerce')
MarketingConnector=ConnectorFacade('marketing')
MessagingConnector=ConnectorFacade('messaging')
AnalyticsConnector=ConnectorFacade('analytics')
MailboxConnector=ConnectorFacade('mailbox')
PaymentConnector=ConnectorFacade('payment')
