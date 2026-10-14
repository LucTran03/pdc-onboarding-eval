-- Kết quả AI chấm buổi onboarding — DB đặt lịch (MentorBookingSEC / repo TeenCareBooking).
-- Chạy trên DB DEV trước. Lên prod phải qua PR vào TeenCareBooking (supabase/schema.sql) và chủ DB duyệt.
--
-- Ai đọc / ghi:
--   obeval (role obeval_writer, xem 003)  ghi các bảng điều phối và kết quả, bị RLS giới hạn (không dùng service-role key)
--   TeenCareWork (service role)  dashboard PDC + trang chi tiết, kiểm quyền ở server
--   Mentor (authenticated)       đọc kết quả buổi của mình khi published_at != null; gửi phản hồi
--   Admin (admin_users)          đọc tất cả
-- Transcript, câu trả lời gốc của model: để trên GCS, DB chỉ giữ đường dẫn.
-- Không có cờ ca thử: thử nghiệm / nghiệm thu chạy trên DB dev hoặc local, prod chỉ nhận ca vận hành thật.

begin;

-- 1. Danh mục tiêu chí (nạp từ prompt/criteria.json, xem 002_seed_onboarding_criteria.sql)
create table if not exists public.onboarding_criteria (
  criterion_id  text        not null,                 -- OB01..OB37
  version       text        not null,                 -- phiên bản bộ tiêu chí, vd '2026-10-09'
  name          text        not null,
  activity      smallint    not null check (activity between 1 and 5),
  requirements  jsonb       not null default '[]'::jsonb,
  created_at    timestamptz not null default now(),
  primary key (criterion_id, version)
);

-- 2. Mỗi buổi một dòng (chấm lại thì ghi đè). Mentor đọc được dòng của mình sau khi published.
create table if not exists public.onboarding_evaluations (
  booking_id        uuid        primary key references public.bookings(id) on delete cascade,
  status            text        not null default 'processing'
                    check (status in ('processing', 'done', 'error', 'insufficient')),
  session_date      date,
  duration_sec      integer,
  overall           numeric(5,4) check (overall is null or overall between 0 and 1),
  threshold         numeric(5,4),                         -- ngưỡng lúc chấm (dashboard so lại theo ngưỡng hiện hành)
  activities        jsonb,      -- [{activity, score, counts:{FF,PF,NF,...}, start_sec, end_sec, estimated}]
  mentor_report     jsonb,      -- nội dung report cho Mentor = email (tóm tắt, điểm tốt, 3 việc ưu tiên, phần chưa follow, cờ)
  flags             jsonb,      -- [{id, script_instructed}] — chỉ mã, cho dashboard
  criteria_version  text,
  model             text,
  scored_at         timestamptz,
  published_at      timestamptz,                         -- null = Mentor chưa thấy
  email_to          text,
  email_sent_at     timestamptz,
  error             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists onboarding_evaluations_session_date_idx
  on public.onboarding_evaluations (session_date) where status = 'done';

-- 3. 37 dòng mỗi buổi — cho biểu đồ "các phần hay bị sai kịch bản nhất"
create table if not exists public.onboarding_evaluation_steps (
  booking_id    uuid     not null references public.onboarding_evaluations(booking_id) on delete cascade,
  criterion_id  text     not null,
  activity      smallint not null check (activity between 1 and 5),
  status        text     not null check (status in ('FF', 'PF', 'NF', 'NA', 'NE')),
  primary key (booking_id, criterion_id)
);
create index if not exists onboarding_evaluation_steps_dev_idx
  on public.onboarding_evaluation_steps (criterion_id) where status in ('NF', 'PF');

-- 4. Phần kiểm định — chỉ admin / server; KHÔNG có quyền cho Mentor
create table if not exists public.onboarding_evaluation_audit (
  booking_id           uuid primary key references public.onboarding_evaluations(booking_id) on delete cascade,
  result               jsonb not null,   -- result.json đầy đủ: 37 tiêu chí + bằng chứng, liên kết, thứ tự, chất lượng dữ liệu
  stability            jsonb,
  ai_issues            jsonb,
  quote_stats          jsonb,
  transcript_warnings  jsonb,
  transcript_uri       text,             -- gs://teenup-transcripts/...
  model_raw_uri        text,
  cost_usd             numeric(8,4),
  usage                jsonb,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

-- 5. Mentor phản hồi "góp ý này chưa đúng" (đo chỉ tiêu ≥ 80% góp ý phù hợp)
create table if not exists public.onboarding_evaluation_feedback (
  id          uuid        primary key default gen_random_uuid(),
  booking_id  uuid        not null references public.onboarding_evaluations(booking_id) on delete cascade,
  mentor_id   uuid        not null references public.mentors(id),
  item_key    text        not null,       -- vd 'improvement:OB31', 'deviation:OB21'
  verdict     text        not null check (verdict in ('agree', 'disagree')),
  comment     text,
  created_at  timestamptz not null default now(),
  unique (booking_id, mentor_id, item_key)
);

-- updated_at tự cập nhật
create or replace function public.onboarding_eval_touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at := now(); return new; end $$;
drop trigger if exists onboarding_evaluations_touch on public.onboarding_evaluations;
create trigger onboarding_evaluations_touch before update on public.onboarding_evaluations
  for each row execute function public.onboarding_eval_touch_updated_at();
drop trigger if exists onboarding_evaluation_audit_touch on public.onboarding_evaluation_audit;
create trigger onboarding_evaluation_audit_touch before update on public.onboarding_evaluation_audit
  for each row execute function public.onboarding_eval_touch_updated_at();

-- RLS: bật cho cả 5 bảng; service role bỏ qua RLS nên obeval / TeenCareWork server không bị ảnh hưởng
alter table public.onboarding_criteria            enable row level security;
alter table public.onboarding_evaluations         enable row level security;
alter table public.onboarding_evaluation_steps    enable row level security;
alter table public.onboarding_evaluation_audit    enable row level security;
alter table public.onboarding_evaluation_feedback enable row level security;

-- Danh mục: ai đăng nhập cũng đọc được (không có dữ liệu cá nhân)
drop policy if exists onboarding_criteria_read on public.onboarding_criteria;
create policy onboarding_criteria_read on public.onboarding_criteria
  for select to authenticated using (true);

-- Kết quả: Mentor đọc buổi của mình khi đã published; admin đọc tất cả
drop policy if exists onboarding_evaluations_mentor_read on public.onboarding_evaluations;
create policy onboarding_evaluations_mentor_read on public.onboarding_evaluations
  for select to authenticated using (
    published_at is not null and exists (
      select 1 from public.bookings b join public.mentors m on m.id = b.mentor_id
      where b.id = onboarding_evaluations.booking_id and m.user_id = auth.uid()));
drop policy if exists onboarding_evaluations_admin_read on public.onboarding_evaluations;
create policy onboarding_evaluations_admin_read on public.onboarding_evaluations
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));

