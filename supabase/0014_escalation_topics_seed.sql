-- The escalation list the owner agreed: what the agent must hand over rather
-- than answer. Each row is editable, and `active` turns one off.
--
-- A trailing * on a pattern matches the start of a word. Everything else matches
-- a whole word, because a bare substring is how "eta" fires on "metallic zari".
-- `custom` deliberately has no star: `custom*` would swallow every message
-- containing the word "customer".
--
-- This decides WHO answers. It does not decide what may be said: the rails on
-- prices, dates and promises live in the function and are checked on the
-- finished draft, because a pattern list cannot catch a confident invention.

insert into escalation_topics (label, patterns, note, sort_order)
select * from (values
  ('Complaint or damage',
   array['damag*','torn','tear','stain*','faded','colour bleed','color bleed',
         'not as shown','not as described','fake','duplicate','cheated','fraud','scam',
         'worst','disappoint*','complaint*','poor quality','legal','consumer court','report you'],
   'Anything that sounds like the piece or the service was wrong. The first reply to an unhappy customer sets the whole exchange, and it should be the owner''s.',
   10),
  ('Return, exchange or cancellation',
   array['return*','exchang*','replace*','cancel*','send it back','take it back'],
   'A return has a cost and a policy decision behind it. The agent must not imply one is accepted.',
   20),
  ('Refund or money back',
   array['refund*','money back','reverse the payment','chargeback','money deducted',
         'amount debited','payment failed','double charged'],
   'Money leaving the business is the owner''s decision, always.',
   30),
  ('Delivery date or courier promise',
   array['when will it','when will i','how long will','how many days','delivery date',
         'by when','reach me by','deliver by','dispatch date','in time for',
         'before diwali','before the wedding','urgent delivery','same day','next day'],
   'The agent can read an order''s tracking, but it cannot promise a date. A promised date that slips is the complaint that follows.',
   40),
  ('Price negotiation or discount',
   array['discount*','best price','last price','final price','any offer','negotiat*',
         'negotiable','reduce the price','lower price','kam kar','kam karo','kitna',
         'thoda kam','coupon','promo code','cheaper','budget me'],
   'Bargaining is the owner''s. Includes the Hinglish a customer actually types, because an uncaught bargaining message gets auto-answered, which is worse than escalating one too many.',
   50),
  ('Custom or made to order',
   array['custom','customise','customize','customised','customized','made to order',
         'can you make','can you weave','same design in','different colour','different color',
         'stitch*','fall and pico','alter','alteration','my measurement'],
   'A commitment to produce something. Only the owner knows what a workshop will actually take on.',
   60),
  ('Bulk, wholesale or reseller',
   array['bulk','wholesale','reseller','re-seller','distributor','dealership','franchise',
         'large quantity','for my shop','for my store'],
   'Different pricing, different terms. Not a retail conversation at all.',
   70),
  ('Press, collaboration or barter',
   array['collaborat*','barter','influencer','feature you','press','media','shoot with',
         'pr package','gifting','sponsor*'],
   'Brand decisions. The agent has no business agreeing to any of them.',
   80),
  ('Asked for a person',
   array['speak to','talk to someone','talk to a person','call me','give me a call',
         'call back','phone me','is this a bot','are you a bot','real person','human',
         'owner','manager','customer care'],
   'If someone asks for a person they get a person. Nothing else is acceptable.',
   90)
) as t(label, patterns, note, sort_order)
where not exists (select 1 from escalation_topics);
