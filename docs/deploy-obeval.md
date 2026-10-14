# Deploy obeval (AI chấm onboarding) lên GCP

> Cập nhật: 14/10/2026 · Người viết: người phát triển obeval · Người đọc: người deploy GCP, chủ DB đặt lịch · Nhánh: `feat/onboarding-service`
>
> Làm theo thứ tự các bước. Lệnh viết cho bash (Cloud Shell hoặc Git Bash). Mọi giá trị trong `<...>` là chỗ trống phải điền.
> **Không dán mật khẩu, token, DSN hay kịch bản PDC vào repo, chat, ticket hay file `.md`.**

## 1. Tổng quan

obeval là một service Cloud Run nhận recording onboarding từ Apps Script, nhờ temp-transcript và STT chép lời, rồi chấm bằng Gemini (Vertex AI) và ghi kết quả vào DB đặt lịch.

```
Apps Script ──POST /v1/recordings──▶ obeval (Cloud Run) ──▶ DB đặt lịch (role obeval_writer)
                                       │  ▲
                 Cloud Tasks ──────────┘  └── POST /v1/tasks/advance, 5 phút/lần, tối đa 3 giờ
                                       │
                                       ├──▶ temp-transcript ──▶ STT ──▶ GCS transcripts/onboarding/<booking>.json
                                       └──▶ đọc file đó trên GCS, chấm bằng Vertex AI, ghi DB
```

Mặc định `OBEVAL_PUBLISH=false`: kết quả được ghi nhưng Mentor chưa thấy.

### 1.1. Thứ tự deploy (bắt buộc)

| # | Việc | Ai làm | Ghi chú |
|---|---|---|---|
| A | Chạy migration `sql/001`, `002`, `003` trên DB **dev**, rồi **prod** | Dev: người phát triển obeval. Prod: chủ DB | Mục 2 |
| B | Deploy **STT server** (nhánh `tanh/feat/onboarding-profile`) | Người phát triển obeval | Mục 3 |
| C | Deploy **temp-transcript** (nhánh `tanh/feat/onboarding-profile`) | Người phát triển obeval | Phải sau B. Mục 4 |
| D | Deploy **obeval** lên Cloud Run: dev trước, prod sau, `OBEVAL_PUBLISH=false` | Người deploy GCP | Mục 5 đến 9 |
| E | Apps Script nhánh onboarding | Người phát triển obeval và người giữ Apps Script | Mục 1.2 |

Vì sao C phải sau B: temp-transcript mới gửi thêm `profile=onboarding` xuống STT. STT cũ bỏ qua trường lạ, nên job vẫn chạy nhưng không ghi vào `transcripts/onboarding/` và có thể không chia người nói. obeval sẽ không tìm thấy file (chờ 3 giờ rồi báo `error`) hoặc đánh dấu ca `insufficient`.

### 1.2. Apps Script (chỉ để biết)

Nhánh onboarding của script đồng bộ recording do người phát triển obeval và người giữ Apps Script làm. Bản lưu nằm ở `tools/apps_script/onboarding.gs` (cùng thư mục có `Code.gs` và `README.md` hướng dẫn cài).
Người deploy chỉ cần đưa cho họ: URL service (`obeval-dev`, sau đó `obeval`) và token (secret `obeval-api-token`) qua kênh an toàn.

## 2. Bước A: migration DB (chủ DB)

File nằm trong thư mục `sql/` của repo. Chạy **theo thứ tự**, trên dev trước.

| File | Việc |
|---|---|
| `sql/001_onboarding_evaluations.sql` | Bảng kết quả, RLS cho Mentor / admin |
| `sql/002_seed_onboarding_criteria.sql` | Nạp 37 tiêu chí |
| `sql/003_obeval_writer.sql` | Cột điều phối, bảng `onboarding_recording_unmatched`, role `obeval_writer`, RLS cho role này |

**Điều kiện tiên quyết của 003:** RLS phải **đã bật** trên `public.bookings` và `public.event_types`. File không tự bật. Nếu chưa bật, file dừng bằng lỗi "RLS chưa bật…" và huỷ toàn bộ giao dịch. Khi đó **dừng và báo người phát triển obeval**, không tự bật RLS (bật RLS mà thiếu policy sẽ làm app đặt lịch mất dữ liệu).

Kiểm trước khi chạy 003:

```sql
select relname, relrowsecurity from pg_class where relname in ('bookings','event_types');
```
Cả hai dòng phải có `relrowsecurity = true`.

**Cách chạy `psql` trong tài liệu này (đừng đưa mật khẩu lên dòng lệnh).** Dòng lệnh nằm lại trong lịch sử shell và hiện trong danh sách tiến trình của máy, nên mật khẩu hoặc DSN đầy đủ không được viết vào đó. Nhập mật khẩu bằng prompt rồi truyền host, user, db bằng cờ riêng:

```bash
read -rs PGPASSWORD; export PGPASSWORD          # gõ mật khẩu, không hiện ra màn hình
psql -h <host> -p <cổng> -U <user> -d postgres -v ON_ERROR_STOP=1 -f sql/001_onboarding_evaluations.sql &&
psql -h <host> -p <cổng> -U <user> -d postgres -v ON_ERROR_STOP=1 -f sql/002_seed_onboarding_criteria.sql &&
psql -h <host> -p <cổng> -U <user> -d postgres -v ON_ERROR_STOP=1 -f sql/003_obeval_writer.sql
unset PGPASSWORD
```
(Ba lệnh nối bằng `&&`: file nào lỗi thì dừng, không chạy file sau. `<user>` ở đây là tài khoản quản trị của DB; nếu đi qua Supavisor (pooler) thì dạng user là `postgres.<project_ref>`. Có thể thay bằng `psql "$(cat <file DSN ngoài git>)"` nếu file đó chỉ chủ DB đọc được.)

