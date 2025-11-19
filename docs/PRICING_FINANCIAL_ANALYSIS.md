# Tabario.com - Financial Analysis & Pricing Strategy
## AI Video Generation Service - Cost Structure & Revenue Model

**Document Version:** 1.2  
**Last Updated:** November 19, 2025  
**Purpose:** Define cost structure and pricing strategy for monthly subscription model

**⚠️ IMPORTANT:** Costs use a **measurement-based framework** on RunPod Serverless:
- Video model: Wan 2.2 Lightning (image-to-video)
- Image model: Qwen
- Effective GPU prices: **$0.00016/sec** for text-to-image, **$0.00019/sec** for image-to-video
- Costs per video are calculated from measured GPU seconds per stage + external API usage

---

## Executive Summary

Tabario.com provides AI-powered long-form video generation services. This document outlines the complete cost structure per video, recommended pricing tiers, and profitability analysis to ensure sustainable growth.

**Key Metrics to Track:**
- Cost Per Video (CPV)
- Customer Acquisition Cost (CAC)
- Lifetime Value (LTV)
- Gross Margin per subscription tier
- Monthly Recurring Revenue (MRR)

---

## 1. Cost Structure Breakdown

### 1.1 Variable Costs (Per Video Generation)

#### A. AI Model Costs (Anthropic Claude)

| Service Component | Usage Pattern | Estimated Cost per Video |
|------------------|---------------|-------------------------|
| **Idea Generation Agent** | 2 video ideas with descriptions & scripts | $0.15 - $0.30 |
| **Script-to-Prompt Agent** | Transform script into 13-15 image/video prompts | $0.20 - $0.40 |
| **Total Claude Cost per Video** | | **$0.35 - $0.70** |

**Assumptions:**
- Average script length: 500-800 tokens
- Prompt generation: ~1,500-2,000 tokens output
- Using Claude 3.5 Sonnet pricing: $3/MTok input, $15/MTok output

#### B. Voice Generation (ElevenLabs)

| Service Component | Usage Pattern | Estimated Cost per Video |
|------------------|---------------|-------------------------|
| **Voiceover Generation** | 50-second video narration | $0.10 - $0.30 |
| **Character Count** | ~150-200 words (750-1,000 chars) | |

**Pricing Reference:**
- ElevenLabs Creator tier: ~$0.30 per 1,000 characters
- Professional voices with emotion: Higher tier required

#### C. Image Generation (Flux via RunPod Serverless)

| Component | Quantity | Unit Cost | Total Cost |
|-----------|----------|-----------|------------|
| **Image Generation (Flux)** | 13-15 images | $0.004 per image | **$0.06** |
| **GPU Time** | 25 seconds per image | RunPod Serverless @ $0.00016/sec | |

**RunPod Serverless Pricing (Actual):**
- Model: Qwen (fast image generation)
- Generation time: 25 seconds per image (measured)
- GPU pricing: text-to-image @ $0.00016/sec
- Cost per image: 25 sec × $0.00016 = $0.004
- Total for 14 images: $0.06

#### D. Video Generation (Wan 2.2 Lightning via RunPod Serverless)

| Component | Quantity | Unit Cost | Total Cost |
|-----------|----------|-----------|------------|
| **Video Clip Generation (Wan 2.2)** | 13-15 clips (3-5 sec each) | $0.034 per clip | **$0.48** |
| **GPU Time** | 180 seconds per clip | RunPod Serverless @ $0.00019/sec | |

**RunPod Serverless Pricing (Actual):**
- Model: Wan 2.2 Lightning (I2V - Image to Video)
- Generation time: 180 seconds per clip (estimated, pending production data)
- GPU pricing: image-to-video @ $0.00019/sec
- Cost per clip: 180 sec × $0.00019 ≈ $0.034
- Total for 14 clips: ~$0.48
- **Note:** This is a conservative estimate; actual times may vary ±30%

#### E. Audio Processing & Subtitles

| Service Component | Usage Pattern | Estimated Cost per Video |
|------------------|---------------|-------------------------|
| **Whisper Transcription** | 50-second audio | $0.01 - $0.02 |
| **Subtitle Generation** | Internal processing | Negligible |
| **Total Audio Processing** | | **$0.01 - $0.02** |

