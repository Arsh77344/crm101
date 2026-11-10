"""Safe owner-facing lifecycle operations for business records.

V25 uses archive/restore for records that can be referenced by business history.
Permanent deletion is intentionally narrow: showrooms can be deleted only after
being archived and only when they have no recorded views/events or linked deals.
Products are archived rather than hard-deleted so order, campaign, asset and
inventory history cannot be orphaned.
"""
from __future__ import annotations

import marketing as m
import db_layer

ACTIVE_PRODUCT_STATUSES={'Draft','Active','Sold Out'}


def is_operationally_active_product(product_or_id) -> bool:
    """Single business rule for whether a product may enter new selling/marketing work.

    Historical references remain valid for archived products, but archived products may
    not start new AI, creative, campaign, publish or stock-authority actions.
    """
    if isinstance(product_or_id,dict):
        row=product_or_id
    else:
        row=m.one('SELECT product_id,status FROM products WHERE product_id=?',(str(product_or_id),))
    return bool(row) and str(row.get('status') or 'Draft')!='Archived'


def require_operationally_active_product(product_or_id) -> dict:
    if isinstance(product_or_id,dict):
        row=product_or_id
    else:
        row=m.one('SELECT * FROM products WHERE product_id=?',(str(product_or_id),))
    if not row:
        raise ValueError('Product not found.')
    if not is_operationally_active_product(row):
        raise ValueError('This product is archived. Restore it before starting new operational work.')
    return row


def product(product_id: str) -> dict:
    row=m.one('''SELECT p.*,coalesce(r.confirmed,0) confirmed,r.evidence,
      (SELECT relative_path FROM product_images i WHERE i.product_id=p.product_id ORDER BY is_primary DESC LIMIT 1) img
      FROM products p LEFT JOIN m4_product_review r USING(product_id) WHERE p.product_id=?''',(product_id,))
    if not row:
        raise ValueError('Product not found.')
    return row


def archive_product(product_id: str) -> None:
    row=product(product_id)
    if row.get('status')=='Archived':
        return
    with m.connect() as con:
        con.execute("UPDATE products SET status='Archived' WHERE product_id=?",(product_id,))
        if m.table_exists('v9_recommendations'):
            con.execute("UPDATE v9_recommendations SET status='Superseded',resolved_at=CURRENT_TIMESTAMP WHERE status='Open' AND (dedupe_key IN (?,?) OR action_url=?)",(f'product-ready:{product_id}',f'product-launch:{product_id}',f'/products/{product_id}'))
        if m.table_exists('v17_processes'):
            con.execute("UPDATE v17_processes SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE process_type='product_to_market' AND object_id=?",(product_id,))
    try:
        import product_engine as pe
        pe.refresh_duplicate_groups()
    except Exception:
        pass
    m.audit('product.archived',product_id,'Removed from active product selectors; historical references were preserved.')


def restore_product(product_id: str) -> None:
    row=product(product_id)
    if row.get('status')!='Archived':
        return
    # Restore to Draft, never straight back to Active: commercial facts and
    # downstream channel readiness may have changed while the product was archived.
    with m.connect() as con:
        con.execute("UPDATE products SET status='Draft' WHERE product_id=?",(product_id,))
        if m.table_exists('v17_processes'):
            con.execute("UPDATE v17_processes SET status='Running',updated_at=CURRENT_TIMESTAMP WHERE process_type='product_to_market' AND object_id=?",(product_id,))
    try:
        import product_engine as pe
        pe.refresh_duplicate_groups()
    except Exception:
        pass
    m.audit('product.restored',product_id,'Restored to Draft for owner review before reactivation.')




def contact(contact_id: str) -> dict:
    row=m.one('''SELECT c.*,cm.archived_at FROM contacts c LEFT JOIN m42_contact_meta cm USING(contact_id) WHERE c.contact_id=?''',(contact_id,))
    if not row:
        raise ValueError('Contact not found.')
    return row


def archive_contact(contact_id: str) -> None:
    row=contact(contact_id)
    if row.get('archived_at'):
        return
    with m.connect() as con:
        con.execute('INSERT INTO m42_contact_meta(contact_id,archived_at) VALUES(?,CURRENT_TIMESTAMP) ON CONFLICT(contact_id) DO UPDATE SET archived_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP',(contact_id,))
    m.audit('contact.archived',contact_id,'Removed from active audiences, lookups and new outreach workflows; historical CRM records were preserved.')