**Đặt mật khẩu `obeval_writer` (tách riêng, không nằm trong file SQL):**
1. Chủ DB tạo mật khẩu ngẫu nhiên dài, đặt trong `psql` bằng `\password obeval_writer` (không gõ mật khẩu vào dòng lệnh, tránh lộ trong lịch sử shell).
2. Chủ DB ghép DSN của Supavisor cho người deploy (mục 5, bước 5) và gửi qua kênh an toàn:
   `postgresql://obeval_writer.<project_ref>:<mật khẩu>@<host pooler>:<cổng transaction pooler>/postgres`
   Mật khẩu có ký tự đặc biệt (`@`, `:`, `/`, `?`, `#`, `%`...) thì phải **mã hoá URL (percent-encode)** trong DSN, nếu không DSN bị đọc sai và không kết nối được. Cách dễ nhất là sinh mật khẩu chỉ gồm chữ và số.

**Kiểm cuối (bắt buộc), hai câu ở cuối `sql/003`:**

```sql
-- (a) RLS đã bật trên 2 bảng nguồn
select relname, relrowsecurity from pg_class where relname in ('bookings','event_types');

-- (b) Hàm SECURITY DEFINER trong public mà obeval_writer gọi được
select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where n.nspname='public' and p.prosecdef and has_function_privilege('obeval_writer', p.oid, 'execute');
```
Câu (b) trả hàm nào thì xem hàm đó có trả dữ liệu cá nhân không. Có thì `revoke execute ... from public`, rồi cấp lại đúng role cần. Chưa xử lý xong thì **chưa** đưa DSN cho người deploy.

Kiểm bằng chính role mới (dùng DSN của `obeval_writer`):

```bash
read -rs PGPASSWORD; export PGPASSWORD          # mật khẩu của obeval_writer
psql -h <host pooler> -p <cổng> -U obeval_writer.<project_ref> -d postgres -c "select count(*) from public.onboarding_criteria"   # > 0
psql -h <host pooler> -p <cổng> -U obeval_writer.<project_ref> -d postgres -c "select * from public.bookings limit 1"             # PHẢI báo permission denied (role chỉ đọc 6 cột)
unset PGPASSWORD
```

**Lên prod:** chép 3 file vào repo TeenCareBooking (nhánh `tanh/dev/onboarding-ai-report`, thư mục `supabase/migrations/`) theo tên `20261014000001_onboarding_evaluations.sql`, `20261014000002_onboarding_criteria_seed.sql`, `20261014000003_obeval_writer.sql`, mở PR. Chủ DB prod duyệt rồi chạy 3 file trên DB prod và đặt mật khẩu như trên. Người deploy **không** chạy migration lên prod.

## 3. Bước B: STT server (người phát triển obeval)

- Repo STT, nhánh `tanh/feat/onboarding-profile`.
- Phần Go (`api-go`) **chưa từng được biên dịch** khi viết code. Trước khi deploy chạy một trong hai:

```bash
docker build -f api-go/Dockerfile api-go
# hoặc
cd api-go && go vet ./... && go build ./...
```
- Lỗi biên dịch thì **không deploy**, báo người phát triển obeval.
- Job không có `profile` giữ nguyên hành vi cũ (luồng hàng tuần không đổi).

## 4. Bước C: temp-transcript (người phát triển obeval)

- Repo temp-transcript, nhánh `tanh/feat/onboarding-profile`. **Chỉ deploy sau khi B xong.**
- **Không deploy trong khung 19h đến 23h** (giờ cao điểm của luồng hàng tuần).
- Trường `profile` mặc định rỗng, nên luồng hàng tuần không đổi.
- Sau khi deploy, kiểm `GET <URL temp-transcript>/healthz` trả `{"status":"ok","service":"temp-transcript"}`.

## 5. Bước D: GCP cho obeval (người deploy)

### 5.1. Điền chỗ trống

| Chỗ trống | Là gì | Lấy ở đâu |
|---|---|---|
| `<P_RUN>` | Project GCP đặt Cloud Run và Cloud Tasks của obeval | Sếp quyết định |
| `<P_TEMP>` | Project chạy service `temp-transcript` (Cloud Run `asia-east1`) | Người giữ Apps Script / sếp |
| `$SA` | Email service account của obeval, tạo ở bước 2 | Tự tạo. Đặt lại biến này nếu mở shell mới |
| `<DSN dev>` / `<DSN prod>` | Chuỗi kết nối của role `obeval_writer` | Chủ DB (mục 2) |
| `<file kịch bản PDC>` | Kịch bản onboarding của PDC (có số tài khoản ngân hàng, **không** nằm trong git) | PDC |

Đặt biến cho cả phiên làm việc (mở shell mới thì đặt lại cả `TT_URL` ở bước 7 và `URL` ở bước 8):

```bash
P_RUN=<P_RUN>
REGION=asia-southeast1
SA=obeval-runner@$P_RUN.iam.gserviceaccount.com
```

### 5.2. Danh sách bước

| Bước | Việc | Kiểm tra kết quả | Xong |
|---|---|---|---|
| 1 | Kiểm bucket có uniform bucket-level access | In ra `True` (kèm số project). `False` thì **dừng**, báo sếp | [ ] |
| 2 | Tạo service account `obeval-runner` và cấp quyền | `gcloud iam service-accounts list` thấy SA; điều kiện IAM của bucket có `onboarding-only` | [ ] |
| 3 | Kiểm SA chỉ đọc được prefix `transcripts/onboarding/` | Đọc file thử được; `ls transcripts/` **bị từ chối** | [ ] |
| 4 | Thêm luật lifecycle 90 ngày, giữ luật cũ | Luật cũ vẫn còn, có thêm đúng một luật `transcripts/onboarding/` 90 ngày; đã so `diff` và lưu `lifecycle-current.json` ngoài git | [ ] |
| 5 | Tạo 3 secret và cấp quyền đọc cho SA | `gcloud secrets list` thấy `obeval-api-token`, `obeval-db-dsn`, `obeval-script` | [ ] |
| 6 | Tạo hàng đợi Cloud Tasks `obeval-onboarding` | `gcloud tasks queues describe` thấy max attempts 5, concurrent 2 | [ ] |
| 7 | Chia sẻ folder Drive "Onboarding" cho SA của temp-transcript | Folder hiện email SA với quyền Viewer; folder **không** để "ai có link" | [ ] |
| 8 | Deploy `obeval-dev` rồi gán `OBEVAL_SELF_URL` | `curl $URL/healthz` trả `{"status":"ok","service":"obeval"}` | [ ] |

