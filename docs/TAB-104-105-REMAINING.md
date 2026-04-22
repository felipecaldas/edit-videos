# TAB-104 & TAB-105 Remaining Work

## TAB-104: Compositor scene_overlays + typographic scenes

### Required Changes

1. **Update `tabario-video-compositor/src/manifest/schema.ts`**:
   - Add optional `scene_overlays` array to scene schema
   - Add optional `clip_filename` field for typographic scenes (no video, just text)
   - Extend overlay component types if needed

2. **Create TypographicBackground component**:
   - New Remotion component for pure typographic scenes
   - Renders text on brand background without video
   - Accepts text, color, font, animation props

3. **Update handoff API contract**:
   - Document new `scene_overlays` field in `docs/api/handoff.md`
   - Document `clip_filename` optional field
   - Provide examples of text-heavy scenes

4. **Tests**:
   - Add unit tests for manifest schema validation with overlays
   - Test typographic scene rendering
   - Test mixed scenes (video + overlays)

## TAB-105: E2E smoke + docs update

### Required Changes

1. **E2E Smoke Test**:
   - Create test brief with:
     - 1 text-heavy scene (should use Fal + text overlay)
     - 1 people scene (should use Runpod z-image-turbo)
   - Run full orchestration flow
   - Verify:
     - Scene classifier runs
     - Correct providers selected
     - Text overlays passed to compositor
     - Final video generated

2. **Update `docs/api/orchestrate-start.md`**:
   - Document new optional fields:
     - `enable_scene_classifier` (boolean)
     - `video_provider_override` (string: "fal" | "runpod")
   - Document new response fields:
     - `scene_classifications` (array)
     - `video_provider_used` (string)

3. **Verify All Tests Pass**:
   - Run full test suite in container
   - Fix any integration issues
   - Ensure no regressions

4. **Final Commit**:
   - Update all Linear issues to Done
   - Close epic TAB-98
   - Document any known limitations

## Implementation Notes

### Compositor Integration

The compositor already supports overlays via the manifest schema. We need to:
- Ensure `scene_overlays` is properly typed
- Pass classifier output through to compositor handoff
- Handle typographic scenes (no video clip, just text rendering)

### Workflow Branching

The workflow needs to:
1. Call `classify_scenes_activity` once per brief
2. For each scene:
   - Check `skip_image_generation` flag
   - If true: skip image/video generation, pass overlay config to compositor
   - If false: use `image_provider` and `image_model` from classification
3. Use `VIDEO_PROVIDER` env var for video generation (with classifier override)

### Testing Strategy

- Unit tests: Already complete for TAB-99, TAB-100, TAB-101, TAB-102
- Integration tests: TAB-103 activities need Temporal context mocking
- E2E tests: TAB-105 smoke test with real brief

## Estimated Effort

- TAB-104: ~2-3 hours (compositor schema + component + tests)
- TAB-105: ~2-3 hours (E2E test + docs + verification)
- Total: ~4-6 hours remaining

## Dependencies

- TAB-104 depends on: TAB-99, TAB-100, TAB-101 (all complete)
- TAB-105 depends on: TAB-102, TAB-103, TAB-104
