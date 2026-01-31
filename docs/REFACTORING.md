# Refactoring Strategy and Architectural Decisions

## Context

This document captures the architectural assessment and refactoring strategy for the Tabario video orchestration service.

**Date:** January 2026  
**Team Size:** 1 developer  
**Current State:** Single Docker container handling video orchestration, media processing, and Temporal workflows

---

## Architectural Assessment Summary

### What This Service Does

The `video-merger` service is a comprehensive video generation orchestration platform that handles:

- **Video/Audio manipulation** - ffmpeg operations (merge, stitch, trim, normalize)
- **Subtitle generation and burning** - Automated subtitle creation and video overlay
- **ComfyUI orchestration** - Text-to-Image (T2I) and Image-to-Video (I2V) workflows
- **Temporal workflow management** - Parent/child workflows for resilient video generation
- **File system coordination** - Shared storage management (`/data/shared`)
- **Webhook coordination** - N8N integration for voiceover, scene prompts, completion notifications
- **Metrics/observability** - Prometheus metrics for monitoring
- **TikTok video archiving** - Content management utilities
- **Upscaling operations** - Video quality enhancement

### Current Architecture Strengths

✅ **Well-organized internal structure:**
- `routers/` - Clean API layer with separation of concerns
- `services/` - Business logic properly isolated
- `temporal/` - Workflow orchestration in dedicated module
- Clear abstraction between local/RunPod ComfyUI clients

✅ **Temporal provides built-in resilience:**
- Parent/child workflow model for scene processing
- Automatic retry logic and state management
- Workflow resumability on failures

✅ **Simple coordination model:**
- File-based coordination via shared volumes
- No complex distributed state management

### Identified Concerns

❌ **Mixed concerns in single container:**
- Stateless operations (ffmpeg) + Stateful orchestration (Temporal)
- External service coordination + Utility operations
- Different resource profiles competing for same container resources

❌ **Deployment coupling:**
- Can't scale components independently
- Single deployment unit for all functionality
- Potential resource contention between heavy operations

---

## Refactoring Options Considered

### Option A: Keep As-Is (SELECTED) ✅

**Decision:** Maintain current monolithic architecture with incremental improvements.

**Rationale:**
- Solo developer - complexity cost outweighs splitting benefits
- No current scaling issues
- Current deployment works reliably
- Well-structured internal code organization
- Temporal already provides resilience and retry logic

**Improvements to implement:**
- ✅ Enhanced monitoring via existing Prometheus metrics
- ✅ Better documentation of architecture and workflows
- ✅ Resource usage profiling to identify future bottlenecks
- 🔄 Separate Temporal task queues for different operation types (future)
- 🔄 Docker resource limits and health check tuning (future)

**When to reconsider:**
- Team grows beyond 1-2 developers
- Deployment times exceed 5 minutes
- Container restarts due to resource exhaustion
- Concrete scaling requirements emerge
- Development velocity suffers due to coupling

---

### Option B: Selective Extraction (Future Consideration)

**Not implementing now, but documented for future reference.**

If scaling issues emerge, consider extracting heavy operations into 2-3 containers:

#### Container 1: Video Orchestrator (Core)
- Temporal workflows and activities
- ComfyUI coordination
- N8N webhook handling
- Metrics endpoint

#### Container 2: Media Processing Service
- `/merge`, `/stitch`, `/subtitles` endpoints
- Pure ffmpeg operations
- Stateless, horizontally scalable

#### Container 3: Utility Service (Optional)
- TikTok archiving
- Upscaling operations
- Background tasks

**Benefits:**
- Independent scaling of media processing
- Faster deployments (smaller images)
- Resource isolation

**Costs:**
- Network latency between services
- More complex deployment orchestration
- Distributed debugging complexity
- Additional operational overhead

**Trigger conditions for Option B:**
- Measured resource contention causing failures
- Need to scale video stitching independently
- Deployment pipeline becomes bottleneck
- Multiple developers working on different components

---

### Option C: Full Microservices (Not Recommended)

**Explicitly rejected** unless:
- Team grows to 5+ developers
- Handling 1000s of concurrent jobs
- Need independent team ownership

**Why avoid:**
- Massive complexity increase
- Distributed tracing requirements
- Network latency and failure modes
- Deployment orchestration overhead
- Debugging becomes significantly harder

---

## Current Action Plan

### Immediate (Completed)
- ✅ Document architectural assessment
- ✅ Establish decision criteria for future refactoring
- ✅ Maintain existing Prometheus metrics

### Short Term (Next 1-3 months)
- Monitor resource usage patterns via Prometheus
- Document any performance bottlenecks
- Profile memory and CPU usage during peak operations
- Establish baseline metrics for:
  - Container memory usage
  - ffmpeg operation duration
  - Temporal workflow completion times
  - ComfyUI request latencies

### Medium Term (3-6 months)
- Review metrics and identify actual bottlenecks
- Implement Temporal task queue separation if needed
- Optimize Docker resource limits based on profiling
- Consider Option B only if concrete issues emerge

### Long Term (6+ months)
- Reassess architecture if team grows
- Evaluate Option B if scaling requirements change
- Keep documentation updated with lessons learned

---

## Decision Criteria for Future Refactoring

**Proceed with Option B (Selective Extraction) if:**
1. Container OOM errors occur regularly (>1/week)
2. Deployment time exceeds 5 minutes consistently
3. Resource contention causes workflow failures
4. Need to scale specific operations independently
5. Team grows to 2+ developers with separate focus areas

**Metrics to monitor:**
- Container restart frequency
- Memory usage during ffmpeg operations
- Temporal workflow failure rates
- Deployment duration
- Development velocity (time to implement features)

**Do NOT refactor based on:**
- Anxiety about complexity
- "Feels wrong" without metrics
- Following microservices trends
- Theoretical scaling concerns

---

## Key Principles

1. **Measure before optimizing** - Use Prometheus metrics to identify real bottlenecks
2. **Simplicity over perfection** - Current architecture works; don't fix what isn't broken
3. **Incremental improvements** - Small, measured changes over big rewrites
4. **Document decisions** - Capture rationale for future reference
5. **Revisit regularly** - Reassess every 3-6 months or when conditions change

---

## Related Documentation

- **Architecture Overview:** `TABARIO_CONTAINER_DIAGRAM.md`
- **Deployment Details:** `TABARIO_DEPLOYMENT_DIAGRAM.md`
- **Processing Flow:** `VIDEO_PROCESSING_SEQUENCE_DIAGRAM.md`
- **Future Enhancements:** `TODO.md`

---

## Revision History

| Date | Decision | Rationale |
|------|----------|-----------|
| Jan 2026 | Option A: Keep As-Is | Solo developer, no scaling issues, well-structured code |

---

## Notes

This is a **living document**. Update when:
- Architecture decisions change
- New scaling requirements emerge
- Team size changes
- Significant performance issues identified
- Refactoring is actually implemented
