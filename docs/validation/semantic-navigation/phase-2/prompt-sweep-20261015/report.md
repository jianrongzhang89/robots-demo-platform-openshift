# Phase 2 development prompt-sensitivity sweep

- **Date:** October 15, 2026
- **Status:** exploratory development result; not an acceptance or held-out evaluation
- **Dataset:** nine independently reviewed development captures in `capture-pilot-v3/combined-visibility-manifest.jsonl` (8 positive, 1 target-absent tile distractor; 2 capture episodes)
- **Model/checkpoint:** local `facebook/sam3`, checkpoint SHA-256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`
- **Runtime:** NVIDIA L40S, CUDA; confidence threshold fixed at `0.5`; same images, labels, and checkpoint for every prompt
- **Prompts:** `red floor mat` (existing baseline), `red mat`, `floor mat`, and `mat`

## Results

| Prompt | Positive detections (IoU ≥ 0.5) | Recall | Median positive IoU (misses = 0) | Negative FP frames | Median / p95 inference |
|---|---:|---:|---:|---:|---:|
| `red floor mat` | 4/8 | 0.500 | 0.450727 | 0/1 | 95.1 / 559.6 ms |
| `red mat` | 7/8 | 0.875 | 0.902475 | 0/1 | 94.8 / 267.5 ms |
| `floor mat` | 0/8 | 0.000 | 0.000000 | 0/1 | 96.4 / 266.2 ms |
| `mat` | 0/8 | 0.000 | 0.000000 | 0/1 | 95.0 / 266.6 ms |

`red mat` recovered all three episode-1 severe-occlusion positives that `red floor mat` missed: their IoUs were 0.900667, 0.899478, and 0.918750. It also detected both episode-2 unoccluded/moderate views, as did the baseline. Both prompts missed the episode-2 severe-occlusion view (about 24% visible). The three newly recovered detections had model scores 0.515625, 0.511719, and 0.542969, close to the fixed 0.5 confidence threshold. Therefore the result indicates strong prompt sensitivity in this scene, but the recovered cases may be threshold-fragile; they do not establish a general visibility limit.

The one negative was rejected by all four prompts, but 0/1 is far too little evidence to estimate false-positive behavior. Frame latency is warm per-image inference and excludes model load, ROS transport, synchronization, queuing, and sustained-rate effects. Each prompt ran in a separate process and loaded the same checkpoint. Full reports, per-image outcomes, model scores, latency, and predicted masks are retained under `results/`.

## Assessment and next step

The earlier severe-occlusion failures were not solely a fixed SAM3 visibility limit: changing only the text prompt from `red floor mat` to `red mat` recovered three reviewed positives in one episode. The remaining episode-2 severe case still fails, so prompt wording alone has not resolved the observed edge case. For development, carry `red mat` forward as the leading candidate and compare it on a broader, independently captured development matrix. Do not freeze it yet: the protocol calls for at least 20 positive and 20 negative development examples across episodes, and the current set has only eight positives and one negative.

After prompt, confidence threshold, and visibility contract are selected on expanded development data, freeze the complete configuration and collect a new episode-separated held-out set (at least 50 positives and 50 negatives). Any later prompt or threshold change requires a fresh held-out set. Phase 2 remains **HOLD**; do not connect SAM3 output to ROS navigation, Nav2/costmaps, RMF, or OpenShift AI serving based on this sweep.