**Notes:**
- Whisper can run on same RunPod infrastructure (minimal cost)
- Or use OpenAI Whisper API: $0.006 per minute

#### F. Video Post-Processing (FFmpeg)

| Service Component | Usage Pattern | Estimated Cost per Video |
|------------------|---------------|-------------------------|
| **Video Stitching** | 13-15 clips + audio sync | Compute cost |
| **Subtitle Burning** | Overlay subtitles on video | Compute cost |
| **Total FFmpeg Processing** | | **$0.05 - $0.10** |

**Notes:**
- FFmpeg runs on your FastAPI backend
- Cost = compute time on your server infrastructure
- Estimated 30-60 seconds processing time

---

### 1.2 Cost Per Video (CPV) – Measurement-Based Formula

Instead of a single fixed value per video, CPV is calculated from **measured timings** and **RunPod Serverless GPU prices**.

Let:
- `C_llm` = Claude cost per video (USD)
- `C_voice` = ElevenLabs voice cost per video (USD)
- `C_gpu` = GPU cost per video (USD)
- `C_storage` = Allocated RunPod network volume cost per video (USD)
- `C_cpu` = CPU/FFmpeg cost per video (USD)

Then for a single video `v`:

> **CPV(v) = C_llm(v) + C_voice(v) + C_gpu(v) + C_storage(v) + C_cpu(v)**

Where:

- **GPU cost per video**
  - Let `p_img = 0.00016` USD/sec (RunPod Serverless text-to-image rate).
  - Let `p_vid = 0.00019` USD/sec (RunPod Serverless video rate).
  - Let `t_img(v)` = total measured GPU seconds spent in **image generation** for video `v` (from `image_generation_seconds`).
  - Let `t_vid(v)` = total measured GPU seconds spent in **video generation** for video `v` (from `video_generation_seconds`).
  - `C_gpu(v) = t_img(v) × p_img + t_vid(v) × p_vid`

- **Storage (RunPod network volume)**
  - Monthly RunPod volume cost: **$7/month**
  - Let `N_month` = number of videos generated in the last 30 days (from `videos_generated_total`).
  - `C_storage(v) ≈ 7 / N_month`

- **CPU/FFmpeg cost**
  - Let `t_ffmpeg(v)` = CPU seconds spent in stitching/subtitles.
  - Let `p_cpu` = effective CPU cost per second on your backend.
  - `C_cpu(v) = t_ffmpeg(v) × p_cpu`

For **aggregated analysis by video length** (current product: 420p at 15s, 30s, 45s):

- Define a `length_bucket` label ∈ {`"15"`, `"30"`, `"45"`} derived from **voiceover generation duration** (e.g. using 0–20s → `"15"`, 20–37s → `"30"`, 37–55s → `"45"`).
- Let `T_img_avg[L]` = average **image-generation GPU seconds** per completed video in bucket `L`, over a period (e.g. 30 days), from `image_generation_seconds_sum`.
- Let `T_vid_avg[L]` = average **video-generation GPU seconds** per completed video in bucket `L`, over a period, from `video_generation_seconds_sum`.

Then:

> **Expected GPU cost for a length bucket L:**  
> `C_gpu_avg[L] = T_img_avg[L] × p_img + T_vid_avg[L] × p_vid`

And:

> **Expected CPV for bucket L:**  
> `CPV_avg[L] = C_llm_avg + C_voice_avg[L] + C_gpu_avg[L] + C_storage_avg + C_cpu_avg[L]`

Where `C_llm_avg`, `C_voice_avg[L]`, `C_storage_avg`, and `C_cpu_avg[L]` are estimated from historic data or vendor pricing.

#### Example: Total Variable Cost Per 50-Second Video (Current Best Estimate)

Using the assumptions above (≈14 images and ≈14 clips for a ~50s video):

| Cost Category | Cost | % of Total |
|--------------|------|------------|
| Claude (Idea + Prompts) | $0.53 | 39% |
| ElevenLabs Voice | $0.20 | 15% |
| Image Generation (Flux, 14 images) | $0.06 | 4% |
| Video Generation (Wan 2.2, 14 clips) | $0.48 | 35% |
| Audio Processing (Whisper) | $0.02 | 1% |
| Video Post-Processing (FFmpeg) | $0.08 | 6% |
| **TOTAL COST PER VIDEO (CPV)** | **$1.37** | **100%** |

