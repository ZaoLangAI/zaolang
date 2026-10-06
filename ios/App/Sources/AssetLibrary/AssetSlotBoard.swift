import SwiftUI
import ZaolangKit

/// 资产板（只读）：一个造型 / 变体的完备度、转面机位覆盖环和槽位网格。点槽位打开 `SlotSheet`
/// 定稿候选；主槽位（定妆照 / 主图）可在 iOS 快速生成，其余槽位在网页端继续。
struct AssetSlotBoard: View {
    let kind: AssetCardKind
    let graph: AssetGraphResponse
    let variant: AssetVariantView
    let generatingSlot: String?
    let onOpen: (AssetSlots.SlotState) -> Void

    var body: some View {
        let states = AssetSlots.slotStates(
            kind, variant: variant, allEntries: graph.variants.flatMap(\.entries), pending: graph.pending
        )
        let completeness = AssetSlots.completeness(states)
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.t("assetWorkspace.completeness", ["done": completeness.done, "total": completeness.total]))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.zl.text)
                    ProgressView(value: Double(completeness.done), total: Double(max(completeness.total, 1)))
                        .tint(Color.zl.primary)
                        .accessibilityHidden(true)
                }
                CoverageRing(coverage: AssetSlots.coverage(kind, variant: variant))
                    .frame(width: 96, height: 96)
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 12) {
                ForEach(states) { state in
                    Button { onOpen(state) } label: {
                        SlotTile(
                            state: state,
                            generating: generatingSlot == AssetDetailViewModel.slotKey(variantID: variant.id, slotID: state.slot.id)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(L10n.t("assetWorkspace.boardLabel"))
    }
}

/// One slot: its approved image (else the newest candidate, dimmed), name and status.
struct SlotTile: View {
    let state: AssetSlots.SlotState
    var generating = false

    private var status: AssetSlots.Status { generating ? .pending : state.status }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ZStack {
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.surfaceSoft)
                if let entry = state.approved ?? state.candidates.last {
                    RemoteImage(url: entry.url.flatMap(URL.init(string:)), aspectRatio: 1)
                        .opacity(state.approved == nil ? 0.6 : 1)
                } else if status == .pending {
                    ProgressView()
                } else {
                    Image(systemName: state.slot.kind == .pose ? "camera.rotate" : "photo")
                        .foregroundStyle(Color.zl.textMuted)
                }
            }
            .aspectRatio(1, contentMode: .fit)
            .zlCornerRadius(ZLRadius.sm)
            .overlay {
                RoundedRectangle.zl(ZLRadius.sm)
                    .stroke(state.slot.isPrimary ? Color.zl.primary : Color.zl.border, lineWidth: state.slot.isPrimary ? 2 : 1)
            }
            Text(L10n.t("assetWorkspace.slot.\(state.slot.id)"))
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.zl.text)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 4) {
                Text(L10n.t("assetWorkspace.status.\(status.rawValue)"))
                    .foregroundStyle(tint)
                if !state.slot.required {
                    Text("· \(L10n.t("assetWorkspace.optional"))").foregroundStyle(Color.zl.textMuted)
                }
            }
            .font(.caption2)
            if status == .candidate || (status == .approved && !state.candidates.isEmpty) {
                Text(L10n.t("assetWorkspace.candidateBadge", ["count": state.candidates.count]))
                    .font(.caption2)
                    .foregroundStyle(Color.zl.amber)
            }
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var tint: Color {
        switch status {
        case .approved: Color.zl.success
        case .candidate: Color.zl.amber
        case .pending: Color.zl.primary
        case .missing: Color.zl.textMuted
        }
    }
}

/// The turnaround ring: eight azimuths around the subject (0° = facing the
/// camera, drawn at the bottom like the web orbit dial); filled = approved,
/// outlined = candidate only, faint = missing.
struct CoverageRing: View {
    let coverage: [Int: AssetSlots.Status]

    var body: some View {
        GeometryReader { proxy in
            let size = min(proxy.size.width, proxy.size.height)
            let radius = size / 2 - 8
            ZStack {
                Circle()
                    .stroke(Color.zl.border, lineWidth: 1)
                    .frame(width: radius * 2, height: radius * 2)
                Circle()
                    .fill(Color.zl.textMuted)
                    .frame(width: 10, height: 10)
                ForEach(AssetSlots.azimuths, id: \.self) { azimuth in
                    dot(coverage[azimuth])
                        .offset(offset(azimuth, radius: radius))
                }
            }
            .frame(width: size, height: size)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L10n.t("assetWorkspace.orbit.dialLabel"))
        .accessibilityValue(accessibilityValue)
    }

    /// Azimuth runs clockwise seen from above with 0° toward the viewer
    /// (bottom of the dial) and 90° — the subject's right — on screen left.
    private func offset(_ azimuth: Int, radius: CGFloat) -> CGSize {
        let angle = Double(azimuth) * .pi / 180
        return CGSize(width: -sin(angle) * radius, height: cos(angle) * radius)
    }

    @ViewBuilder
    private func dot(_ status: AssetSlots.Status?) -> some View {
        switch status {
        case .approved:
            Circle().fill(Color.zl.primary).frame(width: 12, height: 12)
        case .candidate:
            Circle().stroke(Color.zl.primary, style: StrokeStyle(lineWidth: 2, dash: [2, 2])).frame(width: 12, height: 12)
        default:
            Circle().fill(Color.zl.track).frame(width: 8, height: 8)
        }
    }

    private var accessibilityValue: String {
        AssetSlots.azimuths.compactMap { azimuth -> String? in
            guard let status = coverage[azimuth], status == .approved || status == .candidate else { return nil }
            return "\(L10n.t("assetWorkspace.azimuth.\(azimuth)")) · \(L10n.t("assetWorkspace.coverage.\(status.rawValue)"))"
        }
        .joined(separator: "，")
    }
}
