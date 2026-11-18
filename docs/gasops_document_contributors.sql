-- OPTIONAL: after the base gasops_document_storage_policies.sql is applied.
-- Replace the example UUID with the UUID of an explicitly invited Auth user.
-- Repeat the policy with a unique name or edit the IN list for more contributors.
-- Contributors can INSERT only. No UPDATE or DELETE permissions are granted here.
-- Never allow unauthenticated writes or generic authenticated writes.
-- Verify existing policies do not grant broader privileges.
drop policy if exists "gasops_docs_contributor_insert" on storage.objects;
create policy "gasops_docs_contributor_insert"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'gasops-documents'
  and (select auth.uid()) in ('00000000-0000-4000-8000-000000000002'::uuid)
  and name ~ '^[a-f0-9]{64}--[A-Za-z0-9._-]+[.]pdf$'
);