### Bước 1. Kiểm bucket

```bash
gcloud storage buckets describe gs://teenup-transcripts --format="value(uniform_bucket_level_access,project_number)"
```
Phải ra `True`. Nếu `False`: **dừng**, báo sếp. Bật uniform access ảnh hưởng mọi service đang dùng ACL của bucket, và điều kiện IAM ở bước 2 không dùng được khi chưa bật.

### Bước 2. Service account và quyền

Trước khi sửa IAM của bucket, lưu bản hiện tại (giữ **ngoài git**). Cần khôi phục thì đặt lại đúng các binding trong file này (`gcloud storage buckets set-iam-policy gs://teenup-transcripts iam-before.json`; nhờ người quản trị GCP nếu không chắc).

```bash
gcloud storage buckets get-iam-policy gs://teenup-transcripts > iam-before.json
gcloud iam service-accounts create obeval-runner --project $P_RUN --display-name "obeval Cloud Run"
gcloud projects add-iam-policy-binding tcservices2027 --member serviceAccount:$SA --role roles/aiplatform.user
gcloud projects add-iam-policy-binding $P_RUN --member serviceAccount:$SA --role roles/cloudtasks.enqueuer
gcloud storage buckets add-iam-policy-binding gs://teenup-transcripts --member serviceAccount:$SA \
  --role roles/storage.objectViewer \
  --condition='title=onboarding-only,expression=resource.name.startsWith("projects/_/buckets/teenup-transcripts/objects/transcripts/onboarding/")'
```

| Quyền | Trên | Để làm gì |
|---|---|---|
| `roles/aiplatform.user` | project `tcservices2027` (= `OBEVAL_GCP_PROJECT`) | Gọi Gemini trên Vertex AI. Đổi nếu `OBEVAL_GCP_PROJECT` đổi |
| `roles/cloudtasks.enqueuer` | `<P_RUN>` | Tạo Cloud Task gọi lại chính service |
| `roles/storage.objectViewer` **có điều kiện** | bucket `teenup-transcripts` | Chỉ đọc `transcripts/onboarding/`. Không được ghi, không đọc transcript hàng tuần |
| `roles/secretmanager.secretAccessor` | từng secret (bước 5) | Đọc secret lúc chạy |

### Bước 3. Kiểm quyền đọc đúng prefix

Cần quyền Service Account Token Creator trên `$SA` cho tài khoản của bạn, cấp tạm rồi thu lại:

```bash
ME=<email tài khoản gcloud của bạn>
gcloud iam service-accounts add-iam-policy-binding $SA --project $P_RUN \
  --member user:$ME --role roles/iam.serviceAccountTokenCreator
echo '{"check":"iam"}' | gcloud storage cp - gs://teenup-transcripts/transcripts/onboarding/_iam-check.json   # bằng tài khoản của bạn
gcloud storage cat gs://teenup-transcripts/transcripts/onboarding/_iam-check.json --impersonate-service-account $SA   # đọc được
gcloud storage ls gs://teenup-transcripts/transcripts/ --impersonate-service-account $SA                                 # PHẢI bị từ chối
gcloud storage rm gs://teenup-transcripts/transcripts/onboarding/_iam-check.json
gcloud iam service-accounts remove-iam-policy-binding $SA --project $P_RUN \
  --member user:$ME --role roles/iam.serviceAccountTokenCreator
```
**Dọn dẹp luôn phải làm, kể cả khi một dòng ở trên lỗi:** xoá `_iam-check.json` và thu lại quyền Token Creator (hai lệnh cuối). Dòng thứ ba mà **liệt kê được** nghĩa là điều kiện IAM không có tác dụng: **dừng**, xoá binding vừa tạo và báo người phát triển obeval. Lưu ý: quyền IAM mới có thể mất vài phút mới có hiệu lực; nếu dòng 2 báo 403, đợi 2 đến 3 phút rồi thử lại.

### Bước 4. Lifecycle 90 ngày (gộp, không ghi đè)

Bucket đang có luật khác. `--lifecycle-file` **thay toàn bộ** luật, nên phải lấy luật cũ ở dạng thô rồi thêm đúng một luật mới. Làm trong một thư mục ngoài repo.

```bash
# 1. Bản gốc (dạng {"rule":[...]}, nạp lại được trực tiếp)
gsutil lifecycle get gs://teenup-transcripts > lifecycle-current.json
```
Chưa cài `gsutil` thì dùng `gcloud storage buckets describe gs://teenup-transcripts --format=json`, lấy phần luật lifecycle thành file `{"rule":[...]}` bằng tay. Khi đó phải **kiểm tên khoá** (`rule`, `action`, `condition`, `matchesPrefix`) đúng kiểu viết mà `--lifecycle-file` chấp nhận.

```bash
# 2. Thêm đúng một luật vào bản sao
python - <<'PY'
import json
cur = json.load(open("lifecycle-current.json"))
rules = cur.get("rule", [])
new = {"action": {"type": "Delete"}, "condition": {"age": 90, "matchesPrefix": ["transcripts/onboarding/"]}}
if new not in rules:
    rules.append(new)
json.dump({"rule": rules}, open("lifecycle-new.json", "w"), indent=2)
print(len(rules), "luật")
PY

# 3. BẮT BUỘC xem khác biệt trước khi cập nhật
diff <(python -m json.tool --sort-keys lifecycle-current.json) <(python -m json.tool --sort-keys lifecycle-new.json)
```
**Dừng nếu** khác biệt không chỉ là đúng một luật mới được thêm vào (ví dụ điều kiện hoặc hành động của một luật cũ bị đổi, hoặc mất luật). Không chạy bước tiếp theo, báo người phát triển obeval. Không có `diff` thì mở hai file cạnh nhau và so bằng mắt.

