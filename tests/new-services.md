# New Services Integration Tests (tei, lightrag, paperless, paperless-gpt, whishper, linkwarden, chandra)

Userland validation of the five services added after v0.5.5, from a cold start, exactly as a user would run them.

## Prerequisites
- Working directory: repo root (`/home/everlier/code/harbor`); use `./harbor.sh`.
- Docker running; `./harbor.sh config update` already applied (check `./harbor.sh config get tei.host_port` prints `35030`).
- Host has no NVIDIA GPU (ROCm); never start `nvidia` cross-files. `harbor.ollama` may already be running — that is fine.
- Use `docker logs <container>` — never `harbor logs` (tails and hangs).
- Use `AGENT_BROWSER_SESSION=<handle>` for every `agent-browser` call so sessions don't collide.
- Always start with `./harbor.sh up --no-defaults <handles>` (avoid pulling in webui/llamacpp), and finish each group with `./harbor.sh down <handles>` — never bare `harbor down`. `harbor down <handle>` also stops the other services from the same `up` set (ollama included), so restart ollama with `./harbor.sh up --no-defaults ollama` afterwards when a later group needs it.
- Ollama models needed: `qwen2.5:1.5b`, `nomic-embed-text` (`./harbor.sh ollama pull <model>`). LightRAG pulls its own `qwen3.5:4b` and derives `lightrag/qwen3.5:4b` + `-query` at container start (first `up` can take minutes; healthcheck allows 30m).
- Wait for health with a loop over `docker inspect -f '{{.State.Health.Status}}'` or an HTTP poll, up to 5 min; fail the test if not reached.
- Record for every test: exact commands, HTTP status codes, relevant log excerpts, PASS/FAIL per expectation.

## Group 1 — tei

### Test 1.1: Cold start and embedding API
**Steps:**
1. `./harbor.sh up --no-defaults tei`; poll `http://localhost:35030/health` until 200.
2. `curl -s -X POST localhost:35030/embed -H 'Content-Type: application/json' -d '{"inputs":"harbor test"}'`.
3. `curl -s -X POST localhost:35030/v1/embeddings -H 'Content-Type: application/json' -d '{"input":["a","b"],"model":"x"}'`.
4. `curl -s localhost:35030/info`.
5. `docker logs harbor.tei 2>&1 | grep -iE "error|panic"`.

**Expectations:**
1. Container `harbor.tei` reaches healthy within 5 min.
2. Step 2 returns a JSON array containing one array of 384 floats.
3. Step 3 returns OpenAI-shaped `data` with 2 embeddings and `model` = `BAAI/bge-small-en-v1.5`.
4. Step 4 `model_id` = `BAAI/bge-small-en-v1.5`.
5. Step 5 output empty (warnings allowed).
6. `./harbor.sh down tei` exits 0 and `harbor.tei` is gone from `docker ps`.

### Test 1.2: Model override via config
**Steps:**
1. `./harbor.sh config set tei.model sentence-transformers/all-MiniLM-L6-v2`; `./harbor.sh up --no-defaults tei`; poll `/health`.
2. `curl -s localhost:35030/info`.
3. Restore: `./harbor.sh down tei; ./harbor.sh config set tei.model BAAI/bge-small-en-v1.5`.

**Expectations:**
1. `/info` `model_id` = `sentence-transformers/all-MiniLM-L6-v2`; `/embed` returns 384-dim vectors.
2. Config restored (`./harbor.sh config get tei.model` prints `BAAI/bge-small-en-v1.5`).

## Group 2 — lightrag

### Test 2.1: Ollama-backed ingest and grounded query
**Steps:**
1. `./harbor.sh up --no-defaults lightrag ollama`; poll `http://localhost:35040/health` (200).
2. Insert a unique fact: `POST /documents/text` with header `X-API-Key: sk-lightrag`, body `{"text":"The Quorvax Lantern was designed by Mira Oduya in Reykjavik in 2021. Its emblem is an orange fox named Tobin.","file_source":"quorvax.txt"}`.
3. Poll `GET /documents` (same header) until the document status is `processed` (max 5 min).
4. `POST /query` body `{"query":"Who designed the Quorvax Lantern and what is its emblem?","mode":"hybrid"}`; also `mode":"naive"`. Then run `./services/lightrag/check-graph.sh --stack ollama` (5 hybrid questions, cleans up after itself).
5. Web UI: `agent-browser open http://localhost:35040/`, enter API key if prompted, snapshot.
6. Check `docker logs harbor.lightrag` for tracebacks.