**Critical Notes:**
- Video generation (Wan 2.2) is ~35% of total variable cost; Claude + ElevenLabs together are ~54%.
- Total cost is **$1.37 per ~50s video** under current assumptions.
- This is significantly lower than the original $4.60 estimate (≈70% reduction), driven mainly by RunPod Serverless pricing and workflow optimizations.
- Actual costs will vary per customer and over time; use the Prometheus-based formulas above as the source of truth.

---

### 1.3 Fixed Monthly Costs (Infrastructure)

| Service | Purpose | Monthly Cost |
|---------|---------|--------------|
| **Supabase Pro** | Database, Auth, Storage | $25 - $100 |
| **FastAPI Backend Hosting** | Orchestration service | $20 - $100 |
| **RunPod Network Volume** | Persistent GPU storage | $7 |
| **Monitoring & Logging** | Prometheus, Grafana | $0 - $50 |
| **Domain & SSL** | tabario.com | $15 - $30 |
| **CDN (if needed)** | Video delivery | $0 - $100 |
| **Temporal.io** | Workflow orchestration | $0 - $200 |
| **TOTAL FIXED COSTS** | | **$67 - $587/month** |

**Scaling Considerations:**
- Supabase storage: $0.021 per GB (videos add up quickly)
- Consider S3 + CloudFront for video storage at scale
- RunPod serverless = pay-per-use (no fixed GPU costs)

---

## 2. Pricing Strategy & Subscription Tiers

### 2.1 Recommended Monthly Subscription Tiers

#### **Tier 1: Starter** - $49/month
- **10 videos per month** (50-60 seconds each)
- Standard voices (ElevenLabs)
- 720p video quality
- Basic support
- **Cost:** $13.70 (10 videos × $1.37)
- **Gross Margin:** $35.30 (72%)
- **Target:** Individual creators, testing users
- **Positioning:** Entry tier to reduce friction and drive upgrades into Creator/Pro

#### **Tier 2: Creator** - $149/month ✅ VIABLE
- **40 videos per month** (50-60 seconds each)
- Premium voices (ElevenLabs)
- 1080p video quality
- Priority support
- **Cost:** $54.80 (40 videos × $1.37)
- **Gross Margin:** $94.20 (63%)
- **Target:** Small businesses, content creators

#### **Tier 3: Professional** - $399/month ✅ PROFITABLE
- **120 videos per month** (50-60 seconds each)
- Premium voices + custom voice cloning
- 1080p video quality
- Priority support + dedicated account manager
- **Cost:** $164.40 (120 videos × $1.37)
- **Gross Margin:** $234.60 (59%)
- **Target:** Agencies, marketing teams

#### **Tier 4: Enterprise** - $999/month ✅ PROFITABLE
- **350 videos per month** (50-60 seconds each)
- All premium features
- 4K video quality option
- White-label option
- Dedicated support
- **Cost:** $479.50 (350 videos × $1.37)
- **Gross Margin:** $519.50 (52%)
- **Target:** Large agencies, enterprises

---

### 2.2 REVISED Pricing Strategy (Profitable Model)

Given the actual production costs, here are three pricing options:

#### **Option A: Premium Pricing (High Margin)**

| Tier | Price | Videos/Month | Cost | Gross Margin | Margin % |
|------|-------|--------------|------|--------------|----------|
| **Starter** | $99/month | 10 videos | $14 | $85 | 86% |
| **Creator** | $349/month | 40 videos | $55 | $294 | 84% |
| **Professional** | $999/month | 120 videos | $164 | $835 | 84% |
| **Enterprise** | $2,499/month | 350 videos | $480 | $2,019 | 81% |

**Target Gross Margin:** 81-86% (premium positioning)  
**Advantage:** Maximum profitability, strong unit economics  
**Risk:** May be too expensive for early adopters

#### **Option B: Competitive Pricing (Market Entry)**

| Tier | Price | Videos/Month | Cost | Gross Margin | Margin % |
|------|-------|--------------|------|--------------|----------|
| **Starter** | $49/month | 10 videos | $14 | $35 | 71% |
| **Creator** | $149/month | 40 videos | $55 | $94 | 63% |
| **Professional** | $399/month | 120 videos | $164 | $235 | 59% |
| **Enterprise** | $999/month | 350 videos | $480 | $519 | 52% |

