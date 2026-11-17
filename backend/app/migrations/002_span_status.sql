-- Tracing: OTel ids (spans are written at END, so parent rows may not exist yet),
-- outcome, and whether cost_usd is real (unknown-priced models report 0.0).
alter table spans
    add column span_key   text,
    add column parent_key text,
    add column status     text not null default 'ok',
    add column error      text,
    add column cost_known boolean not null default true;
create index spans_started_idx on spans (started_at);
create unique index spans_key_idx on spans (run_id, span_key);
