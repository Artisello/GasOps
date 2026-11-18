-- Eseguire soltanto nel progetto scelto per GasOps.
-- Prima: creare un bucket PUBBLICO gasops-documents (PDF, max 24 MB),
-- e un utente amministratore in Authentication > Users.
-- Sostituire il UUID di esempio con il vero UUID. Non usare service_role.
-- Il bucket e le policy DEVONO essere riservati a documenti PUBBLICI.
create policy "gasops_docs_public_select"
on storage.objects for select to anon, authenticated
using (bucket_id = 'gasops-documents');

create policy "gasops_docs_admin_insert"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'gasops-documents'
  and (select auth.uid()) = '00000000-0000-0000-0000-000000000000'::uuid
  and name ~ '^[a-f0-9]{64}--[A-Za-z0-9._-]+[.]pdf$'
);

create policy "gasops_docs_admin_delete"
on storage.objects for delete to authenticated
using (
  bucket_id = 'gasops-documents'
  and (select auth.uid()) = '00000000-0000-0000-0000-000000000000'::uuid
);
