# Third-Party Notices — `skill_library/catalog.py`

`catalog.py`'s seed catalogue of `CreationSkill` templates has two parts: a
short-drama video-recipe majority, and a smaller "图片风格 image style"
section for the image studio. Both were informed only by genre/shot/scene
*naming conventions* — from open-source projects for the video section, and
from public 2026 AI-image prompt-trend write-ups for the image-style section
(see the second "Sources consulted" list below) — never by copying content.
**No text, prompt, or `SKILL.md` content from any of these sources is
copied into this repository** — every `title`, `description`, and
`prompt_suffix` in `catalog.py` is original text written for this product's
flat `params_json` template shape, which is structurally unrelated to both
an "Agent Skill" (`SKILL.md`, a multi-file instruction set for an LLM coding
agent driving a whole production pipeline) and a prompt-trend article's own
example prompt.

## Sources consulted — short-drama video section

- **[zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills)**
  (MIT License) — informed the production-role breakdown (script → assets →
  storyboard → image/video prompts → review) used to decide which shot/scene/
  look categories this catalogue's `lens`/`scene`/`style` entries cover.
- **[jnMetaCode/ai-shortfilm-prompts](https://github.com/jnMetaCode/ai-shortfilm-prompts)**
  — the `templates/`, `methodology.md`, and `skills/shortfilm-prompt/`
  authored by jnMetaCode are MIT-licensed and informed this catalogue's
  5-stage-structure framing and genre naming (e.g. "15秒身份反转").
  **The original prompt text and document excerpts authored by Mx-Shell in
  that repository are © Mx-Shell, all rights reserved, per that repository's
  own `NOTICE` file — none of that content, or any IP-specific prompt
  language, was used here.**
- **2026 camera-movement glossaries** used by Seedance / Kling / Veo
  write-ups (orbit/arc, crash zoom, rack focus, continuous oner) — informed
  which *named moves* the 2026-08 catalogue supplement covers. No vendor
  prompt string was copied.
- **Chinese short-drama production guides** for 即梦 / 可灵 (subject +
  setting + action + camera + light + style as a six-slot writing habit;
  rebirth-open / time-cut / public-reveal locations such as wedding halls,
  classrooms, parking garages, airport gates) — informed category *gaps*,
  not wording.

## Sources consulted — 图片风格 "image style" section

The dozen `image-*` catalogue rows (`category=STYLE`, `_IMAGE_OPERATIONS`)
name techniques that were extremely widely reproduced across public 2026
write-ups about Nano Banana / Nano Banana 2 / GPT-Image prompting — none of
which are open-source repos with their own licence, so the same
"informed-naming-only, no copied prompt text" rule applies even harder here:
every `title`, `description`, and `prompt_suffix` on these rows is original
text written for this catalogue's flat template shape, not a paraphrase of
any one article's example prompt.

- **[ChatGPT趋势提示：2026年潮流手办、照片编辑与爆款图像创意 (Seedance)](https://www.seedance.tv/zh/blog/chatgpt-trend-prompts-2026)**
  and **[AI 手办／玩偶生成器 (Renoise)](https://renoise.ai/zh-CN/guides/ai-action-figure)**
  — informed the naming of `image-figurine-blindbox` (blister-pack
  collectible figure) as 2026's most-reproduced single trend, and the
  "material / packaging / studio lighting" framing behind its wording.
- **[Nano Banana 2 最佳提示词 (Atlas Cloud)](https://www.atlascloud.ai/zh/blog/guides/nano-banana-2-prompts-guide)**
  and **[Nano Banana 手办提示词指南 (LaoZhang AI)](https://blog.laozhang.ai/zh/posts/nano-banana-figurine-prompt-guide)**
  — informed the same entry's emphasis on naming a concrete material/finish
  and photography terms rather than a vague one-line request.
- **[Nano Banana! 100 Exquisite Prompt Ideas (Boardor)](https://boardor.com/blog/nano-banana-100-exquisite-prompt-ideas)**
  — a round-up of widely-circulated public prompt-trend cases; informed the
  category *gap* behind `image-miniature-diorama` ("Miniature 3D Building"),
  `image-polaroid-retro` ("3D Polaroid Breakthrough Effect"), and
  `image-fashion-magazine-cover` ("Fashion Magazine Cover Style"). No
  example prompt text from that page was reused.
- **[Nano Banana Prompt: IP Emoji Sticker Sheet Poster (Curify AI)](https://www.curify-ai.com/nano-template/ip-emoji-sticker-sheet-poster)**
  and **[Original Character Sticker Pack (Curify AI)](https://www.curify-ai.com/nano-template/original-character-sticker-pack)**
  — informed the "same character, grid of panels, only expression changes"
  structure named by `image-sticker-sheet-ip`; the actual layout wording
  (nine-panel grid, die-cut outline, drop shadow) was written fresh for this
  catalogue rather than adapted from either template's own prompt text.
- **General public familiarity with old-photo colorization, ID-photo
  generators, sketch-to-render tools, e-commerce product photography, and
  architectural visualization** — informed `image-old-photo-restore-color`,
  `image-id-photo`, `image-lineart-to-real`, `image-ecommerce-product-shot`,
  `image-architecture-render`, and `image-retro-propaganda-poster`; these are
  generic, long-established image-editing categories rather than techniques
  traceable to one source, so no single article is cited per entry.
- **Studio Ghibli's own widely-discussed 2025 visual style** (not any AI
  vendor's write-up) — informed `image-ghibli-watercolor`'s naming; the
  `prompt_suffix` describes the *visual traits* commonly associated with that
  studio's hand-painted watercolor look (soft brushwork, warm palette,
  expressive eyes), not a reproduction of any copyrighted frame or artwork.

## What was and wasn't taken

| Taken (informed the catalogue's structure) | Not taken |
| --- | --- |
| Genre/shot naming conventions (e.g. "过肩镜头", "身份反转打脸") | Any verbatim `SKILL.md` instruction text |
| The idea of splitting templates by production role (lens / scene / look / script-beat) | Any external "produce" adapter, provider binding, or agent orchestration logic |
| The 5-stage cinematic-prompt structuring idea | Mx-Shell's original prompt text (ARR) |
| Which 2026 image-prompt *formats* are popular enough to name (figurine, diorama, sticker sheet, magazine cover, ...) | Any blog's actual example prompt sentence, template variable syntax, or marketing copy |

If a maintainer of either project believes this attribution is insufficient,
or wants any resemblance removed, open an issue against this repository.