```bash
# 4. Cập nhật rồi so lại
gcloud storage buckets update gs://teenup-transcripts --lifecycle-file=lifecycle-new.json
gsutil lifecycle get gs://teenup-transcripts > lifecycle-after.json
diff <(python -m json.tool --sort-keys lifecycle-new.json) <(python -m json.tool --sort-keys lifecycle-after.json)     # không được có khác biệt
```
- Kết quả đúng: các luật cũ vẫn còn nguyên, thêm **đúng một** luật 90 ngày cho `transcripts/onboarding/`.
- **Giữ `lifecycle-current.json` ở nơi an toàn ngoài git** (bản gốc để khôi phục).
- Muốn khôi phục: `gcloud storage buckets update gs://teenup-transcripts --lifecycle-file=lifecycle-current.json`.

### Bước 5. Secret Manager

```bash
python -c "import secrets,sys;sys.stdout.write(secrets.token_urlsafe(32))" | gcloud secrets create obeval-api-token --project $P_RUN --data-file=-
read -rs DSN; printf %s "$DSN" > <file tạm ngoài repo>; unset DSN   # dán DSN dev ở prompt (không hiện, không vào lịch sử shell; không dùng trình soạn thảo: tránh xuống dòng ở cuối)
gcloud secrets create obeval-db-dsn --project $P_RUN --data-file=<file tạm ngoài repo>
rm -f <file tạm ngoài repo>
gcloud secrets create obeval-script --project $P_RUN --data-file=<file kịch bản PDC>
for s in obeval-api-token obeval-db-dsn obeval-script; do
  gcloud secrets add-iam-policy-binding $s --project $P_RUN --member serviceAccount:$SA --role roles/secretmanager.secretAccessor
done
```

| Secret | Nội dung | Ghi chú |
|---|---|---|
| `obeval-api-token` | Chuỗi ngẫu nhiên (lệnh trên sinh ra, không tự nghĩ ra) | Token chung cho Apps Script và Cloud Tasks. **Không in ra màn hình, không chép vào file** |
| `obeval-db-dsn` | DSN dev của `obeval_writer` | Khi lên prod tạo thêm `obeval-db-dsn-prod` (DSN prod) |
| `obeval-script` | Toàn bộ nội dung kịch bản PDC | **Không đưa vào image.** Cloud Run mount thành file lúc chạy |

Khuyến nghị: khi lên prod tạo thêm `obeval-api-token-prod` (token riêng). Token dev lộ thì prod không bị ảnh hưởng. Apps Script đổi URL thì đổi cả token.

Token và DSN **không được có ký tự xuống dòng ở cuối**: nếu có, mọi lời gọi bị 401 (token) hoặc không kết nối được DB (DSN). Vì thế token sinh bằng `sys.stdout.write` và DSN ghi bằng `printf %s`. File tạm DSN xoá ngay sau khi tạo secret (lệnh `rm` ở trên).

### Bước 6. Hàng đợi Cloud Tasks

```bash
gcloud tasks queues create obeval-onboarding --project $P_RUN --location $REGION \
  --max-attempts 5 --min-backoff 60s --max-concurrent-dispatches 2
```
Hàng đợi và `OBEVAL_TASKS_PROJECT` / `OBEVAL_TASKS_LOCATION` / `OBEVAL_TASKS_QUEUE` phải khớp nhau. Dev và prod dùng chung một hàng đợi được (mỗi task mang đúng URL của service đã tạo ra nó); khi đó giới hạn 2 lượt chạy đồng thời tính chung cho cả hai.

### Bước 7. Cho temp-transcript đọc folder Onboarding

```bash
gcloud run services describe temp-transcript --project <P_TEMP> --region asia-east1 \
  --format="value(spec.template.spec.serviceAccountName)"
```
Chia sẻ folder Drive "Onboarding recordings" (quyền **Viewer**) cho email in ra. Chỉ chia sẻ cho email này và nhóm PDC. Không bật "ai có link": video có trẻ em.

Lấy URL temp-transcript để điền `OBEVAL_TEMP_TRANSCRIPT_URL` ở bước 8 (không tự nghĩ ra URL):

```bash
TT_URL=$(gcloud run services describe temp-transcript --project <P_TEMP> --region asia-east1 --format="value(status.url)")
curl -s $TT_URL/healthz        # {"status":"ok","service":"temp-transcript"}
```
obeval gọi `POST $TT_URL/beta/transcript` **không kèm** ID token của Cloud Run. Nếu `curl` trên trả 403, service đó đang bắt xác thực Cloud Run: **dừng** và báo người phát triển obeval (obeval chưa hỗ trợ trường hợp này).

### Bước 8. Deploy bản dev

Chạy ở thư mục gốc của repo (nhánh `feat/onboarding-service`). Lần đầu `gcloud` có thể hỏi tạo Artifact Registry repo `cloud-run-source-deploy`, trả lời `y`.
Deploy dev dùng DB dev, `OBEVAL_PUBLISH=false`.

```bash
NAME=obeval-dev
gcloud run deploy $NAME --source . --project $P_RUN --region $REGION --service-account $SA \
  --timeout 900 --concurrency 1 --max-instances 5 --memory 1Gi --cpu 1 --allow-unauthenticated \
  --set-secrets "OBEVAL_DB_DSN=obeval-db-dsn:latest,OBEVAL_API_TOKEN=obeval-api-token:latest,/secrets/script/script.md=obeval-script:latest" \
  --set-env-vars "OBEVAL_SCRIPT=/secrets/script/script.md,OBEVAL_PUBLISH=false,OBEVAL_GOOD_THRESHOLD=0.80,OBEVAL_GCP_PROJECT=tcservices2027,OBEVAL_GCP_LOCATION=us-central1,OBEVAL_TEMP_TRANSCRIPT_URL=$TT_URL,OBEVAL_TASKS_PROJECT=$P_RUN,OBEVAL_TASKS_LOCATION=$REGION,OBEVAL_TASKS_QUEUE=obeval-onboarding"
URL=$(gcloud run services describe $NAME --project $P_RUN --region $REGION --format="value(status.url)")
gcloud run services update $NAME --project $P_RUN --region $REGION --update-env-vars OBEVAL_SELF_URL=$URL
curl -s $URL/healthz
```
Kết quả đúng: `{"status":"ok","service":"obeval"}`.

