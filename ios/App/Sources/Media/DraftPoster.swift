import SwiftUI
import ZaolangKit

/// Draft card media: images stay on `RemoteImage`, video shows the first frame
/// without autoplay, audio keeps an empty surface.
struct DraftPoster: View {
    let draft: DraftResponse
    var aspectRatio: Double = 16.0 / 9.0
    var showsPlayBadge: Bool = true

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            switch draft.outputMediaType {
            case .video:
                VideoFirstFrame(url: draft.outputURL.flatMap(URL.init), aspectRatio: aspectRatio)
            case .audio:
                emptySurface
            default:
                RemoteImage(url: draft.outputURL.flatMap(URL.init), aspectRatio: aspectRatio)
            }

            if draft.outputMediaType == .video, showsPlayBadge {
                Image(systemName: "play.fill")
                    .font(.caption2)
                    .foregroundStyle(.white)
                    .frame(width: 22, height: 22)
                    .background(Color.black.opacity(0.7), in: Circle())
                    .padding(6)
                    .accessibilityHidden(true)
            }
        }
    }

    private var emptySurface: some View {
        RoundedRectangle.zl(ZLRadius.sm)
            .fill(Color.zl.surfaceSoft)
            .aspectRatio(aspectRatio, contentMode: .fit)
            .overlay {
                Image(systemName: "waveform")
                    .foregroundStyle(Color.zl.textMuted)
            }
            .accessibilityHidden(true)
    }
}

struct VideoFirstFrame: View {
    let url: URL?
    var aspectRatio: Double = 16.0 / 9.0

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else if failed {
                RoundedRectangle.zl(ZLRadius.sm)
                    .fill(Color.zl.surfaceSoft)
                    .overlay {
                        Image(systemName: "film")
                            .foregroundStyle(Color.zl.textMuted)
                    }
            } else {
                RoundedRectangle.zl(ZLRadius.sm)
                    .fill(Color.zl.skeleton)
                    .zlSkeletonPulse()
            }
        }
        .aspectRatio(aspectRatio, contentMode: .fit)
        .clipped()
        .accessibilityHidden(true)
        .task(id: url) { await load() }
    }

    private func load() async {
        guard let url else {
            failed = true
            return
        }
        if let cached = VideoFirstFrameLoader.shared.cached(url) {
            image = cached
            return
        }
        failed = false
        image = nil
        if let frame = await VideoFirstFrameLoader.shared.load(url) {
            image = frame
        } else {
            failed = true
        }
    }
}
