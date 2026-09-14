# Third-Party Notices — `skill_library/catalog.py`

`catalog.py`'s seed catalogue of `CreationSkill` templates has four parts: a
short-drama video-recipe majority, a 「提示词格式 format」section of
structural prompt-writing rules, a smaller "图片风格 image style"
section for the image studio, and a dual-shape 「图片资产」section
(`character` / `scene_asset` / `cover_asset`). All four were informed only
by genre/shot/scene or *layout naming conventions*, or — for the format
section — by *which rules vendors state publicly* — from open-source
projects for the video section, from eleven video vendors' own public
prompting documentation for the format section, from public 2026 AI-image
prompt-trend write-ups for the image-style section, and from public
character-sheet / empty-set / cover Agent Skills for the image-asset section
(see the lists below) — never by copying content.
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
  which *named moves* the 2026-08 catalogue supplement covers. A later
  2026-09 pass used the same glossaries plus Chinese short-drama / 即梦 /
  可灵 community lists to name the remaining high-frequency gaps (macro
  close-up, drone ultra-wide establish, Hitchcock dolly zoom, FPV dive,
  Dutch angle, first-person POV, whip-pan handoff, crane-up reveal). No
  vendor prompt string was copied.
- **Chinese short-drama production guides** for 即梦 / 可灵 (subject +
  setting + action + camera + light + style as a six-slot writing habit;
  rebirth-open / time-cut / public-reveal locations such as wedding halls,
  classrooms, parking garages, airport gates) — informed category *gaps*,
  not wording.

## Sources consulted — 提示词格式 "format" section

The 120 `fmt-*` rows (`category=FORMAT`, `_VIDEO_OPERATIONS`) are different
in kind from every other section: they name *constraints on how a prompt is
written* rather than a look. That makes the sourcing question sharper, not
looser, because several of these rules are stated in vendor documentation as
plain imperative sentences — "one action per prompt", "keep it under 10
seconds" — and a rule stated that plainly is easy to reproduce verbatim
without noticing.

The same "informed-naming-only, no copied prompt text" rule therefore
applies, with one addition specific to this section: **a vendor's finding is
recorded as a fact about that model's behaviour, and the wording that
expresses it is written fresh.** So Runway's officially documented
observation that a negation in the prompt body can produce the opposite
result is used as evidence; its sentences are not. Every `title`,
`description`, and `prompt_suffix` on these rows is original text written for
this catalogue's appendable-`prompt_suffix` shape.

`docs/video-prompt-formats.md` is the research document behind this section
and carries the full per-vendor citation list with evidence-strength labels;
it is not duplicated here. The sources fall into four groups:

- **Vendor prompting documentation from eleven video models** — OpenAI
  Sora 2, Google Veo (Vertex AI / Gemini API / DeepMind), 快手可灵 Kling,
  Runway Gen-4 / Gen-4.5, 阿里通义万相 Wan, Vidu, MiniMax 海螺, PixVerse,
  Luma Ray3, Pika, and 字节 Seedance / 即梦 (whose official pages render
  client-side and were cross-checked against three independent
  secondaries). These informed *which* rules are worth seeding, and the
  evidence-strength label each carries in the research document. No vendor
  example prompt, formula string, or documentation sentence is reproduced in
  `catalog.py`.
