import ZaolangKit

/// Display box for generated media. The iPhone 17 canvas (402×874) is a
/// ceiling, not a default shape: 16:9 and 1:1 keep their own ratio; only a
/// taller-than-phone clip is clamped so the page cannot grow past one screen.
enum MediaStageMetrics {
    static var referenceAspect: Double {
        let canvas = ZaolangKit.referenceCanvas
        return canvas.width / canvas.height
    }

    static func stageAspect(for mediaAspect: Double) -> Double {
        let safe = mediaAspect.isFinite && mediaAspect > 0 ? mediaAspect : (16.0 / 9.0)
        return max(safe, referenceAspect)
    }
}