**Target Gross Margin:** 52-71% (competitive positioning)  
**Advantage:** Lower barrier to entry, faster customer acquisition  
**Risk:** Lower margins, less room for CAC

#### **Option C: Hybrid Model (RECOMMENDED)** ⭐

| Tier | Base Price | Included Videos | Cost | Margin | Margin % | Overage Price |
|------|-----------|-----------------|------|--------|----------|---------------|
| **Starter** | $79/month | 10 videos | $14 | $65 | 82% | $6/video |
| **Creator** | $249/month | 40 videos | $55 | $194 | 78% | $5/video |
| **Professional** | $699/month | 120 videos | $164 | $535 | 77% | $4/video |
| **Enterprise** | Custom | Custom | Variable | Variable | 60%+ | $3/video |

**Why This Works:**
- **Excellent margins:** 77-82% gross margin
- **Predictable revenue** from base subscription
- **Overage incentive:** Lower per-video cost at higher tiers
- **Competitive positioning:** Premium but not excessive
- **Room for CAC:** Can spend $50-150 per customer acquisition
- **Scalable:** Heavy users are still profitable

---

## 3. Cost Optimization Opportunities

### 3.1 Immediate Optimizations

| Optimization | Potential Savings | Implementation Difficulty |
|--------------|-------------------|--------------------------|
| **Batch Image Generation** | 15-25% on image costs | Medium |
| **GPU Instance Optimization** | 20-30% on video costs | Medium |
| **Claude Prompt Caching** | 30-50% on Claude costs | Easy |
| **ElevenLabs Volume Discount** | 10-20% on voice costs | Easy (negotiate) |
| **Reduce Video Segments** | 20-30% on total costs | Hard (affects quality) |

### 3.2 Long-Term Optimizations

1. **Self-Hosted Models** (6-12 months)
   - Host own image/video models on dedicated GPUs
   - Potential savings: 40-60% on generation costs
   - Upfront investment: $5,000-$20,000
   - Break-even: ~500-1,000 videos/month

2. **Model Fine-Tuning** (3-6 months)
   - Fine-tune models for faster generation
   - Reduce GPU time by 30-40%
   - Investment: $2,000-$5,000

3. **Caching & Reuse** (1-3 months)
   - Cache common image generations
   - Reuse similar video segments
   - Savings: 10-20% on repeat patterns

---

## 4. Financial Projections & Break-Even Analysis

### 4.1 Monthly Revenue Scenarios (Hybrid Model)

| Scenario | Starter | Creator | Pro | Enterprise | MRR | Total Videos | Total Costs | Gross Profit | Margin % |
|----------|---------|---------|-----|------------|-----|--------------|-------------|--------------|----------|
| **Conservative** | 20 | 10 | 3 | 1 | $11,255 | 730 | $1,000 | $10,255 | 91% |
| **Moderate** | 50 | 30 | 10 | 3 | $31,420 | 2,300 | $3,151 | $28,269 | 90% |
| **Aggressive** | 100 | 60 | 25 | 8 | $68,375 | 5,360 | $7,343 | $61,032 | 89% |

**Fixed Costs:** $300-$600/month (averaged at $450)

**Net Profit (after $450 fixed costs):**
- Conservative: $9,805/month ($117,660/year)
- Moderate: $27,819/month ($333,828/year)
- Aggressive: $60,582/month ($726,984/year)

**Key Insight:** With ~$1.37 CPV, profitability is even higher than initial projections, providing substantial buffer for CAC and overhead.

### 4.2 Break-Even Analysis

**Monthly Fixed Costs:** $500  
**Average Gross Margin per Customer:** $300 (weighted average from scenarios above)

**Break-Even Point:**
- Approximate break-even customers = `Fixed Costs / Avg Gross Margin` = `500 / 300 ≈ 1.7`.
- **Round up to 2 customers** (any mix) to account for variability.

**To Reach $10K MRR:** ~15-20 customers  
**To Reach $50K MRR:** ~80-100 customers  
**To Reach $100K MRR:** ~160-200 customers

---

## 5. Key Metrics to Monitor

### 5.1 Unit Economics

