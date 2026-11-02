# Amina — Custom Egyptian Arabic TTS

| | |
|---|---|
| Status | Draft for technical review |
| Owner | P2 (Speech/TTS) |
| Parent | [system-design.md §8](system-design.md#8-tts-training-evaluation-and-inference-architecture) |
| Decisions | [ADR-002](decisions.md#adr-002-custom-tts-model-niletts-xtts), [ADR-003](decisions.md#adr-003-tts-hosting-container-apps-serverless-gpu), [ADR-004](decisions.md#adr-004-tts-transport-http-chunked-streaming), [ADR-005](decisions.md#adr-005-azure-neural-tts-as-fallback-voice) |

Labels: **Confirmed** (with a source), **Decision**, **Assumption**, **Target**, **Open**. The definitions are in [system-design.md](system-design.md).

---

## 1. Goal and the questions this document answers

**Goal:** Amina speaks natural Egyptian Arabic in one consistent female voice. She reads amounts, dates, card digits and English banking terms correctly, and she starts speaking fast enough for a phone conversation.

The design review asked:

| Question | Short answer | Section |
|---|---|---|
| Fine-tune NileTTS-XTTS, or start from the original XTTS v2? | NileTTS-XTTS. The fine-tune ships only if it beats NileTTS-XTTS on our gate | §3, §6.4 |
| How do we add banking-specific data without damaging the speaker identity? | No new human voice. Banking sentences are synthesised in SPEAKER_02's own voice, filtered, human-checked, and capped as a share of training data | §5.3 |
| Dataset preparation, speaker handling, splits, evaluation? | SPEAKER_02 only; re-segment clips longer than 11 s; split by text; three held-out test sets | §5, §6 |
| Licensing? | Non-commercial only (CPML), whatever the model card says | §2 |
| Inference and deployment on Azure? | Container Apps serverless GPU (T4), internal HTTP streaming service | §7, §8 |
| Is streaming practical, and how do we minimise first-audio latency? | Yes, through `inference_stream`. T4 numbers are unpublished, so we measure on day 2 | §7.3 |
| GPU requirements, cost, scaling? | 1× T4 for inference, ≥ 24 GB GPU for training, cron-based warm window | §8 |

---

## 2. Licensing

| Artifact | Stated licence | What we assume | Source |
|---|---|---|---|
| XTTS v2 weights (`coqui/XTTS-v2`) | Coqui Public Model License 1.0.0 | **Non-commercial use only, including outputs.** Coqui has shut down and no commercial licence can be bought | [idiap discussion #216](https://github.com/idiap/coqui-ai-TTS/discussions/216), [coqui discussion #3711](https://github.com/coqui-ai/TTS/discussions/3711) |
| NileTTS-XTTS weights | Model card says Apache-2.0, "following the original XTTS v2 license" | **We treat them as CPML.** A fine-tune is a derivative of CPML weights and cannot be relicensed. Other Egyptian XTTS fine-tunes label themselves CPML | [model card](https://huggingface.co/KickItLikeShika/NileTTS-XTTS), [comparable card](https://huggingface.co/abdullah-khaled/xtts-egyptian-arabic) |
| NileTTS dataset | Apache-2.0 | Usable. **Open:** the audio was generated with Google NotebookLM, and we have not verified whether NotebookLM's terms restrict training on its outputs. Acceptable risk for non-commercial academic work; flagged for any commercial follow-up | [dataset card](https://huggingface.co/datasets/KickItLikeShika/NileTTS-dataset) |
| `coqui-tts` library (idiap fork) | MPL-2.0 (code) | Usable | [repo](https://github.com/idiap/coqui-ai-TTS) |
| Our fine-tuned weights and voice | Derivative of CPML | Non-commercial; not published publicly without the CPML terms attached | — |
| Azure Neural TTS (fallback) | Azure terms | Usable | — |

**Consequences:**

1. Amina is an academic, non-commercial demonstrator (user decision).
2. The repository README states the CPML restriction and gives attribution to Coqui and the NileTTS authors.
3. The TTS service contract is engine-agnostic. A commercially licensable engine (for example a Chatterbox-based Egyptian model under MIT or Apache-2.0) can replace XTTS without changes to the API.
4. **Transparency:** Amina's greeting says she is a virtual assistant, so the synthetic voice is disclosed to the caller.

---

## 3. Starting point: NileTTS-XTTS vs base XTTS v2

**Evidence (Confirmed, from the [model card](https://huggingface.co/KickItLikeShika/NileTTS-XTTS)):**

| Metric | XTTS v2 | NileTTS-XTTS |
|---|---|---|
| WER | 26.8% | 18.8% |
| CER | 8.1% | 4.1% |
| Speaker similarity | 0.713 | 0.755 |

The card does not say which ASR was used, and it reports training as 8 epochs at a learning rate of 5e-6.

**Decision:** fine-tune from NileTTS-XTTS, for three reasons:

1. NileTTS-XTTS has already learned Egyptian phonology and prosody from 38 h of data. Starting from base XTTS v2 means re-learning that from our much smaller banking set.
2. Our target voice, SPEAKER_02, is *in* NileTTS's training data, so the model already reproduces it well.
3. Both checkpoints carry the same CPML licence, so licensing doesn't favour either.

**We verify this on day 3 instead of trusting the card.** A baseline evaluation (§6) compares base XTTS v2, NileTTS-XTTS and Azure `ar-EG-SalmaNeural`, all on our banking test set with the same SPEAKER_02 reference. This baseline also gives the tutor measured evidence for the claim that "Azure's Egyptian voice is not good enough", which until now was only an opinion.

---

## 4. Text normalisation

Most banking speech errors are **text** problems, not acoustic ones: "150 EGP", "3/11", "4421", "Instapay", "T-2611-0042". XTTS reads digits and Latin script inconsistently in Arabic context. A deterministic normaliser fixes these errors before the model sees the text, and it is cheaper and more reliable than training them away.

`packages/arabic_text` is one Python package, used in three places:

- **dataset preparation**, so training transcripts are normalised;
- **the `amina-tts` service**, so every request is normalised;
- **evaluation**, so the reference text for CER is canonicalised.

Using one package in all three places guarantees that training and inference see identical text.

| Input class | Rule (Egyptian colloquial) | Example |
|---|---|---|
| Money | number → words, with the currency in the right gender and number agreement | `150 جنيه` → `مية وخمسين جنيه` |
| Decimals | piasters | `12.50 جنيه` → `اتناشر جنيه ونص` |
| Dates | day as an ordinal or cardinal, plus the month name | `3/11` / `3 نوفمبر` → `تلاتة نوفمبر` |
| Card last 4, references | digit by digit, with grouping pauses | `4421` → `أربعة، أربعة، اتنين، واحد` |
| Ticket refs | letter + digits in groups | `T-2611-0042` → `تي، ستة وعشرين حداشر، صفر صفر اتنين واتنين`. The exact reading is fixed by a style rule in the package |
| Percentages, times | words | `2.5%` → `اتنين ونص في المية` |
| English banking terms | lexicon → Arabic-script transliteration | `Instapay` → `إنستاباي`, `Overdraft` → `أوفر درافت`, `IBAN` → `آيبان` |
| Arabic-Indic digits | → ASCII first | `١٥٠` → `150` |
| Symbols, URLs, emojis | dropped or spelled | — |
| Diacritics | stripped, except a curated list of disambiguating words | — |

- The lexicon is a versioned YAML file, owned by P2 and reviewed by the team for Egyptian naturalness.
- Unit tests cover every rule, with ≥ 200 cases.
- **Decision:** Egyptian colloquial number forms (`تلاتة`, `اتناشر`, `مية`), not Modern Standard Arabic forms, because Amina speaks Masri.

---

## 5. Training

### 5.1 Data sources

| Source | Content | Use |
|---|---|---|
| NileTTS SPEAKER_02 | 4,656 utterances, female, across all three domains. Hours are not given per speaker; **about half of 38.1 h is an Assumption**, computed during prep | Core training data |
| NileTTS SPEAKER_01 (male) | 4,865 utterances | **Not used.** Single-speaker fine-tuning reinforces the target identity; the base model already generalises across speakers |
| Banking sentences (ours) | 600 sentences written for the bank domain (§5.3) | Synthetic augmentation, ≤ 15% of training hours |

### 5.2 Preparing NileTTS SPEAKER_02

1. **Download** the dataset (24 kHz WAV) and filter to SPEAKER_02. Record the file list and its hash in the training manifest.
2. **Duration check.** The NileTTS clips average 14.4 s (**Confirmed**, dataset card). The coqui-tts XTTS GPT recipe defaults to a maximum training clip of `max_wav_length = 255995` samples, about 11.6 s at 22.05 kHz, and drops longer clips. **Assumption:** these are the defaults in the coqui-tts version we pin; checked when it is pinned. Without intervention, a large share of the data would be silently discarded.
3. **Re-segment** clips longer than 11 s. Use word-level timestamps from a forced alignment or ASR pass (WhisperX-style alignment on the existing transcript), and cut at the longest pauses (≥ 250 ms) so that every segment is 3–11 s. Segments shorter than 2 s are discarded.
4. **Transcript normalisation** with `packages/arabic_text`. The NileTTS transcripts were produced by Whisper and manually verified (**Confirmed**, dataset card), but they may contain digits and Latin script that the model must learn to read in our normalised form.
5. **Quality filter:**
   - re-transcribe each segment with ASR and drop it if the CER against its transcript is > 15% (alignment errors);
   - drop it if the SNR estimate is low or it is clipped.
6. **Resample** to the recipe's input rate (22.05 kHz, per the recipe's `XttsAudioConfig`; **Assumption** until pinned) and write LJSpeech-style metadata (`file|text|speaker`).

### 5.3 Banking sentences without damaging the speaker identity

The constraint (user decision): **Amina = SPEAKER_02, with no human voice mixed in.**

1. **Write 600 sentences** in Egyptian colloquial, in the bank's voice:

   | Category | Count | Examples |
   |---|---|---|
   | Amounts and fees | 120 | fees, balances, limits |
   | Dates and times | 80 | posting dates, deadlines |
   | Card digits and references | 60 | last-4, ticket refs |
   | English banking terms | 80 | Instapay, Overdraft, IBAN, ATM, POS |
   | Verification, confirmation, handoff phrases | 80 | |
   | Policy explanations (short) | 120 | |
   | Apologies and fillers | 60 | |

   An LLM drafts them; every sentence is edited by a team member for natural Masri. The 100-sentence test set (§6.1) is written **separately**, and no test sentence or near-duplicate (more than 80% token overlap) is used for training.
2. **Normalise** each sentence.
3. **Synthesise 4 candidates per sentence** with NileTTS-XTTS conditioned on the fixed SPEAKER_02 reference set (§7.2), at temperature 0.7.
4. **Select automatically:** keep the candidate with the lowest ASR CER. It must have CER ≤ 5%, speaker similarity to the reference set ≥ the 10th percentile of real SPEAKER_02 clips, and a duration-per-character ratio within the real data's 1st–99th percentile. Otherwise the sentence is rejected.
5. **Human check: 100% of the selected clips** (about 50 minutes of audio, split across the three team members). Reject any clip with a wrong reading, an artefact or an unnatural prosody.
6. **Cap:** synthetic clips are ≤ 15% of training hours. Banking clips may be oversampled ×2 if they are under 5%.

**Why this protects the identity:** every training sample is SPEAKER_02, either real or generated from SPEAKER_02's own conditioning. Selection pushes the model towards its *best* readings of banking text. It does not pull it towards anything new.

**Honest limitation:** this is self-distillation. It cannot teach the model sounds it never produces correctly. If a word is always wrong, the fix belongs in the normaliser or the lexicon, not in training. That is why the ship gate (§6.4) can choose the base model.

### 5.4 Splits

| Split | Content | Used for |
|---|---|---|
| `train` | SPEAKER_02 segments from the NileTTS **train** split + selected banking clips | Training |
| `dev` | SPEAKER_02 segments from the NileTTS **eval** split (official) + 10% of the banking clips | Early stopping, checkpoint selection |
| `test-bank` | 100 held-out banking sentences (text only; never synthesised for training) | Ship gate |
| `test-nile` | 100 texts from the NileTTS eval split, SPEAKER_02 | Regression on general speech |
| `test-numbers` | 50 sentences dense in amounts, dates and digits | Number accuracy |

Splits are **by text**, and segments from one original NileTTS clip never cross splits.

### 5.5 Fine-tuning recipe

| Item | Setting |
|---|---|
| Framework | `coqui-tts` (idiap fork, pinned version) `GPTTrainer`, adapted from `recipes/ljspeech/xtts_v2/train_gpt_xtts.py` |
| Trained part | The GPT (text/audio-token) model. The DVAE and the HiFi-GAN decoder are used as provided (the recipe trains the GPT stage) |
| Init | NileTTS-XTTS `model.pth`, `config.json`, `vocab.json` + the XTTS `dvae.pth` and `mel_stats.pth` |
| Language code | `ar` (as in NileTTS-XTTS usage) |
| Learning rate | Start at 5e-6 (NileTTS's value); AdamW; warm-up of 500 steps |
| Epochs | Up to 6, early stopping on dev loss (patience 1 epoch). Fewer epochs than NileTTS, because we start from their converged model |
| Batch | As VRAM allows, with gradient accumulation to an effective batch of ~32 |
| Checkpoints | Each epoch; the top 2 by dev loss go to evaluation |
| Runs | At most 2 runs in the timeline (initial, plus one adjustment) |
| Tracking | Training manifest (data hashes, code commit, config, coqui-tts version) saved with every checkpoint |

### 5.6 Training compute

- **GPU:** 24 GB or more VRAM. A third-party fine-tuning recipe lists 16–24 GB for XTTS v2 ([tts-finetune-recipes](https://github.com/Jeevav62/tts-finetune-recipes)). Preferred: 1× A100 (40/80 GB).
- **Where:** an Azure ML command job on serverless GPU compute is preferred, because it is reproducible, writes artifacts to Blob, and needs quota requested on day 1. The fallback is any ≥ 24 GB GPU the team can access; the artifact contract (§7.2) is the same either way.
- **Duration:** unknown for our data size. **Measured** in the first run; the roadmap reserves days 4–7.

---

## 6. Evaluation

### 6.1 Test sets

These are the three `test-*` sets in §5.4, plus a **listening set**: 20 sentences, mixed across categories, for MOS.

### 6.2 Metrics

| Metric | How | Notes |
|---|---|---|
| **CER / WER** | Transcribe the output with **two** ASR systems: Azure STT `ar-EG` (fast transcription) and an open model (Whisper large-v3 or newer). Compare against the normalised reference after canonicalisation (strip diacritics, unify alef/ya/ta-marbuta forms, numbers in words) | Two judges reduce single-ASR bias. Systems are compared under the same judge |
| **Speaker similarity** | Cosine similarity between the output's speaker embedding and the mean embedding of the SPEAKER_02 reference set, using ECAPA-TDNN (SpeechBrain) and a WavLM-SV model | Identity drift detector |
| **Naturalness (MOS)** | Blind test: ≥ 10 native Egyptian listeners. 20 sentences × systems (base NileTTS-XTTS, fine-tuned, Azure Salma; base XTTS v2 in the day-3 baseline only), randomised, rated 1–5 for naturalness. One extra question: "Would you trust this voice on your bank's phone line?" (1–5) | Report the mean and 95% CI. With n ≈ 10, small differences are not significant, and we say so |
| **A/B preference** | Same listeners, base vs fine-tuned pairs, forced choice | More sensitive than MOS for small differences |
| **Number accuracy** | Human check per `test-numbers` sentence: amount, date and digits read correctly (yes/no) | The banking-critical metric |
| **Artefact rate** | Automatic: duration-per-character outside the real data's 1st–99th percentile; ASR output > 1.3× the reference length (repetition); trailing non-speech energy > 300 ms | XTTS failure modes |
| **Latency** | TTFB and RTF on the **Azure T4**, for 20-, 80- and 200-character sentences: p50/p95 over 100 runs each, with and without DeepSpeed and fp16 | Feeds system-design §17.3 |

### 6.3 Evaluation schedule

| When | What |
|---|---|
| Day 2 | Latency spike: NileTTS-XTTS on the T4 (TTFB, RTF) |
| Day 3 | **Baseline report:** base XTTS v2 vs NileTTS-XTTS vs Azure Salma on `test-bank` and `test-nile` (CER, speaker similarity, number accuracy) + a small MOS |
| Day 7 | Fine-tuned checkpoints vs NileTTS-XTTS, full metric set |
| Day 8 | Ship gate decision |

### 6.4 Ship gate

The fine-tuned checkpoint replaces base NileTTS-XTTS **only if all** of these hold on the test sets (**Decision**):

| Criterion | Threshold |
|---|---|
| `test-bank` CER (mean of the two ASR judges) | ≥ 10% relative improvement over base |
| `test-nile` CER | No worse than base + 5% relative |
| Speaker similarity (mean) | ≥ base − 0.01 |
| Number accuracy on `test-numbers` | ≥ base |
| Artefact rate | ≤ base |
| A/B preference | Fine-tuned preferred in ≥ 50% of pairs |
| TTFB p95 on the T4 | No worse than base + 10% |

If the gate fails, **base NileTTS-XTTS + the normaliser ships**, and the report explains why. A failed gate is a valid, documented outcome, not a project failure.

---

## 7. Inference service (`amina-tts`)

### 7.1 Responsibilities

- Accept one sentence of display text.
- Normalise it.
- Synthesise it in the requested voice.
- Stream PCM16 at 24 kHz as it is produced.
- Report readiness and model version honestly.

It holds no customer data and logs no text.

### 7.2 Voice artifacts

```
blob: tts-models/
  amina-voice-<yyyy-mm-dd>-<tag>/
    model.pth  config.json  vocab.json
    speaker/amina-v1.pt          # precomputed gpt_cond_latent + speaker_embedding
    speaker/reference/*.wav      # 3 clean SPEAKER_02 clips, 6–10 s each (provenance)
    MANIFEST.json                # data hashes, code commit, metrics summary, gate result
```

- **Reference set:** 3 SPEAKER_02 clips, 6–10 s each. They are chosen by speaker-embedding centrality (closest to the speaker's mean embedding), then by SNR, plus a human listen. Conditioning latents are computed **once** at publish time, not per request.
- `MODEL_VERSION` (an environment variable on the Container App) pins which folder is loaded. Rollback means redeploying the previous version.

### 7.3 Streaming and first-audio latency

- **Confirmed:** XTTS v2 provides `inference_stream`. Coqui reports < 200 ms to the first chunk with DeepSpeed, and about 212 ms in a Coqui reply ([docs](https://docs.coqui.ai/en/latest/models/xtts.html), [HF discussion](https://huggingface.co/coqui/XTTS-v2/discussions/10)). Users report 0.25–0.9 s in self-hosted setups ([issue #29](https://github.com/coqui-ai/xtts-streaming-server/issues/29)). **There are no published T4 measurements.**
- **How we minimise time to first audio:**
  1. The model stays loaded and warm (min 1 replica; warm-up synthesis at startup).
  2. Speaker latents are precomputed (§7.2).
  3. The API sends the **first sentence as soon as it is complete**. The chunker also allows an early first chunk at a clause boundary (`،`) once it has ≥ 25 characters.
  4. Tune `stream_chunk_size` (smaller means earlier first audio but more overhead), measured in the spike.
  5. DeepSpeed inference and fp16 autocast are measured. They are adopted only if quality on `test-bank` doesn't regress (Coqui notes fp16 "might give 2–4%" with "a slight drop in quality").
  6. Fillers and fixed phrases are cached on the API side and never hit the GPU on the hot path.
  7. Internal ingress and HTTP keep-alive between the API and TTS.
- **Fallback trigger:** the API's `TTS_TTFB_TIMEOUT_MS` is p95 TTFB × 1.5 from the spike, capped at 1500 ms.

### 7.4 Output safeguards

| XTTS failure mode | Safeguard |
|---|---|
| Hallucinated or noisy audio on very short input | The API chunker merges fragments shorter than 12 characters. The service rejects input with fewer than 2 words (422) |
| Trailing noise or babble after the sentence | Energy-based end trimming of the final chunk; a maximum audio duration of `chars × p99 ratio × 1.3`, after which the stream is cut |
| Run-on generation | The same duration cap |
| Long input degrading prosody | Max 250 characters (422 above that); the API splits first |
| Text the model cannot read (Latin, symbols) | The normaliser and lexicon; unknown Latin tokens are spelled letter by letter |

### 7.5 Process model

- FastAPI on uvicorn (1 worker) for HTTP. **One inference thread owns the GPU model.** Requests are handed to it through a bounded queue (`QUEUE_LIMIT`).
- With `MAX_CONCURRENT = 1`, the worker interleaves nothing. It streams one sentence at a time while the next request waits in the queue.
- Whether two concurrent streams on one T4 improve throughput without hurting TTFB is **measured**. The setting is configurable.
- The API (`amina-api`) never sends more than one request per call at a time, so the queue depth is at most the number of active speaking calls.
- **Client disconnect** (barge-in): the generator checks a cancellation flag between chunks and frees the worker.
- **Startup:** download the artifacts (managed identity) → load the model → load the speaker latents → warm-up synthesis of 3 sentences → `/readyz` = 200.

### 7.6 Image

- Base: an NVIDIA CUDA runtime image matching the pinned PyTorch build, Python 3.12, `coqui-tts` pinned, and DeepSpeed optional (separate build arg).
- Model weights are **not** baked into the image. This keeps image pulls smaller, and changing the model doesn't need an image rebuild.
- **Assumption:** the image is under the size where cold-start pulls dominate. ACR Premium artifact streaming is the documented mitigation if they do.

---

## 8. GPU sizing, scaling and cost

### 8.1 Inference capacity

Let *r* be the T4 real-time factor (synthesis time ÷ audio duration, measured), and let *s* be the share of call time Amina is speaking (**Assumption**: about 0.4, measured in the load test). Then one GPU worker sustains about **1 / (r × s)** concurrent calls before TTFB rises from queueing.

- Example: *r* = 0.25 (Coqui's published RTF on a strong GPU; a T4 will be slower) and *s* = 0.4 give ~10 calls.
- The real number comes from the load test. Beyond the knee, the API falls back to Azure TTS (ADR-005), so overload costs voice quality, not calls.

**Scaling:**

| Mode | `amina-tts` replicas |
|---|---|
| Normal | min 1 / max 2 (the max is limited by T4 quota) |
| Load test | Fixed at 1, so the knee per GPU is measured cleanly |

### 8.2 Cold starts and the warm window

- Serverless GPU cold starts with CUDA images and model loading take minutes, according to user reports ([one report](https://dev.to/aco_dog_32627df9d920ffba4/i-ran-a-gpu-inference-app-for-a-month-on-azure-serverless-gpu-heres-the-actual-bill-i35)). A live call can't wait for that.
- **Decision:** a KEDA cron scale rule holds 1 replica during demo and work hours (Cairo time), and the app scales to zero otherwise. **Assumption:** cron rules apply to GPU workload profiles; checked on day 2.

### 8.3 Cost

**Confirmed:** serverless GPUs are billed per second ([GA](https://techcommunity.microsoft.com/blog/appsonazureblog/announcing-ga-for-azure-container-apps-serverless-gpus/4394302)).

We did not find an official T4 serverless rate in the sources checked. The rate is taken from the Azure pricing calculator on day 1 and recorded in `roadmap.md`. For order of magnitude only, third-party trackers list:

- an NC4as T4 v3 VM at about $0.53/h;
- serverless A100 at about $1.90–2.48/h ([cloudgpuprices](https://cloudgpuprices.com/vendors/azure)).

```
inference_cost ≈ warm_hours_per_day × days × T4_rate_per_hour
training_cost  ≈ gpu_hours_per_run × runs × training_gpu_rate
```

The 2-week budget is computed from these formulas with the official rates on day 1. Inference is the dominant cost item. If it exceeds the agreed budget, the warm window shrinks.

---

## 9. Open items

| # | Item | Due |
|---|---|---|
| T1 | Pin the `coqui-tts` version; confirm Python 3.12 support, recipe defaults (`max_wav_length`, sample rates) and the trained parameters | Day 1 |
| T2 | GPU quota: T4 (Container Apps) and training GPU | Request on day 1 |
| T3 | Measure TTFB and RTF on the T4; DeepSpeed and fp16 decision | Day 2–3 |
| T4 | SPEAKER_02 hours after re-segmentation and filtering | Day 3 |
| T5 | NotebookLM output terms (academic-use risk note) | Before review |
| T6 | Ship gate result | Day 8 |
