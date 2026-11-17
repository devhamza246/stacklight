create extension if not exists vector;

create table documents (
    id           bigserial primary key,
    title        text not null,
    source       text not null,
    content_hash text not null unique,
    status       text not null default 'active',
    created_at   timestamptz not null default now()
);

-- {{EMBEDDING_DIM}} is substituted from Settings.embedding_dim by migrate().
create table chunks (
    id          bigserial primary key,
    document_id bigint not null references documents(id) on delete cascade,
    ord         integer not null,
    text        text not null,
    embedding   vector({{EMBEDDING_DIM}}),
    tsv         tsvector generated always as (to_tsvector('english', text)) stored,
    unique (document_id, ord)
);
create index chunks_embedding_idx on chunks using hnsw (embedding vector_cosine_ops);
create index chunks_tsv_idx on chunks using gin (tsv);

create table approvals (
    id         bigserial primary key,
    kind       text not null,
    payload    jsonb not null default '{}',
    status     text not null default 'pending',
    decided_at timestamptz,
    applied_at timestamptz
);

create table spans (
    id            bigserial primary key,
    run_id        text not null,
    parent_id     bigint references spans(id),
    agent         text not null,
    name          text not null,
    started_at    timestamptz not null default now(),
    ended_at      timestamptz,
    input_tokens  integer not null default 0,
    output_tokens integer not null default 0,
    cost_usd      numeric(12, 6) not null default 0,
    attrs         jsonb not null default '{}'
);
create index spans_run_idx on spans (run_id);
