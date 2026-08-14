import SwiftUI
import ZaolangKit

/// Read-only generation spec on draft detail / publish, matching the web publish page.
struct DraftSpecSection: View {
    let draft: DraftResponse

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let prompt = draft.stringParam("prompt") {
                VStack(alignment: .leading, spacing: 4) {
                    Text(L10n.t("publishPage.prompt")).font(.caption.weight(.semibold))
                    Text(prompt).font(.caption).foregroundStyle(Color.zl.textMuted)
                }
            }

            ForEach(rows, id: \.key) { row in
                HStack(alignment: .firstTextBaseline) {
                    Text(row.label).foregroundStyle(Color.zl.textMuted)
                    Spacer(minLength: 12)
                    Text(row.value).multilineTextAlignment(.trailing)
                }
                .font(.caption)
            }
        }
    }

    private var rows: [(key: String, label: String, value: String)] {
        var rows: [(key: String, label: String, value: String)] = []
        if let operation = draft.stringParam("operation") {
            rows.append((
                "operation",
                L10n.t("publishPage.operationLabel"),
                localizedOrRaw("publishPage.operation.\(operation)", operation)
            ))
        }
        if let quality = draft.stringParam("quality_tier") {
            rows.append((
                "quality",
                L10n.t("publishPage.quality"),
                localizedOrRaw("publishPage.tier.\(quality)", quality)
            ))
        }
        if let aspect = draft.stringParam("aspect_ratio") {
            rows.append(("aspect", L10n.t("publishPage.aspect"), aspect))
        }
        if let seconds = draft.durationSeconds {
            rows.append((
                "duration",
                L10n.t("publishPage.duration"),
                L10n.t("publishPage.durationSeconds", ["count": seconds])
            ))
        }
        if let width = draft.width, let height = draft.height, width > 0, height > 0 {
            rows.append(("resolution", L10n.t("publishPage.resolution"), "\(width)×\(height)"))
        }
        rows.append((
            "createdAt",
            L10n.t("publishPage.createdAt"),
            draft.createdAt.formatted(date: .abbreviated, time: .shortened)
        ))
        return rows
    }

    private func localizedOrRaw(_ key: String, _ raw: String) -> String {
        let value = L10n.t(key)
        return value == key ? raw : value
    }
}
