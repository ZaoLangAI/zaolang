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

/** A frame with a mountain-and-sun snapshot, sparking into being from text. */
export function TextToImageIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="44" y="18" width="82" height="56" rx="6" fillOpacity="0.06" fill="currentColor" />
      <circle cx="68" cy="38" r="6" />
      <path d="M50 62 68 44l12 12 10-10 18 16" />
      <path d="M18 30h16M18 40h22M18 50h14" strokeOpacity="0.55" />
      <path d="M132 22 135.4 29.5 143 32.8 135.4 36.1 132 43.5 128.6 36.1 121 32.8 128.6 29.5Z" />
    </Scene>
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

/** A still photo pivoting into motion, with a sweep arc between the two. */
export function ImageToVideoIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="16" y="22" width="52" height="52" rx="6" fillOpacity="0.06" fill="currentColor" />
      <circle cx="34" cy="38" r="5" />
      <path d="M22 62 36 48l8 8 8-8 8 6" />
      <path d="M78 48c8-14 22-14 30-2" strokeDasharray="4 5" />
      <path d="M104 40 108 47 100 47Z" fill="currentColor" />
      <rect x="98" y="20" width="46" height="52" rx="6" fillOpacity="0.06" fill="currentColor" />
      <path d="M112 34 132 46 112 58Z" fill="currentColor" strokeLinejoin="round" />
    </Scene>
  );
}

/** Two overlapping frames with a wand redrawing the top one. */
export function ImageToImageIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="18" y="30" width="70" height="50" rx="6" fillOpacity="0.05" fill="currentColor" />
      <rect x="40" y="16" width="70" height="50" rx="6" fillOpacity="0.08" fill="currentColor" />
      <circle cx="60" cy="32" r="5" />
      <path d="M46 54 60 40l8 8 8-8 10 8" />
      <path d="M118 58 132 44" />
      <path d="M136 40 138 44 142 46 138 48 136 52 134 48 130 46 134 44Z" fill="currentColor" />
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
      <rect x="66" y="66" width="28" height="4" rx="2" fill="currentColor" stroke="none" fillOpacity="0.5" />
      <rect x="66" y="74" width="18" height="4" rx="2" fill="currentColor" stroke="none" fillOpacity="0.35" />
    </Scene>
  );
}

/** Two frames branching from a shared root, tracing where a remix came from. */
export function RemixIllustration(props: IllustrationProps) {
  return (
    <Scene {...props}>
      <rect x="16" y="38" width="44" height="34" rx="6" fillOpacity="0.08" fill="currentColor" />
      <path d="M28 60 38 50l6 6 8-8" />
      <path d="M60 55h16" />
      <path d="M76 55c10 0 10-20 20-20M76 55c10 0 10 20 20 20" />
      <rect x="96" y="20" width="44" height="30" rx="6" fillOpacity="0.06" fill="currentColor" />
      <circle cx="110" cy="32" r="4" />
      <path d="M100 44 112 36l6 5 8-6" />
      <rect x="96" y="60" width="44" height="30" rx="6" fillOpacity="0.06" fill="currentColor" />
      <circle cx="110" cy="72" r="4" />
      <path d="M100 84 112 76l6 5 8-6" />
    </Scene>
  );
}
