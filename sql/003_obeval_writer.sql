-- obeval chạy tự động: cột điều phối, bảng file không khớp, role ghi riêng (không dùng service-role key).
-- Chạy SAU 001 và 002. Dev: anh Tuấn Anh chạy. Prod: chủ DB chạy qua PR vào TeenCareBooking.
-- Mật khẩu role KHÔNG nằm trong file: chạy riêng `alter role obeval_writer password '<giá trị trong Secret Manager>';`
-- Điều kiện tiên quyết: RLS đã BẬT sẵn trên public.bookings và public.event_types (file này không tự bật RLS;
-- nếu chưa bật, file dừng với lỗi ở bước 4 và toàn bộ giao dịch bị huỷ).

begin;

-- 1. Cột điều phối của một lượt chấm
alter table public.onboarding_evaluations
  add column if not exists recording_file_id text,      -- Drive file id
  add column if not exists recording_url     text,      -- link Drive gửi cho temp-transcript
  add column if not exists run_id            bigint,    -- mỗi lần bắt đầu lại có run_id mới; Cloud Task cũ bị bỏ
  add column if not exists attempts          integer not null default 0;

-- 2. Recording không ghép được booking — chờ xử lý tay (chỉ admin xem; tên file có tên / SĐT phụ huynh)
create table if not exists public.onboarding_recording_unmatched (
  file_id        text        primary key,
  file_name      text        not null,
  reason         text        not null check (reason in ('unparsable_name', 'no_booking', 'duplicate_recording')),
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now()
);
alter table public.onboarding_recording_unmatched enable row level security;
drop policy if exists onboarding_recording_unmatched_admin_read on public.onboarding_recording_unmatched;
create policy onboarding_recording_unmatched_admin_read on public.onboarding_recording_unmatched
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));

-- 3. Role riêng của obeval: đăng nhập được, không kế thừa, không bỏ qua RLS
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'obeval_writer') then
    create role obeval_writer login noinherit nobypassrls;
  end if;
end $$;

-- Không ghi SUPERUSER / BYPASSRLS ở đây: role không phải superuser (Supabase) không được nêu hai từ khoá đó và lệnh sẽ lỗi.
alter role obeval_writer noinherit nocreaterole nocreatedb connection limit 10;

-- Cùng đảm bảo đó, kiểm bằng catalog: role phải KHÔNG là superuser và KHÔNG bỏ qua RLS, nếu không thì dừng cả file.
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'obeval_writer' and (rolsuper or rolbypassrls)) then
    raise exception 'Role obeval_writer đang là superuser hoặc có BYPASSRLS — bỏ quyền đó (chủ DB xử lý) rồi chạy lại file này';
  end if;
end $$;

grant usage on schema public to obeval_writer;
-- Chỉ 6 cột cần để ghép buổi — không tên / SĐT / email phụ huynh
grant select (id, event_type_id, mentor_id, start_at, status, student_code) on public.bookings to obeval_writer;
grant select (id, name) on public.event_types to obeval_writer;
grant select on public.onboarding_criteria to obeval_writer;
grant select, insert, update on public.onboarding_evaluations to obeval_writer;
grant select, insert, update, delete on public.onboarding_evaluation_steps to obeval_writer;
grant select, insert, update on public.onboarding_evaluation_audit to obeval_writer;
grant select, insert, update on public.onboarding_recording_unmatched to obeval_writer;

-- 4. RLS cho role này (Mentor / admin giữ nguyên policy ở 001)
-- Chốt chặn: nếu RLS chưa bật trên bookings / event_types thì bộ lọc loại buổi bên dưới vô hiệu -> dừng.
do $$ begin
  if exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname in ('bookings', 'event_types') and not c.relrowsecurity
  ) or (
    select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname in ('bookings', 'event_types')
  ) < 2 then
    raise exception 'RLS chưa bật trên public.bookings / public.event_types — bật RLS và kiểm policy hiện có trước khi chạy file này';
  end if;
end $$;
drop policy if exists obeval_writer_bookings on public.bookings;
create policy obeval_writer_bookings on public.bookings for select to obeval_writer
  using (event_type_id in (select id from public.event_types where name = 'Gia sư tâm lý 1:1 Onboarding'));
drop policy if exists obeval_writer_event_types on public.event_types;
create policy obeval_writer_event_types on public.event_types for select to obeval_writer using (true);
drop policy if exists obeval_writer_criteria on public.onboarding_criteria;
create policy obeval_writer_criteria on public.onboarding_criteria for select to obeval_writer using (true);
drop policy if exists obeval_writer_evaluations on public.onboarding_evaluations;
create policy obeval_writer_evaluations on public.onboarding_evaluations for all to obeval_writer using (true)
  with check (exists (select 1 from public.bookings b where b.id = onboarding_evaluations.booking_id));
drop policy if exists obeval_writer_steps on public.onboarding_evaluation_steps;
create policy obeval_writer_steps on public.onboarding_evaluation_steps for all to obeval_writer using (true)
  with check (exists (select 1 from public.bookings b where b.id = onboarding_evaluation_steps.booking_id));
drop policy if exists obeval_writer_audit on public.onboarding_evaluation_audit;
create policy obeval_writer_audit on public.onboarding_evaluation_audit for all to obeval_writer using (true)
  with check (exists (select 1 from public.bookings b where b.id = onboarding_evaluation_audit.booking_id));
drop policy if exists obeval_writer_unmatched on public.onboarding_recording_unmatched;
create policy obeval_writer_unmatched on public.onboarding_recording_unmatched for all to obeval_writer using (true) with check (true);

commit;

-- Hoàn tác (chỉ DEV):
-- drop policy if exists obeval_writer_bookings on public.bookings; drop policy if exists obeval_writer_event_types on public.event_types;
-- drop table if exists public.onboarding_recording_unmatched;
-- alter table public.onboarding_evaluations drop column if exists recording_file_id, drop column if exists recording_url,
--   drop column if exists run_id, drop column if exists attempts;
-- drop owned by obeval_writer; drop role obeval_writer;

-- Kiểm sau khi chạy (DB owner):
-- (a) RLS đã bật trên 2 bảng nguồn:
--   select relname, relrowsecurity from pg_class where relname in ('bookings','event_types');
-- (b) Hàm SECURITY DEFINER trong public mà obeval_writer gọi được (Postgres mặc định cấp EXECUTE cho PUBLIC):
--   select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
--   where n.nspname='public' and p.prosecdef and has_function_privilege('obeval_writer', p.oid, 'execute');
--   -> mỗi hàm trả dữ liệu cá nhân phải revoke execute from public rồi cấp lại đúng role cần.
