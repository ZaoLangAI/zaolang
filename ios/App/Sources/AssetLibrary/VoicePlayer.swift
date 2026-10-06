import AVFoundation
import Observation

/// 一次只播一段音色试听；再点同一段就停。
@MainActor
@Observable
final class VoicePlayer {
    private var player: AVPlayer?
    private var endObserver: NSObjectProtocol?
    private(set) var playingURL: String?

    func toggle(_ url: String) {
        if playingURL == url {
            stop()
            return
        }
        stop()
        guard let parsed = URL(string: url) else { return }
        let item = AVPlayerItem(url: parsed)
        let player = AVPlayer(playerItem: item)
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.stop() }
        }
        self.player = player
        playingURL = url
        player.play()
    }

    func stop() {
        player?.pause()
        player = nil
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = nil
        playingURL = nil
    }
}
