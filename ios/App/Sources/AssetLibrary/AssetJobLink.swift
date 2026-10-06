import ZaolangKit

/// Where an image job's notification resumes: the card it filed into
/// (`linked_*`, set at write-back), else the card the request named
/// (`target_*`), opened on its `target_variant_id`. Mirrors web
/// `assetWorkspaceHref` (`front/src/lib/asset-job-href.ts`); `nil` — a video
/// job, or a general / cover image from before AC-8 — keeps the job page.
struct AssetJobLink: Equatable {
    let kind: AssetCardKind
    let cardID: String
    let variantID: String?

    /// `field` reads one string from a notification payload or push `userInfo`.
    init?(field: (String) -> String?) {
        func value(_ key: String) -> String? {
            guard let raw = field(key), !raw.isEmpty else { return nil }
            return raw
        }
        var found: (AssetCardKind, String)?
        for kind in AssetCardKind.allCases {
            if let id = value("linked_\(kind.rawValue)_id") ?? value("target_\(kind.rawValue)_id") {
                found = (kind, id)
                break
            }
        }
        guard let (kind, cardID) = found else { return nil }
        self.kind = kind
        self.cardID = cardID
        variantID = value("target_variant_id")
    }

    var route: CreateRoute {
        .assetDetail(kind: kind, cardID: cardID, variantID: variantID)
    }
}