| Metric | Formula | Target |
|--------|---------|--------|
| **Cost Per Video (CPV)** | `C_llm + C_voice + C_gpu + C_storage + C_cpu` (measured per video) | Track separately for 15s / 30s / 45s |
| **Revenue Per Video** | Total revenue / videos generated | $6-8+ (depends on tier) |
| **Gross Margin per Video** | (Revenue - CPV) / Revenue | **>60% for all length buckets** |
| **Customer Acquisition Cost (CAC)** | Marketing spend / new customers | <$150 |
| **Lifetime Value (LTV)** | Avg monthly revenue × avg customer lifetime (12 months) | >$900 |
| **LTV:CAC Ratio** | LTV / CAC | >6:1 |

### 5.2 Operational Metrics

- **Average Videos per Customer per Month**
- **Churn Rate** (target: <5% monthly)
- **Upgrade Rate** (Starter → Creator → Pro)
- **Overage Revenue** (% of total revenue)
- **GPU Utilization Rate**
- **Video Generation Success Rate** (target: >95%)

### 5.3 RunPod Cost & Performance Metrics (Serverless)

To support accurate CPV calculations for **15s / 30s / 45s** videos, Prometheus should capture:

- **Histograms (per job)**
  - `image_generation_seconds_bucket{length_bucket}` – total **image-generation** GPU time.
  - `video_generation_seconds_bucket{length_bucket}` – total **video-generation** GPU time.
  - `voiceover_generation_seconds_bucket{length_bucket}` – aligns with final video length and defines the `length_bucket`.
  - `stitch_seconds_bucket{length_bucket}` – FFmpeg CPU time.

- **Counters**
  - `videos_generated_total{length_bucket}` – number of successfully completed videos.

- **Recommended labels**
  - `length_bucket` ∈ {`"15"`, `"30"`, `"45"`} (derived from voiceover duration)
  - `resolution` (e.g. `"420p"`, future `"1080p"`)
  - `pipeline_version` (for when workflows change)

- **Example Prometheus queries (30‑day window)**

  - Average image and video GPU seconds per 30s video:
    - `T_img_avg[30] = sum(rate(image_generation_seconds_sum{length_bucket="30"}[30d])) /
       sum(rate(videos_generated_total{length_bucket="30"}[30d]))`
    - `T_vid_avg[30] = sum(rate(video_generation_seconds_sum{length_bucket="30"}[30d])) /
       sum(rate(videos_generated_total{length_bucket="30"}[30d]))`

  - Videos per month (for allocating the $7 RunPod volume):
    - `N_month = sum(increase(videos_generated_total[30d]))`
    - `C_storage_per_video = 7 / N_month`

These queries back the formulas in **Section 1.2**, allowing you to derive **CPV per length bucket** directly from historic production data.

---

## 6. Competitive Analysis & Market Positioning

### 6.1 Competitor Pricing (Estimated)

| Competitor | Entry Price | Videos/Month | Price per Video | Notes |
|------------|-------------|--------------|-----------------|-------|
| **Synthesia** | $29/month | 10 min | ~$3/min | Avatar-based |
| **Pictory** | $23/month | 30 videos | ~$0.77/video | Shorter clips |
| **InVideo** | $25/month | Unlimited | N/A | Template-based |
| **Runway ML** | $12/month | 125 credits | ~$0.10/sec | Raw generation |
| **Tabario (Proposed)** | $79/month | 10 videos | $7.90/video | Full automation |

**Positioning:** Premium, fully-automated long-form video generation

**Competitive Advantage:**
- End-to-end automation (idea → script → video)
- High-quality models (Wan 2.2 + Flux)
- Cost structure allows for 77-82% margins (Hybrid model)
- Can compete on price OR invest heavily in marketing

---

## 7. Recommendations & Action Items

### 7.1 Immediate Actions (Week 1)

- [ ] **Implement Hybrid Pricing Model** ($79/$249/$699 tiers)
- [ ] **Set up cost tracking** per video generation
- [ ] **Negotiate ElevenLabs volume discount**
- [ ] **Implement Claude prompt caching**
- [ ] **Create financial dashboard** (track CPV, MRR, margins)

### 7.2 Short-Term (Month 1-3)

