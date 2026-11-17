-- Source text of the document as ingested; the approval gate edits this, then re-chunks.
-- NULL for rows ingested before this migration until the next ingest of the same content.
alter table documents add column body text;