def restore_contact(contact_id: str) -> None:
    row=contact(contact_id)
    if not row.get('archived_at'):
        return
    with m.connect() as con:
        con.execute('UPDATE m42_contact_meta SET archived_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE contact_id=?',(contact_id,))
    m.audit('contact.restored',contact_id,'Restored to active CRM use. Existing channel permissions were not changed.')


def campaign(campaign_id: str) -> dict:
    row=m.one('SELECT * FROM campaigns WHERE campaign_id=?',(campaign_id,))
    if not row:
        raise ValueError('Campaign not found.')
    return row


def archive_campaign(campaign_id: str) -> None:
    row=campaign(campaign_id)
    if row.get('status')=='Archived':
        return
    with m.connect() as con:
        con.execute("UPDATE campaigns SET status='Archived' WHERE campaign_id=?",(campaign_id,))
        if m.table_exists('v10_unified_campaigns'):con.execute("UPDATE v10_unified_campaigns SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE id=?",(campaign_id,))
    m.audit('campaign.archived',campaign_id,'Removed from active campaign planning; members, drafts, attribution and history were preserved.')


def restore_campaign(campaign_id: str) -> None:
    row=campaign(campaign_id)
    if row.get('status')!='Archived':
        return
    with m.connect() as con:
        con.execute("UPDATE campaigns SET status='Draft' WHERE campaign_id=?",(campaign_id,))
        if m.table_exists('v10_unified_campaigns'):con.execute("UPDATE v10_unified_campaigns SET status='Draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",(campaign_id,))
    m.audit('campaign.restored',campaign_id,'Restored to Draft for review before further work.')


def require_active_campaign(campaign_id: str) -> dict:
    row=campaign(campaign_id)
    status=str(row.get('status') or 'Draft')
    if status=='Archived':
        raise ValueError('This campaign is archived. Restore it before changing drafts, audiences or handoffs.')
    if status=='Paused':
        raise ValueError('This campaign is paused. Resume it before changing drafts, audiences or handoffs.')
    return row

def pause_campaign(campaign_id: str) -> None:
    row=campaign(campaign_id)
    status=str(row.get('status') or 'Draft')
    if status=='Archived':raise ValueError('Restore this campaign before pausing it.')
    if status=='Paused':return
    with m.connect() as con:
        con.execute("UPDATE campaigns SET status='Paused' WHERE campaign_id=?",(campaign_id,))
        if m.table_exists('v10_unified_campaigns'):
            con.execute("UPDATE v10_unified_campaigns SET status='Paused',updated_at=CURRENT_TIMESTAMP WHERE id=?",(campaign_id,))
    m.audit('campaign.paused',campaign_id,'Local campaign execution paused. Existing external provider activity is not changed automatically.')

def resume_campaign(campaign_id: str) -> None:
    row=campaign(campaign_id)
    if str(row.get('status') or 'Draft')!='Paused':return
    with m.connect() as con:
        con.execute("UPDATE campaigns SET status='Draft' WHERE campaign_id=?",(campaign_id,))
        if m.table_exists('v10_unified_campaigns'):
            con.execute("UPDATE v10_unified_campaigns SET status='Draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",(campaign_id,))
    m.audit('campaign.resumed',campaign_id,'Resumed to Draft for owner review. No external provider campaign was activated automatically.')