- Gán `OBEVAL_SELF_URL` là bước **thứ hai** vì URL chỉ biết sau lần deploy đầu. Thiếu biến này thì mọi lần nhận recording trả lỗi 500 (không tạo được Cloud Task).
- Nếu nhóm nghiệm thu chốt `OBEVAL_RUNS=5` (cổng chất lượng) thì thêm `OBEVAL_RUNS=5` vào `--set-env-vars`.
- Nếu `--allow-unauthenticated` bị chặn bởi chính sách tổ chức: **dừng** và báo sếp. Không tự gỡ token để "cho chạy".

### Cập nhật code obeval (redeploy)

Khi chỉ đổi code, deploy lại **không** kèm `--set-env-vars` và `--set-secrets`: Cloud Run giữ nguyên biến và secret cũ.

```bash
NAME=<obeval-dev|obeval>      # chọn đúng service cần cập nhật
gcloud run deploy $NAME --source . --project $P_RUN --region $REGION
URL=$(gcloud run services describe "$NAME" --project $P_RUN --region $REGION --format='value(status.url)')
```
Cần đổi một biến thì dùng `--update-env-vars <TÊN>=<giá trị>` (chỉ đổi biến đó). **`--set-env-vars` thay TOÀN BỘ biến môi trường**: dùng nó khi deploy lại sẽ làm mất `OBEVAL_SELF_URL` (và mọi biến không liệt kê), service sẽ lỗi 500 khi tạo Cloud Task. Nếu lỡ dùng, gán lại bằng `gcloud run services update $NAME --project $P_RUN --region $REGION --update-env-vars OBEVAL_SELF_URL=$URL`.

### Lên prod

Chỉ làm khi dev đã chạy đầu-cuối tốt (mục 9.2) và chủ DB đã chạy migration prod (mục 2).

```bash
read -rs DSN; printf %s "$DSN" > <file tạm ngoài repo>; unset DSN   # dán DSN prod ở prompt (không hiện, không vào lịch sử shell)
gcloud secrets create obeval-db-dsn-prod --project $P_RUN --data-file=<file tạm ngoài repo>
rm -f <file tạm ngoài repo>
python -c "import secrets,sys;sys.stdout.write(secrets.token_urlsafe(32))" | gcloud secrets create obeval-api-token-prod --project $P_RUN --data-file=-
for s in obeval-db-dsn-prod obeval-api-token-prod; do
  gcloud secrets add-iam-policy-binding $s --project $P_RUN --member serviceAccount:$SA --role roles/secretmanager.secretAccessor
done

TT_URL=$(gcloud run services describe temp-transcript --project <P_TEMP> --region asia-east1 --format="value(status.url)")
NAME=obeval
gcloud run deploy $NAME --source . --project $P_RUN --region $REGION --service-account $SA \
  --timeout 900 --concurrency 1 --max-instances 5 --memory 1Gi --cpu 1 --allow-unauthenticated \
  --set-secrets "OBEVAL_DB_DSN=obeval-db-dsn-prod:latest,OBEVAL_API_TOKEN=obeval-api-token-prod:latest,/secrets/script/script.md=obeval-script:latest" \
  --set-env-vars "OBEVAL_SCRIPT=/secrets/script/script.md,OBEVAL_PUBLISH=false,OBEVAL_GOOD_THRESHOLD=0.80,OBEVAL_GCP_PROJECT=tcservices2027,OBEVAL_GCP_LOCATION=us-central1,OBEVAL_TEMP_TRANSCRIPT_URL=$TT_URL,OBEVAL_TASKS_PROJECT=$P_RUN,OBEVAL_TASKS_LOCATION=$REGION,OBEVAL_TASKS_QUEUE=obeval-onboarding"
URL=$(gcloud run services describe $NAME --project $P_RUN --region $REGION --format="value(status.url)")
gcloud run services update $NAME --project $P_RUN --region $REGION --update-env-vars OBEVAL_SELF_URL=$URL
curl -s $URL/healthz
```
**`OBEVAL_PUBLISH=false` ở prod.** Kết quả ghi vào DB nhưng Mentor chưa thấy cho tới khi qua cổng chất lượng (mục 8).

## 6. Cấu hình Cloud Run

| Cấu hình | Giá trị | Lý do |
|---|---|---|
| `--timeout` | `900` (giây) | **Bắt buộc.** Lượt `advance` gọi temp-transcript với timeout 600 giây rồi chấm 3 đến 4 phút. Mặc định 300 giây sẽ cắt giữa chừng |
| `--concurrency` | `1` | Mỗi lượt chấm gọi Gemini 3 lần song song và tốn RAM; một instance làm một việc |
| `--max-instances` | `5` | Giới hạn chi phí và quota Vertex. Cloud Tasks chỉ chạy 2 lượt cùng lúc |
| `--memory` / `--cpu` | `1Gi` / `1` | Đủ cho transcript và chấm. Thiếu bộ nhớ thì tăng `--memory`, không tăng `--concurrency` |
| `--allow-unauthenticated` | **có** | Apps Script và Cloud Tasks gọi bằng header chung `X-Obeval-Token`, không dùng ID token của Cloud Run. Nên **không** dùng `--no-allow-unauthenticated` |
| Vùng | `asia-southeast1` | Phải khớp `OBEVAL_TASKS_LOCATION` và hàng đợi |
| Project | `<P_RUN>` | Phải khớp `OBEVAL_TASKS_PROJECT` |
| Service account | `obeval-runner` | Quyền ở bước 2 và 5 |