- [ ] **A/B test pricing** with early customers
- [ ] **Optimize RunPod GPU selection** (cost vs. speed)
- [ ] **Implement video segment caching**
- [ ] **Set up automated cost alerts** (>$2.00/video)
- [ ] **Analyze customer usage patterns**

### 7.3 Medium-Term (Month 3-6)

- [ ] **Evaluate self-hosted models** (ROI analysis)
- [ ] **Implement tiered quality options** (reduce costs for lower tiers)
- [ ] **Explore alternative video generation models**
- [ ] **Build customer success program** (reduce churn)
- [ ] **Develop enterprise sales motion**

### 7.4 Long-Term (Month 6-12)

- [ ] **Deploy self-hosted GPU infrastructure** (if volume justifies)
- [ ] **Develop proprietary models** (competitive moat)
- [ ] **Expand to international markets**
- [ ] **Build API offering** (B2B revenue stream)
- [ ] **Explore white-label partnerships**

---

## 8. Risk Analysis

### 8.1 Financial Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Video costs increase** | High | Medium | Lock in RunPod rates, optimize models |
| **Low conversion rate** | High | Medium | Freemium tier, better onboarding |
| **High churn** | High | Medium | Customer success, quality improvements |
| **Competitor undercuts pricing** | Medium | High | Focus on quality & automation |
| **API rate limits/outages** | Medium | Low | Multi-provider strategy |

### 8.2 Operational Risks

- **RunPod serverless cold starts** → Slow first video (pre-warm instances)
- **ComfyUI workflow failures** → Lost revenue + poor UX (robust error handling)
- **Storage costs balloon** → Implement retention policies (30-90 days)
- **Claude/ElevenLabs rate limits** → Queue management, rate limiting

---

## 9. Sensitivity Analysis

### 9.1 Impact of Cost Changes

| Scenario | Video Cost | Starter Margin | Creator Margin | Pro Margin |
|----------|-----------|----------------|----------------|------------|
| **Base Case** | $1.37 | 82% | 78% | 77% |
| **10% Cost Increase** | $1.51 | 81% | 76% | 74% |
| **20% Cost Increase** | $1.64 | 79% | 74% | 72% |
| **30% Cost Reduction** | $0.96 | 88% | 85% | 84% |
| **50% Cost Increase** | $2.05 | 74% | 67% | 65% |

**Conclusion:** 
- Every 10% cost change moves margins by only a few percentage points
- Even with a 50% cost increase, margins remain strong (65-74%)
- Strong buffer against cost volatility

### 9.2 Impact of Pricing Changes

| Scenario | Starter Price | MRR (50 customers) | Gross Profit | Churn Risk |
|----------|---------------|-------------------|--------------|------------|
| **Current** | $79 | $3,950 | $2,650 | Low |
| **+20%** | $95 | $4,750 | $3,450 | Medium |
| **+50%** | $119 | $5,950 | $4,650 | High |
| **-20%** | $63 | $3,150 | $1,850 | Very Low |

**Recommendation:** Test $99 Starter tier (26% increase, manageable churn risk)

---

## 10. Appendix: Detailed Cost Assumptions

### 10.1 RunPod Serverless GPU Pricing (Current Rates)

For cost modeling we assume **separate effective GPU prices** on RunPod Serverless:

- Text-to-image (Qwen): **$0.00016/sec** (USD)
- Video generation (Wan 2.2 Lightning): **$0.00019/sec** (USD)

**Cost per video is fully measurement-based:**

- Let `t_img(v)` = total GPU seconds used for all image generations for video `v`.
- Let `t_vid(v)` = total GPU seconds used for all video generations for video `v`.
- `C_gpu(v) = t_img(v) × 0.00016 + t_vid(v) × 0.00019`

All CPV calculations in this document use these rates together with the duration-based `length_bucket` metrics from Prometheus.

### 10.2 Claude API Pricing (Anthropic)

| Model | Input (per MTok) | Output (per MTok) | Use Case |
|-------|------------------|-------------------|----------|
| **Claude 3.5 Sonnet** | $3.00 | $15.00 | Idea + Prompt generation |
| **Claude 3 Haiku** | $0.25 | $1.25 | Simple tasks (future) |
| **Claude 3 Opus** | $15.00 | $75.00 | Not recommended |

### 10.3 ElevenLabs Pricing

