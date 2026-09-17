import AVKit
import SwiftUI
import ZaolangKit

/// Playable draft output for detail / publish: video uses the work stage player,
/// stills stay on `RemoteImage`, audio gets a compact native bar.
struct DraftMediaView: View {
    let draft: DraftResponse
    var aspectRatio: Double? = nil

    private var stageAspect: Double {
        if let width = draft.width, let height = draft.height, width > 0, height > 0 {
            return MediaStageMetrics.stageAspect(for: Double(width) / Double(height))
        }
        if let aspectRatio {
            return MediaStageMetrics.stageAspect(for: aspectRatio)
        }
        return MediaStageMetrics.stageAspect(for: 16.0 / 9.0)
    }

    var body: some View {
        switch draft.outputMediaType {
        case .video:
            WorkMediaStage(
                mediaType: .video,
                mediaURL: draft.outputURL,
                coverURL: nil,
                aspectRatio: stageAspect,
                isTombstoned: false,
                isOffline: false
            )
        case .audio:
            DraftAudioBar(url: draft.outputURL.flatMap(URL.init))
        default:
            RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: stageAspect)
                .zlCornerRadius(ZLRadius.md)
        }
    }
}

private struct DraftAudioBar: View {
    let url: URL?

    @State private var player: AVPlayer?
    @State private var playing = false

    var body: some View {
        HStack(spacing: 12) {
            Button {
                guard let player else { return }
                if playing {
                    player.pause()
                    playing = false
                } else {
                    player.play()
                    playing = true
                }
            } label: {
                Image(systemName: playing ? "pause.fill" : "play.fill")
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .disabled(url == nil)
            .accessibilityLabel(L10n.t(playing ? "a11y.pause" : "a11y.play"))

            Text(L10n.t("publishPage.previewLabel"))
                .font(.subheadline)
            Spacer()
        }
        .padding(12)
        .background(Color.zl.surfaceSoft)
        .zlCornerRadius(ZLRadius.md)
        .task(id: url) {
            guard let url else { return }
            player = AVPlayer(url: url)
        }
        .onDisappear {
            player?.pause()
            playing = false
        }
    }
}
