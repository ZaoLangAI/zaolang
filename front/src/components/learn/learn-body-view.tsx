import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Poster } from '@/components/media/poster';

const ASSET_SCHEME = 'learn-asset:';

/**
 * 正文里的图片引用一律是 `learn-asset:{id}`（详见 `LearnPostDetail.body_markdown`
 * 文档注释），不是可直接访问的 URL——真正能用的地址要在 `assetUrls` 里查。
 * 查不到（素材被删、或引用本身就不合法）时返回 `null`，交给 `Poster` 的空态兜底，
 * 不拼接猜测出来的地址，也不让 `next/image` 因为非法 `src` 崩掉。
 */
function resolveImageSrc(
  src: string | undefined,
  assetUrls: Record<string, string>,
): string | null {
  if (!src) return null;
  if (!src.startsWith(ASSET_SCHEME)) return src;
  return assetUrls[src.slice(ASSET_SCHEME.length)] ?? null;
}

/**
 * 学习内容正文的只读渲染，详情页和后台审核控制台共用。
 *
 * 用 `react-markdown` 把 `body_markdown` 解析成 React 元素树——绝不走
 * `dangerouslySetInnerHTML`。项目未引入 Tailwind Typography 插件，标题/列表/
 * 引用块等排版样式在下面的 `components` 里手写，对齐既有的设计 token。
 */
export function LearnBodyView({
  markdown,
  assetUrls,
  emptyImageLabel,
}: {
  markdown: string;
  assetUrls: Record<string, string>;
  /** 图片引用解析不出真实地址时的占位文案，由调用方传入（通常复用 `states.empty`）。 */
  emptyImageLabel: string;
}) {
  const components: Components = {
    h1: ({ children }) => <h2 className="mt-2 text-2xl font-bold tracking-tight">{children}</h2>,
    h2: ({ children }) => <h2 className="mt-2 text-xl font-semibold">{children}</h2>,
    h3: ({ children }) => <h3 className="mt-1 text-lg font-semibold">{children}</h3>,
    h4: ({ children }) => <h4 className="mt-1 text-base font-semibold">{children}</h4>,
    h5: ({ children }) => <h5 className="mt-1 text-base font-semibold">{children}</h5>,
    h6: ({ children }) => <h6 className="mt-1 text-base font-semibold">{children}</h6>,
    p: ({ children }) => <p className="text-sm leading-relaxed text-text">{children}</p>,
    ul: ({ children }) => (
      <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-text">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal space-y-1 pl-5 text-sm leading-relaxed text-text">{children}</ol>
    ),
    li: ({ children }) => <li className="pl-1">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-border pl-4 text-sm italic text-muted">
        {children}
      </blockquote>
    ),
    hr: () => <hr className="border-border" />,
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="text-primary underline underline-offset-2 hover:text-primary/80"
      >
        {children}
      </a>
    ),
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    del: ({ children }) => <del className="text-muted line-through">{children}</del>,
    code: ({ children }) => (
      <code className="rounded-[var(--radius-sm)] bg-surface-soft px-1 py-0.5 font-mono text-[13px]">
        {children}
      </code>
    ),
    pre: ({ children }) => (
      <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3 font-mono text-[13px] leading-relaxed">
        {children}
      </pre>
    ),
    table: ({ children }) => (
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="border border-border px-2 py-1 text-left font-medium">{children}</th>
    ),
    td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
    input: ({ checked, disabled }) => (
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        className="mr-1.5 align-middle"
      />
    ),
    img: ({ src, alt }) => {
      // React 19 的 `img.src` 类型联合了一个实验性的非字符串变体，markdown
      // 解析出的图片引用不会命中它，这里只是让类型检查满意。
      const resolved = resolveImageSrc(typeof src === 'string' ? src : undefined, assetUrls);
      return (
        <Poster
          src={resolved}
          alt={resolved ? (alt ?? '') : emptyImageLabel}
          aspect="video"
          className="max-w-xl"
        />
      );
    },
  };

  return (
    <div className="flex flex-col gap-4">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