| Tier | Monthly Cost | Characters/Month | Cost per 1K Chars | Notes |
|------|--------------|------------------|-------------------|-------|
| **Free** | $0 | 10,000 | $0 | Not viable |
| **Starter** | $5 | 30,000 | $0.17 | 30 videos max |
| **Creator** | $22 | 100,000 | $0.22 | 100 videos max |
| **Pro** | $99 | 500,000 | $0.20 | **Recommended** |
| **Scale** | $330 | 2,000,000 | $0.17 | Enterprise |

**Recommendation:** Start with Creator tier, upgrade to Pro at 100+ videos/month

---

## 11. Glossary

- **CPV (Cost Per Video)**  
  Total variable cost to generate one finished video, including Claude, ElevenLabs, GPU time (image + video), allocated RunPod network volume, and FFmpeg CPU. Formally: `CPV(v) = C_llm(v) + C_voice(v) + C_gpu(v) + C_storage(v) + C_cpu(v)`.

- **CPV_avg[L] (Average Cost Per Video for length bucket L)**  
  Average CPV for a specific video length bucket `L ∈ {"15","30","45"}` over a period (e.g. 30 days), computed from Prometheus metrics. Used for pricing and margin analysis per video length.

- **CAC (Customer Acquisition Cost)**  
  Average sales + marketing spend required to acquire one paying customer. Calculated as `Total acquisition spend / Number of new customers acquired`.

- **LTV (Lifetime Value)**  
  Total expected gross revenue from a customer over their lifecycle. Approximated here as `Average monthly revenue per customer × Average customer lifetime (in months)`.

- **MRR (Monthly Recurring Revenue)**  
  Sum of all subscription revenue in a given month, normalized to a monthly basis (e.g. number of customers per tier × tier price).

- **Gross Margin**  
  Profit after variable costs but before fixed costs and overhead. For a video: `(Revenue per video − CPV) / Revenue per video`. For a customer: `(Subscription price − variable costs of included videos) / Subscription price`.

- **ARPU (Average Revenue Per User/Customer)**  
  Average monthly revenue per active paying customer. Calculated as `MRR / Number of active customers`.

- **Churn Rate**  
  Percentage of customers who cancel in a given period. Calculated as `Customers lost during period / Customers at start of period`.

- **length_bucket**  
  Label used in Prometheus metrics to group videos by target length: `"15"`, `"30"`, or `"45"` seconds. Derived from voiceover duration and used to compute CPV by video length.

- **GPU Seconds (t_img, t_vid)**  
  Measured GPU time spent on image generation (`t_img`) and video generation (`t_vid`) for a single video. Used with RunPod per‑second pricing to compute `C_gpu(v)`.

---

## Document Control

**Prepared by:** CFO Advisory Team  
**Reviewed by:** [Pending]  
**Approved by:** [Pending]  
**Next Review Date:** 30 days after launch

**Change Log:**
- v1.0 (Oct 27, 2025): Initial financial analysis and pricing strategy
- v1.1 (Oct 27, 2025): Updated with actual production costs
  - Video model: Wan 2.2 Lightning (180 sec/clip)
  - Image model: Qwen (25 sec/image)
  - Total CPV reduced from $4.60 to $2.12 (54% reduction)
  - Gross margins improved to 64-73% (from 42-46%)
  - All pricing tiers now profitable
 - v1.2 (Nov 19, 2025): Updated for RunPod Serverless + Flux and measurement-based CPV
   - Image model: Flux via RunPod Serverless (text-to-image @ $0.00016/sec)
   - Video pricing: Wan 2.2 Lightning (image-to-video @ $0.00019/sec)
   - New CPV example: ~$1.37 per 50s video (significant further reduction)
   - Pricing tables, projections, and sensitivity analysis recalculated using new CPV

---

## Questions for Leadership Team

1. **What is the target customer profile?** (B2C creators vs. B2B agencies)
2. **What is the acceptable CAC?** (marketing budget available)
3. **What is the minimum viable margin?** (30%? 40%? 50%?)
4. **Are we optimizing for growth or profitability?** (affects pricing strategy)
5. **What is the competitive moat?** (quality? speed? automation? price?)
6. **What is the go-to-market strategy?** (freemium? free trial? demo?)
7. **What is the target for Year 1 ARR?** (affects infrastructure decisions)