**Expectations:**
1. Health 200; unauthenticated `POST /documents/text` (no header) returns 401/403.
2. Document reaches `processed`.
3. At least one of the two query responses contains "Mira Oduya" AND ("fox" or "Tobin"); `check-graph.sh` exits 0 and the document list is unchanged afterwards.
4. UI snapshot shows the Documents view listing `quorvax.txt`.
5. No Python tracebacks in logs.
6. `docker exec harbor.lightrag id -u` prints the host uid and `find services/lightrag/data ! -user $USER` is empty.

### Test 2.2: TEI embedding cross-file
**Steps:**
1. `./harbor.sh down lightrag` (this also stops ollama; it is restarted in the next step). No storage cleanup is needed: TEI-embedded data lives in its own `rag_storage/tei/` directory.
2. `./harbor.sh up --no-defaults lightrag ollama tei`; poll both healths.
3. Insert the same document as 2.1 and wait for `processed`.
4. `POST /query` mode `naive`.
5. `docker logs harbor.tei 2>&1 | grep -c embed`; `docker logs harbor.lightrag 2>&1 | grep -i "embedding"`.

**Expectations:**
1. lightrag logs show embedding binding `openai` with model `BAAI/bge-small-en-v1.5` and dim 384.
2. TEI logs show ≥1 embed request.
3. Naive query answer mentions "Mira Oduya".
4. `./harbor.sh down lightrag tei` exits 0.

## Group 3 — paperless + paperless-gpt

### Test 3.1: paperless-ngx standalone
**Steps:**
1. `./harbor.sh up --no-defaults paperless`; poll `http://localhost:35050/api/` until non-5xx.
2. `curl -u admin:admin localhost:35050/api/documents/` (status).
3. Generate `scratch/invoice.txt` with text "Invoice 4471 from Northwind Traders, total 128.50 EUR, dated 2024-05-02", `curl -u admin:admin -F document=@scratch/invoice.txt localhost:35050/api/documents/post_document/`.
4. Poll `GET /api/documents/?query=Northwind` until `count`≥1 (max 5 min).
5. `agent-browser` login at `http://localhost:35050/` with admin/admin, snapshot the Documents page.

**Expectations:**
1. `harbor.paperless` healthy, `harbor.paperless-valkey` running.
2. Step 2 returns 200.
3. Step 3 returns 200 with a task id; step 4 finds the document with `content` containing "Northwind".
4. Login succeeds; snapshot shows the document in the list.
5. `docker logs harbor.paperless` has no `ERROR` lines after consumption.
6. `find services/paperless/data -path '*/valkey' -prune -o ! -user $USER -print` is empty (app dirs host-owned).

### Test 3.2: paperless-gpt alone is a valid project
**Steps:**
1. `$(./harbor.sh cmd paperless-gpt) config -q; echo $?`.
2. `$(./harbor.sh cmd paperless paperless-gpt) config | grep -A2 "^      paperless:"`.

**Expectations:**
1. Exit 0.
2. Combined config shows `paperless-gpt` depends on `paperless` with `condition: service_healthy`.