**Cảnh báo bảo mật.** Endpoint `https://…run.app/v1/…` là **công khai trên mạng**. Chỉ có `X-Obeval-Token` bảo vệ. Vì vậy:
- token phải dài và ngẫu nhiên (lệnh ở bước 5);
- token chỉ nằm ở Secret Manager và Script Properties của Apps Script;
- token lộ (chat, email, ảnh chụp màn hình, log) thì **đổi ngay**:
  1. `python -c "import secrets,sys;sys.stdout.write(secrets.token_urlsafe(32))" | gcloud secrets versions add obeval-api-token --project $P_RUN --data-file=-`
  2. `gcloud run services update <tên service> --project $P_RUN --region $REGION --update-secrets OBEVAL_API_TOKEN=<tên secret token của service đó>:latest` (tạo revision mới đọc token mới)
  3. Đổi `OBEVAL_TOKEN` trong Script Properties của Apps Script.
  4. Vô hiệu hoá phiên bản secret cũ (`gcloud secrets versions disable <số> --secret <tên secret>`).
  5. Cloud Task đang nằm trong hàng đợi mang theo **token cũ** nên sẽ nhận 401. Gửi lại các file đang `processing` (mục 10).

## 7. Biến môi trường và secret của obeval

Giá trị lấy từ code: `obeval/config.py`, `app.py`, `store.py`, `tasks.py`, `gcs.py`, `transcribe_client.py`.

| Tên | Ví dụ | Lấy từ đâu | Bắt buộc? |
|---|---|---|---|
| `OBEVAL_DB_DSN` | `postgresql://obeval_writer.<project_ref>:<mật khẩu>@<host pooler>:<cổng>/postgres` | Chủ DB → Secret Manager `obeval-db-dsn` (dev) / `obeval-db-dsn-prod` | **Có.** Thiếu thì lỗi "Thiếu OBEVAL_DB_DSN" |
| `OBEVAL_API_TOKEN` | (chuỗi ngẫu nhiên) | Secret Manager `obeval-api-token` | **Có.** Thiếu thì mọi lời gọi bị 401 |
| `OBEVAL_SCRIPT` | `/secrets/script/script.md` | Đường dẫn file Secret Manager mount vào (`--set-secrets`) | **Có.** Mặc định trỏ vào `data/raw/…` không có trong image |
| `OBEVAL_TEMP_TRANSCRIPT_URL` | `https://<tên service>-<…>.asia-east1.run.app` | Lệnh `gcloud run services describe temp-transcript … value(status.url)` (bước 7) | **Có** |
| `OBEVAL_TRANSCRIPT_BUCKET` | `teenup-transcripts` | Mặc định đúng; chỉ đặt nếu bucket khác | Không |
| `OBEVAL_TASKS_PROJECT` | `<P_RUN>` | Project của hàng đợi | **Có** |
| `OBEVAL_TASKS_LOCATION` | `asia-southeast1` | Vùng của hàng đợi | **Có** |
| `OBEVAL_TASKS_QUEUE` | `obeval-onboarding` | Bước 6 | **Có** |
| `OBEVAL_SELF_URL` | `https://obeval-dev-<…>.asia-southeast1.run.app` | `status.url` của chính service, gán sau lần deploy đầu (bước 8) | **Có** (thiếu thì không tạo được Cloud Task) |
| `OBEVAL_PUBLISH` | `false` | Đặt `false` khi deploy | Không (mặc định `false`). `true` chỉ sau cổng chất lượng (mục 8) |
| `OBEVAL_GOOD_THRESHOLD` | `0.80` | **PDC chốt.** `0.80` là tạm thời. Đổi không cần chấm lại | Không (mặc định `0.80`) |
| `OBEVAL_RUNS` | `3` | Mặc định `3`. Nếu nghiệm thu (`docs/nghiem-thu.md`) kết luận cần thì `5` (chi phí mỗi ca tăng khoảng 5/3) | Không |
| `OBEVAL_GCP_PROJECT` | `tcservices2027` | Project có Vertex AI. Phải khớp project đã cấp `aiplatform.user` | Không (mặc định `tcservices2027`) |
| `OBEVAL_GCP_LOCATION` | `us-central1` | Vùng Vertex AI | Không (mặc định `us-central1`) |
| `OBEVAL_MODEL` | `gemini-2.5-pro` | Model chấm | Không |
| `OBEVAL_THINKING` | `16384` | Ngân sách "suy nghĩ" của model | Không |
| `OBEVAL_ENSEMBLE_TEMPERATURE` | `1.0` | Nhiệt độ các lần chấm | Không |
| `OBEVAL_NE_RATIO` | `0.30` | Tỉ lệ tiêu chí "không đánh giá được" thì coi là thiếu dữ liệu. PDC chưa chốt | Không |

Không đặt trên Cloud Run: `OBEVAL_DATA_ROOT`, `OBEVAL_OUT_ROOT`, `OBEVAL_PROMPT_DIR`, `OBEVAL_GCP_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`. Cloud Run dùng service account gắn sẵn, không có file key.

## 8. Cổng chất lượng: khi nào cho Mentor thấy kết quả

**Chỉ làm khi cả hai điều kiện đều đúng:**
1. `docs/nghiem-thu.md` ghi kết luận **đạt** (5 chỉ tiêu × 5 ca). File này chưa có: nó được tạo khi chạy cổng chất lượng (Task 4 của kế hoạch `docs/superpowers/plans/2026-10-14-onboarding-eval-service.md`). **Chưa có file, hoặc file chưa ghi "đạt", thì coi như cổng chưa qua.**
2. PDC đã chốt ngưỡng đạt (`OBEVAL_GOOD_THRESHOLD`).

Chưa đạt thì **không** bật. Làm theo thứ tự:

```bash
gcloud run services update obeval --project $P_RUN --region $REGION \
  --update-env-vars OBEVAL_PUBLISH=true,OBEVAL_GOOD_THRESHOLD=<ngưỡng PDC chốt>
OBEVAL_DB_DSN=$(gcloud secrets versions access latest --secret obeval-db-dsn-prod --project $P_RUN) python run.py publish
```
- Dòng đầu: ca chấm **từ giờ** sẽ tự hiện cho Mentor.
- Dòng sau (chạy từ máy có repo và đã `pip install -r requirements.txt`; `run.py` không nằm trong image): cho Mentor xem mọi ca đã `done` mà trước đó chưa hiện. In `Đã cho Mentor xem <N> ca`.
- Kiểm: Mentor thử thấy nút "Góp ý AI" ở trang Lịch đã đặt.
- Giá trị DSN chỉ nằm trong biến của dòng lệnh đó, không ghi ra file.

