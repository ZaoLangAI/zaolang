import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.fn();

vi.mock('@/lib/api/client', () => ({
  api: { get: (...args: unknown[]) => get(...args) },
}));

import { downloadAsset, fetchAssetDownloadUrl, openDownloadUrl } from './download-asset';

beforeEach(() => {
  get.mockReset();
});

describe('fetchAssetDownloadUrl', () => {
  it('returns the signed url from GET ?download=true', async () => {
    get.mockResolvedValue({ url: 'https://store.example/clip.mp4?x=1' });

    await expect(fetchAssetDownloadUrl('ast_1')).resolves.toBe(
      'https://store.example/clip.mp4?x=1',
    );
    expect(get).toHaveBeenCalledWith('/v1/assets/ast_1', { query: { download: true } });
  });

  it('rejects when the asset has no url', async () => {
    get.mockResolvedValue({ url: null });

    await expect(fetchAssetDownloadUrl('ast_1')).rejects.toThrow('no download URL');
  });

  it('rejects when the request fails', async () => {
    get.mockRejectedValue(new Error('network'));

    await expect(fetchAssetDownloadUrl('ast_1')).rejects.toThrow('network');
  });
});

describe('openDownloadUrl', () => {
  it('clicks a new-tab anchor at the signed url', () => {
    const click = vi.fn();
    const createElement = vi.spyOn(document, 'createElement');
    createElement.mockReturnValue({
      href: '',
      target: '',
      rel: '',
      click,
    } as unknown as HTMLAnchorElement);

    openDownloadUrl('https://store.example/clip.mp4');

    expect(createElement).toHaveBeenCalledWith('a');
    const anchor = createElement.mock.results[0]?.value as HTMLAnchorElement;
    expect(anchor.href).toBe('https://store.example/clip.mp4');
    expect(anchor.target).toBe('_blank');
    expect(anchor.rel).toBe('noreferrer');
    expect(click).toHaveBeenCalledOnce();
    createElement.mockRestore();
  });
});

describe('downloadAsset', () => {
  it('opens the minted url after a successful fetch', async () => {
    get.mockResolvedValue({ url: 'https://store.example/clip.mp4' });
    const click = vi.fn();
    const createElement = vi.spyOn(document, 'createElement');
    createElement.mockReturnValue({
      href: '',
      target: '',
      rel: '',
      click,
    } as unknown as HTMLAnchorElement);

    await downloadAsset('ast_1');

    expect(click).toHaveBeenCalledOnce();
    createElement.mockRestore();
  });
});