### Test 3.3: paperless-gpt suggestions via Ollama
**Steps:**
1. (paperless still up from 3.1) `./harbor.sh up --no-defaults paperless paperless-gpt ollama`; poll `http://localhost:35051/` until 200.
2. `docker logs harbor.paperless-gpt 2>&1 | grep -i token`.
3. The `paperless-gpt` and `paperless-gpt-auto` tags are created by the paperless-gpt entrypoint (`[harbor] created paperless tag` in its logs); look up the id via `GET /api/tags/?name__iexact=paperless-gpt` and attach it to the Northwind document (`PATCH /api/documents/<id>/ {"tags":[<tagid>]}`).
4. `curl localhost:35051/api/documents` — list.
5. Request suggestions: `POST localhost:35051/api/generate-suggestions` with `{"documents":[{"id":<id>,...}],"generate_titles":true,"generate_tags":true,"generate_correspondents":true}` (mirror the payload the UI sends — inspect via agent-browser network or the paperless-gpt README).
6. Apply via `PATCH localhost:35051/api/update-documents` with the suggestion, then `GET /api/documents/<id>/` on paperless.

**Expectations:**
1. Step 2 shows `token acquired` (no auth errors); both trigger tags exist in paperless.
2. Step 4 lists the Northwind doc.
3. Step 5 returns a `suggested_title` containing "Northwind" or "Invoice" (case-insensitive) and a non-empty correspondent.
4. Step 6: paperless document title changed to the suggested title.
5. `./harbor.sh down paperless paperless-gpt` exits 0.

## Group 4 — whishper

### Test 4.1: Transcription
**Steps:**
1. `./harbor.sh up --no-defaults whishper`; poll `docker inspect -f '{{.State.Health.Status}}' harbor.whishper` until `healthy` (first run downloads every model in `HARBOR_WHISHPER_MODELS`, may take minutes). `/` returns 200 earlier, but jobs submitted before healthy fail with status -1.
2. Generate audio: `espeak -w scratch/hello.wav "Harbor integration test. The quick brown fox jumps over the lazy dog."` (or ffmpeg sine if espeak missing — then only check that a transcription object is created).
3. `curl -F file=@scratch/hello.wav -F language=en -F modelSize=tiny localhost:35060/api/transcriptions` (check whishper docs for exact field names) → note id.
4. Poll `GET localhost:35060/api/transcriptions/<id>` until status = 2 (done).
5. `agent-browser open http://localhost:35060/`, snapshot; confirm the transcription appears.

**Expectations:**
1. Containers `harbor.whishper` and `harbor.whishper-mongo` running.
2. Transcription reaches status 2 with non-empty `result.text` containing "fox" or "dog" (if espeak was used).
3. UI lists the transcription.
4. Data persisted under `services/whishper/data/` (uploads + models present) and `uploads/`, `models/` are owned by the host user after a restart (`./harbor.sh down whishper && ./harbor.sh up --no-defaults whishper`).

### Test 4.2: Translation via libretranslate cross-file
**Steps:**
1. `./harbor.sh up --no-defaults whishper libretranslate`; poll `http://localhost:35060/languages` (proxied) until 200 with a non-empty JSON array.
2. In the UI (agent-browser), open the transcription from 4.1 → Translate → pick Spanish → submit; or call the route the UI uses: `GET localhost:35060/api/translate/<id>/es`.
3. `GET /api/transcriptions/<id>` and check `translations`.
4. Standalone check: with only `whishper` up, `GET /languages` must return 502 (nginx starts without libretranslate); logs must contain no nginx `emerg`.

**Expectations:**
1. `/languages` returns a list including `es`.
2. A Spanish translation is stored on the transcription.
3. Standalone `/languages` → 502 and no `emerg` in `docker logs harbor.whishper` (libretranslate has no per-request access log, so the stored translation is the evidence).
4. `./harbor.sh down whishper libretranslate` exits 0.

## Group 5 — linkwarden

### Test 5.1: Signup, save link, archive
**Steps:**
1. `./harbor.sh up --no-defaults linkwarden`; poll `http://localhost:35070/` until 200 (initial migration takes ~1–2 min).
2. `agent-browser` (session `linkwarden`): go to `/register`, create user `tester` / password `testerpass1` (no email field without an email provider), log in.
3. Add link `https://github.com/av/harbor` via the UI.
4. Poll via the UI or `docker exec harbor.linkwarden-db psql -U postgres -c 'select id,url,"textContent" is not null from "Link";'` until the link exists and archives finish (max 5 min).