- **Traditional film craft** — shot-size and camera-move terminology,
  key-to-fill lighting ratios, shot-list field sets, and trailer structure.
  These are decades-old industry conventions with no single owner; the
  research document cites the specific glossaries consulted (StudioBinder,
  No Film School, Tools for Film, Derek Lieu's trailer-editing write-ups)
  for traceability rather than because any of them is the origin of a term.
- **Chinese vertical short-drama practice** — hook taxonomies, per-episode
  pacing skeletons, cast-size limits, and vertical-framing habits, from
  industry reports and platform methodology write-ups (快手研究院, 人民网,
  爱奇艺's public creation methodology, 第一财经). These informed the
  `fmt-hook-*`, `fmt-vertical-*` and `fmt-teaser-*` category *gaps*. Note
  that no video vendor documents anything about opening seconds or trailer
  structure at all, so these rows are labelled community practice in the
  research document and their descriptions say so.
- **Anti-pattern round-ups from tool vendors' blogs** (VIDEOAI.ME,
  QuestStudio, PixVerse's own tutorials) — informed which failure modes are
  common enough to seed a `fmt-guard-*` row for. Any measured figure in
  those posts is self-reported by the vendor with no third-party
  verification; the research document flags this explicitly, and no such
  figure appears in any catalogue row or product copy.

## Sources consulted — 戏码与情绪 "drama" section

The 80 `drama-*` rows (`category=DRAMA`, `_VIDEO_OPERATIONS`) are the mirror
of the section above: a `format` row stays true whatever the clip is about, a
`drama` row means nothing outside the one situation or emotion it names.
That flips the sourcing question, because **no video vendor documents any of
this** — none of them will tell you how a hospital-bedside standoff should be
cut into beats. `docs/video-drama-scenes.md` is the research document behind
this section and carries the per-group evidence-strength table; the three
source groups are:

- **Traditional blocking and coverage convention** — the 180-degree line,
  screen direction across a cut, side-by-side staging for a conversation
  that cannot be had face to face, reaction shots landing before the event
  they react to. These are decades-old craft conventions with no single
  owner, and they are the strongest evidence in this section precisely
  because they predate every model involved.
- **Chinese vertical short-drama practice** — which scene types recur often
  enough to be worth seeding, where the four-beat break usually falls, and
  which openings hold. Same sources and same caveat as the `fmt-hook-*` /
  `fmt-vertical-*` rows above: community practice, self-reported, no
  first-party data. The scene-type *taxonomy* was informed by the
  categorisations that recur across public short-drama script-structure
  discussion; no scene list, beat sheet, or example line was copied, and
  every `title` / `description` / `prompt_suffix` is original text written
  for this catalogue.
- **Acting-training tell inventories** — the visible physiological signals
  behind the 30 `drama-emotion-*` rows (a swallow travelling the throat,
  nails in the palm, shoulders dropping several centimetres). These are
  long-standing performance conventions rather than anyone's proprietary
  method. The open question is a different one and the research document
  states it plainly: whether a given model can actually render a named tell
  is unverified, which is why these rows are fed to the agents as reference
  material rather than stapled onto the outgoing prompt.

No character, plot, line of dialogue, or title from any actual short drama
appears in these rows. A row names a *kind* of scene ("a bedside
confrontation held at a whisper"), never a specific work's version of it.

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

## Sources consulted — 图片资产 "image asset" section

The two-dozen `asset-*` catalogue rows (`category=CHARACTER` /
`SCENE_ASSET` / `COVER_ASSET`, `_IMAGE_OPERATIONS`) name *layout recipes*
that are widely used as reusable reference stills — turnaround sheets,
expression grids, empty establishing shots, title-safe covers — not
finished characters from any show. The same "informed-naming-only, no
copied prompt text" rule applies: every `title`, `description`, and
`prompt_suffix` is original text written for this catalogue's hybrid
`prompt_suffix` + nested `reference_assets` shape.

- **[fal-ai-community/skills character-design prompt-patterns](https://github.com/fal-ai-community/skills/blob/main/skills/character-design/references/prompt-patterns.md)**
  and **[prunaai/pruna-skills character-turnaround-sheet](https://github.com/prunaai/pruna-skills/blob/main/skills/guides/image-prompting/references/character-turnaround-sheet.md)**
  — informed the *names* of `asset-char-turnaround-sheet`,
  `asset-char-expression-grid`, and `asset-char-wardrobe-grid` (front/side/back
  on one plate; a grid of distinct expressions; outfit-only variation). No
  prompt sentence from either file was reused.
- **[ShinChven/nano-banana-skills character-reference-sheet](https://github.com/ShinChven/nano-banana-skills/blob/main/skills/character-reference-sheet/SKILL.md)**
  and **[inference-sh/skills character-design-sheet](https://github.com/inference-sh/skills)**
  — informed the three-column portrait / front / back layout named by
  `asset-char-three-column-ref`, and the "50+ word identity lock" habit
  named by `asset-char-identity-anchor`. The actual suffix wording
  (waist-up, one signature accessory, no second character) was written
  fresh.
- **[edhahn/agent-skills concept-art](https://github.com/edhahn/agent-skills)**
  and public FLUX.2 prompting guides (scene → light → camera, empty-set
  stills) — informed the "无人建立镜头" gap behind the eight
  `asset-scene-*-empty` / `asset-scene-vertical-establish` rows. Location
  *types* overlap this catalogue's own video `scene-*` titles on purpose
  (alley, mansion, hospital, office, parking, balcony, wedding hall) but
  the image-asset titles add 「空镜」and the suffixes forbid people.
- **[black-forest-labs/skills typography-text](https://github.com/black-forest-labs/skills/blob/master/skills/flux-image-best-practices/rules/typography-text.md)**
  and **[haoyiyin/mflux-cover](https://github.com/haoyiyin/mflux-cover)**
  — informed the title-safe / overlay-later habit named by
  `asset-cover-title-safe` and the other seven vertical cover rows. This
  catalogue still forbids rendered lettering on the still itself (same
  rule as the image-style posters), leaving a blank header band instead of
  asking the image model to spell a title.

## What was and wasn't taken

| Taken (informed the catalogue's structure) | Not taken |
| --- | --- |
| Genre/shot naming conventions (e.g. "过肩镜头", "身份反转打脸") | Any verbatim `SKILL.md` instruction text |
| The idea of splitting templates by production role (lens / scene / look / script-beat) | Any external "produce" adapter, provider binding, or agent orchestration logic |
| The 5-stage cinematic-prompt structuring idea | Mx-Shell's original prompt text (ARR) |
| Which 2026 image-prompt *formats* are popular enough to name (figurine, diorama, sticker sheet, magazine cover, ...) | Any blog's actual example prompt sentence, template variable syntax, or marketing copy |
| Character-sheet / empty-set / title-safe-cover *layout names* (turnaround, expression grid, establishing still) | Any Agent Skill's `SKILL.md` body, example prompt, or generated artwork |
| Which prompt-writing rules eleven video vendors state publicly, and how strong the evidence for each is | Any vendor's formula string, example prompt, field-name list as written, or documentation sentence |
| Which *kinds* of scene and which emotional beats recur across public short-drama structure discussion | Any actual drama's characters, plot, dialogue, title, scene list, or beat sheet |
| Film-craft terminology that predates all of these models (shot sizes, camera moves, lighting ratios, trailer structure) | Any single glossary's phrasing or ordering |
| Vendors' self-reported behavioural findings, used as evidence about a model | Vendors' self-reported *numbers*, which are unverified and stay out of the catalogue and product copy entirely |

If a maintainer of either project believes this attribution is insufficient,
or wants any resemblance removed, open an issue against this repository.
