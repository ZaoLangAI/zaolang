import AVKit
import SwiftUI
import ZaolangKit

/// 对应 `components/media/video-player.tsx` + `work-stage.tsx`。视频用 `AVPlayer`，
/// 图片退回封面图；墓碑态与离线态都不播放，只显示封面加一条说明条。
struct WorkMediaStage: View {
    let mediaType: MediaType?
    let mediaURL: String?
    let coverURL: String?
    let aspectRatio: Double
    let isTombstoned: Bool
    let isOffline: Bool

    @State private var player: AVPlayer?

    var body: some View {
        ZStack {
            if isTombstoned || isOffline || mediaType != .video || mediaURL == nil {
                RemoteImage(url: coverURL.flatMap(URL.init), aspectRatio: aspectRatio, contentMode: .fill)
            } else if let player {
                VideoPlayer(player: player)
                    .aspectRatio(aspectRatio, contentMode: .fit)
            }
        }
        .zlCornerRadius(ZLRadius.md)
        .overlay(alignment: .top) { banner }
        .task(id: mediaURL) { await preparePlayer() }
        .onDisappear { player?.pause() }
    }

    @ViewBuilder
    private var banner: some View {
        if isTombstoned {
            Text(L10n.t("work.tombstonedHint"))
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.zl.onPrimary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
                .background(Color.zl.amber)
        } else if isOffline {
            Text(L10n.t("states.offline"))
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.zl.onPrimary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
                .background(Color.zl.danger)
        }
    }

    private func preparePlayer() async {
        guard !isTombstoned, !isOffline, mediaType == .video, let mediaURL, let url = URL(string: mediaURL) else {
            player = nil
            return
        }
        player = AVPlayer(url: url)
    }
}
