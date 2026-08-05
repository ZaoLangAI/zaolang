'use client';

import dynamic from 'next/dynamic';

import { Spinner } from '@/components/ui/spinner';

const MarkdownBodyEditorImpl = dynamic(() => import('./markdown-body-editor-impl'), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-40 items-center justify-center rounded-[var(--radius-sm)] border border-border bg-surface-soft">
      <Spinner className="size-4" />
    </div>
  ),
});

/**
 * 学习内容正文的 markdown 富文本编辑器（发表 / 编辑表单共用）。
 *
 * 只是 `MarkdownBodyEditorImpl` 的动态导入外壳——真正的 MDXEditor 配置见
 * 那个文件，拆分的唯一原因是让它安全地跳过 SSR。
 */
export function MarkdownBodyEditor(props: {
  markdown: string;
  assetUrls: Record<string, string>;
  onChange: (markdown: string) => void;
  placeholder?: string;
}) {
  return <MarkdownBodyEditorImpl {...props} />;
}
