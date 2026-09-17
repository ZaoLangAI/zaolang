'use client';

import '@mdxeditor/editor/style.css';

import {
  BlockTypeSelect,
  BoldItalicUnderlineToggles,
  CreateLink,
  headingsPlugin,
  imagePlugin,
  InsertImage,
  linkDialogPlugin,
  linkPlugin,
  listsPlugin,
  ListsToggle,
  markdownShortcutPlugin,
  MDXEditor,
  quotePlugin,
  Separator,
  thematicBreakPlugin,
  toolbarPlugin,
  UndoRedo,
} from '@mdxeditor/editor';
import { useState } from 'react';

import { useTheme } from '@/components/theme/theme-provider';
import { uploadFile } from '@/lib/upload';

const ASSET_SCHEME = 'learn-asset:';

/**
 * MDXEditor 的实际实现，只应该通过 `markdown-body-editor.tsx` 的动态导入加载。
 * 库内部依赖浏览器 API（Lexical 挂载时直接摸 `document`），拆成独立模块配合
 * `next/dynamic({ ssr: false })` 才能保证这段代码完全不进入 SSR 渲染路径。
 */
export default function MarkdownBodyEditorImpl({
  markdown,
  assetUrls,
  onChange,
  placeholder,
}: {
  markdown: string;
  assetUrls: Record<string, string>;
  onChange: (markdown: string) => void;
  placeholder?: string;
}) {
  const { resolved } = useTheme();

  // 刚上传成功、还没被写进服务端响应里的资产预览地址。存储格式里图片引用
  // 一律是不过期的 `learn-asset:{id}`，画布渲染却需要立刻看到真实图片——
  // 服务端 `asset_urls` 只覆盖「已保存过」的资产，这次会话里新上传的图片
  // 靠这份本地缓存兜底，直到下一次从服务端拉取详情为止。用 state 而不是
  // ref：`imagePlugin` 内部按最新 props 响应式同步 handler，用 ref 闭包
  // 在渲染期间被读取反而会被 `react-hooks/refs` 判定为不安全。
  const [uploadedPreviews, setUploadedPreviews] = useState<Record<string, string>>({});

  const handleImageUpload = async (file: File): Promise<string> => {
    const asset = await uploadFile(file, 'learn_media');
    if (asset.url) {
      const url = asset.url;
      setUploadedPreviews((current) => ({ ...current, [asset.id]: url }));
    }
    return `${ASSET_SCHEME}${asset.id}`;
  };

  const handleImagePreview = async (src: string): Promise<string> => {
    if (!src.startsWith(ASSET_SCHEME)) return src;
    const assetId = src.slice(ASSET_SCHEME.length);
    return uploadedPreviews[assetId] ?? assetUrls[assetId] ?? src;
  };

  return (
    <MDXEditor
      markdown={markdown}
      onChange={onChange}
      placeholder={placeholder}
      className={resolved === 'dark' ? 'dark-theme' : undefined}
      contentEditableClassName="min-h-[420px] rounded-[var(--radius-sm)] border border-border"
      plugins={[
        headingsPlugin(),
        listsPlugin(),
        quotePlugin(),
        linkPlugin(),
        linkDialogPlugin(),
        thematicBreakPlugin(),
        imagePlugin({
          imageUploadHandler: handleImageUpload,
          imagePreviewHandler: handleImagePreview,
        }),
        markdownShortcutPlugin(),
        toolbarPlugin({
          toolbarContents: () => (
            <>
              <UndoRedo />
              <Separator />
              <BoldItalicUnderlineToggles />
              <Separator />
              <BlockTypeSelect />
              <Separator />
              <ListsToggle />
              <Separator />
              <CreateLink />
              <InsertImage />
            </>
          ),
        }),
      ]}
    />
  );
}