def bulk_archive_campaigns(campaign_ids: list[str]) -> int:
    ids=list(dict.fromkeys(str(x or '').strip() for x in (campaign_ids or []) if str(x or '').strip()))
    if not ids:raise ValueError('Select at least one campaign.')
    if len(ids)>100:raise ValueError('Select no more than 100 campaigns at a time.')
    for cid in ids:campaign(cid)
    with m.connect() as con:
        for cid in ids:
            con.execute("UPDATE campaigns SET status='Archived' WHERE campaign_id=?",(cid,))
            if m.table_exists('v10_unified_campaigns'):
                con.execute("UPDATE v10_unified_campaigns SET status='Archived',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,))
    for cid in ids:m.audit('campaign.archived',cid,'Bulk archive; members, drafts, attribution and history were preserved.')
    return len(ids)

def bulk_restore_campaigns(campaign_ids: list[str]) -> int:
    ids=list(dict.fromkeys(str(x or '').strip() for x in (campaign_ids or []) if str(x or '').strip()))
    if not ids:raise ValueError('Select at least one campaign.')
    if len(ids)>100:raise ValueError('Select no more than 100 campaigns at a time.')
    for cid in ids:campaign(cid)
    with m.connect() as con:
        for cid in ids:
            con.execute("UPDATE campaigns SET status='Draft' WHERE campaign_id=?",(cid,))
            if m.table_exists('v10_unified_campaigns'):
                con.execute("UPDATE v10_unified_campaigns SET status='Draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,))
    for cid in ids:m.audit('campaign.restored',cid,'Bulk restore to Draft for review before further work.')
    return len(ids)

def company(company_id: str) -> dict:
    row=m.one('SELECT * FROM companies WHERE company_id=?',(company_id,))
    if not row:
        raise ValueError('Account not found.')
    return row


def archive_company(company_id: str) -> None:
    row=company(company_id)
    if (row.get('status') or 'Active')=='Archived':
        return
    with m.connect() as con:
        con.execute("UPDATE companies SET status='Archived' WHERE company_id=?",(company_id,))
    m.audit('company.archived',company_id,'Removed from new account links and active account lists; relationship history was preserved.')


def restore_company(company_id: str) -> None:
    row=company(company_id)
    if (row.get('status') or 'Active')!='Archived':
        return
    with m.connect() as con:
        con.execute("UPDATE companies SET status='Active' WHERE company_id=?",(company_id,))
    m.audit('company.restored',company_id,'Restored to the active B2B account list.')

def showroom(showroom_id: str) -> dict:
    row=m.one('SELECT * FROM showrooms WHERE showroom_id=?',(showroom_id,))
    if not row:
        raise ValueError('Showroom not found.')
    return row


def archive_showroom(showroom_id: str) -> None:
    row=showroom(showroom_id)
    if row.get('status')=='Archived' and not int(row.get('public_enabled') or 0):
        return
    with m.connect() as con:
        con.execute("UPDATE showrooms SET status='Archived',public_enabled=0 WHERE showroom_id=?",(showroom_id,))
    m.audit('showroom.archived',showroom_id,'Preview disabled; products, analytics and linked history preserved.')


def restore_showroom(showroom_id: str) -> None:
    row=showroom(showroom_id)
    if row.get('status')!='Archived':
        return
    with m.connect() as con:
        # Restoring history must not silently republish a showroom. Return it to
        # Inactive and require an explicit owner action before it becomes usable.
        con.execute("UPDATE showrooms SET status='Inactive',public_enabled=0 WHERE showroom_id=?",(showroom_id,))
    m.audit('showroom.restored',showroom_id,'Restored as Inactive; review and activate it when ready.')


def showroom_delete_blockers(showroom_id: str) -> list[str]:
    showroom(showroom_id)
    checks=[
        ('opportunities','showroom_id','linked sales deal(s)'),
        ('showroom_views','showroom_id','recorded legacy view(s)'),
        ('showroom_events','showroom_id','recorded interest/event(s)'),
    ]
    blockers=[]
    for table,column,label in checks:
        row=m.one(f'SELECT count(*) n FROM {table} WHERE {column}=?',(showroom_id,))
        count=int((row or {}).get('n') or 0)
        if count:
            blockers.append(f'{count} {label}')
    return blockers


def delete_showroom(showroom_id: str) -> None:
    row=showroom(showroom_id)
    if row.get('status')!='Archived':
        raise ValueError('Archive the showroom before deleting it permanently.')
    blockers=showroom_delete_blockers(showroom_id)
    if blockers:
        raise ValueError('This showroom has business history and cannot be permanently deleted: '+', '.join(blockers)+'. Keep it archived instead.')
    with m.connect() as con:
        con.execute('DELETE FROM showroom_products WHERE showroom_id=?',(showroom_id,))
        con.execute('DELETE FROM showrooms WHERE showroom_id=?',(showroom_id,))
    m.audit('showroom.deleted',showroom_id,'Permanently deleted after archive; no recorded engagement or linked sales deals existed.')

# V42 central lifecycle semantics. Business modules use these terms consistently;
# archive preserves business history, delete is destructive and dependency-aware.
LIFECYCLE_MATRIX={
    'Product':      {'create':True,'view':True,'edit':True,'duplicate':True,'archive':True,'restore':True,'delete':'only_if_unused'},
    'Collection':   {'create':'via_product_assignment','view':'product_context','edit':False,'archive':False,'restore':False,'delete':False,'note':'Merchandise collections can be created/assigned from product workflows; standalone collection administration is not yet exposed.'},
    'Contact':      {'create':True,'view':True,'edit':True,'archive':True,'restore':True,'delete':False,'note':'Permanent deletion/anonymisation is not exposed as a normal CRM action.'},
    'Company':      {'create':True,'view':True,'edit':True,'archive':True,'restore':True,'delete':False},
    'Lead':         {'create':True,'view':True,'edit':True,'archive':False,'restore':False,'delete':False,'note':'Leads are contact lifecycle states, not a separate destructible record.'},
    'Opportunity':  {'create':True,'view':True,'edit':True,'archive':False,'restore':False,'delete':False,'close':True},
    'Task':         {'create':True,'view':True,'edit':True,'archive':False,'restore':False,'delete':False,'complete':True,'cancel':True},
    'Order':        {'create':True,'view':True,'edit':'state_limited','archive':False,'restore':False,'delete':False,'cancel':'state_limited','refund':'state_limited','return':'state_limited'},
    'Showroom':     {'create':True,'view':True,'edit':True,'archive':True,'restore':True,'delete':'only_if_unused'},
    'Campaign':     {'create':True,'view':True,'edit':True,'duplicate':True,'archive':True,'restore':True,'delete':False,'pause':True,'resume':True},
    'Asset':        {'create':True,'view':True,'edit':'metadata_only','archive':False,'restore':False,'delete':False,'reject':True},
    'Automation':   {'create':True,'view':True,'edit':True,'archive':False,'restore':False,'delete':False,'deactivate':True,'reactivate':True},
    'Integration':  {'connect':True,'view':True,'edit':'manage','archive':False,'restore':False,'delete':False,'disconnect':True,'reconnect':True},
    'User':         {'create':True,'view':True,'edit':True,'archive':False,'restore':False,'delete':False,'deactivate':True,'reactivate':True},
}


def lifecycle_policy(object_type: str) -> dict:
    return dict(LIFECYCLE_MATRIX.get(object_type,{"create":False,"edit":False,"archive":False,"restore":False,"delete":False}))


def product_delete_blockers(product_id: str) -> list[str]:
    product(product_id)
    checks=[
        ('order_items','product_id','order line(s)'),
        ('showroom_products','product_id','customer selection link(s)'),
        ('v7_creative_assets','product_id','creative asset(s)'),
        ('v7_creative_jobs','product_id','creative job(s)'),
        ('v8_creative_campaign_assets','product_id','campaign creative link(s)'),
        ('v9_inventory','product_id','inventory record(s)'),
        ('v9_attribution_touchpoints','product_id','attribution touchpoint(s)'),
        ('v13_quality_checks','entity_id','quality/audit record(s)'),
    ]
    blockers=[]
    for table,column,label in checks:
        try:
            if not m.table_exists(table):continue
            # v13 quality rows need entity type discrimination.
            if table=='v13_quality_checks':
                row=m.one("SELECT count(*) n FROM v13_quality_checks WHERE entity_type='product' AND entity_id=?",(product_id,))
            else:row=m.one(f'SELECT count(*) n FROM {table} WHERE {column}=?',(product_id,))
            count=int((row or {}).get('n') or 0)
            if count: blockers.append(f'{count} {label}')
        except Exception:
            # A failed dependency check must fail safe: do not hard-delete.
            blockers.append(f'unverified dependency in {table}')
    return blockers


def delete_product(product_id: str) -> None:
    row=product(product_id)
    if row.get('status')!='Archived':
        raise ValueError('Archive the product before considering permanent deletion.')
    blockers=product_delete_blockers(product_id)
    if blockers:
        raise ValueError('This product has business history and cannot be permanently deleted: '+', '.join(blockers)+'. Keep it archived instead.')
    with m.connect() as con:
        # Only non-business-history helper rows are removed here. Historical tables
        # are blockers above, so this operation cannot orphan an order or report.
        for table,column in [('product_images','product_id'),('m4_product_review','product_id')]:
            try:
                if m.table_exists(table):con.execute(f'DELETE FROM {table} WHERE {column}=?',(product_id,))
            except Exception:pass
        con.execute('DELETE FROM products WHERE product_id=?',(product_id,))
    m.audit('product.deleted',product_id,'Permanently deleted only after archive and zero business-history dependencies.')


def bulk_archive_products(product_ids: list[str]) -> int:
    done=0
    for pid in dict.fromkeys(product_ids or []):
        archive_product(pid);done+=1
    return done


def bulk_restore_products(product_ids: list[str]) -> int:
    done=0
    for pid in dict.fromkeys(product_ids or []):
        restore_product(pid);done+=1
    return done


def bulk_delete_products(product_ids: list[str]) -> dict:
    result={'deleted':0,'blocked':{}}
    for pid in dict.fromkeys(product_ids or []):
        try:delete_product(pid);result['deleted']+=1
        except ValueError as exc:result['blocked'][pid]=str(exc)
    return result