**Expectations:**
1. `harbor.linkwarden`, `harbor.linkwarden-db`, `harbor.linkwarden-meili` running.
2. Registration and login succeed (dashboard visible in snapshot).
3. Link row exists; archive columns (`pdf`/`image`/`readable`) populated, `textContent` non-null.
4. `docker logs harbor.linkwarden` shows no unhandled errors.
5. `find services/linkwarden/data ! -user $USER` is empty.

### Test 5.2: AI tagging via Ollama
**Steps:**
1. `./harbor.sh ollama pull qwen2.5:1.5b` (nothing pulls it automatically); `./harbor.sh up --no-defaults linkwarden ollama` (recreate with cross-file).
2. Enable auto-tagging for the user AFTER the first login has completed (the first session upserts user defaults and would revert an earlier change): `docker exec harbor.linkwarden-db psql -U postgres -c 'update "User" set "aiTaggingMethod"='"'"'GENERATE'"'"' where username='"'"'tester'"'"';'` (verify the column/enum name in the schema first: `\d "User"`).
3. Add a second link `https://example.com/` via UI.
4. Poll `docker logs harbor.linkwarden` for `Auto-tagging` … `Succeeded`; then query `"Tag"` joined to `"Link"` for the new link.

**Expectations:**
1. Worker log shows auto-tagging succeeded for the new link.
2. At least one tag row is associated with that link.
3. `./harbor.sh down linkwarden` exits 0 and linkwarden containers are gone (ollama from the same `up` set stops too, see Prerequisites).

## Group 6 — chandra

> **SKIPPED on this host.** Chandra is GPU-only and the reference host is ROCm/AMD, so the
> `nvidia` cross-file must never be started here (see Prerequisites). Run this group only on a
> host with an NVIDIA GPU and the container toolkit installed; otherwise mark every test SKIP.
>
> Last verified on a 16GB RTX 4090 Laptop GPU host from a throwaway `/tmp` clone:
> healthy in ~80s after the weights were cached, ~13.9GB VRAM steady at the default
> `--max-model-len 18000`, OCR completion returned the expected text. Budget ~14GB of free
> VRAM, not the whole card.

### Test 6.1: Cold start and OCR chat completion
**Steps:**
1. Skip check: `nvidia-smi` must succeed. If it does not, record SKIP for 6.1 and stop.
2. `./harbor.sh config get chandra.host_port` prints `35080`.
3. `./harbor.sh up --no-defaults chandra nvidia`; poll `http://localhost:35080/health` until 200 (first run downloads ~9.9GB of weights, allow up to 30 min; on a warm cache it is healthy in ~80s).
4. `curl -s http://localhost:35080/v1/models | jq -r '.data[].id'`.
5. OCR a real page: fetch any text-bearing PNG (e.g. `curl -sL -o /tmp/page.png https://raw.githubusercontent.com/datalab-to/chandra/main/static/images/example.png` or use a local scan), then
   `IMG=$(base64 -w0 /tmp/page.png); curl -s http://localhost:35080/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"chandra","messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,'"$IMG"'"}},{"type":"text","text":"Convert this page to markdown."}]}],"max_tokens":2048}'`.
6. `./harbor.sh down chandra`.

**Expectations:**
1. `harbor.chandra` running and healthy (`docker inspect -f '{{.State.Health.Status}}' harbor.chandra` = `healthy`).
2. `/v1/models` lists exactly `chandra` (not the Hugging Face id).
3. The `/v1/chat/completions` call returns 200 and `choices[0].message.content` contains text actually present in the image. The raw content also carries an empty `<think></think>` block and HTML-ish markup (possibly unbalanced) — that is expected, match on the text, not on clean Markdown.
4. `docker logs harbor.chandra` shows the vLLM engine started with `--served-model-name chandra`, no CUDA OOM and no `assert num_cache_lines >= batch` (the latter means `--max-num-seqs 16` was overridden away).
   `nvidia-smi` reports ~13.9GB used by the container, idle and during the request alike.
5. Weights landed in `${HARBOR_HF_CACHE}/hub/models--datalab-to--chandra-ocr-2`.
6. `./harbor.sh down chandra` exits 0 and the container is gone.
