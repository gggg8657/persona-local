#!/usr/bin/env python3
# 페르소나 얼굴 그림 다시 만들기 (선택): diffusers + torch(GPU) 환경에서  python scripts/gen_faces.py out/  → out/<이름>_<seed>.png 중 골라 personas/<이름>.png 로
"""페르소나 얼굴: 가상 인물(실존 인물 아님) 상반신 정면 초상 — Realistic Vision 5.1 (SD1.5, CreativeML OpenRAIL-M)"""
import os, sys, torch
from diffusers import StableDiffusionPipeline, AutoencoderKL, DPMSolverMultistepScheduler
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
vae = AutoencoderKL.from_pretrained("stabilityai/sd-vae-ft-mse", torch_dtype=torch.float16)
pipe = StableDiffusionPipeline.from_pretrained("SG161222/Realistic_Vision_V5.1_noVAE", vae=vae, torch_dtype=torch.float16, safety_checker=None).to("cuda")
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True)
BASE = "RAW photo, upper body portrait, looking straight at the camera, front view, centered face, closed mouth, soft natural window light, plain light grey background, sharp focus, 85mm, high detail skin"
P = {
 "gf": "28 year old korean woman, book editor, long dark wavy hair, warm gentle smile, cream knit cardigan",
 "bf": "31 year old korean man, firefighter, short black hair, kind calm expression, slight smile, navy t-shirt, broad shoulders",
 "tsundere": "27 year old korean woman, short bob haircut, slightly sulky unimpressed expression, grey hoodie",
 "mentor": "42 year old korean woman, senior researcher, shoulder-length hair, thin glasses, friendly confident expression, white shirt with id lanyard",
 "interviewer": "52 year old korean man, interviewer at a research institute, neat short grey hair, dark suit and tie, neutral professional expression",
 "english": "30 year old british woman from london, designer, light brown hair in a loose bun, light freckles, friendly smile, denim shirt",
}
NEG = "cartoon, anime, illustration, painting, 3d render, cgi, deformed, disfigured, blurry, sunglasses, hat, hands, text, watermark, side view, profile, tilted head, open mouth, teeth, nsfw, nude, cleavage"
for name, p in P.items():
    for seed in range(3):
        g = torch.Generator("cuda").manual_seed(1000 + seed)
        im = pipe(f"{BASE}, {p}", negative_prompt=NEG, width=640, height=640, num_inference_steps=28, guidance_scale=5.5, generator=g).images[0]
        im.save(f"{out}/{name}_{seed}.png"); print(name, seed, flush=True)
