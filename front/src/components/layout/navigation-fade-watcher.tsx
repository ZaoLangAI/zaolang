'use client';

import { usePathname } from 'next/navigation';
import { useEffect } from 'react';

import { endLocaleTransition } from '@/lib/locale-transition';

/**
 * 清除地区切换动画留下的导航态标记。
 *
 * 用的是 `next/navigation` 的原生 `usePathname`（带 locale 前缀），不是
 * `@/i18n/navigation` 那份去掉前缀的版本——只有原生版本会在切地区时真正变化。
 * 挂载在 `AppProviders` 里、只渲染一次：不管发起跳转的组件在导航过程中是否被
 * 卸载重建，只要新路径挂载完成，这里就会重新求值并清掉淡出状态。
 */
export function NavigationFadeWatcher() {
  const pathname = usePathname();

  useEffect(() => {
    endLocaleTransition();
  }, [pathname]);

  return null;
}