## 9. Kiểm sau deploy

### 9.1. Kiểm nhanh (dev, rồi prod)

```bash
TOKEN=$(gcloud secrets versions access latest --secret obeval-api-token --project $P_RUN)   # không echo

# 1. Sống
curl -s $URL/healthz                                                                         # {"status":"ok","service":"obeval"}

# 2. Không token: PHẢI 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST $URL/v1/recordings \
  -H "Content-Type: application/json" -d '{"id":"x","name":"x","webViewLink":"x"}'            # 401

# 3. Đúng token, file không phải onboarding: bị bỏ qua, không đụng DB
curl -s -X POST $URL/v1/recordings -H "Content-Type: application/json" -H "X-Obeval-Token: $TOKEN" \
  -d '{"id":"smoke-test","name":"not an onboarding file","webViewLink":"x"}'                 # {"status":"ignored","reason":"not_onboarding"}
```
(Với prod dùng secret `obeval-api-token-prod`.)

Token hoặc DSN có ký tự xuống dòng ở cuối làm mọi lời gọi bị 401 (hoặc DB không kết nối được). Gặp vậy thì tạo lại **phiên bản secret mới không có ký tự đó** (`sys.stdout.write` / `printf %s` như bước 5, dùng `gcloud secrets versions add`), rồi cho service đọc phiên bản mới bằng lệnh `gcloud run services update <tên service> --project $P_RUN --region $REGION --update-secrets OBEVAL_API_TOKEN=<tên secret token của service đó>:latest` ở mục 6 (với DSN thì `OBEVAL_DB_DSN=<tên secret DSN>:latest`).

Sai token cũng phải trả 401. Nếu dòng 3 trả 500, xem log: `gcloud run services logs read $NAME --project $P_RUN --region $REGION --limit 50`.

### 9.2. Chạy đầu-cuối trên dev (ca giả)

Chỉ làm trên **dev**, bằng dữ liệu giả. Không dùng buổi của gia đình thật.

1. Chủ DB dev tạo một booking giả: loại sự kiện `Gia sư tâm lý 1:1 Onboarding`, `student_code` giả (dạng `TC` + số), `start_at` gần giờ ghi âm.
2. Người phát triển obeval đưa một recording thử (người lớn đóng vai, không phải trẻ em thật) vào folder "Onboarding recordings", tên đúng mẫu của Meet (`… Onboarding -<mã TC>_PH … - <YYYY_MM_DD HH_MM> GMT+07_00 – Recording.mp4`); Apps Script chạy, hoặc gọi tay `POST /v1/recordings` với `id`, `name`, `webViewLink` của file đó.
3. Chờ (mỗi lượt 5 phút) rồi kiểm:

```bash
read -rs PGPASSWORD; export PGPASSWORD          # mật khẩu obeval_writer của DB dev; cách chạy psql như ở mục 2
psql -h <host pooler dev> -p <cổng> -U obeval_writer.<project_ref dev> -d postgres -c "select status, attempts, overall, published_at, error from public.onboarding_evaluations where booking_id = '<booking giả>'"
unset PGPASSWORD
gcloud run services logs read obeval-dev --project $P_RUN --region $REGION --limit 50
```
Kết quả đúng:
- `status` đi `processing` → `done` (hoặc `insufficient` nếu STT không chia được người nói);
- `published_at` là `null`;
- trên GCS có `transcripts/onboarding/<booking giả>.json`, **không** có `transcripts/<booking giả>.json`;
- gửi lại đúng file đó: `{"status":"already_done",...}`, không có lượt chấm thứ hai (không tốn tiền Gemini).

### 9.3. Theo dõi hàng ngày ở prod (chạy im lặng; câu 3 là kiểm tra thường trực, không chỉ tuần đầu)

```sql
select status, count(*) from public.onboarding_evaluations where created_at > now() - interval '1 day' group by 1;
select reason, count(*) from public.onboarding_recording_unmatched where last_seen_at > now() - interval '1 day' group by 1;
select booking_id, attempts, error, updated_at from public.onboarding_evaluations where status = 'processing' and updated_at < now() - interval '30 minutes';
```

| Câu | Đọc thế nào |
|---|---|
| 1 | Số ca `done` xấp xỉ số buổi onboarding đã diễn ra. Nhiều `error` / `insufficient` thì xem cột `error` |
| 2 | Có dòng nào nghĩa là recording không ghép được booking (`unparsable_name`: tên file lạ; `no_booking`: không có booking khớp; `duplicate_recording`: booking đã có recording được chấm, file thứ hai không bị chấm đè). Với hai lý do đầu: xử lý tay rồi chạy `markRecentPendingOnboarding`. Với `duplicate_recording`: người xem xét file nào đúng (quy tắc "recording hoàn tất đầu tiên thắng", xem mục 10) |
| 3 | Dòng `processing` **không được cập nhật quá 30 phút** nghĩa là chuỗi lượt chấm đã đứt (dòng đang chờ STT được cập nhật mỗi 5 phút). Xử lý theo mục 10. 3 giờ là giới hạn chờ STT bình thường, không phải ngưỡng kẹt: ca chờ STT 2 giờ vẫn khoẻ nếu `updated_at` còn mới. **Đây là kiểm tra thường trực mỗi ngày, mãi mãi**: người giữ obeval nên đặt cảnh báo tự động (Cloud Monitoring / job gửi mail) cho câu này; có dòng nào là phải xử lý, vì không có cơ chế nào khác tự báo ca đứt |

## 10. Giới hạn đã biết và cách xử lý