-- Từng tiêu chí và phần kiểm định: chỉ admin
drop policy if exists onboarding_evaluation_steps_admin_read on public.onboarding_evaluation_steps;
create policy onboarding_evaluation_steps_admin_read on public.onboarding_evaluation_steps
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));
drop policy if exists onboarding_evaluation_audit_admin_read on public.onboarding_evaluation_audit;
create policy onboarding_evaluation_audit_admin_read on public.onboarding_evaluation_audit
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));

-- Phản hồi: Mentor thêm / đọc phản hồi của chính mình cho buổi của mình đã published; admin đọc tất cả
drop policy if exists onboarding_evaluation_feedback_mentor_rw on public.onboarding_evaluation_feedback;
create policy onboarding_evaluation_feedback_mentor_rw on public.onboarding_evaluation_feedback
  for all to authenticated
  using (exists (select 1 from public.mentors m where m.id = mentor_id and m.user_id = auth.uid()))
  with check (
    exists (select 1 from public.mentors m where m.id = mentor_id and m.user_id = auth.uid())
    and exists (
      select 1 from public.onboarding_evaluations e join public.bookings b on b.id = e.booking_id
      where e.booking_id = onboarding_evaluation_feedback.booking_id
        and e.published_at is not null and b.mentor_id = onboarding_evaluation_feedback.mentor_id));
drop policy if exists onboarding_evaluation_feedback_admin_read on public.onboarding_evaluation_feedback;
create policy onboarding_evaluation_feedback_admin_read on public.onboarding_evaluation_feedback
  for select to authenticated using (exists (select 1 from public.admin_users a where a.user_id = auth.uid()));

commit;

-- Hoàn tác (chỉ trên DEV):
-- drop table if exists public.onboarding_evaluation_feedback, public.onboarding_evaluation_audit,
--   public.onboarding_evaluation_steps, public.onboarding_evaluations, public.onboarding_criteria cascade;
-- drop function if exists public.onboarding_eval_touch_updated_at();
