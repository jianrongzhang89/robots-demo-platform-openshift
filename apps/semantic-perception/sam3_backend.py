"""SAM3 runner and local predict adapter, independently usable without ROS."""
import os
import time

from PIL import Image

from inference_contract import response_base, success_response, validate_request


class Sam3ModelRunner:
    def __init__(self, checkpoint, threshold):
        if not os.path.isfile(checkpoint):
            raise FileNotFoundError(checkpoint)
        import torch
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model
        self.torch = torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA required for Phase 3")
        model = build_sam3_image_model(device="cuda", checkpoint_path=checkpoint,
                                      load_from_HF=False, eval_mode=True)
        self.processor = Sam3Processor(model, device="cuda", confidence_threshold=threshold)
        self.threshold = threshold
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def infer(self, image, prompt, threshold):
        if threshold != self.threshold:
            raise ValueError("threshold change requires explicit backend restart")
        torch = self.torch
        with torch.inference_mode(), torch.autocast("cuda", dtype=self.dtype):
            state = self.processor.set_image(image)
            result = self.processor.set_text_prompt(state=state, prompt=prompt)
        torch.cuda.synchronize()
        return (result["masks"].detach().float().cpu().numpy(),
                result["scores"].detach().float().cpu().numpy())


class LocalSam3Backend:
    def __init__(self, runner):
        self.runner = runner

    def predict(self, request):
        started = time.monotonic()
        try:
            raw = validate_request(request)
        except (ValueError, KeyError, TypeError) as error:
            return response_base(request, "invalid_input", str(error))
        if self.runner is None:
            return response_base(request, "not_ready", "model not loaded")
        try:
            image = Image.frombytes("RGB", (request["width"], request["height"]), raw)
            masks, scores = self.runner.infer(image, request["prompt"], request["threshold"])
            response = success_response(request, masks, scores)
            if (time.monotonic() - started) * 1000 >= request["budget_ms"]:
                return response_base(request, "timeout", "backend budget expired")
            return response
        except Exception as error:
            return response_base(request, "inference_error", f"{type(error).__name__}: {error}")
