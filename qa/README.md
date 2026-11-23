# The checks

    bash qa/run.sh

Seventeen checks. Three read the source; fourteen drive a real build in a
headless browser. Nothing here touches the live Supabase project and none of
them needs a key: the browser suites intercept every request to
`stub.supabase.co` and answer with fixtures, which is why `run.sh` builds with
that host and refuses to run against a build pointed anywhere else.

## What each one is for

Reading the source:

| | |
|---|---|
| `schema.py` | every column and join the app asks Postgres for, against a snapshot of the real schema. Written after the dashboard asked for `order_items.units`, which has never existed. Refresh the snapshot after a migration — the query is in the file. |
| `parts.py` | the part labels the browser offers for a piece are the ones the launch function knows how to read. |
| `contract.py` | three seams where the browser and an edge function have to agree: fields read off a reply against what the function returns, fields read off a stored proposal against the shape it declares, and the shape of config a page hands a shared component. |

Driving the site:

| | |
|---|---|
| `test.py` | every route renders with an empty database and says something useful rather than nothing. |
| `nav.py` | the rail, its sections and the header. |
| `dashboard.py` `details.py` | the dashboard's panels; the detail panel behind every list's Open button. |
| `looks.py` `launch.py` | the look library; the product launch wizard, including that later frames of one shoot anchor to the first. |
| `studio.py` | the campaign studio: the conversation, the directions it offers, the channel plan, the six C's, and that nothing is written to the calendar until somebody approves it. |
| `occasions.py` | the occasions calendar, the run-up arithmetic against a third implementation of the rule, and the festival markers on the month grid. |
| `courier.py` `track.py` | per-vendor Shiprocket booking; the customer's own tracking page, including what it must not leak. |
| `outreach.py` `dictate.py` | outreach drafting; dictation. |
| `contrast.py` `mobile.py` | field contrast in both schemes; the whole app at phone width. |

## Adding a check

A check nobody has watched fail is a check that does not work. Break the thing
on purpose, watch the check report it, put it back. Every check in here was
proved that way, and several of them earned their place by catching something
real afterwards.
