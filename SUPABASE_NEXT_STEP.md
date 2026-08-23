# Geoffrey 2.0 — Supabase integration

The shared Supabase database is now provisioned separately. Before wiring the browser app to it, configure the frontend with the Supabase project URL and publishable key using a safe client-side configuration. Never put a service-role/secret key in this repository.

Required next steps:
1. Add the Supabase project URL and publishable key to the app configuration.
2. Read shared managers/gameweeks/fines from Supabase.
3. Restrict fine-payment writes to Ayrton/Admin through the database's RLS policies.
4. Add realtime subscriptions so all phones see payment changes immediately.
5. Test Admin marks PAID -> member devices see PAID.
