alter table approvals
    add column created_at timestamptz not null default now(),
    add column decided_by text,
    add column reason     text,
    add column result     jsonb;

-- One row per applied approval; the unique key makes "applied exactly once" a DB invariant.
create table approval_audit (
    id          bigserial primary key,
    approval_id bigint not null unique references approvals(id),
    kind        text not null,
    detail      jsonb not null default '{}',
    created_at  timestamptz not null default now()
);
