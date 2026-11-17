create table runs (
    id          text primary key,
    mode        text not null,
    status      text not null default 'queued',
    message     text not null default '',
    result      jsonb,
    error       text,
    created_at  timestamptz not null default now(),
    started_at  timestamptz,
    finished_at timestamptz
);
create index runs_created_idx on runs (created_at desc);
