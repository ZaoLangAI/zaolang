import type { ScriptScene } from '@/features/script/api';
import type { SceneLighting, ScenePresets, SceneWeather } from '@/features/image-assets/vocabulary';

/**
 * Best-effort lighting/weather presets from a screenplay scene heading.
 *
 * Headings have no enforced format (`便利店 - 夜`, `第一场 · 便利店 - 夜`,
 * `内景 值班室`, `雨巷`, `EXT. STREET - NIGHT`), so this only recognises the
 * conventional tokens: 内景/外景 (内/外, INT/EXT) and 日/夜/晨/黄昏 (DAY/
 * NIGHT/DAWN/DUSK), plus 雨/雪/雾. A heading that names nothing falls back
 * to the scene's own `scene` blocks. The heading itself is a key
 * (`breakpointKey`, link matching) — this parses it, never rewrites it.
 */
export function parseScenePresets(scene: Pick<ScriptScene, 'heading' | 'blocks'>): ScenePresets {
  const fromHeading = parseText(scene.heading, { strictTime: false });
  if (fromHeading.lighting && fromHeading.weather) return fromHeading;
  const blockText = scene.blocks
    .filter((block) => block.type === 'scene')
    .map((block) => block.text)
    .join('，');
  const fromBlocks = parseText(blockText, { strictTime: true });
  return {
    lighting: fromHeading.lighting ?? fromBlocks.lighting,
    weather: fromHeading.weather ?? fromBlocks.weather,
  };
}

const EXTERIOR = /外景|(?:^|[\s·\-—/|，,])外(?:$|[\s·\-—/|，,])|\bEXT\b/i;
const INTERIOR = /内景|(?:^|[\s·\-—/|，,])内(?:$|[\s·\-—/|，,])|\bINT\b/i;

/** Ordered: the first matching rule wins (黄昏 before a bare 日 etc.). */
const TIME_RULES: { pattern: RegExp; strict: RegExp; value: 'dawn' | 'day' | 'dusk' | 'night' }[] =
  [
    {
      pattern: /黄昏|傍晚|日落|夕阳|\bDUSK\b|\bSUNSET\b/i,
      strict: /黄昏|傍晚|日落|夕阳/,
      value: 'dusk',
    },
    {
      pattern: /清晨|拂晓|黎明|晨|\bDAWN\b|\bMORNING\b/i,
      strict: /清晨|拂晓|黎明|晨光/,
      value: 'dawn',
    },
    { pattern: /深夜|夜晚|午夜|夜|\bNIGHT\b/i, strict: /深夜|夜晚|午夜|夜色|夜里/, value: 'night' },
    {
      pattern: /白天|日间|正午|中午|下午|上午|(?:^|[\s·\-—/|，,])日(?:$|[\s·\-—/|，,])|\bDAY\b/i,
      strict: /白天|日间|正午|中午|阳光/,
      value: 'day',
    },
  ];

const WEATHER_RULES: { pattern: RegExp; value: SceneWeather }[] = [
  { pattern: /暴雨|大雨|小雨|雨夜|雨天|下雨|雨巷|雨中|\bRAIN/i, value: 'rain' },
  { pattern: /大雪|下雪|雪夜|雪地|风雪|\bSNOW/i, value: 'snow' },
  { pattern: /大雾|浓雾|雾气|薄雾|\bFOG/i, value: 'fog' },
  { pattern: /沙尘|风沙|沙暴/, value: 'sandstorm' },
];

function parseText(text: string, { strictTime }: { strictTime: boolean }): ScenePresets {
  const presets: ScenePresets = {};
  if (!text.trim()) return presets;
  const time = TIME_RULES.find((rule) =>
    (strictTime ? rule.strict : rule.pattern).test(text),
  )?.value;
  if (time) presets.lighting = lightingFor(time, text);
  const weather = WEATHER_RULES.find((rule) => rule.pattern.test(text))?.value;
  if (weather) presets.weather = weather;
  return presets;
}

function lightingFor(time: 'dawn' | 'day' | 'dusk' | 'night', text: string): SceneLighting {
  if (time !== 'night') return time;
  if (EXTERIOR.test(text)) return 'night_exterior';
  if (INTERIOR.test(text)) return 'night_interior';
  // An unmarked night scene is most often an interior in short drama.
  return 'night_interior';
}
