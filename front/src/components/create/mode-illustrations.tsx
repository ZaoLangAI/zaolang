/**
 * Mode-card illustrations for the create page.
 *
 * Drawn in the same hand-rolled, stroke-based language as
 * `components/ui/icons.tsx` (currentColor, rounded joins) rather than as
 * raster art, so every card stays crisp and correct in both themes without a
 * second, theme-specific asset to maintain. Each one fills the card's
 * `aspect-[16/10]` slot, so the `viewBox` is proportioned to match.
 */
type IllustrationProps = { className?: string };

function Scene({ className, children }: IllustrationProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 160 100"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

/** A film frame with a play mark, unspooling from the same text lines. */
export function TextToVideoIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="46" y="16" width="80" height="60" rx="6" fillOpacity="0.06" fill="currentColor" />
      {[24, 34, 44, 54, 64].map((y) => (
        <rect key={y} x="50" y={y} width="4" height="4" rx="1" strokeOpacity="0.5" />
      ))}
      <circle cx="90" cy="46" r="15" />
      <path d="M85 38 100 46 85 54Z" fill="currentColor" strokeLinejoin="round" />
      <path d="M18 30h16M18 40h22M18 50h14" strokeOpacity="0.55" />
    </Scene>
  );
}

/** A character bust portrait beside a small landscape frame, standing in for
 * the three asset purposes this card fans out to (character views, scene
 * stills, covers) once inside the studio. */
export function ImageCreationIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="16" y="12" width="62" height="76" rx="8" fillOpacity="0.06" fill="currentColor" />
      <circle cx="47" cy="38" r="12" />
      <path d="M27 80c2-17 10-25 20-25s18 8 20 25" />
      <rect x="92" y="24" width="54" height="40" rx="6" fillOpacity="0.06" fill="currentColor" />
      <circle cx="112" cy="36" r="4" />
      <path d="M98 56 112 42l8 8 10-10 14 12" />
      <path d="M132 10 135.4 17.5 143 20.8 135.4 24.1 132 31.5 128.6 24.1 121 20.8 128.6 17.5Z" />
    </Scene>
  );
}

/** A waveform with a microphone capsule beside it. */
export function AudioGenerationIllustration(props: IllustrationProps) {
  const bars = [10, 22, 34, 20, 40, 26, 16, 30, 14];
  return (
    <Scene {...props}>
      {bars.map((h, index) => (
        <rect
          key={index}
          x={20 + index * 8}
          y={50 - h / 2}
          width="4"
          height={h}
          rx="2"
          fill="currentColor"
          stroke="none"
          fillOpacity={index % 2 === 0 ? 0.9 : 0.55}
        />
      ))}
      <rect x="118" y="26" width="16" height="26" rx="8" fillOpacity="0.08" fill="currentColor" />
      <path d="M110 40a16 16 0 0 0 32 0" />
      <path d="M126 56v8M118 68h16" />
    </Scene>
  );
}

/** A vertical phone with a centred play mark and two caption bars. */
export function ShortformIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="58" y="10" width="44" height="80" rx="9" fillOpacity="0.06" fill="currentColor" />
      <path d="M74 10h12" strokeWidth="3" strokeOpacity="0.6" />
      <circle cx="80" cy="42" r="13" />
      <path d="M76 35 90 42 76 49Z" fill="currentColor" strokeLinejoin="round" />
      <rect
        x="66"
        y="66"
        width="28"
        height="4"
        rx="2"
        fill="currentColor"
        stroke="none"
        fillOpacity="0.5"
      />
      <rect
        x="66"
        y="74"
        width="18"
        height="4"
        rx="2"
        fill="currentColor"
        stroke="none"
        fillOpacity="0.35"
      />
    </Scene>
  );
}


/** A film frame with a magnifying glass over it, standing in for "analyse
 * an existing video" rather than "generate a new one" (`TextToVideoIllustration`
 * above uses the same frame shape with a play mark instead). */
export function VideoAnalysisIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="14" y="16" width="92" height="68" rx="6" fillOpacity="0.06" fill="currentColor" />
      <path d="M14 32h92M36 16v16M64 16v16M92 16v16" strokeOpacity="0.35" />
      <path d="M28 66 44 48l10 9 16-18 14 12" strokeOpacity="0.55" />
      <g>
        <circle cx="112" cy="62" r="17" fillOpacity="0.08" fill="currentColor" />
        <circle cx="112" cy="62" r="17" />
        <path d="M124 74 138 88" strokeWidth="4" />
      </g>
    </Scene>
  );
}

/** A bust portrait beside two smaller ones, standing in for a saved roster
 * rather than a single generated still (`ImageCreationIllustration` uses the
 * same bust shape for the "character" asset kind, singular). */
export function CharacterLibraryIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="16" y="10" width="64" height="80" rx="8" fillOpacity="0.06" fill="currentColor" />
      <circle cx="48" cy="38" r="13" />
      <path d="M27 82c2-18 10-27 21-27s19 9 21 27" />
      <circle cx="112" cy="26" r="16" fillOpacity="0.06" fill="currentColor" />
      <circle cx="112" cy="20" r="7" />
      <path d="M99 40c1-9 6-13 13-13s12 4 13 13" />
      <circle cx="140" cy="52" r="13" fillOpacity="0.06" fill="currentColor" />
      <circle cx="140" cy="47" r="5.5" />
      <path d="M130 62c1-6.5 4.5-10 10-10s9 3.5 10 10" />
    </Scene>
  );
}

/** Two landscape frames stacked behind a third, standing in for a saved
 * library rather than a single scene reference. */
export function SceneLibraryIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="26" y="8" width="98" height="24" rx="5" fillOpacity="0.05" fill="currentColor" strokeOpacity="0.3" />
      <rect x="18" y="34" width="106" height="30" rx="5" fillOpacity="0.06" fill="currentColor" strokeOpacity="0.55" />
      <rect x="10" y="62" width="114" height="28" rx="6" fillOpacity="0.08" fill="currentColor" />
      <circle cx="30" cy="76" r="4" />
      <path d="M18 88 40 70l10 8 14-12 20 16" strokeOpacity="0.7" />
      <circle cx="140" cy="26" r="8" />
      <path d="M132 26h-6M140 18v-6M148 26h6M140 34v6M135 21l-4-4M145 21l4-4M135 31l-4 4M145 31l4 4" strokeOpacity="0.5" />
    </Scene>
  );
}

export function ScriptIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="18" y="10" width="70" height="80" rx="6" fillOpacity="0.06" fill="currentColor" />
      <path d="M30 26h46M30 36h46M30 46h30" strokeOpacity="0.55" />
      <rect
        x="30"
        y="58"
        width="34"
        height="4"
        rx="2"
        fill="currentColor"
        stroke="none"
        fillOpacity="0.5"
      />
      <rect
        x="30"
        y="68"
        width="20"
        height="4"
        rx="2"
        fill="currentColor"
        stroke="none"
        fillOpacity="0.35"
      />
      <path
        d="M104 20h30a8 8 0 0 1 8 8v14a8 8 0 0 1-8 8h-14l-10 10v-10h-6a8 8 0 0 1-8-8V28a8 8 0 0 1 8-8Z"
        fillOpacity="0.08"
        fill="currentColor"
      />
      <path d="M114 32h20M114 40h14" strokeOpacity="0.6" />
    </Scene>
  );
}
