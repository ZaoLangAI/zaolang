export const CHANNEL_LABEL_KEYS: Record<string, string> = {
  douyin: 'channelDouyin',
  kuaishou: 'channelKuaishou',
  manual_download: 'channelManualDownload',
};

/** Every channel a series-level metrics rollup can contain. */
export const SERIES_CHANNELS = ['douyin', 'kuaishou', 'manual_download'] as const;

/** Every channel a single work's own metrics endpoint can return
 *  (`manual_download` is series-aggregate-only, never a per-work pull). */
export const WORK_CHANNELS = ['douyin', 'kuaishou'] as const;