| Vấn đề | Chi tiết và cách xử lý |
|---|---|
| **Chưa build Docker** | Trước lần deploy đầu chạy ở máy có Docker: `docker build -t obeval:local .` rồi `docker run --rm obeval:local ls /app`. Chỉ được thấy `obeval`, `prompt`, `requirements.txt`. **Thấy `data`, `tests` hoặc file kịch bản thì dừng.** `gcloud run deploy --source .` build bằng Cloud Build cùng `Dockerfile` |
| Container không chạy bằng root | Image chạy bằng user không đặc quyền `app` (`USER app` trong `Dockerfile`). Nếu cần ghi file ngoài `/tmp` thì phải cấp quyền cho user này |
| **Token chung nằm trong header của Cloud Task** | Token `X-Obeval-Token` đi kèm mỗi Cloud Task (header của task). Ai có quyền `cloudtasks.tasks.get` với view FULL trên project đều đọc được token. Hạn chế quyền đó cho đúng người; đổi token theo mục 6 nếu nghi ngờ. Cải tiến sau: xác thực bằng OIDC token của service account thay cho token chung |
| Recording thứ hai cho cùng booking | **Recording hoàn tất đầu tiên thắng.** Booking đã có kết quả `done` / `insufficient` thì file Drive khác (vd. Meet tạo file thứ hai do ghi lại giữa chừng) KHÔNG được chấm: nó được ghi vào `onboarding_recording_unmatched` với `reason = 'duplicate_recording'`, `register` trả `{"status":"duplicate"}`, Apps Script đánh `transcript:no-match` và gửi mail `ONB_ALERT_EMAIL`. Người quyết định file nào đúng; muốn chấm file thứ hai thì làm theo hướng dẫn của người phát triển obeval (không tự sửa DB). Nếu dòng đang `processing` / `error` thì file khác bắt đầu lượt mới và thay file cũ (hiếm: bản chép lời của file cũ còn sót có thể bị chấm nhầm, chấp nhận) |
| Thư viện không khoá phiên bản | `requirements.txt` dùng `>=`, nên mỗi lần build có thể lấy bản mới hơn. Build lỗi sau một thời gian mà code không đổi thì nghi ngờ điều này |
| Cloud Tasks thử lại khi service trả 5xx | Lỗi DB hoặc lỗi ngoài dự kiến ở `/v1/tasks/advance` trả 500; hàng đợi thử lại tối đa 5 lần (cấu hình ở bước 6). Hết 5 lần mà chưa xong thì dòng vẫn ở `processing` |
| Lỗi tạm của model (429, 503, quota, timeout) | obeval tự chờ và thử lại ở lượt sau (tối đa 6 lượt thêm ngoài ngân sách chờ STT) |
| Lỗi cố định (4xx từ temp-transcript, STT báo lỗi, lỗi code không lường trước) | Ca kết thúc ngay với `status=error` và ghi cột `error`. **Không** tự thử lại |
| STT không chia người nói (`legacy-*`, bản rỗng) | Ca `insufficient`, không chấm |
| Chờ STT | Mỗi 5 phút hỏi một lần, tối đa 3 giờ (giờ cao điểm STT 20h đến 22h trùng giờ onboarding). Quá 3 giờ: `status=error` |
| Lỗi 403 khi đọc GCS | `download` chỉ coi "không có file" là chưa xong. 403 (sai IAM) làm ca kết thúc `error`. Kiểm lại bước 2 và 3 |
| Token đổi nhưng Cloud Task cũ còn trong hàng đợi | Task cũ nhận 401, thử lại rồi chết. Xem mục "đổi token" ở mục 6 |

**Ca kẹt ở `processing`.** Ngưỡng là **30 phút không cập nhật** (`updated_at`): dòng đang chờ STT được cập nhật mỗi 5 phút, nên quá 30 phút là chuỗi lượt chấm đã đứt. (3 giờ là giới hạn chờ STT bình thường của một ca khoẻ, không phải ngưỡng kẹt.) Xử lý, không cần sửa DB:
- chạy `markRecentPendingOnboarding` trong Apps Script để gửi lại file (file trong folder Onboarding tạo trong 2 ngày gần đây);
- hoặc gọi lại `POST /v1/recordings` với đúng file đó.
`register` thấy dòng `processing` quá 30 phút (hoặc `error`) thì bắt đầu lại với `run_id` mới; Cloud Task cũ tự bị bỏ. File đã `done` / `insufficient` thì không chấm lại (`already_done`).

## 11. Tắt và hoàn tác

Không cần xoá gì ở DB prod.

| Muốn | Làm | Hậu quả |
|---|---|---|
| Ngừng nhận ca mới | Xoá (hoặc để trống) Script Property `OBEVAL_URL`, hoặc xoá trigger của Apps Script. Nhánh onboarding tự tắt, luồng hàng tuần không bị ảnh hưởng | Kết quả cũ giữ nguyên. Bật lại sau một thời gian tắt: chạy **`backfillOldRecordings` trước** (chuyển recording còn nằm trong "Google Meet" vào folder Onboarding), **rồi `markRecentPendingOnboarding`** (đưa file 2 ngày gần nhất vào hàng chờ, kể cả file đã `sent`); file cũ hơn gửi tay |
| Dừng hẳn service | Tạm dừng hàng đợi (dòng dưới), rồi `gcloud run services delete obeval --project $P_RUN --region $REGION`. Bật lại bằng **đủ** lệnh deploy lần đầu (bước 8 hoặc "Lên prod", có `--set-secrets` / `--set-env-vars`, rồi gán lại `OBEVAL_SELF_URL`); secret, SA, hàng đợi giữ nguyên | Dịch vụ không nhận gì. Dòng `processing` giữ nguyên, xử lý theo mục 10 khi bật lại |
| Dừng lượt đang chạy | `gcloud tasks queues pause obeval-onboarding --project $P_RUN --location $REGION` (bật lại: `resume`) | Task giữ nguyên trong hàng đợi |
| Mentor đã thấy kết quả mà cần ẩn | Báo người phát triển obeval. `published_at` do chủ DB đặt lại `null` sau khi cân nhắc | Không tự sửa DB |

- **Không** chạy khối "Hoàn tác" ở cuối `sql/003_obeval_writer.sql` trên prod. Khối đó chỉ dành cho dev.
- Không xoá bảng `onboarding_*` ở prod: chúng chứa kết quả chấm của Mentor.
- Hoàn tác temp-transcript: deploy lại revision trước (`gcloud run services update-traffic temp-transcript --project <P_TEMP> --region asia-east1 --to-revisions <revision cũ>=100`). Luồng hàng tuần không bị ảnh hưởng vì `profile` mặc định rỗng.
