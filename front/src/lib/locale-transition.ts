const FALLBACK_TIMEOUT_MS = 4000;

let fallbackTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * 地区切换会跳转到新的 `[locale]` 前缀路径，触发整段 RSC 树重新渲染，
 * 期间在 `<html data-navigating>` 上留一个标记，配合 `globals.css` 淡出页面。
 *
 * 不用 `useTransition` 的 `isPending`：发起跳转的组件（如顶栏地区菜单）在
 * 跳转过程中是否保持挂载并不确定，直接写 `document.documentElement.dataset`
 * 才能保证标记一定被设置，清除则交给始终挂载的 `NavigationFadeWatcher`。
 *
 * 兜底定时器只是防止跳转异常（失败/极慢）时页面卡在淡出状态，不是主路径。
 */
export function beginLocaleTransition(): void {
  document.documentElement.dataset.navigating = 'true';
  clearTimeout(fallbackTimer);
  fallbackTimer = setTimeout(endLocaleTransition, FALLBACK_TIMEOUT_MS);
}

/** 由 `NavigationFadeWatcher` 在新路径挂载后调用，清除淡出标记与兜底定时器。 */
export function endLocaleTransition(): void {
  clearTimeout(fallbackTimer);
  document.documentElement.dataset.navigating = 'false';
}
